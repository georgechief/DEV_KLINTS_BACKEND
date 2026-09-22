"""Get-or-create AI-01 tasks (PRD-AI-01 §3 / §9)."""

from __future__ import annotations

import logging
from typing import Any

from dataruns.ai.allowlist import (
    project_explain_finding_context,
    project_fix_suggestion_context,
    project_nba_blurb_context,
)
from dataruns.ai.constants import (
    PROMPT_EXPLAIN_FINDING_V1,
    PROMPT_FIX_SUGGESTION_V1,
    PROMPT_NBA_BLURB_V1,
    PROMPT_REPORT_NARRATIVE_V1,
    TASK_EXPLAIN_FINDING,
    TASK_FIX_SUGGESTION,
    TASK_NBA_BLURB,
    TASK_REPORT_NARRATIVE,
)
from dataruns.ai.exceptions import (
    AiDisabledError,
    AiGateDeniedError,
    AiJsonRetryExhaustedError,
    AiNotFoundError,
    AiProviderError,
)
from dataruns.ai.issue_loader import load_issue_for_ai, resolve_dcs_run_for_ai
from dataruns.ai.prompts import (
    explain_finding_prompt_v1,
    fix_suggestion_prompt_v1,
    nba_blurb_prompt_v1,
    report_narrative_prompt_v1,
)
from dataruns.ai.report_context import build_report_narrative_projected
from dataruns.ai.runner import (
    AiTaskResult,
    ai_enabled,
    policy_version,
    result_from_saved_suggestion,
    run_gated_ai_task,
    serialize_ai_result,
)
from dataruns.ai.fingerprints import compute_fix_content_hash
from dataruns.ai.privacy_gate import ensure_safe_context
from dataruns.ai.providers.base import AiProvider
from dataruns.ai.schemas import parse_task_output
from dataruns.models import AssessmentReport, AiSuggestion
from tenants.models import Company

logger = logging.getLogger(__name__)

FixSuggestionResult = AiTaskResult


def _valid_fix_payload(suggestion: AiSuggestion) -> bool:
    payload = suggestion.payload_json if isinstance(suggestion.payload_json, dict) else None
    if not payload:
        return False
    try:
        parse_task_output(TASK_FIX_SUGGESTION, payload)
    except Exception:
        return False
    return True


def _first_valid_soft(
    qs,
    *,
    check_id: str,
    stale: bool,
) -> AiTaskResult | None:
    """Walk newest-first; skip invalid payloads instead of failing the soft path."""
    for soft in qs.iterator(chunk_size=20):
        if _valid_fix_payload(soft):
            return result_from_saved_suggestion(
                suggestion=soft,
                prompt_version=PROMPT_FIX_SUGGESTION_V1,
                stale=stale,
            )
        logger.info(
            "fix_suggestion_soft_skip_invalid check_id=%s suggestion_id=%s",
            check_id,
            soft.id,
        )
    return None


def _soft_fix_suggestion_or_none(
    *,
    company: Company,
    check_id: str,
    content_hash: str,
) -> AiTaskResult | None:
    """
    Soft hit when a valid saved suggestion matches finding-level content_hash.

    - Prefer any run whose content_hash matches current finding
    - Legacy empty content_hash → reuse latest blank-hash row, mark stale
    - Never reuse a hashed row for a different finding
    """
    normalized = str(check_id or "").strip().upper()
    current = str(content_hash or "").strip().lower()
    base = AiSuggestion.objects.filter(
        company=company,
        task_type=TASK_FIX_SUGGESTION,
        check_id=normalized,
    ).select_related("ai_call", "dcs_data_run")

    if current:
        matched = _first_valid_soft(
            base.filter(content_hash=current).order_by("-updated_at"),
            check_id=normalized,
            stale=False,
        )
        if matched is not None:
            return matched

    # Legacy rows only — never reuse a hashed row with a different finding.
    return _first_valid_soft(
        base.filter(content_hash="").order_by("-updated_at"),
        check_id=normalized,
        stale=True,
    )


def get_or_create_fix_suggestion(
    *,
    company: Company,
    check_id: str,
    dcs_run_id: int | None = None,
    provider: AiProvider | None = None,
    skip_cache: bool = False,
    force_refresh: bool = False,
) -> AiTaskResult:
    """
    Soft-first by finding content_hash (no Mistral) unless force_refresh / skip_cache.

    Same check + same finding_summary → reuse DB across DCS runs.
    Finding changed → generate. force_refresh always generates.
    """
    if not ai_enabled():
        raise AiDisabledError()

    data_run, issue = load_issue_for_ai(
        company=company,
        check_id=check_id,
        dcs_run_id=dcs_run_id,
    )
    normalized_check_id = str(issue.get("check_id") or check_id).strip().upper()
    prompt_version = PROMPT_FIX_SUGGESTION_V1
    projected = project_fix_suggestion_context(
        issue=issue,
        company_name=company.name,
        company_domain=getattr(company, "domain", None),
        dcs_run_id=data_run.id,
        prompt_version=prompt_version,
        policy_version=policy_version(),
    )
    # Hash post-PrivacyGate so soft compare matches what we persist/send.
    gate = ensure_safe_context(projected)
    hash_context = gate.context if gate.ok and gate.context is not None else projected
    content_hash = compute_fix_content_hash(hash_context)

    soft_ok = not force_refresh and not skip_cache
    if soft_ok:
        soft_result = _soft_fix_suggestion_or_none(
            company=company,
            check_id=normalized_check_id,
            content_hash=content_hash,
        )
        if soft_result is not None:
            return soft_result

    return run_gated_ai_task(
        company=company,
        task_type=TASK_FIX_SUGGESTION,
        prompt_version=prompt_version,
        projected=projected,
        task_prompt=fix_suggestion_prompt_v1(),
        check_id=normalized_check_id,
        data_run=data_run,
        provider=provider,
        skip_cache=force_refresh or skip_cache,
        content_hash=content_hash,
    )


def get_or_create_explain_finding(
    *,
    company: Company,
    check_id: str,
    dcs_run_id: int | None = None,
    provider: AiProvider | None = None,
    skip_cache: bool = False,
) -> AiTaskResult:
    if not ai_enabled():
        raise AiDisabledError()

    data_run, issue = load_issue_for_ai(
        company=company,
        check_id=check_id,
        dcs_run_id=dcs_run_id,
    )
    normalized_check_id = str(issue.get("check_id") or check_id).strip().upper()
    prompt_version = PROMPT_EXPLAIN_FINDING_V1
    projected = project_explain_finding_context(
        issue=issue,
        company_name=company.name,
        company_domain=getattr(company, "domain", None),
        dcs_run_id=data_run.id,
        prompt_version=prompt_version,
        policy_version=policy_version(),
    )
    return run_gated_ai_task(
        company=company,
        task_type=TASK_EXPLAIN_FINDING,
        prompt_version=prompt_version,
        projected=projected,
        task_prompt=explain_finding_prompt_v1(),
        check_id=normalized_check_id,
        data_run=data_run,
        provider=provider,
        skip_cache=skip_cache,
    )


def get_or_create_nba_blurb(
    *,
    company: Company,
    check_id: str,
    dcs_run_id: int | None = None,
    plan_rank: int | None = None,
    provider: AiProvider | None = None,
    skip_cache: bool = False,
) -> AiTaskResult:
    if not ai_enabled():
        raise AiDisabledError()

    data_run, issue = load_issue_for_ai(
        company=company,
        check_id=check_id,
        dcs_run_id=dcs_run_id,
    )
    normalized_check_id = str(issue.get("check_id") or check_id).strip().upper()
    prompt_version = PROMPT_NBA_BLURB_V1
    projected = project_nba_blurb_context(
        issue=issue,
        plan_rank=plan_rank,
        company_name=company.name,
        company_domain=getattr(company, "domain", None),
        dcs_run_id=data_run.id,
        prompt_version=prompt_version,
        policy_version=policy_version(),
    )
    return run_gated_ai_task(
        company=company,
        task_type=TASK_NBA_BLURB,
        prompt_version=prompt_version,
        projected=projected,
        task_prompt=nba_blurb_prompt_v1(),
        check_id=normalized_check_id,
        data_run=data_run,
        provider=provider,
        skip_cache=skip_cache,
    )


def get_or_create_report_narrative(
    *,
    company: Company,
    dcs_run_id: int | None = None,
    provider: AiProvider | None = None,
    skip_cache: bool = False,
) -> AiTaskResult:
    if not ai_enabled():
        raise AiDisabledError()

    data_run = resolve_dcs_run_for_ai(company=company, dcs_run_id=dcs_run_id)
    prompt_version = PROMPT_REPORT_NARRATIVE_V1
    projected = build_report_narrative_projected(
        company=company,
        data_run=data_run,
        prompt_version=prompt_version,
        policy_version=policy_version(),
    )
    return run_gated_ai_task(
        company=company,
        task_type=TASK_REPORT_NARRATIVE,
        prompt_version=prompt_version,
        projected=projected,
        task_prompt=report_narrative_prompt_v1(),
        check_id="",
        data_run=data_run,
        provider=provider,
        skip_cache=skip_cache,
    )


def narratives_dict_from_result(result: AiTaskResult) -> dict[str, Any]:
    return {
        "report_narrative": result.suggestion.payload_json,
        "suggestion_id": str(result.suggestion.id),
        "prompt_version": result.prompt_version,
        "model": result.model,
        "cached": result.cached,
    }


def attach_narratives_to_report(report: AssessmentReport, result: AiTaskResult) -> None:
    report.ai_narratives = narratives_dict_from_result(result)
    report.save(update_fields=["ai_narratives"])


def attach_report_narrative_fail_open(report: AssessmentReport) -> None:
    """Compose still succeeds if AI is off, gated, or down (PRD fail-open for reports)."""
    try:
        if not ai_enabled():
            return
        result = get_or_create_report_narrative(
            company=report.company,
            dcs_run_id=report.dcs_data_run_id,
        )
        attach_narratives_to_report(report, result)
    except (
        AiDisabledError,
        AiGateDeniedError,
        AiJsonRetryExhaustedError,
        AiNotFoundError,
        AiProviderError,
    ) as exc:
        logger.info(
            "report_narrative_skipped report_id=%s code=%s",
            report.id,
            getattr(exc, "code", "unknown"),
        )
    except Exception:
        logger.exception("report_narrative_attach_failed report_id=%s", report.id)


def serialize_fix_suggestion_result(result: AiTaskResult) -> dict[str, Any]:
    return serialize_ai_result(result)
