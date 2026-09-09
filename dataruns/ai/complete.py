"""JSON-only complete helper with parse retry (PRD-AI-01 §6)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from dataruns.ai.exceptions import AiJsonRetryExhaustedError, AiProviderError
from dataruns.ai.privacy_gate import scan_for_leaks
from dataruns.ai.providers.base import AiProvider, ProviderResult
from dataruns.ai.schemas import parse_task_output
from dataruns.ai.tracing import start_ai_trace

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.I)


def _assert_output_matches_context(
    *,
    task_type: str,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> None:
    """Ensure model output cannot drift from gated input (PRD hard bans)."""
    if task_type in {"fix_suggestion", "explain_finding", "nba_blurb"}:
        expected = str(context.get("check_id") or "").strip().upper()
        actual = str(payload.get("check_id") or "").strip().upper()
        if expected and actual != expected:
            raise ValueError(
                f"Model check_id mismatch: expected {expected}, got {actual}"
            )


def _extract_json_object(text: str) -> dict[str, Any]:
    token = (text or "").strip()
    if not token:
        raise json.JSONDecodeError("Empty response", token, 0)
    fence = _JSON_FENCE_RE.search(token)
    if fence:
        token = fence.group(1).strip()
    try:
        parsed = json.loads(token)
    except json.JSONDecodeError:
        start = token.find("{")
        end = token.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(token[start : end + 1])
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("JSON root must be an object", token, 0)
    return parsed


def complete_json(
    *,
    provider: AiProvider,
    task_type: str,
    system_prompt: str,
    user_prompt: str,
    context: dict[str, Any],
    model: str,
    temperature: float = 0.3,
    timeout_seconds: float = 30.0,
    max_retries: int = 3,
    trace_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ProviderResult, int]:
    """
    Call provider, parse JSON, validate schema.

    Retries up to max_retries on parse/validation failure, then fail closed.
    Returns (validated_payload_dict, last_provider_result, attempts).
    Tracing (LangSmith) is always attempted from this helper so callers cannot skip it.
    """
    # PRD-AI-01 §6: retry ≤3; never zero attempts.
    try:
        retries = int(max_retries)
    except (TypeError, ValueError):
        retries = 3
    max_retries = max(1, min(3, retries))

    trace = start_ai_trace(
        task_type=task_type,
        model=model,
        context=context,
        metadata=trace_metadata,
    )
    try:
        payload, result, attempts = _complete_json_loop(
            provider=provider,
            task_type=task_type,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context=context,
            model=model,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        if trace.run_id:
            result.langsmith_run_id = result.langsmith_run_id or trace.run_id
        trace.finish_ok(
            payload=payload,
            attempts=attempts,
            model=result.model,
            provider=result.provider,
        )
        return payload, result, attempts
    except Exception as exc:
        trace.finish_error(exc)
        raise


def _complete_json_loop(
    *,
    provider: AiProvider,
    task_type: str,
    system_prompt: str,
    user_prompt: str,
    context: dict[str, Any],
    model: str,
    temperature: float,
    timeout_seconds: float,
    max_retries: int,
) -> tuple[dict[str, Any], ProviderResult, int]:
    last_error: Exception | None = None
    last_result: ProviderResult | None = None
    attempts = 0

    for attempt in range(1, max_retries + 1):
        attempts = attempt
        try:
            result = provider.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context=context,
                model=model,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
            )
            last_result = result
            raw_obj = _extract_json_object(result.text)
            validated = parse_task_output(task_type, raw_obj)
            payload = validated.model_dump(mode="json")
            _assert_output_matches_context(task_type=task_type, payload=payload, context=context)
            leak = scan_for_leaks(payload)
            if leak:
                raise ValueError(f"Model output failed privacy scan ({leak})")
            return payload, result, attempts
        except AiProviderError:
            raise
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            last_error = exc
            logger.info(
                "ai_complete_json_retry attempt=%s/%s task_type=%s error=%s",
                attempt,
                max_retries,
                task_type,
                type(exc).__name__,
            )
            continue

    # Exhausted — caller persists AiCall(status=failed).
    # Do not put raw model text into the client-facing message (PII / secrets).
    logger.info(
        "ai_complete_json_exhausted attempts=%s task_type=%s error=%s",
        attempts,
        task_type,
        type(last_error).__name__ if last_error else "unknown",
    )
    raise AiJsonRetryExhaustedError() from last_error
