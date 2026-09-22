"""Persist AiCall / AiSuggestion rows (PRD-AI-01 §7)."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from dataruns.ai.constants import SCHEMA_VERSION
from dataruns.ai.schemas import parse_task_output
from dataruns.models import AiCall, AiSuggestion, DataRun
from tenants.models import Company


def build_envelope(
    *,
    prompt_version: str,
    policy_version: str,
    model: str,
    provider: str,
    fingerprint: str,
    output: dict[str, Any],
) -> dict[str, Any]:
    """§6.4 stored envelope metadata."""
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_version": prompt_version,
        "policy_version": policy_version,
        "model": model,
        "provider": provider,
        "fingerprint": fingerprint,
        "output": output,
    }


def extract_headline(task_type: str, payload: dict[str, Any]) -> str:
    if task_type == "fix_suggestion":
        return str(payload.get("headline") or "").strip()[:240]
    if task_type == "explain_finding":
        return str(payload.get("headline") or "").strip()[:240]
    if task_type == "report_narrative":
        summary = str(payload.get("exec_summary") or "").strip()
        return summary[:240] if summary else "Report narrative"
    if task_type == "nba_blurb":
        return str(payload.get("blurb") or "").strip()[:240]
    return str(payload.get("headline") or task_type)[:240]


@transaction.atomic
def create_ai_call(
    *,
    company: Company,
    task_type: str,
    fingerprint: str,
    prompt_version: str,
    policy_version: str,
    model: str,
    provider: str,
    status: str,
    check_id: str | None = None,
    dcs_data_run: DataRun | None = None,
    langsmith_run_id: str | None = None,
    error_code: str | None = None,
    latency_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> AiCall:
    """Always persist an attempt — success, failed, or gate_denied."""
    return AiCall.objects.create(
        company=company,
        task_type=task_type,
        check_id=check_id,
        dcs_data_run=dcs_data_run,
        fingerprint=fingerprint,
        prompt_version=prompt_version,
        policy_version=policy_version,
        model=model,
        provider=provider,
        langsmith_run_id=langsmith_run_id,
        status=status,
        error_code=error_code,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def get_cached_suggestion(
    *,
    company: Company,
    task_type: str,
    fingerprint: str,
) -> AiSuggestion | None:
    return (
        AiSuggestion.objects.filter(
            company=company,
            task_type=task_type,
            fingerprint=fingerprint,
        )
        .select_related("ai_call")
        .first()
    )


def get_latest_suggestion_for_check(
    *,
    company: Company,
    task_type: str,
    check_id: str,
    prefer_dcs_run_id: int | str | None = None,
) -> AiSuggestion | None:
    """Latest saved suggestion for a check — prefer current DCS run when set."""
    normalized = str(check_id or "").strip().upper()
    if not normalized:
        return None
    base = AiSuggestion.objects.filter(
        company=company,
        task_type=task_type,
        check_id=normalized,
    ).select_related("ai_call", "dcs_data_run")
    if prefer_dcs_run_id is not None and str(prefer_dcs_run_id).strip() != "":
        same_run = (
            base.filter(dcs_data_run_id=prefer_dcs_run_id)
            .order_by("-updated_at")
            .first()
        )
        if same_run is not None:
            return same_run
    return base.order_by("-updated_at").first()


@transaction.atomic
def upsert_ai_suggestion(
    *,
    company: Company,
    ai_call: AiCall,
    task_type: str,
    fingerprint: str,
    payload: dict[str, Any],
    check_id: str | None = None,
    dcs_data_run: DataRun | None = None,
    content_hash: str | None = None,
) -> AiSuggestion:
    """
    Upsert customer-facing artifact on success.

    Same company + task + fingerprint → update payload/headline and link latest call.
    New fingerprint → new row.
    """
    validated = parse_task_output(task_type, payload)
    output = validated.model_dump(mode="json")
    headline = extract_headline(task_type, output)
    normalized_check = str(check_id or output.get("check_id") or "").strip().upper()

    defaults: dict[str, Any] = {
        "ai_call": ai_call,
        "check_id": normalized_check,
        "dcs_data_run": dcs_data_run,
        "payload_json": output,
        "headline": headline,
    }
    # Only write content_hash when provided — avoid wiping on unrelated upserts.
    if content_hash is not None:
        defaults["content_hash"] = str(content_hash or "").strip().lower()

    row, _created = AiSuggestion.objects.update_or_create(
        company=company,
        task_type=task_type,
        fingerprint=fingerprint,
        defaults=defaults,
    )
    return row
