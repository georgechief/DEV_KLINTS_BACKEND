"""Build canonical assessment report payload (PRD-RPT-01 §3, pack schema)."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.utils import timezone

from dataruns.architecture.models import ArchitectureAssessment
from dataruns.architecture.serialize import serialize_architecture_assessment
from dataruns.audit import stable_json
from dataruns.dcs.worklist import (
    SEVERITY_ORDER,
    _dimension_label,
    _redact_secrets,
    build_check_summary,
    build_enriched_issues,
    build_status_enrichment,
    coerce_headline_score,
    extract_dcs_payload,
    load_check_master_by_id,
    sort_worklist_issues,
)
from dataruns.models import DataRun
from dataruns.reports.constants import (
    PII_FORBIDDEN_KEYS,
    REPORT_VERSION,
    RETENTION_POLICY_ID,
    SCHEMA_VERSION,
    TEMPLATE_VERSION,
)
from dataruns.orchestration.scoring import sort_tasks_by_priority
from dataruns.reports.humanize import (
    architecture_incomplete_copy,
    format_customer_title,
    format_display_domain,
    format_systems_label,
    humanize_check_detail,
    incomplete_assessment_copy,
)
from tenants.models import Company, Connector

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_REMEDIATION_FALLBACK = "See Data Center for this check"
_COVERAGE_INCOMPLETE_THRESHOLD = 0.70


def compute_payload_hash(payload_without_hash: dict[str, Any]) -> str:
    body = dict(payload_without_hash)
    body.pop("payload_hash", None)
    canonical = stable_json(body)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _as_of_iso(value: datetime | None = None) -> str:
    as_of = value or timezone.now()
    if timezone.is_naive(as_of):
        as_of = timezone.make_aware(as_of, dt_timezone.utc)
    return as_of.isoformat().replace("+00:00", "Z")


def _run_as_of_iso(data_run: DataRun) -> str:
    at = data_run.finished_at or data_run.created_at
    if at is None:
        return _as_of_iso()
    return _as_of_iso(at)


def _compute_coverage(check_results: list[dict[str, Any]]) -> float:
    applicable = 0
    scored = 0
    for result in check_results:
        if not isinstance(result, dict):
            continue
        status = str(result.get("status") or "").upper()
        if status == "NOT_APPLICABLE":
            continue
        applicable += 1
        if status not in {"UNKNOWN", "NOT_CONNECTED"}:
            scored += 1
    if applicable == 0:
        return 0.0
    return round(scored / applicable, 4)


def _issue_summary_counts(open_issues: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "informational": 0,
    }
    for issue in open_issues:
        severity = str(issue.get("severity") or "").lower()
        if severity in counts:
            counts[severity] += 1
    return counts


def _severity_sort_key(issue: dict[str, Any]) -> tuple[int, float, str]:
    severity = str(issue.get("severity") or "").lower()
    order = SEVERITY_ORDER.get(severity, len(SEVERITY_ORDER))
    revenue = issue.get("revenue_impact")
    try:
        revenue_f = float(revenue) if revenue is not None else 0.0
    except (TypeError, ValueError):
        revenue_f = 0.0
    return (order, -revenue_f, str(issue.get("check_id") or ""))


def _top_issues(open_issues: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(open_issues, key=_severity_sort_key)
    top: list[dict[str, Any]] = []
    for issue in ranked[:limit]:
        detail = _redact_secrets(str(issue.get("detail") or issue.get("title") or ""))
        summary = humanize_check_detail(detail) if detail else format_customer_title(
            str(issue.get("title") or "")
        )
        top.append(
            {
                "check_id": issue.get("check_id"),
                "severity": issue.get("severity"),
                "summary": (summary or format_customer_title(str(issue.get("title") or "")))[
                    :240
                ],
            }
        )
    return top


def _safe_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _redact_secrets(value.strip())


def _required_fix_text(value: Any, *, fallback: str = _REMEDIATION_FALLBACK) -> str:
    token = _safe_text(value) if isinstance(value, str) else ""
    if not token and value is not None and not isinstance(value, str):
        token = _safe_text(str(value))
    # Never ship a lone dash placeholder in What to fix (PRD-RPT-01B §2.1).
    if not token or token in {"-", "\u2013", "\u2014"}:
        return fallback
    return token


def _connector_status_for_company(company: Company) -> list[dict[str, str]]:
    rows = list(
        Connector.objects.filter(company=company).only("name", "status", "type")
    )
    by_platform: dict[str, str] = {}
    for row in rows:
        name = (row.name or "").strip().lower()
        status = (row.status or "unknown").strip().lower() or "unknown"
        if name in {"manago_ai", "manago"}:
            by_platform["manago"] = status
        elif name == "shopify":
            by_platform["shopify"] = status
        elif "erp" in name or name == "erp":
            by_platform["erp"] = status
    return [
        {"key": "manago", "status": by_platform.get("manago", "unknown")},
        {"key": "shopify", "status": by_platform.get("shopify", "unknown")},
        {"key": "erp", "status": by_platform.get("erp", "unknown")},
    ]


def _fix_first_asset_names(assessment: ArchitectureAssessment) -> list[str]:
    verdicts = (
        assessment.asset_verdicts.filter(verdict="FIX_FIRST")
        .order_by("asset_id")
        .values_list("asset_id", flat=True)[:12]
    )
    asset_ids = [aid for aid in verdicts if isinstance(aid, str) and aid]
    if not asset_ids:
        return []
    names_by_id = {
        row.asset_id: (row.name or row.asset_id)
        for row in assessment.assets.filter(asset_id__in=asset_ids)
    }
    out: list[str] = []
    for asset_id in asset_ids:
        name = names_by_id.get(asset_id) or asset_id
        cleaned = _safe_text(str(name))
        if cleaned:
            out.append(cleaned)
        if len(out) >= 3:
            break
    return out


def _plan_by_check_id(plan_tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for task in plan_tasks:
        check_id = task.get("check_id")
        if isinstance(check_id, str) and check_id and check_id not in out:
            out[check_id] = task
    return out


def _open_issues_by_check_id(
    open_issues: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(issue["check_id"]): issue
        for issue in open_issues
        if isinstance(issue.get("check_id"), str) and issue.get("check_id")
    }


def _build_check_register(
    *,
    check_results: list[dict[str, Any]],
    open_issues: list[dict[str, Any]],
    plan_tasks: list[dict[str, Any]],
    master_by_id: dict[str, Any],
) -> dict[str, Any]:
    issue_map = _open_issues_by_check_id(open_issues)
    plan_map = _plan_by_check_id(plan_tasks)
    open_rows: list[dict[str, Any]] = []
    healthy_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []

    for result in check_results:
        if not isinstance(result, dict):
            continue
        check_id = result.get("check_id")
        if not isinstance(check_id, str) or not check_id.strip():
            continue
        status = str(result.get("status") or "UNKNOWN").upper()
        master = master_by_id.get(check_id)
        title = None
        if master is not None and master.check_name:
            title = master.check_name
        if not title and issue_map.get(check_id):
            title = issue_map[check_id].get("title")
        if not title:
            title = _safe_text(result.get("message")) or check_id
        title = format_customer_title(str(title))
        severity = None
        issue = issue_map.get(check_id)
        if issue is not None:
            severity = issue.get("severity")
        if not severity:
            severity = str(result.get("severity") or "high").lower()
        systems = ""
        if issue is not None:
            systems = str(issue.get("systems_compared") or "").strip()
        if not systems and master is not None and isinstance(master.systems_compared, str):
            systems = master.systems_compared.strip()
        systems = format_systems_label(systems)

        base = {
            "check_id": check_id,
            "title": title,
            "dimension": _dimension_label(master)
            or (issue.get("dimension") if issue else None),
            "status": status,
            "severity": severity,
            "systems": systems,
        }
        if status in {"FAIL", "WARN"}:
            whats_wrong = ""
            if issue is not None:
                whats_wrong = _safe_text(issue.get("detail"))
            if not whats_wrong:
                whats_wrong = _safe_text(result.get("message"))
            whats_wrong = humanize_check_detail(whats_wrong) or whats_wrong
            plan = plan_map.get(check_id)
            open_rows.append(
                {
                    **base,
                    "whats_wrong": whats_wrong,
                    "revenue_impact": issue.get("revenue_impact") if issue else None,
                    "currency": issue.get("currency") if issue else None,
                    "priority_class": plan.get("priority_class") if plan else None,
                    "priority_score": plan.get("priority_score") if plan else None,
                }
            )
        elif status == "PASS":
            healthy_rows.append(base)
        else:
            coverage_rows.append(base)

    seen_open = {
        row["check_id"] for row in open_rows if isinstance(row.get("check_id"), str)
    }
    for issue in open_issues:
        check_id = issue.get("check_id")
        if not isinstance(check_id, str) or not check_id or check_id in seen_open:
            continue
        plan = plan_map.get(check_id)
        master = master_by_id.get(check_id) if isinstance(master_by_id, dict) else None
        systems = str(issue.get("systems_compared") or "").strip()
        if not systems and master is not None and isinstance(master.systems_compared, str):
            systems = master.systems_compared.strip()
        open_rows.append(
            {
                "check_id": check_id,
                "title": format_customer_title(str(issue.get("title") or check_id)),
                "dimension": issue.get("dimension")
                or (_dimension_label(master) if master else None),
                "status": str(issue.get("status") or "FAIL").upper(),
                "severity": issue.get("severity"),
                "systems": format_systems_label(systems),
                "whats_wrong": humanize_check_detail(_safe_text(issue.get("detail")))
                or _safe_text(issue.get("detail")),
                "revenue_impact": issue.get("revenue_impact"),
                "currency": issue.get("currency"),
                "priority_class": plan.get("priority_class") if plan else None,
                "priority_score": plan.get("priority_score") if plan else None,
            }
        )
        seen_open.add(check_id)

    return {
        "open_checks": open_rows,
        "healthy_checks": healthy_rows,
        "coverage_checks": coverage_rows,
    }


def _build_remediation(
    open_issues: list[dict[str, Any]],
    *,
    master_by_id: dict[str, Any] | None = None,
) -> dict[str, Any]:
    masters = master_by_id or {}
    items: list[dict[str, Any]] = []
    for issue in sort_worklist_issues(open_issues):
        check_id = issue.get("check_id")
        if not isinstance(check_id, str) or not check_id:
            continue
        master = masters.get(check_id)
        suggested = _safe_text(issue.get("suggested_fix"))
        fix_type = _safe_text(issue.get("fix_type")) if isinstance(issue.get("fix_type"), str) else ""
        if not fix_type and issue.get("fix_type") is not None:
            fix_type = _safe_text(str(issue.get("fix_type")))
        fix_owner = _safe_text(issue.get("fix_owner")) if isinstance(issue.get("fix_owner"), str) else ""
        if not fix_owner and issue.get("fix_owner") is not None:
            fix_owner = _safe_text(str(issue.get("fix_owner")))
        if master is not None:
            if not suggested and isinstance(master.suggested_fix, str):
                suggested = master.suggested_fix.strip()
            if not fix_type and isinstance(master.fix_type, str):
                fix_type = master.fix_type.strip()
            if not fix_owner and isinstance(master.fix_owner, str):
                fix_owner = master.fix_owner.strip()
        title = format_customer_title(
            str(issue.get("title") or (master.check_name if master else "") or check_id)
        )
        items.append(
            {
                "check_id": check_id,
                "title": title,
                "suggested_fix": _required_fix_text(suggested),
                "fix_type": _required_fix_text(fix_type),
                "fix_owner": _required_fix_text(fix_owner),
                "root_cause_ids": list(issue.get("root_cause_ids") or []),
                "fix_href": f"/fix?issue={check_id}",
            }
        )
    return {"items": items, "count": len(items)}


def _build_execution_plan(plan_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = sort_tasks_by_priority(list(plan_tasks))
    rows = [
        {
            "rank": index + 1,
            "task_id": task.get("task_id"),
            "check_id": task.get("check_id"),
            "title": task.get("title"),
            "priority_score": task.get("priority_score"),
            "priority_class": task.get("priority_class"),
        }
        for index, task in enumerate(tasks)
    ]
    return {
        "tasks": rows,
        "count": len(rows),
        "empty_reason": None if rows else "no_open_issues",
    }


def _architecture_content(
    assessment: ArchitectureAssessment | None,
) -> dict[str, Any]:
    if assessment is None:
        return {
            "assessed": False,
            "mode": None,
            "weighted_score": None,
            "summary": "Not assessed",
            "verdict_counts": None,
            "incomplete_reason": (
                "No architecture assessment was available for this run."
            ),
            "fix_first_assets": [],
        }
    payload = serialize_architecture_assessment(assessment)
    weighted = payload["weighted_score"]
    mode = payload["mode"]
    incomplete_reason = architecture_incomplete_copy(
        mode=mode, weighted_score=weighted
    )
    return {
        "assessed": True,
        "assessment_id": payload["assessment_id"],
        "mode": mode,
        "weighted_score": weighted,
        "summary": (
            f"{payload['asset_count']} assets · "
            f"{payload['verdict_counts'].get('FIX_FIRST', 0)} fix-first"
        ),
        "verdict_counts": payload["verdict_counts"],
        "critical_defects": payload["critical_defects"],
        "evidence_coverage": payload["evidence_coverage"],
        "incomplete_reason": incomplete_reason,
        "fix_first_assets": _fix_first_asset_names(assessment),
    }


def _business_impact_content(
    enrichment: dict[str, Any],
) -> dict[str, Any]:
    raw = enrichment.get("business_impact")
    if not isinstance(raw, dict):
        return {
            "currency": None,
            "estimate": None,
            "confidence": None,
            "note": "No business impact rollup persisted for this run.",
        }
    return {
        "currency": raw.get("currency"),
        "estimate": raw.get("estimate"),
        "confidence": raw.get("confidence"),
        "note": raw.get("note"),
        "window_days": raw.get("window_days"),
        "as_of": raw.get("as_of"),
    }


def _snapshot_ids(
    *,
    dcs_run: DataRun,
    assessment: ArchitectureAssessment | None,
) -> list[str]:
    ids = [f"dcs:{dcs_run.id}"]
    if assessment is not None:
        ids.append(f"af:{assessment.id}")
    return ids


def _dimension_scores_map(enrichment: dict[str, Any]) -> dict[str, Any]:
    dimensions = enrichment.get("dimensions")
    if not isinstance(dimensions, dict):
        return {}
    scores: dict[str, Any] = {}
    for name, row in dimensions.items():
        if isinstance(row, dict) and row.get("score") is not None:
            scores[str(name)] = row.get("score")
    return scores


def build_report_payload(
    *,
    report_id: uuid.UUID,
    company: Company,
    dcs_run: DataRun,
    architecture_assessment: ArchitectureAssessment | None,
    open_issues: list[dict[str, Any]],
    plan_tasks: list[dict[str, Any]],
    created_by_email: str,
    include_architecture: bool = True,
    include_plan: bool = True,
    period_from: str | None = None,
    period_to: str | None = None,
) -> dict[str, Any]:
    metadata = dcs_run.metadata if isinstance(dcs_run.metadata, dict) else {}
    payload = extract_dcs_payload(metadata)
    check_results = [
        row for row in payload.get("check_results") or [] if isinstance(row, dict)
    ]
    master_by_id = load_check_master_by_id()
    enrichment = build_status_enrichment(data_run=dcs_run, company=company)
    headline = coerce_headline_score(payload.get("headline_score"))
    run_state = payload.get("run_state") or "UNKNOWN"
    check_summary = build_check_summary(check_results)
    check_register = _build_check_register(
        check_results=check_results,
        open_issues=open_issues,
        plan_tasks=plan_tasks if include_plan else [],
        master_by_id=master_by_id,
    )
    coverage = _compute_coverage(check_results)
    state_upper = str(run_state or "").upper()
    unknown_n = int(check_summary.get("UNKNOWN") or 0)
    not_connected_n = int(check_summary.get("NOT_CONNECTED") or 0)
    show_incomplete = state_upper == "INCOMPLETE" or coverage < _COVERAGE_INCOMPLETE_THRESHOLD
    incomplete_banner = (
        incomplete_assessment_copy(
            score=headline,
            coverage=coverage,
            unknown=unknown_n,
            not_connected=not_connected_n,
        )
        if show_incomplete
        else None
    )
    display_domain = format_display_domain(company.domain)
    connectors = _connector_status_for_company(company)

    content: dict[str, Any] = {
        "dcs": {
            "state": run_state,
            "headline_score": headline,
            "coverage": coverage,
            "dimension_scores": _dimension_scores_map(enrichment),
            "check_summary": check_summary,
            "dimensions": enrichment.get("dimensions"),
            "incomplete_banner": incomplete_banner,
        },
        "issue_summary": _issue_summary_counts(open_issues),
        "architecture": (
            _architecture_content(architecture_assessment)
            if include_architecture
            else {
                "assessed": False,
                "mode": None,
                "weighted_score": None,
                "summary": "Excluded",
                "incomplete_reason": None,
                "fix_first_assets": [],
            }
        ),
        "business_impact": _business_impact_content(enrichment),
        "top_issues": _top_issues(open_issues),
        "check_register": check_register,
        "remediation": _build_remediation(open_issues, master_by_id=master_by_id),
        "execution_plan": (
            _build_execution_plan(plan_tasks) if include_plan else {"tasks": [], "count": 0, "empty_reason": "excluded"}
        ),
        "locked_sections": [],
        "render_context": {
            "company_name": company.name,
            "company_domain": display_domain,
            "period_from": period_from,
            "period_to": period_to,
            "report_title": "Data consistency assessment report",
            "aggregate_notice": "Aggregate report - no contact-level PII",
            "connector_status": connectors,
            "show_incomplete_banner": show_incomplete,
        },
    }

    created_at = _as_of_iso()
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_id": str(report_id),
        "tenant_id": str(company.tenant_id),
        "report_version": REPORT_VERSION,
        "variant": "PAID_FULL",
        "status": "READY",
        "data_as_of": _run_as_of_iso(dcs_run),
        "input_snapshot_ids": _snapshot_ids(
            dcs_run=dcs_run,
            assessment=architecture_assessment if include_architecture else None,
        ),
        "template_version": TEMPLATE_VERSION,
        "content": content,
        "access_policy": {
            "tenant_scoped": True,
            "pii_policy": "AGGREGATE_NO_CONTACT_LEVEL_PII",
            "retention_policy_id": RETENTION_POLICY_ID,
        },
        "artifacts": [],
        "created_at": created_at,
        "expires_at": None,
        "provenance": {
            "source_versions": {
                "dcs": SCHEMA_VERSION,
                "architecture": SCHEMA_VERSION,
                "orchestration": SCHEMA_VERSION,
                "template": TEMPLATE_VERSION,
            },
            "created_at": created_at,
            "created_by": created_by_email,
        },
    }
    body["payload_hash"] = compute_payload_hash(body)
    return body


def scan_payload_for_pii(payload: dict[str, Any]) -> list[str]:
    """Return dotted paths where forbidden keys or email patterns appear in report content."""
    findings: list[str] = []
    content = payload.get("content")
    if not isinstance(content, dict):
        content = payload

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}" if path else str(key)
                if str(key) in PII_FORBIDDEN_KEYS:
                    findings.append(child)
                walk(value, child)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str):
            if _EMAIL_RE.search(node):
                findings.append(path)

    walk(content, "content")
    return findings
