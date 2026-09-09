"""ContextAllowlist — project worklist / company facts → AI context (PRD-AI-01 §4.2)."""

from __future__ import annotations

from typing import Any

from dataruns.ai.constants import ALLOWLIST_VERSION, MAX_STRING_CHARS, POLICY_VERSION
from dataruns.ai.privacy_gate import sanitize_mismatch_list, scrub_text, strip_domain_to_hostname
from dataruns.reports.humanize import format_customer_title, format_systems_label

# Only these top-level keys may enter a model prompt after projection.
_ALLOWED_TOP_LEVEL = frozenset(
    {
        "task_type",
        "check_id",
        "check_name",
        "dimension",
        "severity",
        "status",
        "systems_compared",
        "suggested_fix",
        "fix_type",
        "fix_owner",
        "finding_summary",
        "revenue_impact",
        "currency",
        "architecture_verdict",
        "company_display_name",
        "company_hostname",
        "industry_vertical",
        "policy_version",
        "allowlist_version",
        "dcs_run_id",
        "prompt_version",
        "headline_score",
        "revenue_impact_total",
        "top_checks",
        "plan_check_ids",
        "plan_rank",
    }
)


def _cap(value: str | None, *, limit: int = MAX_STRING_CHARS) -> str:
    text = scrub_text((value or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _platform_names(raw: str | None) -> str:
    """Product names only (Shopify · Manago.ai) — no URLs."""
    return format_systems_label(raw) or _cap(raw, limit=120)


def _finding_summary_from_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Aggregates + mismatch shapes only — no values."""
    mismatches = issue.get("mismatches")
    if not isinstance(mismatches, list) or len(mismatches) == 0:
        preview = issue.get("evidence_preview")
        if isinstance(preview, list) and preview:
            # Map worklist evidence rows → mismatch shapes (path/kind/side only).
            mapped: list[dict[str, Any]] = []
            for row in preview:
                if not isinstance(row, dict):
                    continue
                mapped.append(
                    {
                        "path": row.get("locator") or row.get("path") or row.get("field"),
                        "kind": row.get("kind") or row.get("type") or "evidence",
                        "side": row.get("source") or row.get("side") or row.get("system"),
                    }
                )
            mismatches = mapped
        else:
            mismatches = []
    shapes = sanitize_mismatch_list(mismatches)

    detail = issue.get("detail") or issue.get("message") or ""
    # Detail often embeds rates/counts — scrub PII but keep aggregate phrasing.
    detail_s = _cap(str(detail) if detail else "", limit=400)

    summary: dict[str, Any] = {
        "detail": detail_s,
        "mismatch_count": len(shapes),
        "mismatches": shapes,
    }
    # Optional aggregate keys if already computed by DCS (numbers only).
    for key in ("drift_pct", "share_pct", "cluster_count", "weak_or_missing"):
        value = issue.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            summary[key] = value
    return summary


def _issue_base_fields(
    *,
    issue: dict[str, Any],
    company_name: str | None,
    company_domain: str | None,
    industry_vertical: str | None,
    dcs_run_id: int | str | None,
    prompt_version: str | None,
    policy_version: str | None,
    task_type: str,
) -> dict[str, Any]:
    check_id = str(issue.get("check_id") or "").strip().upper()
    check_name = format_customer_title(
        str(issue.get("title") or issue.get("check_name") or check_id)
    )
    systems = _platform_names(
        str(issue.get("systems_compared") or issue.get("systems") or "")
    )
    revenue = issue.get("revenue_impact")
    if isinstance(revenue, bool):
        revenue = None
    elif isinstance(revenue, (int, float)):
        revenue = float(revenue)
    else:
        try:
            revenue = float(revenue) if revenue is not None else None
        except (TypeError, ValueError):
            revenue = None
    currency = issue.get("currency")
    currency_s = str(currency).strip().upper() if currency else None
    if currency_s and len(currency_s) != 3:
        currency_s = None
    return {
        "task_type": task_type,
        "check_id": check_id,
        "check_name": check_name,
        "dimension": _cap(str(issue.get("dimension") or ""), limit=120) or None,
        "severity": _cap(str(issue.get("severity") or "").lower(), limit=32) or None,
        "status": _cap(str(issue.get("status") or "").upper(), limit=32) or None,
        "systems_compared": systems or None,
        "suggested_fix": _cap(str(issue.get("suggested_fix") or ""), limit=800) or None,
        "fix_type": _cap(str(issue.get("fix_type") or ""), limit=120) or None,
        "fix_owner": _cap(str(issue.get("fix_owner") or ""), limit=120) or None,
        "finding_summary": _finding_summary_from_issue(issue),
        "revenue_impact": revenue,
        "currency": currency_s,
        "company_display_name": _cap(company_name, limit=120) or None,
        "company_hostname": strip_domain_to_hostname(company_domain),
        "industry_vertical": _cap(industry_vertical, limit=80) or None,
        "architecture_verdict": _cap(
            str(issue.get("architecture_verdict") or ""), limit=64
        )
        or None,
        "dcs_run_id": dcs_run_id,
        "prompt_version": prompt_version,
        "policy_version": (policy_version or POLICY_VERSION),
        "allowlist_version": ALLOWLIST_VERSION,
    }


def project_fix_suggestion_context(
    *,
    issue: dict[str, Any],
    company_name: str | None = None,
    company_domain: str | None = None,
    industry_vertical: str | None = None,
    dcs_run_id: int | str | None = None,
    prompt_version: str | None = None,
    policy_version: str | None = None,
) -> dict[str, Any]:
    """
    Build allowlisted context for task_type=fix_suggestion.

    Input is typically an enriched worklist issue dict. Non-allowlisted keys are dropped.
    """
    return project(
        _issue_base_fields(
            issue=issue,
            company_name=company_name,
            company_domain=company_domain,
            industry_vertical=industry_vertical,
            dcs_run_id=dcs_run_id,
            prompt_version=prompt_version,
            policy_version=policy_version,
            task_type="fix_suggestion",
        )
    )


def project_explain_finding_context(
    *,
    issue: dict[str, Any],
    company_name: str | None = None,
    company_domain: str | None = None,
    industry_vertical: str | None = None,
    dcs_run_id: int | str | None = None,
    prompt_version: str | None = None,
    policy_version: str | None = None,
) -> dict[str, Any]:
    return project(
        _issue_base_fields(
            issue=issue,
            company_name=company_name,
            company_domain=company_domain,
            industry_vertical=industry_vertical,
            dcs_run_id=dcs_run_id,
            prompt_version=prompt_version,
            policy_version=policy_version,
            task_type="explain_finding",
        )
    )


def project_nba_blurb_context(
    *,
    issue: dict[str, Any],
    plan_rank: int | None = None,
    company_name: str | None = None,
    company_domain: str | None = None,
    industry_vertical: str | None = None,
    dcs_run_id: int | str | None = None,
    prompt_version: str | None = None,
    policy_version: str | None = None,
) -> dict[str, Any]:
    ctx = _issue_base_fields(
        issue=issue,
        company_name=company_name,
        company_domain=company_domain,
        industry_vertical=industry_vertical,
        dcs_run_id=dcs_run_id,
        prompt_version=prompt_version,
        policy_version=policy_version,
        task_type="nba_blurb",
    )
    if isinstance(plan_rank, int) and plan_rank > 0:
        ctx["plan_rank"] = plan_rank
    return project(ctx)


def project_report_narrative_context(
    *,
    headline_score: float | None,
    currency: str | None,
    revenue_impact_total: float | None,
    top_checks: list[dict[str, Any]],
    plan_check_ids: list[str],
    architecture_verdict: str | None = None,
    company_name: str | None = None,
    company_domain: str | None = None,
    dcs_run_id: int | str | None = None,
    prompt_version: str | None = None,
    policy_version: str | None = None,
) -> dict[str, Any]:
    """Allowlisted rollup only — no full worklist dumps (PRD §6.3)."""
    cleaned_checks: list[dict[str, Any]] = []
    for row in top_checks[:8]:
        if not isinstance(row, dict):
            continue
        check_id = str(row.get("check_id") or "").strip().upper()
        if not check_id:
            continue
        item: dict[str, Any] = {
            "check_id": check_id,
            "check_name": _cap(str(row.get("check_name") or check_id), limit=160),
            "severity": _cap(str(row.get("severity") or ""), limit=32),
            "status": _cap(str(row.get("status") or "").upper(), limit=16),
        }
        impact = row.get("revenue_impact")
        if isinstance(impact, (int, float)) and not isinstance(impact, bool):
            item["revenue_impact"] = float(impact)
        cleaned_checks.append(item)

    ids: list[str] = []
    for token in plan_check_ids[:8]:
        cid = str(token or "").strip().upper()
        if cid and cid not in ids:
            ids.append(cid)

    currency_s = str(currency).strip().upper() if currency else None
    if currency_s and len(currency_s) != 3:
        currency_s = None

    return project(
        {
            "task_type": "report_narrative",
            "headline_score": headline_score,
            "currency": currency_s,
            "revenue_impact_total": revenue_impact_total,
            "top_checks": cleaned_checks,
            "plan_check_ids": ids,
            "architecture_verdict": _cap(architecture_verdict, limit=64) or None,
            "company_display_name": _cap(company_name, limit=120) or None,
            "company_hostname": strip_domain_to_hostname(company_domain),
            "dcs_run_id": dcs_run_id,
            "prompt_version": prompt_version,
            "policy_version": (policy_version or POLICY_VERSION),
            "allowlist_version": ALLOWLIST_VERSION,
        }
    )


def project(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only approved top-level keys (default deny)."""
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in _ALLOWED_TOP_LEVEL:
            continue
        if value is None or value == "":
            continue
        out[key] = value
    return out
