"""Bootstrap health report helpers (PRD-CONN-01 §4 E5–E7, §5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any

from django.utils import timezone

from dataruns.models import DataRun
from tenants.models import ConnectorSnapshot

# Canonical scope names used in health_report and PRD messaging. Preflight treats
# each name as an Admin API capability, not a literal OAuth handle.
SHOPIFY_REQUIRED_SCOPES = frozenset({"read_customers", "read_orders"})
SHOPIFY_RECOMMENDED_SCOPES = frozenset()

# Shopify Admin API scopes are paired read/write handles; write_* grants the same
# REST/GraphQL resource access as read_* (Shopify access-scopes docs, 2026).
# Customer Account API handles (customer_read_*, customer_write_*) are separate
# and do not satisfy Admin API bootstrap requirements.
SHOPIFY_ADMIN_SCOPE_CAPABILITY_HANDLES: dict[str, frozenset[str]] = {
    "read_customers": frozenset({"read_customers", "write_customers"}),
    "read_orders": frozenset({"read_orders", "write_orders"}),
    "read_products": frozenset({"read_products", "write_products"}),
    "read_inventory": frozenset({"read_inventory", "write_inventory"}),
}
_SHOPIFY_PAGE_LIMIT = 250

RC_HINTS: dict[str, str] = {
    "AUTH_FAILED": "Reconnect the connector.",
    "SCOPES_MISSING": "Grant required scopes.",
    "EMPTY_CONTACTS_WINDOW": "Verify data exists in the selected window.",
    "EMPTY_ORDERS_WINDOW": "Verify orders exist in the selected window.",
    "PARTIAL_FETCH": "Retry bootstrap or investigate API limits.",
    "RATE_LIMIT": "Retry later.",
    "FETCH_FAILED": "Review connector logs.",
    "PERSIST_FAILED": "Check database persistence.",
}


def health_issue(
    *,
    code: str,
    severity: str,
    message: str,
    rc_hint: str | None = None,
) -> dict[str, str]:
    issue: dict[str, str] = {"code": code, "severity": severity, "message": message}
    hint = rc_hint if rc_hint is not None else RC_HINTS.get(code)
    if hint:
        issue["rc_hint"] = hint
    return issue


def with_rc_hint(issue: dict[str, str]) -> dict[str, str]:
    """Attach rc_hint when known; backward compatible for issues missing it."""
    if issue.get("rc_hint"):
        return issue
    code = issue.get("code")
    hint = RC_HINTS.get(code) if isinstance(code, str) else None
    if hint:
        return {**issue, "rc_hint": hint}
    return issue


def with_rc_hints(issues: list[dict[str, str]]) -> list[dict[str, str]]:
    return [with_rc_hint(issue) for issue in issues]


def parse_shopify_scopes(scopes_value: Any) -> set[str]:
    if not isinstance(scopes_value, str) or not scopes_value.strip():
        return set()
    return {
        scope.strip()
        for scope in scopes_value.split(",")
        if scope.strip()
    }


def shopify_admin_scope_satisfied(granted_scopes: set[str], canonical_scope: str) -> bool:
    """Return True when granted handles satisfy an Admin API scope capability."""
    acceptable_handles = SHOPIFY_ADMIN_SCOPE_CAPABILITY_HANDLES.get(canonical_scope)
    if acceptable_handles is None:
        return canonical_scope in granted_scopes
    return bool(granted_scopes & acceptable_handles)


def missing_shopify_scopes(
    granted_scopes: set[str],
    *,
    required: frozenset[str] = SHOPIFY_REQUIRED_SCOPES,
    recommended: frozenset[str] = SHOPIFY_RECOMMENDED_SCOPES,
) -> tuple[list[str], list[str]]:
    """Return unsatisfied required and recommended canonical scopes."""
    missing_required = sorted(
        scope
        for scope in required
        if not shopify_admin_scope_satisfied(granted_scopes, scope)
    )
    missing_recommended = sorted(
        scope
        for scope in recommended
        if not shopify_admin_scope_satisfied(granted_scopes, scope)
    )
    return missing_required, missing_recommended


def build_preflight_section(
    *,
    platform: str,
    config: dict[str, Any],
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    """Build the PRD §5 preflight block from preflight issues and connector config."""
    if platform == "shopify":
        granted = sorted(parse_shopify_scopes(config.get("scopes")))
        granted_set = set(granted)
        missing_required, missing_recommended = missing_shopify_scopes(granted_set)
        scopes_missing = sorted(set(missing_required) | set(missing_recommended))
        auth_ok = not any(issue.get("code") == "AUTH_FAILED" for issue in issues)
        scopes_ok = not any(
            issue.get("code") == "SCOPES_MISSING" and issue.get("severity") == "error"
            for issue in issues
        )
        return {
            "auth_ok": auth_ok,
            "scopes_ok": scopes_ok,
            "scopes_granted": granted,
            "scopes_missing": scopes_missing,
            "issues": list(issues),
        }

    auth_ok = not any(issue.get("code") == "AUTH_FAILED" for issue in issues)
    return {
        "auth_ok": auth_ok,
        "scopes_ok": True,
        "scopes_granted": [],
        "scopes_missing": [],
        "issues": list(issues),
    }


def postflight_health(
    *,
    platform: str,
    days: int,
    result: dict[str, Any],
    snapshot_data: dict[str, Any],
) -> list[dict[str, str]]:
    """Evaluate import result and snapshot data for post-bootstrap issues (PRD §4 E5)."""
    issues: list[dict[str, str]] = []
    counts = result.get("counts") or {}
    contacts_upserted = int(counts.get("contacts") or 0)
    orders_upserted = int(counts.get("orders") or 0)

    if contacts_upserted == 0:
        issues.append(
            health_issue(
                code="EMPTY_CONTACTS_WINDOW",
                severity="warn",
                message=f"0 contacts in last {days} days",
            )
        )
    if orders_upserted == 0:
        issues.append(
            health_issue(
                code="EMPTY_ORDERS_WINDOW",
                severity="warn",
                message=f"0 orders in last {days} days",
            )
        )

    raw = snapshot_data.get("raw")
    if isinstance(raw, dict):
        issues.extend(
            _partial_fetch_issues(platform=platform, raw=raw, snapshot_data=snapshot_data)
        )

    return issues


def _partial_fetch_issues(
    *,
    platform: str,
    raw: dict[str, Any],
    snapshot_data: dict[str, Any],
) -> list[dict[str, str]]:
    """Detect PARTIAL_FETCH from snapshot notes or Shopify page-limit heuristic.

    Import snapshots do not record pagination truncation metadata today (see
    import_data._build_snapshot_data notes=[]). Without changing the import
    pipeline, notes and the Shopify 250-item boundary heuristic are the only
    signals available.
    """
    issues: list[dict[str, str]] = []
    notes = snapshot_data.get("notes")
    if isinstance(notes, list):
        for note in notes:
            if not isinstance(note, str):
                continue
            lowered = note.lower()
            if "truncat" in lowered or "partial" in lowered:
                issues.append(
                    health_issue(
                        code="PARTIAL_FETCH",
                        severity="warn",
                        message=note,
                    )
                )
                return issues

    if platform == "shopify":
        customers = raw.get("customers")
        orders = raw.get("orders")
        customer_count = len(customers) if isinstance(customers, list) else 0
        order_count = len(orders) if isinstance(orders, list) else 0
        if customer_count > 0 and customer_count % _SHOPIFY_PAGE_LIMIT == 0:
            issues.append(
                health_issue(
                    code="PARTIAL_FETCH",
                    severity="warn",
                    message=(
                        "Customer fetch reached Shopify pagination limit; "
                        "additional pages may exist."
                    ),
                )
            )
        if order_count > 0 and order_count % _SHOPIFY_PAGE_LIMIT == 0:
            issues.append(
                health_issue(
                    code="PARTIAL_FETCH",
                    severity="warn",
                    message=(
                        "Order fetch reached Shopify pagination limit; "
                        "additional pages may exist."
                    ),
                )
            )
    return issues


def build_fetch_section(
    *,
    result: dict[str, Any],
    snapshot_data: dict[str, Any],
    duration_ms: int,
    import_succeeded: bool,
) -> dict[str, Any]:
    """Build the PRD §5 fetch block from import result and snapshot data."""
    counts = result.get("counts") or {}
    contacts_upserted = int(counts.get("contacts") or 0)
    orders_upserted = int(counts.get("orders") or 0)
    raw = snapshot_data.get("raw") if isinstance(snapshot_data.get("raw"), dict) else {}
    platform = str(result.get("connector") or snapshot_data.get("platform") or "")
    raw_contacts, raw_orders = _raw_entity_counts(platform=platform, raw=raw)

    fetch: dict[str, Any] = {
        "ok": import_succeeded,
        "contacts_upserted": contacts_upserted,
        "orders_upserted": orders_upserted,
        "raw_customers_or_contacts": raw_contacts,
        "raw_orders_or_transactions": raw_orders,
        "duration_ms": duration_ms,
    }
    rate_budget = result.get("rate_budget")
    if isinstance(rate_budget, dict) and rate_budget:
        fetch["rate_budget"] = rate_budget
    return fetch


def _raw_entity_counts(*, platform: str, raw: dict[str, Any]) -> tuple[int, int]:
    if platform == "shopify":
        customers = raw.get("customers")
        orders = raw.get("orders")
        return (
            len(customers) if isinstance(customers, list) else 0,
            len(orders) if isinstance(orders, list) else 0,
        )
    if platform == "manago_ai":
        contacts = raw.get("contacts")
        transactions = raw.get("transactions")
        return (
            len(contacts) if isinstance(contacts, list) else 0,
            len(transactions) if isinstance(transactions, list) else 0,
        )
    return 0, 0


def compute_summary_status(
    *,
    import_succeeded: bool,
    issues: list[dict[str, str]],
) -> str:
    """Derive summary_status per PRD §5."""
    if not import_succeeded:
        return "error"
    if any(issue.get("severity") == "error" for issue in issues):
        return "error"
    if any(issue.get("severity") == "warn" for issue in issues):
        return "degraded"
    return "ok"


def connector_status_from_summary(summary_status: str) -> str:
    """Map summary_status to Connector.status (PRD §5)."""
    if summary_status == "ok":
        return "connected"
    if summary_status == "degraded":
        return "degraded"
    return "error"


def classify_import_failure(exc: BaseException) -> dict[str, str]:
    """Map import exceptions to PRD issue codes."""
    message = str(exc)
    lowered = message.lower()
    if "429" in message or "rate limit" in lowered:
        return health_issue(
            code="RATE_LIMIT",
            severity="error",
            message=message,
        )
    if _looks_like_persist_failure(lowered):
        return health_issue(
            code="PERSIST_FAILED",
            severity="error",
            message=message,
        )
    return health_issue(
        code="FETCH_FAILED",
        severity="error",
        message=message,
    )


def _looks_like_persist_failure(message_lower: str) -> bool:
    persist_markers = (
        "persist",
        "database",
        "integrity",
        "duplicate key",
        "upsert",
        "operationalerror",
        "integrityerror",
    )
    return any(marker in message_lower for marker in persist_markers)


def resolve_window_bounds(
    *,
    days: int,
    window_start: str | None = None,
    window_end: str | None = None,
    data_run: DataRun | None = None,
) -> tuple[str | None, str | None]:
    if window_start and window_end:
        return window_start, window_end
    if data_run is None or data_run.started_at is None:
        return window_start, window_end
    end = data_run.started_at
    if timezone.is_naive(end):
        end = timezone.make_aware(end, dt_timezone.utc)
    start = end - timedelta(days=days)
    return _format_timestamp(start), _format_timestamp(end)


def _format_timestamp(value: datetime) -> str:
    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_health_report(
    *,
    platform: str,
    days: int,
    config: dict[str, Any],
    preflight_issues: list[dict[str, str]],
    postflight_issues: list[dict[str, str]],
    result: dict[str, Any] | None,
    snapshot_data: dict[str, Any],
    duration_ms: int,
    import_succeeded: bool,
    import_issue: dict[str, str] | None = None,
    data_run: DataRun | None = None,
) -> dict[str, Any]:
    """Assemble the canonical PRD §5 health_report object."""
    preflight_issues = with_rc_hints(preflight_issues)
    postflight_issues = with_rc_hints(postflight_issues)
    if import_issue is not None:
        import_issue = with_rc_hint(import_issue)

    preflight = build_preflight_section(
        platform=platform,
        config=config,
        issues=preflight_issues,
    )
    fetch_result = result or {
        "connector": platform,
        "counts": {},
        "window_start": None,
        "window_end": None,
    }
    fetch = build_fetch_section(
        result=fetch_result,
        snapshot_data=snapshot_data,
        duration_ms=duration_ms,
        import_succeeded=import_succeeded,
    )
    postflight_issue_list = list(postflight_issues)
    if import_issue is not None:
        postflight_issue_list.append(import_issue)

    all_issues = list(preflight_issues) + postflight_issue_list
    summary_status = compute_summary_status(
        import_succeeded=import_succeeded,
        issues=all_issues,
    )
    blocking = summary_status == "error"
    window_start, window_end = resolve_window_bounds(
        days=days,
        window_start=fetch_result.get("window_start"),
        window_end=fetch_result.get("window_end"),
        data_run=data_run,
    )

    return {
        "platform": platform,
        "days": days,
        "window_start": window_start,
        "window_end": window_end,
        "preflight": preflight,
        "fetch": fetch,
        "postflight": {"issues": postflight_issue_list},
        "blocking": blocking,
        "summary_status": summary_status,
    }


def persist_health_report(*, data_run: DataRun, health_report: dict[str, Any]) -> None:
    """Store health_report on DataRun.metadata (PRD §4 E6)."""
    data_run.metadata = {
        **(data_run.metadata or {}),
        "health_report": health_report,
    }
    data_run.save(update_fields=["metadata", "updated_at"])


def load_snapshot_data(snapshot_id: str | None) -> dict[str, Any]:
    if not snapshot_id:
        return {}
    try:
        snapshot = ConnectorSnapshot.objects.get(pk=snapshot_id)
    except ConnectorSnapshot.DoesNotExist:
        return {}
    snapshot_data = snapshot.snapshot_data
    return snapshot_data if isinstance(snapshot_data, dict) else {}


def warn_issues_from_health_report(health_report: dict[str, Any]) -> list[dict[str, str]]:
    """Collect all warn-severity issues from preflight and postflight sections."""
    warn_issues: list[dict[str, str]] = []
    preflight = health_report.get("preflight")
    if isinstance(preflight, dict):
        preflight_issues = preflight.get("issues")
        if isinstance(preflight_issues, list):
            warn_issues.extend(
                issue
                for issue in preflight_issues
                if isinstance(issue, dict) and issue.get("severity") == "warn"
            )
    postflight = health_report.get("postflight")
    if isinstance(postflight, dict):
        postflight_issues = postflight.get("issues")
        if isinstance(postflight_issues, list):
            warn_issues.extend(
                issue
                for issue in postflight_issues
                if isinstance(issue, dict) and issue.get("severity") == "warn"
            )
    return warn_issues


def count_health_report_issues(health_report: dict[str, Any]) -> int:
    """Count all health issues in preflight + postflight (PRD-CONN-04)."""
    total = 0
    preflight = health_report.get("preflight")
    if isinstance(preflight, dict):
        preflight_issues = preflight.get("issues")
        if isinstance(preflight_issues, list):
            total += sum(1 for issue in preflight_issues if isinstance(issue, dict))
    postflight = health_report.get("postflight")
    if isinstance(postflight, dict):
        postflight_issues = postflight.get("issues")
        if isinstance(postflight_issues, list):
            total += sum(1 for issue in postflight_issues if isinstance(issue, dict))
    return total


def build_latest_bootstrap_payload(data_run: DataRun) -> dict[str, Any]:
    """Build latest_bootstrap object for GET /api/v1/connectors/ (PRD-CONN-04)."""
    metadata = data_run.metadata or {}
    health_report = metadata.get("health_report")
    if not isinstance(health_report, dict):
        health_report = {}

    fetch = health_report.get("fetch")
    if not isinstance(fetch, dict):
        fetch = {}

    counts = metadata.get("counts")
    if not isinstance(counts, dict):
        counts = {}

    contacts = fetch.get("contacts_upserted")
    if contacts is None:
        contacts = counts.get("contacts", 0)
    orders = fetch.get("orders_upserted")
    if orders is None:
        orders = counts.get("orders", 0)

    finished_at = data_run.finished_at
    return {
        "data_run_id": data_run.id,
        "run_id": metadata.get("run_id"),
        "data_run_status": data_run.status,
        "contacts": int(contacts or 0),
        "orders": int(orders or 0),
        "issue_count": count_health_report_issues(health_report),
        "summary_status": health_report.get("summary_status"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z")
        if finished_at is not None
        else None,
    }
