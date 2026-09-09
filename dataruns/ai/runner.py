"""Shared gated get-or-create for AI-01 task types."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction

from dataruns.ai.complete import complete_json
from dataruns.ai.constants import DEFAULT_MODEL_ID, DEFAULT_PROVIDER, POLICY_VERSION
from dataruns.ai.exceptions import (
    AiDisabledError,
    AiGateDeniedError,
    AiJsonRetryExhaustedError,
    AiProviderError,
)
from dataruns.ai.fingerprints import compute_fingerprint
from dataruns.ai.persistence import create_ai_call, get_cached_suggestion, upsert_ai_suggestion
from dataruns.ai.privacy_gate import ensure_safe_context
from dataruns.ai.prompts import system_prompt_v1
from dataruns.ai.providers import get_ai_provider
from dataruns.ai.providers.base import AiProvider
from dataruns.models import AiCall, AiSuggestion, DataRun
from tenants.models import Company

logger = logging.getLogger(__name__)


@dataclass
class AiTaskResult:
    suggestion: AiSuggestion
    fingerprint: str
    cached: bool
    model: str
    prompt_version: str
    provider: str


def ai_enabled() -> bool:
    return bool(getattr(settings, "AI_ENABLED", False))


def policy_version() -> str:
    return str(
        getattr(settings, "AI_PRIVACY_POLICY_VERSION", None) or POLICY_VERSION
    ).strip() or POLICY_VERSION


def model_id() -> str:
    return str(getattr(settings, "MISTRAL_MODEL", None) or DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID


def timeout_seconds() -> float:
    return float(getattr(settings, "AI_CALL_TIMEOUT_SECONDS", 30) or 30)


def temperature() -> float:
    return float(getattr(settings, "AI_TEMPERATURE", 0.3) or 0.3)


def provider_label(provider: AiProvider | None = None) -> str:
    if provider is not None:
        return getattr(provider, "name", DEFAULT_PROVIDER)
    configured = str(getattr(settings, "AI_PROVIDER", "mock") or "mock").strip().lower()
    return configured or "mock"


def max_retries_clamped() -> int:
    try:
        raw = int(getattr(settings, "AI_JSON_MAX_RETRIES", 3))
    except (TypeError, ValueError):
        raw = 3
    return max(1, min(3, raw))


def build_user_prompt(*, task_prompt: str, context: dict[str, Any]) -> str:
    body = json.dumps(context, sort_keys=True, separators=(",", ":"))
    return f"{task_prompt.strip()}\n\nALLOWLISTED_CONTEXT_JSON:\n{body}\n"


def run_gated_ai_task(
    *,
    company: Company,
    task_type: str,
    prompt_version: str,
    projected: dict[str, Any],
    task_prompt: str,
    check_id: str | None = None,
    data_run: DataRun | None = None,
    provider: AiProvider | None = None,
    skip_cache: bool = False,
) -> AiTaskResult:
    """Allowlist context already projected → PrivacyGate → cache → provider → persist."""
    if not ai_enabled():
        raise AiDisabledError()

    policy = policy_version()
    model = model_id()
    normalized_check_id = str(check_id or projected.get("check_id") or "").strip().upper()
    gate = ensure_safe_context(projected)
    fingerprint = compute_fingerprint(
        task_type=task_type,
        prompt_version=prompt_version,
        allowlisted_context=gate.context if gate.ok and gate.context else projected,
        policy_version=policy,
    )

    if not gate.ok or gate.context is None:
        create_ai_call(
            company=company,
            task_type=task_type,
            fingerprint=fingerprint,
            prompt_version=prompt_version,
            policy_version=policy,
            model=model,
            provider=provider_label(provider),
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
            task_type=task_type,
            fingerprint=fingerprint,
        )
        if cached is not None:
            cached_call = cached.ai_call if cached.ai_call_id else None
            return AiTaskResult(
                suggestion=cached,
                fingerprint=fingerprint,
                cached=True,
                model=cached_call.model if cached_call else model,
                prompt_version=prompt_version,
                provider=cached_call.provider if cached_call else provider_label(provider),
            )

    active_provider = provider
    if active_provider is None:
        try:
            active_provider = get_ai_provider()
        except AiProviderError as exc:
            create_ai_call(
                company=company,
                task_type=task_type,
                fingerprint=fingerprint,
                prompt_version=prompt_version,
                policy_version=policy,
                model=model,
                provider=provider_label(None),
                status=AiCall.Status.FAILED,
                check_id=normalized_check_id,
                dcs_data_run=data_run,
                error_code=exc.code,
            )
            raise
    try:
        payload, provider_result, _attempts = complete_json(
            provider=active_provider,
            task_type=task_type,
            system_prompt=system_prompt_v1(),
            user_prompt=build_user_prompt(task_prompt=task_prompt, context=safe_context),
            context=safe_context,
            model=model,
            temperature=temperature(),
            timeout_seconds=timeout_seconds(),
            max_retries=max_retries_clamped(),
            trace_metadata={
                "company_id": str(company.id),
                "prompt_version": prompt_version,
                "policy_version": policy,
                "check_id": normalized_check_id or None,
            },
        )
    except AiJsonRetryExhaustedError as exc:
        create_ai_call(
            company=company,
            task_type=task_type,
            fingerprint=fingerprint,
            prompt_version=prompt_version,
            policy_version=policy,
            model=model,
            provider=provider_label(active_provider),
            status=AiCall.Status.FAILED,
            check_id=normalized_check_id,
            dcs_data_run=data_run,
            error_code=exc.code,
        )
        raise
    except AiProviderError as exc:
        create_ai_call(
            company=company,
            task_type=task_type,
            fingerprint=fingerprint,
            prompt_version=prompt_version,
            policy_version=policy,
            model=model,
            provider=provider_label(active_provider),
            status=AiCall.Status.FAILED,
            check_id=normalized_check_id,
            dcs_data_run=data_run,
            error_code=exc.code,
        )
        raise

    try:
        with transaction.atomic():
            call = create_ai_call(
                company=company,
                task_type=task_type,
                fingerprint=fingerprint,
                prompt_version=prompt_version,
                policy_version=policy,
                model=provider_result.model or model,
                provider=provider_result.provider or provider_label(active_provider),
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
                task_type=task_type,
                fingerprint=fingerprint,
                payload=payload,
                check_id=normalized_check_id,
                dcs_data_run=data_run,
            )
    except IntegrityError:
        raced = get_cached_suggestion(
            company=company,
            task_type=task_type,
            fingerprint=fingerprint,
        )
        if raced is None:
            raise AiProviderError(
                "AI suggestion could not be saved.",
                code="provider_error",
            )
        raced_call = raced.ai_call if raced.ai_call_id else None
        return AiTaskResult(
            suggestion=raced,
            fingerprint=fingerprint,
            cached=True,
            model=raced_call.model if raced_call else model,
            prompt_version=prompt_version,
            provider=raced_call.provider if raced_call else provider_label(active_provider),
        )
    return AiTaskResult(
        suggestion=suggestion,
        fingerprint=fingerprint,
        cached=False,
        model=call.model,
        prompt_version=prompt_version,
        provider=call.provider,
    )


def serialize_ai_result(result: AiTaskResult) -> dict[str, Any]:
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
