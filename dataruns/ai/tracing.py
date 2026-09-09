"""LangSmith tracing for AI-01 — allowlisted I/O only (PRD §4.4 / §8.2).

Tracing is fail-open: a LangSmith outage must never block a suggestion.
Never send raw evidence, mismatch values, or ungated prompts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from django.conf import settings

logger = logging.getLogger(__name__)


def _env_flag(*names: str) -> bool:
    for name in names:
        raw = getattr(settings, name, False)
        if isinstance(raw, bool):
            if raw:
                return True
            continue
        token = str(raw or "").strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
    return False


def _env_str(*names: str, default: str = "") -> str:
    for name in names:
        token = str(getattr(settings, name, "") or "").strip()
        if token:
            return token
    return default


def tracing_enabled() -> bool:
    # Django tests must not POST traces unless a test opts in.
    import sys

    if "test" in sys.argv and not getattr(settings, "AI_LANGSMITH_IN_TESTS", False):
        return False
    if not _env_flag("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        return False
    return bool(_env_str("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"))


def _project_name() -> str:
    return _env_str("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT", default="klints-mvp1-ai")


def _endpoint() -> str:
    return _env_str(
        "LANGSMITH_ENDPOINT",
        "LANGCHAIN_ENDPOINT",
        default="https://api.smith.langchain.com",
    )


def _api_key() -> str:
    return _env_str("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")


def allowlisted_trace_inputs(
    *,
    task_type: str,
    model: str,
    context: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Only gated allowlist + ids — never raw prompts or evidence values."""
    meta = metadata or {}
    return {
        "task_type": task_type,
        "model": model,
        "check_id": context.get("check_id") or meta.get("check_id"),
        "company_id": meta.get("company_id"),
        "prompt_version": meta.get("prompt_version") or context.get("prompt_version"),
        "policy_version": meta.get("policy_version") or context.get("policy_version"),
        "allowlisted_context": context,
    }


@dataclass
class AiTrace:
    """Handle for one complete_json run. No-op when tracing is off."""

    enabled: bool = False
    run_id: str | None = None
    _run: Any = field(default=None, repr=False)

    def finish_ok(
        self,
        *,
        payload: dict[str, Any],
        attempts: int,
        model: str,
        provider: str,
    ) -> None:
        if not self.enabled or self._run is None:
            return
        try:
            self._run.end(
                outputs={
                    "payload": payload,
                    "attempts": attempts,
                    "model": model,
                    "provider": provider,
                }
            )
            self._run.patch()
        except Exception:
            logger.info("ai_langsmith_finish_ok_failed")

    def finish_error(self, exc: BaseException) -> None:
        if not self.enabled or self._run is None:
            return
        try:
            code = getattr(exc, "code", None)
            self._run.end(
                error=f"{type(exc).__name__}:{code or 'error'}",
                outputs={"error_type": type(exc).__name__, "error_code": code},
            )
            self._run.patch()
        except Exception:
            logger.info("ai_langsmith_finish_error_failed")


def start_ai_trace(
    *,
    task_type: str,
    model: str,
    context: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> AiTrace:
    if not tracing_enabled():
        return AiTrace(enabled=False)
    try:
        from langsmith.run_trees import RunTree

        inputs = allowlisted_trace_inputs(
            task_type=task_type,
            model=model,
            context=context,
            metadata=metadata,
        )
        tags = [
            f"task_type:{task_type}",
            f"check_id:{inputs.get('check_id') or 'none'}",
            f"prompt_version:{inputs.get('prompt_version') or 'none'}",
            f"policy_version:{inputs.get('policy_version') or 'none'}",
        ]
        if inputs.get("company_id"):
            tags.append(f"company_id:{inputs['company_id']}")
        from langsmith import Client

        ls_client = Client(api_key=_api_key(), api_url=_endpoint())
        run = RunTree(
            name="klints.ai.complete_json",
            run_type="llm",
            inputs=inputs,
            tags=tags,
            project_name=_project_name(),
            client=ls_client,
            extra={
                "metadata": {
                    "task_type": task_type,
                    "check_id": inputs.get("check_id"),
                    "company_id": inputs.get("company_id"),
                    "prompt_version": inputs.get("prompt_version"),
                    "policy_version": inputs.get("policy_version"),
                }
            },
        )
        run.post()
        run_id = str(getattr(run, "id", "") or uuid4())
        return AiTrace(enabled=True, run_id=run_id, _run=run)
    except Exception:
        logger.info("ai_langsmith_start_failed")
        return AiTrace(enabled=False)
