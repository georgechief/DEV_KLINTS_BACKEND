"""DCS guided worklist builders (PRD-FE-06 §4).

Read-only aggregation over persisted DataRun metadata, RunIssue, and
RunIssueImpact. Does not recompute scores or invent revenue.
"""

from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal
from typing import Any

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.dcs.gates import is_optional_check_id, load_optional_check_ids
from dataruns.models import CheckMaster, Contact, DataRun, RunIssue
from tenants.models import Company

TERMINAL_STATUSES = (DataRun.Status.SUCCEEDED, DataRun.Status.FAILED)

INCLUDE_STATUSES = frozenset({"FAIL", "WARN"})
EXCLUDE_STATUSES = frozenset(
    {"PASS", "UNKNOWN", "NOT_CONNECTED", "NOT_APPLICABLE"}
)

SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "informational": 4,
}

STATUS_ISSUES_CAP = 30
EVIDENCE_PREVIEW_MAX = 5
EVIDENCE_VALUE_MAX_CHARS = 500

CHECK_SUMMARY_KEYS = (
    "PASS",
    "WARN",
    "FAIL",
    "UNKNOWN",
    "NOT_CONNECTED",
    "NOT_APPLICABLE",
)

# Scrub credential-like values (aligned with status.py).
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b("
    r"access_token|refresh_token|api_key|api_secret|password|authorization"
    r")\s*[:=]\s*([^\s,;]+)"
)
_SHOPIFY_TOKEN_RE = re.compile(r"\b(shpat_|shprt_|shpss_)[A-Za-z0-9]+")


class WorklistDetailNotFound(Exception):
    """Raised when detail lookup has no FAIL/WARN issue for check_id."""


def _redact_secrets(text: str) -> str:
    scrubbed = _SECRET_VALUE_RE.sub(r"\1=****", text)
    return _SHOPIFY_TOKEN_RE.sub(r"\1****", scrubbed)


def _severity_key(value: str | None) -> int:
    if not value:
        return len(SEVERITY_ORDER)
    return SEVERITY_ORDER.get(value.strip().lower(), len(SEVERITY_ORDER))


def _company_dcs_runs(*, company: Company):
    return DataRun.objects.filter(
        tenant=company.tenant,
        name=DCS_SCORE_DATA_RUN_NAME,
        metadata__kind=DCS_SCORE_KIND,
        metadata__company_id=str(company.id),
    ).order_by("-created_at")


def get_latest_terminal_dcs_run(*, company: Company) -> DataRun | None:
    """Latest succeeded or failed DCS DataRun for the company."""
    return (
        _company_dcs_runs(company=company)
        .filter(status__in=TERMINAL_STATUSES)
        .first()
    )


def load_check_master_by_id() -> dict[str, CheckMaster]:
    return {
        row.check_id: row
        for row in CheckMaster.objects.select_related("dimension").all()
    }


def extract_dcs_payload(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Parse DCS fields from DataRun.metadata (same rules as status.py)."""
    metadata = metadata or {}
    dcs_run = metadata.get("dcs_run")
    if not isinstance(dcs_run, dict):
        dcs_run = {}
    check_results = metadata.get("check_results")
    if not isinstance(check_results, list):
        check_results = dcs_run.get("check_results")
    if not isinstance(check_results, list):
        check_results = []

    run_state = dcs_run.get("run_state") or dcs_run.get("score_state")
    headline_score = dcs_run.get("headline_score")
    if headline_score is None:
        headline_score = metadata.get("headline_score")

    domain_run_id = dcs_run.get("run_id") or metadata.get("run_id")
    blocking_gates_failed = dcs_run.get("blocking_gates_failed")
    if blocking_gates_failed is None:
        blocking_gates_failed = metadata.get("blocking_gates_failed", 0)

    return {
        "dcs_run": dcs_run,
        "check_results": check_results,
        "run_state": run_state,
        "headline_score": headline_score,
        "domain_run_id": domain_run_id,
        "blocking_gates_failed": blocking_gates_failed,
    }


def coerce_headline_score(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


def build_check_summary(check_results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {key: 0 for key in CHECK_SUMMARY_KEYS}
    for result in check_results:
        if not isinstance(result, dict):
            continue
        status = str(result.get("status") or "").upper()
        if status in summary:
            summary[status] += 1
    return summary


def _is_executor_stub(result: dict[str, Any]) -> bool:
    return (
        str(result.get("status") or "").upper() == "UNKNOWN"
        and str(result.get("reason_code") or "") == "EXECUTOR_NOT_IMPLEMENTED"
    )


def should_include_check_result(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if _is_executor_stub(result):
        return False
    status = str(result.get("status") or "").upper()
    if status in EXCLUDE_STATUSES:
        return False
    return status in INCLUDE_STATUSES


def _parse_domain_run_uuid(domain_run_id: Any) -> uuid.UUID | None:
    if domain_run_id is None:
        return None
    try:
        return uuid.UUID(str(domain_run_id))
    except (ValueError, TypeError):
        return None


def load_run_issues_by_check_id(
    domain_run_id: Any,
) -> dict[str, RunIssue]:
    """Map check_id → RunIssue for a domain Run, with impacts prefetched."""
    parsed = _parse_domain_run_uuid(domain_run_id)
    if parsed is None:
        return {}

    by_check: dict[str, RunIssue] = {}
    queryset = (
        RunIssue.objects.filter(run_id=parsed)
        .prefetch_related("impacts")
        .order_by("detected_at", "id")
    )
    for issue in queryset:
        details = issue.details if isinstance(issue.details, dict) else {}
        check_id = str(details.get("check_id") or issue.issue_type or "")
        if not check_id:
            continue
        # Prefer first row per check_id; entity_type dcs_check preferred.
        existing = by_check.get(check_id)
        if existing is None:
            by_check[check_id] = issue
            continue
        if issue.entity_type == "dcs_check" and existing.entity_type != "dcs_check":
            by_check[check_id] = issue
    return by_check


def _coerce_revenue(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 0.0
    try:
        return float(Decimal(str(value)))
    except Exception:  # noqa: BLE001
        return 0.0


def _revenue_from_run_issue(issue: RunIssue | None) -> float | None:
    if issue is None:
        return None
    impacts = list(issue.impacts.all())
    if not impacts:
        return None
    return _coerce_revenue(impacts[0].revenue_impact)


def _revenue_from_result(result: dict[str, Any] | None) -> float | None:
    if not isinstance(result, dict):
        return None
    provenance = result.get("provenance")
    if isinstance(provenance, dict) and provenance.get("revenue_impact") is not None:
        return _coerce_revenue(provenance.get("revenue_impact"))
    for item in result.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if isinstance(value, dict) and value.get("revenue_impact") is not None:
            return _coerce_revenue(value.get("revenue_impact"))
    return None


def resolve_revenue_impact(
    *,
    run_issue: RunIssue | None,
    result: dict[str, Any] | None,
) -> float:
    """Persisted revenue only — RunIssueImpact first, then provenance."""
    from_issue = _revenue_from_run_issue(run_issue)
    if from_issue is not None:
        return from_issue
    from_result = _revenue_from_result(result)
    if from_result is not None:
        return from_result
    return 0.0


def resolve_currency(
    *,
    revenue_impact: float,
    run_issue: RunIssue | None,
    result: dict[str, Any] | None,
) -> str | None:
    if revenue_impact <= 0:
        return None
    if isinstance(result, dict):
        provenance = result.get("provenance")
        if isinstance(provenance, dict):
            cur = provenance.get("revenue_currency")
            if isinstance(cur, str) and cur.strip():
                return cur.strip()
    return None


def resolve_revenue_formula_id(result: dict[str, Any] | None) -> str | None:
    if not isinstance(result, dict):
        return None
    provenance = result.get("provenance")
    if isinstance(provenance, dict):
        formula = provenance.get("revenue_formula_id")
        if isinstance(formula, str) and formula.strip():
            return formula.strip()
    return None


def _truncate_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        text = str(value)
        if len(text) > EVIDENCE_VALUE_MAX_CHARS:
            return f"{text[: EVIDENCE_VALUE_MAX_CHARS - 3]}..."
        return value
    try:
        encoded = json.dumps(value, default=str)
    except (TypeError, ValueError):
        encoded = str(value)
    if len(encoded) > EVIDENCE_VALUE_MAX_CHARS:
        return f"{encoded[: EVIDENCE_VALUE_MAX_CHARS - 3]}..."
    return value


def _infer_evidence_source(*, source: Any, locator: Any) -> str:
    if isinstance(source, str) and source.strip() and source.strip().lower() != "unknown":
        return source.strip()
    locator_text = str(locator or "").lower()
    if "shopify" in locator_text or locator_text.startswith("connector:shopify"):
        return "shopify"
    if (
        "manago" in locator_text
        or "salesmanago" in locator_text
        or locator_text.startswith("connector:manago")
    ):
        return "manago_ai"
    if locator_text.startswith("snapshot") or "snapshot" in locator_text:
        return "snapshot"
    if locator_text.startswith("live:"):
        return "live"
    if locator_text:
        return "klints"
    return "klints"


def _normalize_evidence_item(
    item: Any,
    *,
    truncate: bool = True,
) -> dict[str, Any] | None:
    if item is None:
        return None
    if not isinstance(item, dict):
        item = {"value": item}
    locator = item.get("locator")
    if locator is not None and not isinstance(locator, str):
        locator = str(locator)
    if not isinstance(locator, str):
        locator = ""
    observed_at = item.get("observed_at")
    if not isinstance(observed_at, str):
        observed_at = ""
    raw_value = item.get("value")
    if raw_value is None and "value" not in item:
        # Accept bare key/value rows used in some provenance payloads.
        leftover = {
            key: value
            for key, value in item.items()
            if key not in {"source", "locator", "observed_at"}
        }
        if leftover:
            raw_value = leftover if len(leftover) > 1 else next(iter(leftover.values()))
    source = _infer_evidence_source(source=item.get("source"), locator=locator)
    return {
        "source": source,
        "locator": locator or "—",
        "observed_at": observed_at,
        "value": _truncate_value(raw_value) if truncate else raw_value,
    }


def build_evidence_preview(
    *,
    details: dict[str, Any] | None,
    result: dict[str, Any] | None,
    max_items: int = EVIDENCE_PREVIEW_MAX,
) -> list[dict[str, Any]]:
    """Prefer mismatches, then evidence, then matches — cap at max_items."""
    details = details if isinstance(details, dict) else {}
    result = result if isinstance(result, dict) else {}

    candidates: list[Any] = []
    for key in ("mismatches", "evidence", "matches"):
        rows = details.get(key)
        if isinstance(rows, list) and rows:
            candidates.extend(rows)
            break
    if not candidates:
        rows = result.get("evidence")
        if isinstance(rows, list):
            candidates = list(rows)

    preview: list[dict[str, Any]] = []
    for item in candidates:
        # PRD §4.3: truncate large values on preview only.
        normalized = _normalize_evidence_item(item, truncate=True)
        if normalized is None:
            continue
        preview.append(normalized)
        if len(preview) >= max_items:
            break
    return preview


def _dimension_label(master: CheckMaster | None) -> str | None:
    if master is None or master.dimension is None:
        return None
    # Prefer key ("01 Customer Identity") so labels match assemble dimension scores.
    key = master.dimension.key
    if isinstance(key, str) and key.strip():
        return key.strip()
    name = master.dimension.name
    return name if isinstance(name, str) and name.strip() else None


def _title_for_issue(
    *,
    check_id: str | None,
    details: dict[str, Any],
    result: dict[str, Any] | None,
    master: CheckMaster | None,
) -> str:
    # Prefer CheckMaster label, then RunIssue.details, then check_results.
    if master is not None and master.check_name:
        return master.check_name
    for source in (details, result):
        if not isinstance(source, dict):
            continue
        for key in ("title", "message"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return check_id or "DCS issue"


def _detail_text(
    *,
    details: dict[str, Any],
    result: dict[str, Any] | None,
) -> str:
    # Prefer RunIssue.details; fill gaps from check_results (PRD §4.5).
    for source in (details, result):
        if not isinstance(source, dict):
            continue
        for key in ("detail", "message", "reason_code"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _suggested_fix(
    *,
    details: dict[str, Any],
    result: dict[str, Any] | None,
    master: CheckMaster | None = None,
) -> str:
    # Prefer RunIssue.details; fill gaps from check_results, then CheckMaster.
    for source in (details, result):
        if not isinstance(source, dict):
            continue
        value = source.get("suggested_fix")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if master is not None and isinstance(master.suggested_fix, str):
        return master.suggested_fix.strip()
    return ""


def _fix_ownership(
    *,
    details: dict[str, Any],
    result: dict[str, Any] | None,
    master: CheckMaster | None,
    suggested_fix: str,
) -> dict[str, Any]:
    """Attach Excel Fix Type / Fix Owner fields for FE CTAs."""
    from dataruns.dcs.fix_ownership import (
        fix_ownership_fields,
        is_klints_automated_fix,
    )

    fix_type = ""
    fix_owner = ""
    for source in (details, result):
        if not isinstance(source, dict):
            continue
        if not fix_type:
            value = source.get("fix_type")
            if isinstance(value, str) and value.strip():
                fix_type = value.strip()
        if not fix_owner:
            value = source.get("fix_owner")
            if isinstance(value, str) and value.strip():
                fix_owner = value.strip()

    if master is not None:
        if not fix_type:
            fix_type = (master.fix_type or "").strip()
        if not fix_owner:
            fix_owner = (master.fix_owner or "").strip()
        if not suggested_fix:
            suggested_fix = (master.suggested_fix or "").strip()

    ownership = fix_ownership_fields(
        fix_type=fix_type,
        fix_owner=fix_owner,
        suggested_fix=suggested_fix,
    )
    if isinstance(result, dict) and result.get("fix_in_klints") is not None:
        ownership["fix_in_klints"] = bool(result.get("fix_in_klints"))
    elif isinstance(details, dict) and details.get("fix_in_klints") is not None:
        ownership["fix_in_klints"] = bool(details.get("fix_in_klints"))
    elif ownership["fix_owner"]:
        ownership["fix_in_klints"] = is_klints_automated_fix(
            ownership["fix_owner"]
        )
    return ownership


def _root_cause_ids(
    *,
    details: dict[str, Any],
    result: dict[str, Any] | None,
    master: CheckMaster | None,
) -> list[str]:
    # Prefer RunIssue.details; fill gaps from check_results, then CheckMaster.
    for source in (details, result):
        if not isinstance(source, dict):
            continue
        ids = source.get("root_cause_ids")
        if isinstance(ids, list):
            return [str(item) for item in ids]
    if master is not None and isinstance(master.root_cause_ids, list):
        return [str(item) for item in master.root_cause_ids]
    return []


def build_synthetic_failed_run_issue(
    *,
    data_run: DataRun,
) -> dict[str, Any] | None:
    metadata = data_run.metadata or {}
    if data_run.status != DataRun.Status.FAILED:
        return None
    error_text = metadata.get("error")
    if not isinstance(error_text, str) or not error_text.strip():
        return None
    return {
        "check_id": None,
        "run_issue_id": None,
        "title": "DCS run failed",
        "status": "FAIL",
        "severity": "critical",
        "dimension": None,
        "detail": _redact_secrets(error_text.strip()),
        "suggested_fix": (
            "Fix connectors under Connected stack, then retry scoring."
        ),
        "fix_type": "Configuration",
        "fix_owner": "Klints (automated)",
        "fix_in_klints": True,
        "systems_compared": "",
        "root_cause_ids": [],
        "is_optional": False,
        "revenue_impact": 0.0,
        "currency": None,
        "evidence_preview": [],
    }


def build_enriched_issue(
    *,
    check_id: str,
    status: str,
    result: dict[str, Any] | None,
    run_issue: RunIssue | None,
    master: CheckMaster | None,
    optional_check_ids: frozenset[str],
) -> dict[str, Any]:
    details = (
        run_issue.details
        if run_issue is not None and isinstance(run_issue.details, dict)
        else {}
    )
    severity = None
    # Prefer RunIssue.severity, then check_results, then CheckMaster (PRD §4.5).
    if run_issue is not None and run_issue.severity:
        severity = run_issue.severity
    if not severity and isinstance(result, dict):
        severity = result.get("severity")
    if not severity and master is not None:
        severity = master.severity
    is_optional = is_optional_check_id(
        check_id, optional_check_ids=optional_check_ids
    ) or bool(master and master.is_optional)

    revenue_impact = resolve_revenue_impact(run_issue=run_issue, result=result)
    currency = resolve_currency(
        revenue_impact=revenue_impact,
        run_issue=run_issue,
        result=result,
    )
    suggested_fix = _suggested_fix(
        details=details, result=result, master=master
    )
    ownership = _fix_ownership(
        details=details,
        result=result,
        master=master,
        suggested_fix=suggested_fix,
    )
    systems_compared = ""
    if master is not None and isinstance(master.systems_compared, str):
        systems_compared = master.systems_compared.strip()
    if not systems_compared and isinstance(result, dict):
        raw = result.get("systems_compared")
        if isinstance(raw, str):
            systems_compared = raw.strip()
    if not systems_compared and isinstance(details, dict):
        raw = details.get("systems_compared")
        if isinstance(raw, str):
            systems_compared = raw.strip()

    return {
        "check_id": check_id,
        "run_issue_id": str(run_issue.id) if run_issue is not None else None,
        "title": _title_for_issue(
            check_id=check_id,
            details=details,
            result=result,
            master=master,
        ),
        "status": status,
        "severity": str(severity or "high").lower(),
        "dimension": _dimension_label(master),
        "detail": _detail_text(details=details, result=result),
        "suggested_fix": ownership["suggested_fix"] or suggested_fix,
        "fix_type": ownership["fix_type"],
        "fix_owner": ownership["fix_owner"],
        "fix_in_klints": ownership["fix_in_klints"],
        "systems_compared": systems_compared,
        "root_cause_ids": _root_cause_ids(
            details=details, result=result, master=master
        ),
        "is_optional": is_optional,
        "revenue_impact": revenue_impact,
        "currency": currency,
        "evidence_preview": build_evidence_preview(
            details=details, result=result
        ),
    }


def sort_worklist_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PRD §4.2: revenue DESC → required before optional → severity → check_id ASC."""

    def sort_key(issue: dict[str, Any]):
        revenue = _coerce_revenue(issue.get("revenue_impact"))
        return (
            -revenue,
            bool(issue.get("is_optional", False)),
            _severity_key(issue.get("severity")),
            issue.get("check_id") or "",
        )

    return sorted(issues, key=sort_key)


def build_enriched_issues(
    *,
    data_run: DataRun | None,
    optional_check_ids: frozenset[str] | None = None,
    check_master_by_id: dict[str, CheckMaster] | None = None,
    cap: int | None = None,
) -> list[dict[str, Any]]:
    """Build FAIL+WARN enriched issues for a terminal DataRun."""
    if data_run is None:
        return []

    if optional_check_ids is None:
        optional_check_ids = load_optional_check_ids()
    if check_master_by_id is None:
        check_master_by_id = load_check_master_by_id()

    metadata = data_run.metadata or {}
    payload = extract_dcs_payload(metadata)
    check_results = [
        row for row in payload["check_results"] if isinstance(row, dict)
    ]
    run_issues = load_run_issues_by_check_id(payload.get("domain_run_id"))

    issues: list[dict[str, Any]] = []
    seen_check_ids: set[str] = set()

    for result in check_results:
        if not should_include_check_result(result):
            continue
        check_id = result.get("check_id")
        if not isinstance(check_id, str) or not check_id:
            continue
        seen_check_ids.add(check_id)
        status = str(result.get("status") or "").upper()
        master = check_master_by_id.get(check_id)
        run_issue = run_issues.get(check_id)
        issues.append(
            build_enriched_issue(
                check_id=check_id,
                status=status,
                result=result,
                run_issue=run_issue,
                master=master,
                optional_check_ids=optional_check_ids,
            )
        )

    # Include RunIssue FAIL/WARN rows not present in check_results (edge case).
    for check_id, run_issue in run_issues.items():
        if check_id in seen_check_ids:
            continue
        details = (
            run_issue.details if isinstance(run_issue.details, dict) else {}
        )
        status = str(details.get("status") or "").upper()
        if status not in INCLUDE_STATUSES:
            continue
        master = check_master_by_id.get(check_id)
        issues.append(
            build_enriched_issue(
                check_id=check_id,
                status=status,
                result=None,
                run_issue=run_issue,
                master=master,
                optional_check_ids=optional_check_ids,
            )
        )

    synthetic = build_synthetic_failed_run_issue(data_run=data_run)
    if synthetic is not None:
        issues.append(synthetic)

    issues = sort_worklist_issues(issues)

    if cap is not None:
        return issues[:cap]
    return issues


def extract_business_impact(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    metadata = metadata or {}
    business_impact = metadata.get("business_impact")
    if isinstance(business_impact, dict):
        return business_impact
    return None


def extract_dimensions(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = extract_dcs_payload(metadata)
    dcs_run = payload.get("dcs_run") or {}
    dimensions = dcs_run.get("dimensions")
    if isinstance(dimensions, dict) and dimensions:
        # Normalize DimensionScore dataclasses already stored as dicts.
        out: dict[str, Any] = {}
        for key, value in dimensions.items():
            if isinstance(value, dict):
                out[str(key)] = value
            else:
                out[str(key)] = value
        return out or None
    return None


def build_dimension_checks(
    *,
    check_results: list[dict[str, Any]],
    check_master_by_id: dict[str, CheckMaster] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Group check results under dimension labels for DCS sub-score expand."""
    if check_master_by_id is None:
        check_master_by_id = load_check_master_by_id()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in check_results:
        if not isinstance(result, dict):
            continue
        check_id = result.get("check_id")
        if not isinstance(check_id, str) or not check_id.strip():
            continue
        master = check_master_by_id.get(check_id)
        dimension = _dimension_label(master) or "Other"
        status = str(result.get("status") or "UNKNOWN").upper()
        name = None
        if master is not None and master.check_name:
            name = master.check_name
        if not name and isinstance(result.get("check_name"), str):
            name = result["check_name"]
        if not name:
            name = check_id
        grouped.setdefault(dimension, []).append(
            {
                "check_id": check_id,
                "name": name,
                "status": status,
            }
        )
    for rows in grouped.values():
        rows.sort(key=lambda row: row.get("check_id") or "")
    return grouped


def extract_sample_size(
    *,
    data_run: DataRun | None,
    company: Company | None = None,
) -> int | None:
    """Profile/contact universe size for the DCS rail (design: Sample size)."""

    def as_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None
        return n if n >= 0 else None

    def from_counts(counts: Any) -> int | None:
        if not isinstance(counts, dict):
            return None
        for key in ("contacts_total", "manago_contacts", "shopify_customers", "contacts"):
            n = as_int(counts.get(key))
            if n is not None and n > 0:
                return n
        candidates = [
            as_int(counts.get(key))
            for key in (
                "contacts_total",
                "manago_contacts",
                "shopify_customers",
                "contacts",
            )
        ]
        positives = [n for n in candidates if n is not None]
        return max(positives) if positives else None

    if data_run is not None:
        snapshot = data_run.run_snapshot
        if isinstance(snapshot, dict):
            n = from_counts(snapshot.get("counts"))
            if n is not None and n > 0:
                return n

        metadata = data_run.metadata if isinstance(data_run.metadata, dict) else {}
        # Prefer totals from the frozen snapshot; fall back to fresh-import counts.
        fresh = metadata.get("fresh_imports")
        if isinstance(fresh, dict):
            for platform in ("manago_ai", "shopify"):
                block = fresh.get(platform)
                if isinstance(block, dict):
                    n = from_counts(block.get("counts"))
                    if n is not None and n > 0:
                        return n

    # Live DB fallback so the rail still shows a real number when snapshot
    # counts were never persisted (or an older run lacks them).
    resolved_company = company
    if resolved_company is None and data_run is not None:
        company_id = None
        metadata = data_run.metadata if isinstance(data_run.metadata, dict) else {}
        raw_id = metadata.get("company_id")
        if isinstance(raw_id, str) and raw_id.strip():
            company_id = raw_id.strip()
        if company_id:
            resolved_company = Company.objects.filter(id=company_id).first()

    if resolved_company is not None:
        n = Contact.objects.filter(company=resolved_company).count()
        if n > 0:
            return n

    return None


def _dimension_sort_key(label: str) -> tuple[str, str]:
    token = label.strip().split(" ", 1)[0]
    if len(token) == 2 and token.isdigit():
        return (token, label)
    return ("99", label)


def get_previous_scored_dcs_run(
    *,
    company: Company,
    before_data_run_id: int | None = None,
) -> DataRun | None:
    """Latest succeeded scored run strictly before ``before_data_run_id`` (chronological)."""
    from django.db.models import DateTimeField
    from django.db.models.functions import Coalesce

    at = Coalesce("finished_at", "created_at", output_field=DateTimeField())
    qs = (
        _company_dcs_runs(company=company)
        .filter(status=DataRun.Status.SUCCEEDED)
        .annotate(at=at)
        .exclude(at__isnull=True)
        .order_by("-at", "-id")
    )
    if before_data_run_id is not None:
        qs = qs.exclude(id=before_data_run_id)
        current = (
            DataRun.objects.filter(pk=before_data_run_id)
            .annotate(at=at)
            .only("id", "finished_at", "created_at")
            .first()
        )
        if current is not None and current.at is not None:
            qs = qs.filter(at__lt=current.at)

    for data_run in qs:
        metadata = data_run.metadata if isinstance(data_run.metadata, dict) else {}
        payload = extract_dcs_payload(metadata)
        if coerce_headline_score(payload.get("headline_score")) is not None:
            return data_run
    return None


def enrich_dimensions_for_status(
    *,
    dimensions: dict[str, Any] | None,
    company: Company | None,
    current_data_run_id: int | None,
) -> dict[str, Any] | None:
    """Canonical dimension order plus ``score_delta`` vs the previous scored run."""
    if not dimensions:
        return None

    previous_dims: dict[str, Any] | None = None
    if company is not None:
        previous_run = get_previous_scored_dcs_run(
            company=company,
            before_data_run_id=current_data_run_id,
        )
        if previous_run is not None:
            previous_dims = extract_dimensions(previous_run.metadata)

    enriched: dict[str, Any] = {}
    for name in sorted(dimensions.keys(), key=lambda key: _dimension_sort_key(str(key))):
        dim = dimensions[name]
        if not isinstance(dim, dict):
            continue
        row = dict(dim)
        current_score = dim.get("score")
        prev_score = None
        if isinstance(previous_dims, dict) and isinstance(previous_dims.get(name), dict):
            prev_score = previous_dims[name].get("score")
        score_delta = None
        if current_score is not None and prev_score is not None:
            try:
                score_delta = round(float(current_score)) - round(float(prev_score))
            except (TypeError, ValueError):
                score_delta = None
        row["score_delta"] = score_delta
        enriched[str(name)] = row
    return enriched or None


def build_status_enrichment(
    *,
    data_run: DataRun | None,
    company: Company | None = None,
) -> dict[str, Any]:
    """Extra status fields: check_summary, dimensions, business_impact, dimension_checks."""
    if data_run is None:
        sample = extract_sample_size(data_run=None, company=company)
        return {
            "check_summary": None,
            "dimensions": None,
            "business_impact": None,
            "dimension_checks": None,
            "sample_size": sample,
        }
    metadata = data_run.metadata or {}
    payload = extract_dcs_payload(metadata)
    check_results = [
        row for row in payload["check_results"] if isinstance(row, dict)
    ]
    summary = build_check_summary(check_results) if check_results else None
    masters = load_check_master_by_id() if check_results else {}
    return {
        "check_summary": summary,
        "dimensions": enrich_dimensions_for_status(
            dimensions=extract_dimensions(metadata),
            company=company,
            current_data_run_id=data_run.id,
        ),
        "business_impact": extract_business_impact(metadata),
        "dimension_checks": (
            build_dimension_checks(
                check_results=check_results,
                check_master_by_id=masters,
            )
            if check_results
            else None
        ),
        "sample_size": extract_sample_size(data_run=data_run, company=company),
    }


def build_worklist_payload(*, company: Company) -> dict[str, Any]:
    """GET /api/v1/dcs/worklist/ response body."""
    data_run = get_latest_terminal_dcs_run(company=company)
    if data_run is None:
        return {
            "data_run_id": None,
            "domain_run_id": None,
            "run_state": None,
            "headline_score": None,
            "business_impact": None,
            "count": 0,
            "issues": [],
        }

    optional_check_ids = load_optional_check_ids()
    check_master_by_id = load_check_master_by_id()
    metadata = data_run.metadata or {}
    payload = extract_dcs_payload(metadata)
    issues = build_enriched_issues(
        data_run=data_run,
        optional_check_ids=optional_check_ids,
        check_master_by_id=check_master_by_id,
        cap=None,
    )
    return {
        "data_run_id": data_run.id,
        "domain_run_id": payload.get("domain_run_id"),
        "run_state": payload.get("run_state"),
        "headline_score": coerce_headline_score(payload.get("headline_score")),
        "business_impact": extract_business_impact(metadata),
        "count": len(issues),
        "issues": issues,
    }


def _normalize_evidence_list(rows: Any, *, truncate: bool) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for item in rows:
        normalized = _normalize_evidence_item(item, truncate=truncate)
        if normalized is not None:
            out.append(normalized)
    return out


def _synthesize_evidence_from_result(
    *,
    details: dict[str, Any],
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build readable evidence rows when executors left lists empty."""
    observed = ""
    if isinstance(result.get("evaluated_at"), str):
        observed = result["evaluated_at"]
    rows: list[dict[str, Any]] = []

    def add(locator: str, value: Any, source: str = "klints") -> None:
        if value is None or value == "" or value == [] or value == {}:
            return
        normalized = _normalize_evidence_item(
            {
                "source": source,
                "locator": locator,
                "value": value,
                "observed_at": observed,
            },
            truncate=False,
        )
        if normalized is not None:
            rows.append(normalized)

    add("status", result.get("status") or details.get("status"))
    add("reason_code", result.get("reason_code") or details.get("reason_code"))
    add("message", result.get("message") or details.get("message"))
    root_causes = result.get("root_cause_ids") or details.get("root_cause_ids")
    add("root_cause_ids", root_causes)

    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        provenance = details.get("provenance") if isinstance(details.get("provenance"), dict) else {}
    skip = {
        "matches",
        "mismatches",
        "evidence",
        "sample_rows",
        "samples",
        "rows",
    }
    for key, value in provenance.items():
        if key in skip:
            continue
        add(f"provenance.{key}", value)

    return rows


def _full_evidence_lists(
    *,
    details: dict[str, Any],
    result: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Full evidence for detail API — no preview truncation (PRD §4.5)."""
    details = details if isinstance(details, dict) else {}
    result = result if isinstance(result, dict) else {}
    provenance = (
        result.get("provenance")
        if isinstance(result.get("provenance"), dict)
        else {}
    )
    if not provenance and isinstance(details.get("provenance"), dict):
        provenance = details["provenance"]

    evidence = _normalize_evidence_list(details.get("evidence"), truncate=False)
    matches = _normalize_evidence_list(details.get("matches"), truncate=False)
    mismatches = _normalize_evidence_list(details.get("mismatches"), truncate=False)

    if not evidence:
        evidence = _normalize_evidence_list(result.get("evidence"), truncate=False)
    if not matches:
        matches = _normalize_evidence_list(provenance.get("matches"), truncate=False)
    if not mismatches:
        mismatches = _normalize_evidence_list(
            provenance.get("mismatches"), truncate=False
        )

    status = str(result.get("status") or details.get("status") or "").upper()
    if not mismatches and not matches and evidence:
        if status in INCLUDE_STATUSES:
            mismatches = list(evidence)
        elif status == "PASS":
            matches = list(evidence)

    if not evidence and not matches and not mismatches:
        evidence = _synthesize_evidence_from_result(details=details, result=result)
        if evidence and status in INCLUDE_STATUSES and not mismatches:
            mismatches = list(evidence)

    return evidence, matches, mismatches


def build_worklist_detail(
    *,
    company: Company,
    check_id: str,
) -> dict[str, Any]:
    """GET /api/v1/dcs/worklist/{check_id}/ — raises WorklistDetailNotFound."""
    check_id = (check_id or "").strip()
    if not check_id:
        raise WorklistDetailNotFound(check_id)

    data_run = get_latest_terminal_dcs_run(company=company)
    if data_run is None:
        raise WorklistDetailNotFound(check_id)

    optional_check_ids = load_optional_check_ids()
    check_master_by_id = load_check_master_by_id()
    metadata = data_run.metadata or {}
    payload = extract_dcs_payload(metadata)
    check_results = [
        row for row in payload["check_results"] if isinstance(row, dict)
    ]
    results_by_id = {
        str(row.get("check_id")): row
        for row in check_results
        if isinstance(row.get("check_id"), str)
    }
    run_issues = load_run_issues_by_check_id(payload.get("domain_run_id"))

    result = results_by_id.get(check_id)
    run_issue = run_issues.get(check_id)

    status: str | None = None
    if isinstance(result, dict) and should_include_check_result(result):
        status = str(result.get("status") or "").upper()
    elif run_issue is not None:
        details = (
            run_issue.details if isinstance(run_issue.details, dict) else {}
        )
        candidate = str(details.get("status") or "").upper()
        # INCLUDE_STATUSES is FAIL/WARN only; stubs are already excluded.
        if candidate in INCLUDE_STATUSES:
            status = candidate

    if status not in INCLUDE_STATUSES:
        raise WorklistDetailNotFound(check_id)

    master = check_master_by_id.get(check_id)
    enriched = build_enriched_issue(
        check_id=check_id,
        status=status,
        result=result,
        run_issue=run_issue,
        master=master,
        optional_check_ids=optional_check_ids,
    )
    details = (
        run_issue.details
        if run_issue is not None and isinstance(run_issue.details, dict)
        else {}
    )
    evidence, matches, mismatches = _full_evidence_lists(
        details=details, result=result
    )
    provenance: dict[str, Any] = {}
    if isinstance(result, dict) and isinstance(result.get("provenance"), dict):
        provenance = dict(result["provenance"])
    elif isinstance(details.get("provenance"), dict):
        provenance = dict(details["provenance"])

    return {
        "data_run_id": data_run.id,
        "domain_run_id": payload.get("domain_run_id"),
        "check_id": check_id,
        "run_issue_id": enriched["run_issue_id"],
        "title": enriched["title"],
        "status": enriched["status"],
        "severity": enriched["severity"],
        "dimension": enriched["dimension"],
        "detail": enriched["detail"],
        "suggested_fix": enriched["suggested_fix"],
        "fix_type": enriched.get("fix_type") or "",
        "fix_owner": enriched.get("fix_owner") or "",
        "fix_in_klints": bool(enriched.get("fix_in_klints")),
        "systems_compared": enriched.get("systems_compared") or "",
        "root_cause_ids": enriched["root_cause_ids"],
        "is_optional": enriched["is_optional"],
        "revenue_impact": enriched["revenue_impact"],
        "currency": enriched["currency"],
        "revenue_formula_id": resolve_revenue_formula_id(result),
        "evidence": evidence,
        "matches": matches,
        "mismatches": mismatches,
        "provenance": provenance,
    }
