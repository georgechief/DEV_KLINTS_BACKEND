"""PRD-AI-01 Phase C — mock provider, get_or_create service, Fix suggestion API."""

from __future__ import annotations

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from dataruns.ai.complete import complete_json
from dataruns.ai.constants import DEFAULT_MODEL_ID, PROMPT_FIX_SUGGESTION_V1, TASK_FIX_SUGGESTION
from dataruns.ai.exceptions import (
    AiDisabledError,
    AiGateDeniedError,
    AiJsonRetryExhaustedError,
    AiNotFoundError,
)
from dataruns.ai.providers.flaky import FlakyJsonProvider
from dataruns.ai.providers.mock import MockAiProvider
from dataruns.ai.service import get_or_create_fix_suggestion, serialize_fix_suggestion_result
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import AiCall, AiSuggestion, CheckMaster, DataRun, DimensionMaster
from tenants.models import Company, Tenant, User
from unittest.mock import patch


class CapturePromptProvider(MockAiProvider):
    """Records the gated context and user prompt sent to the provider."""

    name = "capture"

    def __init__(self) -> None:
        self.last_user_prompt = ""
        self.last_context: dict = {}

    def complete_json(self, **kwargs):
        self.last_user_prompt = str(kwargs.get("user_prompt") or "")
        ctx = kwargs.get("context")
        self.last_context = dict(ctx) if isinstance(ctx, dict) else {}
        return super().complete_json(**kwargs)


def _seed_masters() -> None:
    dim = DimensionMaster.objects.filter(dimension_id="02").first()
    if dim is None:
        dim = DimensionMaster.objects.create(
            dimension_id="02",
            key="02 Lifecycle Event",
            name="Lifecycle Event",
            purpose="",
        )
    if not CheckMaster.objects.filter(check_id="LE-04").exists():
        CheckMaster.objects.create(
            sequence=204,
            check_id="LE-04",
            check_name="Duplicate purchase events per order",
            dimension=dim,
            check_class=CheckMaster.CheckClass.RULE_BASED,
            check_type="Consistency",
            role=CheckMaster.Role.SCORED,
            cadence="Daily",
            phase="MVP1-A",
            systems_compared="Shopify / Manago",
            numeric_weight=5,
            severity=CheckMaster.Severity.HIGH,
            root_cause_ids=[],
            suggested_fix="Deduplicate PURCHASE events by order externalId.",
            fix_type="Automated writeback",
            fix_owner="Klints (automated)",
        )


@override_settings(AI_ENABLED=True, AI_PROVIDER="mock")
class CompleteJsonRetryTests(TestCase):
    def test_retries_invalid_json_then_succeeds(self):
        provider = FlakyJsonProvider(fail_times=2)
        payload, result, attempts = complete_json(
            provider=provider,
            task_type=TASK_FIX_SUGGESTION,
            system_prompt="system",
            user_prompt="user",
            context={"check_id": "LE-04", "check_name": "Dup", "suggested_fix": "Fix"},
            model=DEFAULT_MODEL_ID,
            max_retries=3,
        )
        self.assertEqual(attempts, 3)
        self.assertEqual(payload["task_type"], "fix_suggestion")
        self.assertEqual(payload["check_id"], "LE-04")
        self.assertTrue(result.text)

    def test_exhausted_retries_raise(self):
        provider = FlakyJsonProvider(fail_times=5)
        with self.assertRaises(AiJsonRetryExhaustedError):
            complete_json(
                provider=provider,
                task_type=TASK_FIX_SUGGESTION,
                system_prompt="system",
                user_prompt="user",
                context={"check_id": "LE-04"},
                model=DEFAULT_MODEL_ID,
                max_retries=3,
            )
        self.assertEqual(provider.attempts, 3)

    def test_max_retries_capped_at_three(self):
        provider = FlakyJsonProvider(fail_times=5)
        with self.assertRaises(AiJsonRetryExhaustedError):
            complete_json(
                provider=provider,
                task_type=TASK_FIX_SUGGESTION,
                system_prompt="system",
                user_prompt="user",
                context={"check_id": "LE-04"},
                model=DEFAULT_MODEL_ID,
                max_retries=99,
            )
        self.assertEqual(provider.attempts, 3)

    def test_zero_max_retries_clamped_to_one(self):
        provider = FlakyJsonProvider(fail_times=1)
        with self.assertRaises(AiJsonRetryExhaustedError):
            complete_json(
                provider=provider,
                task_type=TASK_FIX_SUGGESTION,
                system_prompt="system",
                user_prompt="user",
                context={"check_id": "LE-04"},
                model=DEFAULT_MODEL_ID,
                max_retries=0,
            )
        self.assertEqual(provider.attempts, 1)


@override_settings(AI_ENABLED=True, AI_PROVIDER="mock")
class FixSuggestionServiceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="AI Phase C", slug="ai-phase-c")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Lumera Skin",
            domain="localhost",
        )
        _seed_masters()
        self.run = DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 69.28,
                "dcs_run": {
                    "run_state": "INCOMPLETE",
                    "headline_score": 69.28,
                    "check_results": [
                        {
                            "check_id": "LE-04",
                            "status": "FAIL",
                            "severity": "high",
                            "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
                        }
                    ],
                },
                "check_results": [
                    {
                        "check_id": "LE-04",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
                    }
                ],
            },
        )

    def test_creates_suggestion_and_call(self):
        result = get_or_create_fix_suggestion(
            company=self.company,
            check_id="LE-04",
            provider=MockAiProvider(),
        )
        self.assertFalse(result.cached)
        self.assertEqual(AiSuggestion.objects.count(), 1)
        self.assertEqual(AiCall.objects.filter(status=AiCall.Status.SUCCESS).count(), 1)
        self.assertEqual(result.suggestion.payload_json["check_id"], "LE-04")
        self.assertGreaterEqual(len(result.suggestion.payload_json["suggestions"]), 2)
        body = serialize_fix_suggestion_result(result)
        self.assertTrue(body["fingerprint"].startswith("sha256:"))
        self.assertEqual(body["prompt_version"], PROMPT_FIX_SUGGESTION_V1)
        self.assertFalse(body["cached"])

    def test_cache_hit_skips_second_provider_call(self):
        first = get_or_create_fix_suggestion(
            company=self.company,
            check_id="LE-04",
            provider=MockAiProvider(),
        )
        calls_before = AiCall.objects.count()
        second = get_or_create_fix_suggestion(
            company=self.company,
            check_id="LE-04",
            provider=MockAiProvider(),
        )
        self.assertTrue(second.cached)
        self.assertEqual(second.suggestion.id, first.suggestion.id)
        self.assertEqual(AiCall.objects.count(), calls_before)
        self.assertEqual(AiSuggestion.objects.count(), 1)

    def test_unknown_check_404(self):
        with self.assertRaises(AiNotFoundError):
            get_or_create_fix_suggestion(
                company=self.company,
                check_id="ZZ-99",
                provider=MockAiProvider(),
            )

    def test_lowercase_check_id_resolves(self):
        result = get_or_create_fix_suggestion(
            company=self.company,
            check_id="le-04",
            provider=MockAiProvider(),
        )
        self.assertEqual(result.suggestion.check_id, "LE-04")

    def test_lowercase_check_id_in_metadata_resolves(self):
        self.run.metadata["check_results"] = [
            {
                "check_id": "le-04",
                "status": "FAIL",
                "severity": "high",
                "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
            }
        ]
        self.run.metadata["dcs_run"]["check_results"] = self.run.metadata["check_results"]
        self.run.save(update_fields=["metadata"])
        result = get_or_create_fix_suggestion(
            company=self.company,
            check_id="LE-04",
            provider=MockAiProvider(),
        )
        self.assertEqual(result.suggestion.check_id, "LE-04")

    def test_gate_denied_persists_call_and_raises(self):
        from dataruns.ai.privacy_gate import GateResult

        denied = GateResult(ok=False, reason_code="pii_remaining", context=None)
        with patch(
            "dataruns.ai.service.ensure_safe_context",
            return_value=denied,
        ):
            with self.assertRaises(AiGateDeniedError) as ctx:
                get_or_create_fix_suggestion(
                    company=self.company,
                    check_id="LE-04",
                    provider=MockAiProvider(),
                )
            self.assertEqual(ctx.exception.reason, "pii_remaining")
        self.assertEqual(AiSuggestion.objects.count(), 0)
        gate_calls = AiCall.objects.filter(status=AiCall.Status.GATE_DENIED)
        self.assertEqual(gate_calls.count(), 1)
        self.assertEqual(gate_calls.first().error_code, "pii_remaining")

    @override_settings(AI_ENABLED=False)
    def test_ai_disabled(self):
        with self.assertRaises(AiDisabledError):
            get_or_create_fix_suggestion(
                company=self.company,
                check_id="LE-04",
                provider=MockAiProvider(),
            )

    def test_failed_json_persists_ai_call_without_suggestion(self):
        with self.assertRaises(AiJsonRetryExhaustedError):
            get_or_create_fix_suggestion(
                company=self.company,
                check_id="LE-04",
                provider=FlakyJsonProvider(fail_times=5),
            )
        self.assertEqual(AiSuggestion.objects.count(), 0)
        failed = AiCall.objects.filter(status=AiCall.Status.FAILED)
        self.assertEqual(failed.count(), 1)
        self.assertEqual(failed.first().error_code, "json_retry_exhausted")

    def test_gate_denied_records_configured_provider(self):
        from dataruns.ai.privacy_gate import GateResult

        denied = GateResult(ok=False, reason_code="pii_remaining", context=None)
        with patch(
            "dataruns.ai.service.ensure_safe_context",
            return_value=denied,
        ):
            with self.assertRaises(AiGateDeniedError):
                get_or_create_fix_suggestion(
                    company=self.company,
                    check_id="LE-04",
                    provider=MockAiProvider(),
                )
        gate_call = AiCall.objects.filter(status=AiCall.Status.GATE_DENIED).first()
        self.assertIsNotNone(gate_call)
        self.assertEqual(gate_call.provider, "mock")

    @override_settings(AI_ENABLED=True, AI_PROVIDER="")
    def test_empty_ai_provider_records_mock_on_gate_deny(self):
        from dataruns.ai.privacy_gate import GateResult

        denied = GateResult(ok=False, reason_code="pii_remaining", context=None)
        with patch(
            "dataruns.ai.service.ensure_safe_context",
            return_value=denied,
        ):
            with self.assertRaises(AiGateDeniedError):
                get_or_create_fix_suggestion(
                    company=self.company,
                    check_id="LE-04",
                )
        gate_call = AiCall.objects.filter(status=AiCall.Status.GATE_DENIED).first()
        self.assertIsNotNone(gate_call)
        self.assertEqual(gate_call.provider, "mock")

    def test_cross_company_dcs_run_id_not_found(self):
        other = Company.objects.create(
            tenant=self.tenant,
            name="Other Brand",
            domain="other.example.com",
        )
        other_run = DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(other.id),
                "check_results": [
                    {
                        "check_id": "LE-04",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "Duplicate PURCHASE.",
                    }
                ],
                "dcs_run": {
                    "check_results": [
                        {
                            "check_id": "LE-04",
                            "status": "FAIL",
                            "severity": "high",
                        }
                    ],
                },
            },
        )
        with self.assertRaises(AiNotFoundError):
            get_or_create_fix_suggestion(
                company=self.company,
                check_id="LE-04",
                dcs_run_id=other_run.id,
                provider=MockAiProvider(),
            )

    def test_pii_in_provenance_mismatches_still_creates_suggestion(self):
        self.run.metadata["check_results"] = [
            {
                "check_id": "LE-04",
                "status": "FAIL",
                "severity": "high",
                "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
                "provenance": {
                    "mismatches": [
                        {
                            "path": "contact.email",
                            "kind": "conflict",
                            "side": "shopify",
                            "value": "alice@brand.com",
                        }
                    ]
                },
            }
        ]
        self.run.save(update_fields=["metadata"])
        result = get_or_create_fix_suggestion(
            company=self.company,
            check_id="LE-04",
            provider=MockAiProvider(),
        )
        self.assertFalse(result.cached)
        self.assertEqual(result.suggestion.check_id, "LE-04")

    def test_provenance_mismatches_when_details_mismatches_empty(self):
        self.run.metadata["check_results"] = [
            {
                "check_id": "LE-04",
                "status": "FAIL",
                "severity": "high",
                "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
                "provenance": {
                    "mismatches": [
                        {
                            "path": "order.externalId",
                            "kind": "conflict",
                            "side": "shopify",
                            "value": "should-not-leak@brand.com",
                        }
                    ]
                },
            }
        ]
        self.run.save(update_fields=["metadata"])
        capture = CapturePromptProvider()
        result = get_or_create_fix_suggestion(
            company=self.company,
            check_id="LE-04",
            provider=capture,
        )
        shapes = capture.last_context.get("finding_summary", {}).get("mismatches", [])
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0]["path"], "order.externalId")
        self.assertNotIn("should-not-leak@brand.com", capture.last_user_prompt)
        self.assertEqual(result.suggestion.check_id, "LE-04")

    def test_warn_status_issue_works(self):
        self.run.metadata["check_results"] = [
            {
                "check_id": "LE-04",
                "status": "WARN",
                "severity": "high",
                "message": "Duplicate PURCHASE rate=25.00% clusters=2.",
            }
        ]
        self.run.metadata["dcs_run"]["check_results"] = self.run.metadata["check_results"]
        self.run.save(update_fields=["metadata"])
        result = get_or_create_fix_suggestion(
            company=self.company,
            check_id="LE-04",
            provider=MockAiProvider(),
        )
        self.assertEqual(result.suggestion.check_id, "LE-04")

    def test_pass_status_check_not_found(self):
        self.run.metadata["check_results"] = [
            {
                "check_id": "LE-04",
                "status": "PASS",
                "severity": "high",
                "message": "All clear.",
            }
        ]
        self.run.metadata["dcs_run"]["check_results"] = self.run.metadata["check_results"]
        self.run.save(update_fields=["metadata"])
        with self.assertRaises(AiNotFoundError):
            get_or_create_fix_suggestion(
                company=self.company,
                check_id="LE-04",
                provider=MockAiProvider(),
            )

    def test_non_terminal_dcs_run_rejected(self):
        running = DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.RUNNING,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "check_results": [
                    {
                        "check_id": "LE-04",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "Duplicate PURCHASE.",
                    }
                ],
            },
        )
        with self.assertRaises(AiNotFoundError):
            get_or_create_fix_suggestion(
                company=self.company,
                check_id="LE-04",
                dcs_run_id=running.id,
                provider=MockAiProvider(),
            )

    def test_provider_prompt_never_contains_pii(self):
        self.run.metadata["check_results"] = [
            {
                "check_id": "LE-04",
                "status": "FAIL",
                "severity": "high",
                "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
                "provenance": {
                    "mismatches": [
                        {
                            "path": "contact.email",
                            "kind": "conflict",
                            "side": "shopify",
                            "value": "alice@brand.com",
                        }
                    ]
                },
            }
        ]
        self.run.save(update_fields=["metadata"])
        capture = CapturePromptProvider()
        get_or_create_fix_suggestion(
            company=self.company,
            check_id="LE-04",
            provider=capture,
        )
        self.assertNotIn("alice@brand.com", capture.last_user_prompt)
        self.assertNotIn('"value"', capture.last_user_prompt)
        mismatches = capture.last_context.get("finding_summary", {}).get("mismatches", [])
        for row in mismatches:
            self.assertNotIn("value", row)


@override_settings(AI_ENABLED=True, AI_PROVIDER="mock")
class FixSuggestionApiTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="AI API", slug="ai-api")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Lumera Skin",
            domain="lumera.example.com",
        )
        self.admin = User.objects.create_user(
            email="admin@ai-api.test",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        _seed_masters()
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "check_results": [
                    {
                        "check_id": "LE-04",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
                    }
                ],
                "dcs_run": {
                    "run_state": "SCORED",
                    "check_results": [
                        {
                            "check_id": "LE-04",
                            "status": "FAIL",
                            "severity": "high",
                            "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
                        }
                    ],
                },
            },
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_post_creates_then_caches(self):
        url = "/api/v1/ai/suggestions/fix/"
        first = self.client.post(url, {"check_id": "LE-04"}, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.data["cached"])
        self.assertEqual(first.data["check_id"], "LE-04")
        self.assertIn("headline", first.data["payload"])
        self.assertIn("suggestions", first.data["payload"])

        second = self.client.post(url, {"check_id": "LE-04"}, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["cached"])
        self.assertEqual(second.data["suggestion_id"], first.data["suggestion_id"])

    def test_post_unknown_check_404(self):
        response = self.client.post(
            "/api/v1/ai/suggestions/fix/",
            {"check_id": "NO-PE"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    @override_settings(AI_ENABLED=False)
    def test_post_ai_disabled_503(self):
        response = self.client.post(
            "/api/v1/ai/suggestions/fix/",
            {"check_id": "LE-04"},
            format="json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "ai_disabled")

    def test_missing_check_id_400(self):
        response = self.client.post("/api/v1/ai/suggestions/fix/", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_post_gate_denied_422(self):
        from dataruns.ai.privacy_gate import GateResult

        denied = GateResult(ok=False, reason_code="pii_remaining", context=None)
        with patch(
            "dataruns.ai.service.ensure_safe_context",
            return_value=denied,
        ):
            response = self.client.post(
                "/api/v1/ai/suggestions/fix/",
                {"check_id": "LE-04"},
                format="json",
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["code"], "gate_denied")
        self.assertEqual(response.data["reason"], "pii_remaining")

    def test_post_json_retry_exhausted_503(self):
        with patch(
            "dataruns.ai.service.get_ai_provider",
            return_value=FlakyJsonProvider(fail_times=5),
        ):
            response = self.client.post(
                "/api/v1/ai/suggestions/fix/",
                {"check_id": "LE-04"},
                format="json",
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "json_retry_exhausted")

    @override_settings(AI_ENABLED=True, AI_PROVIDER="mistral")
    def test_post_mistral_not_configured_503(self):
        response = self.client.post(
            "/api/v1/ai/suggestions/fix/",
            {"check_id": "LE-04"},
            format="json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "provider_not_configured")
        failed = AiCall.objects.filter(status=AiCall.Status.FAILED)
        self.assertEqual(failed.count(), 1)
        self.assertEqual(failed.first().error_code, "provider_not_configured")
        self.assertEqual(AiSuggestion.objects.count(), 0)
