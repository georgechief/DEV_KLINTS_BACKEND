"""Allowlisted rollup for report_narrative (PRD-AI-01 §6.3)."""

from __future__ import annotations

from typing import Any

from dataruns.ai.allowlist import project_report_narrative_context
from dataruns.dcs.worklist import (
    build_enriched_issues,
    coerce_headline_score,
    extract_dcs_payload,
    load_check_master_by_id,
    sort_worklist_issues,
)
from dataruns.models import DataRun
from dataruns.orchestration.candidates import build_fix_tasks_for_data_run
from dataruns.reports.resolve import resolve_architecture_assessment_for_run
from tenants.models import Company


def _finite_revenue(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount != amount:  # NaN
        return None
    return amount


def build_report_narrative_projected(
    *,
    company: Company,
    data_run: DataRun,
    prompt_version: str,
    policy_version: str,
) -> dict[str, Any]:
    metadata = data_run.metadata if isinstance(data_run.metadata, dict) else {}
    payload = extract_dcs_payload(metadata)
    headline_score = coerce_headline_score(payload.get("headline_score"))
    issues = build_enriched_issues(
        data_run=data_run,
        check_master_by_id=load_check_master_by_id(),
        cap=None,
    )
    ranked = sort_worklist_issues(issues)
    top_checks: list[dict[str, Any]] = []
    revenue_total = 0.0
    currency: str | None = None
    for issue in ranked[:8]:
        check_id = str(issue.get("check_id") or "").strip().upper()
        if not check_id:
            continue
        row: dict[str, Any] = {
            "check_id": check_id,
            "check_name": str(issue.get("title") or issue.get("check_name") or check_id),
            "severity": str(issue.get("severity") or ""),
            "status": str(issue.get("status") or "").upper(),
        }
        impact = _finite_revenue(issue.get("revenue_impact"))
        if impact is not None and impact > 0:
            row["revenue_impact"] = impact
            revenue_total += impact
        if currency is None:
            token = str(issue.get("currency") or "").strip().upper()
            if len(token) == 3:
                currency = token
        top_checks.append(row)

    for issue in ranked[8:]:
        impact = _finite_revenue(issue.get("revenue_impact"))
        if impact is not None and impact > 0:
            revenue_total += impact

    plan_tasks = build_fix_tasks_for_data_run(company=company, data_run=data_run)
    plan_check_ids: list[str] = []
    for task in plan_tasks:
        cid = str(task.get("check_id") or "").strip().upper()
        if cid and cid not in plan_check_ids:
            plan_check_ids.append(cid)

    architecture = resolve_architecture_assessment_for_run(
        company=company,
        dcs_run=data_run,
    )
    architecture_verdict = None
    if architecture is not None and architecture.mode:
        architecture_verdict = str(architecture.mode)

    return project_report_narrative_context(
        headline_score=headline_score,
        currency=currency,
        revenue_impact_total=revenue_total if revenue_total > 0 else None,
        top_checks=top_checks,
        plan_check_ids=plan_check_ids,
        architecture_verdict=architecture_verdict,
        company_name=company.name,
        company_domain=getattr(company, "domain", None),
        dcs_run_id=data_run.id,
        prompt_version=prompt_version,
        policy_version=policy_version,
    )
