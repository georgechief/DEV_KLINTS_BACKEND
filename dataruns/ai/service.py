"""get_or_create Fix AI suggestion (PRD-AI-01 §3 / §9.1)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction

from dataruns.ai.allowlist import project_fix_suggestion_context
from dataruns.ai.complete import complete_json
from dataruns.ai.constants import (
    DEFAULT_MODEL_ID,
    DEFAULT_PROVIDER,
    POLICY_VERSION,
    PROMPT_FIX_SUGGESTION_V1,
    TASK_FIX_SUGGESTION,
)
from dataruns.ai.exceptions import (
    AiDisabledError,
    AiGateDeniedError,
    AiJsonRetryExhaustedError,
    AiProviderError,
)
from dataruns.ai.fingerprints import compute_fingerprint
from dataruns.ai.issue_loader import load_issue_for_ai
from dataruns.ai.persistence import create_ai_call, get_cached_suggestion, upsert_ai_suggestion
from dataruns.ai.privacy_gate import ensure_safe_context
from dataruns.ai.prompts import fix_suggestion_prompt_v1, system_prompt_v1
from dataruns.ai.providers import get_ai_provider
from dataruns.ai.providers.base import AiProvider
from dataruns.models import AiCall, AiSuggestion
from tenants.models import Company

logger = logging.getLogger(__name__)


@dataclass
class FixSuggestionResult:
    suggestion: AiSuggestion
    fingerprint: str
    cached: bool
    model: str
    prompt_version: str
    provider: str


def _ai_enabled() -> bool:
    return bool(getattr(settings, "AI_ENABLED", False))


def _policy_version() -> str:
    return str(
        getattr(settings, "AI_PRIVACY_POLICY_VERSION", None) or POLICY_VERSION
    ).strip() or POLICY_VERSION


def _model_id() -> str:
    return str(getattr(settings, "MISTRAL_MODEL", None) or DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID


def _timeout_seconds() -> float:
    return float(getattr(settings, "AI_CALL_TIMEOUT_SECONDS", 30) or 30)


def _temperature() -> float:
    return float(getattr(settings, "AI_TEMPERATURE", 0.3) or 0.3)


def _provider_label(provider: AiProvider | None = None) -> str:
    if provider is not None:
        return getattr(provider, "name", DEFAULT_PROVIDER)
    # Match get_ai_provider() — empty AI_PROVIDER falls back to mock, not mistral.
    configured = str(getattr(settings, "AI_PROVIDER", "mock") or "mock").strip().lower()
    return configured or "mock"


def _max_retries_clamped() -> int:
    """PRD-AI-01 §6: parse retry ≤3."""
    try:
        raw = int(getattr(settings, "AI_JSON_MAX_RETRIES", 3))
    except (TypeError, ValueError):
        raw = 3
    return max(1, min(3, raw))


def _build_user_prompt(context: dict[str, Any]) -> str:
    task_prompt = fix_suggestion_prompt_v1().strip()
    body = json.dumps(context, sort_keys=True, separators=(",", ":"))
    return f"{task_prompt}\n\nALLOWLISTED_CONTEXT_JSON:\n{body}\n"


def get_or_create_fix_suggestion(
    *,
    company: Company,
    check_id: str,
    dcs_run_id: int | None = None,
    provider: AiProvider | None = None,
    skip_cache: bool = False,
) -> FixSuggestionResult:
    """
    Allowlist → PrivacyGate → fingerprint → cache → provider → validate → persist.

    skip_cache is off by default (PRD: no billable re-call on fingerprint hit).
    """
    if not _ai_enabled():
        raise AiDisabledError()

    data_run, issue = load_issue_for_ai(
        company=company,
        check_id=check_id,
        dcs_run_id=dcs_run_id,
    )
    normalized_check_id = str(issue.get("check_id") or check_id).strip().upper()
    prompt_version = PROMPT_FIX_SUGGESTION_V1
    policy_version = _policy_version()
    model = _model_id()

    projected = project_fix_suggestion_context(
        issue=issue,
        company_name=company.name,
        company_domain=getattr(company, "domain", None),
        dcs_run_id=data_run.id,
        prompt_version=prompt_version,
        policy_version=policy_version,
    )
    gate = ensure_safe_context(projected)
    fingerprint = compute_fingerprint(
        task_type=TASK_FIX_SUGGESTION,
        prompt_version=prompt_version,
        allowlisted_context=gate.context if gate.ok and gate.context else projected,
        policy_version=policy_version,
    )

    if not gate.ok or gate.context is None:
        create_ai_call(
            company=company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=fingerprint,
            prompt_version=prompt_version,
            policy_version=policy_version,
            model=model,
            provider=_provider_label(provider),
            status=AiCall.Status.GATE_DENIED,
            check_id=normalized_check_id,
            dcs_data_run=data_run,
            error_code=gate.reason_code,
        )
        raise AiGateDeniedError(reason=gate.reason_code)

    safe_context = gate.context

    if not skip_cache:
        cached = get_cached_suggestion(
            company=company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=fingerprint,
        )
        if cached is not None:
            cached_call = cached.ai_call if cached.ai_call_id else None
            return FixSuggestionResult(
                suggestion=cached,
                fingerprint=fingerprint,
                cached=True,
                model=cached_call.model if cached_call else model,
                prompt_version=prompt_version,
                provider=cached_call.provider if cached_call else _provider_label(provider),
            )

    active_provider = provider
    if active_provider is None:
        try:
            active_provider = get_ai_provider()
        except AiProviderError as exc:
            create_ai_call(
                company=company,
                task_type=TASK_FIX_SUGGESTION,
                fingerprint=fingerprint,
                prompt_version=prompt_version,
                policy_version=policy_version,
                model=model,
                provider=_provider_label(None),
                status=AiCall.Status.FAILED,
                check_id=normalized_check_id,
                dcs_data_run=data_run,
                error_code=exc.code,
            )
            raise
    try:
        payload, provider_result, _attempts = complete_json(
            provider=active_provider,
            task_type=TASK_FIX_SUGGESTION,
            system_prompt=system_prompt_v1(),
            user_prompt=_build_user_prompt(safe_context),
            context=safe_context,
            model=model,
            temperature=_temperature(),
            timeout_seconds=_timeout_seconds(),
            max_retries=_max_retries_clamped(),
        )
    except AiJsonRetryExhaustedError as exc:
        create_ai_call(
            company=company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=fingerprint,
            prompt_version=prompt_version,
            policy_version=policy_version,
            model=model,
            provider=_provider_label(active_provider),
            status=AiCall.Status.FAILED,
            check_id=normalized_check_id,
            dcs_data_run=data_run,
            error_code=exc.code,
        )
        raise
    except AiProviderError as exc:
        create_ai_call(
            company=company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=fingerprint,
            prompt_version=prompt_version,
            policy_version=policy_version,
            model=model,
            provider=_provider_label(active_provider),
            status=AiCall.Status.FAILED,
            check_id=normalized_check_id,
            dcs_data_run=data_run,
            error_code=exc.code,
        )
        raise

    with transaction.atomic():
        call = create_ai_call(
            company=company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=fingerprint,
            prompt_version=prompt_version,
            policy_version=policy_version,
            model=provider_result.model or model,
            provider=provider_result.provider or _provider_label(active_provider),
            status=AiCall.Status.SUCCESS,
            check_id=normalized_check_id,
            dcs_data_run=data_run,
            langsmith_run_id=provider_result.langsmith_run_id,
            latency_ms=provider_result.latency_ms,
            input_tokens=provider_result.input_tokens,
            output_tokens=provider_result.output_tokens,
        )
        suggestion = upsert_ai_suggestion(
            company=company,
            ai_call=call,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=fingerprint,
            payload=payload,
            check_id=normalized_check_id,
            dcs_data_run=data_run,
        )
    return FixSuggestionResult(
        suggestion=suggestion,
        fingerprint=fingerprint,
        cached=False,
        model=call.model,
        prompt_version=prompt_version,
        provider=call.provider,
    )


def serialize_fix_suggestion_result(result: FixSuggestionResult) -> dict[str, Any]:
    suggestion = result.suggestion
    return {
        "suggestion_id": str(suggestion.id),
        "check_id": suggestion.check_id,
        "fingerprint": f"sha256:{result.fingerprint}",
        "cached": result.cached,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "payload": suggestion.payload_json,
    }
