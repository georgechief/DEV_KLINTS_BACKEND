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
    run_gated_ai_task,
    serialize_ai_result,
)
from dataruns.ai.providers.base import AiProvider
from dataruns.models import AssessmentReport
from tenants.models import Company

logger = logging.getLogger(__name__)

FixSuggestionResult = AiTaskResult


def get_or_create_fix_suggestion(
    *,
    company: Company,
    check_id: str,
    dcs_run_id: int | None = None,
    provider: AiProvider | None = None,
    skip_cache: bool = False,
) -> AiTaskResult:
    """
    Allowlist → PrivacyGate → fingerprint → cache → provider → validate → persist.

    skip_cache is off by default (PRD: no billable re-call on fingerprint hit).
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
    return run_gated_ai_task(
        company=company,
        task_type=TASK_FIX_SUGGESTION,
        prompt_version=prompt_version,
        projected=projected,
        task_prompt=fix_suggestion_prompt_v1(),
        check_id=normalized_check_id,
        data_run=data_run,
        provider=provider,
        skip_cache=skip_cache,
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
