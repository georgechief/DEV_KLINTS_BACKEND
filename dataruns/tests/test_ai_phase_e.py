"""PRD-AI-01 Phase E — Mistral adapter + LangSmith tracing (no live network)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from dataruns.ai.complete import complete_json
from dataruns.ai.constants import DEFAULT_MODEL_ID, TASK_FIX_SUGGESTION
from dataruns.ai.exceptions import AiProviderError
from dataruns.ai.providers import get_ai_provider
from dataruns.ai.providers.mock import MockAiProvider
from dataruns.ai.providers.mistral import MistralAiProvider
from dataruns.ai.tracing import AiTrace, allowlisted_trace_inputs, start_ai_trace, tracing_enabled


def _fix_json() -> str:
    return (
        '{"task_type":"fix_suggestion","check_id":"LE-04","headline":"Purchases look duplicated",'
        '"whats_wrong":"About half of purchases look duplicated.",'
        '"why_it_matters":"Journeys may fire twice.",'
        '"suggestions":[{"step":1,"title":"Confirm Source Of Truth","detail":"Decide ownership."},'
        '{"step":2,"title":"Deduplicate Events","detail":"Dedupe by order externalId."}],'
        '"cautions":["Do not bulk-delete without a sandbox proof."],"confidence":"medium"}'
    )


class FakeMistralClient:
    def __init__(self, text: str = _fix_json()):
        self.text = text
        self.calls = 0
        self.chat = SimpleNamespace(complete=self._complete)

    def _complete(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return SimpleNamespace(
            model=kwargs.get("model") or DEFAULT_MODEL_ID,
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
        )


class MistralProviderTests(SimpleTestCase):
    def test_missing_key_raises_not_configured(self):
        provider = MistralAiProvider(api_key="")
        with self.assertRaises(AiProviderError) as ctx:
            provider.complete_json(
                system_prompt="s",
                user_prompt="u",
                context={"check_id": "LE-04"},
                model=DEFAULT_MODEL_ID,
                temperature=0.3,
                timeout_seconds=5,
            )
        self.assertEqual(ctx.exception.code, "provider_not_configured")

    def test_maps_json_response_and_tokens(self):
        fake = FakeMistralClient()
        provider = MistralAiProvider(api_key="test-key", client=fake)
        result = provider.complete_json(
            system_prompt="system",
            user_prompt="user",
            context={"check_id": "LE-04"},
            model=DEFAULT_MODEL_ID,
            temperature=0.3,
            timeout_seconds=5,
        )
        self.assertEqual(fake.calls, 1)
        self.assertEqual(fake.last_kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(fake.last_kwargs.get("tool_choice"), "none")
        self.assertNotIn("tools", fake.last_kwargs)
        self.assertIn("check_id", result.text)
        self.assertEqual(result.provider, "mistral")
        self.assertEqual(result.input_tokens, 11)
        self.assertEqual(result.output_tokens, 22)
        self.assertFalse(result.raw.get("mock"))

    def test_transport_error_is_provider_error(self):
        fake = FakeMistralClient()

        def boom(**kwargs):
            raise RuntimeError("timeout")

        fake.chat = SimpleNamespace(complete=boom)
        provider = MistralAiProvider(api_key="test-key", client=fake)
        with self.assertRaises(AiProviderError) as ctx:
            provider.complete_json(
                system_prompt="s",
                user_prompt="u",
                context={"check_id": "LE-04"},
                model=DEFAULT_MODEL_ID,
                temperature=0.3,
                timeout_seconds=5,
            )
        self.assertEqual(ctx.exception.code, "provider_error")


@override_settings(AI_PROVIDER="mistral", MISTRAL_API_KEY="")
class ProviderFactoryTests(SimpleTestCase):
    def test_mistral_without_key_fails_closed(self):
        with self.assertRaises(AiProviderError) as ctx:
            get_ai_provider()
        self.assertEqual(ctx.exception.code, "provider_not_configured")

    @override_settings(AI_PROVIDER="mistral", MISTRAL_API_KEY="sk-test")
    def test_mistral_with_key_returns_adapter(self):
        provider = get_ai_provider()
        self.assertIsInstance(provider, MistralAiProvider)

    @override_settings(AI_PROVIDER="mock")
    def test_mock_still_default(self):
        self.assertIsInstance(get_ai_provider(), MockAiProvider)


class TracingPrivacyTests(SimpleTestCase):
    def test_trace_inputs_are_allowlisted_only(self):
        context = {
            "check_id": "LE-04",
            "check_name": "Duplicate Purchase Events",
            "suggested_fix": "Deduplicate.",
            "finding_summary": {"mismatches": [{"path": "contact.email", "kind": "conflict", "side": "shopify"}]},
        }
        inputs = allowlisted_trace_inputs(
            task_type=TASK_FIX_SUGGESTION,
            model=DEFAULT_MODEL_ID,
            context=context,
            metadata={"company_id": "abc", "prompt_version": "ai01.fix_suggestion.v1"},
        )
        blob = str(inputs)
        self.assertNotIn("value", blob)
        self.assertNotIn("alice@", blob)
        self.assertEqual(inputs["allowlisted_context"], context)
        self.assertEqual(inputs["company_id"], "abc")
        self.assertNotIn("system_prompt", inputs)
        self.assertNotIn("user_prompt", inputs)

    def test_start_trace_disabled_is_noop(self):
        self.assertFalse(tracing_enabled())
        trace = start_ai_trace(
            task_type=TASK_FIX_SUGGESTION,
            model=DEFAULT_MODEL_ID,
            context={"check_id": "LE-04"},
        )
        self.assertFalse(trace.enabled)
        self.assertIsNone(trace.run_id)
        trace.finish_ok(payload={}, attempts=1, model="x", provider="mock")
        trace.finish_error(RuntimeError("x"))

    def test_complete_json_records_trace_run_id(self):
        fake_trace = MagicMock()
        fake_trace.run_id = "ls-run-123"
        fake_trace.finish_ok = MagicMock()
        fake_trace.finish_error = MagicMock()
        with patch("dataruns.ai.complete.start_ai_trace", return_value=fake_trace):
            payload, result, attempts = complete_json(
                provider=MockAiProvider(),
                task_type=TASK_FIX_SUGGESTION,
                system_prompt="s",
                user_prompt="u",
                context={"check_id": "LE-04", "check_name": "Dup", "suggested_fix": "Fix"},
                model=DEFAULT_MODEL_ID,
            )
        self.assertEqual(result.langsmith_run_id, "ls-run-123")
        self.assertEqual(payload["check_id"], "LE-04")
        self.assertEqual(attempts, 1)
        fake_trace.finish_ok.assert_called_once()
        fake_trace.finish_error.assert_not_called()

    def test_complete_json_provider_error_calls_finish_error(self):
        fake = FakeMistralClient()

        def boom(**kwargs):
            raise RuntimeError("alice@example.com")

        fake.chat = SimpleNamespace(complete=boom)
        fake_trace = MagicMock()
        fake_trace.run_id = "ls-err"
        fake_trace.finish_ok = MagicMock()
        fake_trace.finish_error = MagicMock()
        with patch("dataruns.ai.complete.start_ai_trace", return_value=fake_trace):
            with self.assertRaises(AiProviderError) as ctx:
                complete_json(
                    provider=MistralAiProvider(api_key="test-key", client=fake),
                    task_type=TASK_FIX_SUGGESTION,
                    system_prompt="s",
                    user_prompt="u",
                    context={"check_id": "LE-04"},
                    model=DEFAULT_MODEL_ID,
                )
        self.assertEqual(ctx.exception.code, "provider_error")
        fake_trace.finish_error.assert_called_once()
        fake_trace.finish_ok.assert_not_called()

    def test_finish_error_does_not_send_exception_text(self):
        run = MagicMock()
        trace = AiTrace(enabled=True, run_id="ls-x", _run=run)
        trace.finish_error(AiProviderError("alice@example.com leaked", code="provider_error"))
        kwargs = run.end.call_args.kwargs
        blob = str(kwargs)
        self.assertNotIn("alice@", blob)
        self.assertNotIn("leaked", blob)
        self.assertEqual(kwargs["error"], "AiProviderError:provider_error")
        self.assertEqual(kwargs["outputs"]["error_code"], "provider_error")

    @override_settings(
        AI_LANGSMITH_IN_TESTS=True,
        LANGSMITH_TRACING=True,
        LANGSMITH_API_KEY="ls-test-key",
        LANGCHAIN_API_KEY="ls-test-key",
        LANGSMITH_PROJECT="klints",
    )
    def test_start_trace_fail_open_when_langsmith_down(self):
        self.assertTrue(tracing_enabled())
        with patch("langsmith.Client"):
            with patch("langsmith.run_trees.RunTree", side_effect=RuntimeError("langsmith down")):
                trace = start_ai_trace(
                    task_type=TASK_FIX_SUGGESTION,
                    model=DEFAULT_MODEL_ID,
                    context={"check_id": "LE-04"},
                )
        self.assertFalse(trace.enabled)
        self.assertIsNone(trace.run_id)

    def test_complete_json_succeeds_when_tracing_is_noop(self):
        disabled = AiTrace(enabled=False)
        with patch("dataruns.ai.complete.start_ai_trace", return_value=disabled):
            payload, result, attempts = complete_json(
                provider=MockAiProvider(),
                task_type=TASK_FIX_SUGGESTION,
                system_prompt="s",
                user_prompt="u",
                context={"check_id": "LE-04", "check_name": "Dup", "suggested_fix": "Fix"},
                model=DEFAULT_MODEL_ID,
            )
        self.assertEqual(payload["check_id"], "LE-04")
        self.assertEqual(attempts, 1)
        self.assertIsNone(result.langsmith_run_id)

    @override_settings(
        AI_LANGSMITH_IN_TESTS=True,
        LANGSMITH_TRACING=True,
        LANGSMITH_API_KEY="ls-test-key",
        LANGCHAIN_API_KEY="ls-test-key",
        LANGSMITH_PROJECT="klints",
    )
    def test_start_trace_posts_allowlisted_inputs_only(self):
        fake_run = MagicMock()
        fake_run.id = "ls-posted"
        with patch("langsmith.Client"):
            with patch("langsmith.run_trees.RunTree", return_value=fake_run) as ctor:
                trace = start_ai_trace(
                    task_type=TASK_FIX_SUGGESTION,
                    model=DEFAULT_MODEL_ID,
                    context={"check_id": "LE-04", "suggested_fix": "Dedupe."},
                    metadata={"company_id": "co-1", "prompt_version": "ai01.fix_suggestion.v1"},
                )
        self.assertTrue(trace.enabled)
        self.assertEqual(trace.run_id, "ls-posted")
        fake_run.post.assert_called_once()
        inputs = ctor.call_args.kwargs["inputs"]
        blob = str(inputs)
        self.assertNotIn("system_prompt", blob)
        self.assertNotIn("user_prompt", blob)
        self.assertEqual(inputs["check_id"], "LE-04")
        self.assertEqual(inputs["company_id"], "co-1")

    def test_mistral_sdk_importable(self):
        try:
            from mistralai.client import Mistral
        except ImportError:
            from mistralai import Mistral
        self.assertTrue(callable(Mistral))
