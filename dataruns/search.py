"""Company-scoped Spotlight search (PRD-FE-05 §6)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils import timezone

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.status import _extract_dcs_payload
from dataruns.models import AuditLog, CheckMaster, DataRun, RunIssue
from tenants.models import Company, Connector, ConnectorSnapshot

V1_SEARCH_TYPES = frozenset({"issue", "audit", "connector", "run"})
TYPE_ORDER = ("issue", "run", "connector", "audit")

_ISSUE_STATUS_RANK = {
    "FAIL": 0,
    "WARN": 1,
    "PASS": 2,
}


@dataclass(frozen=True)
class SearchHit:
    type: str
    id: str
    title: str
    subtitle: str
    href: str
    meta: dict[str, Any]


def _connector_display_name(name: str) -> str:
    if name == "manago_ai":
        return "Manago.ai"
    if name == "shopify":
        return "Shopify"
    return name


def _normalize_query(q: str) -> str:
    return (q or "").strip()


def _icontains_match(q: str, *values: str | None) -> bool:
    needle = q.casefold()
    for value in values:
        if isinstance(value, str) and needle in value.casefold():
            return True
    return False


def _exact_match(q: str, *values: str | None) -> bool:
    needle = q.casefold()
    for value in values:
        if isinstance(value, str) and value.casefold() == needle:
            return True
    return False


def _format_short_date(value: datetime | None) -> str:
    if value is None:
        return ""
    return f"{value.day} {value.strftime('%b')}"


def _format_relative_time(value: datetime | None) -> str:
    if value is None:
        return ""
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone=timezone.utc)
    delta = timezone.now() - value
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    return f"{value.day} {value.strftime('%b')}"


def _latest_dcs_data_run(*, company: Company) -> DataRun | None:
    return (
        DataRun.objects.filter(
            tenant=company.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            metadata__kind=DCS_SCORE_KIND,
            metadata__company_id=str(company.id),
        )
        .order_by("-created_at")
        .first()
    )


def _load_check_master_lookup() -> dict[str, CheckMaster]:
    return {
        row.check_id: row
        for row in CheckMaster.objects.select_related("dimension").all()
    }


def _latest_snapshot_data(connector: Connector) -> dict[str, Any]:
    snapshot = (
        ConnectorSnapshot.objects.filter(connector=connector)
        .order_by("-version")
        .first()
    )
    if snapshot is None:
        return {}
    data = snapshot.snapshot_data
    return data if isinstance(data, dict) else {}


def _connector_search_text(connector: Connector) -> tuple[str, str, dict[str, Any]]:
    display_name = _connector_display_name(connector.name)
    snapshot = _latest_snapshot_data(connector)
    account_bits = [
        connector.external_account_key or "",
        str(snapshot.get("shop_domain") or ""),
        str(snapshot.get("shop_name") or ""),
        str(snapshot.get("workspace_id") or ""),
        str(snapshot.get("base_url") or ""),
    ]
    account_label = next(
        (bit for bit in account_bits if isinstance(bit, str) and bit.strip()),
        "",
    )
    return display_name, account_label, snapshot


def _issue_title(
    *,
    check_id: str,
    details: dict[str, Any],
    master: CheckMaster | None,
) -> str:
    if master is not None and master.check_name:
        return master.check_name
    message = details.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    title = details.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return check_id


def _issue_subtitle(
    *,
    check_id: str,
    status: str,
    master: CheckMaster | None,
) -> str:
    dimension = ""
    if master is not None and master.dimension is not None:
        dimension = master.dimension.name
    parts = [check_id, status]
    if dimension:
        parts.append(dimension)
    return " · ".join(parts)


def _search_issues(
    *,
    company: Company,
    q: str,
    limit: int,
    check_master_by_id: dict[str, CheckMaster],
) -> list[SearchHit]:
    latest = _latest_dcs_data_run(company=company)
    if latest is None:
        return []

    payload = _extract_dcs_payload(latest.metadata)
    domain_run_id = payload.get("domain_run_id")
    hits: list[tuple[tuple[int, int, str], SearchHit]] = []

    def add_hit(
        *,
        hit_id: str,
        check_id: str,
        details: dict[str, Any],
        status: str,
        run_id: str | None,
        rank_bias: int = 0,
    ) -> None:
        master = check_master_by_id.get(check_id)
        title = _issue_title(check_id=check_id, details=details, master=master)
        message = details.get("message")
        if not _icontains_match(
            q,
            check_id,
            title,
            str(message or ""),
            master.check_name if master else None,
        ):
            return

        exact = 0 if _exact_match(q, check_id) else 1
        status_rank = _ISSUE_STATUS_RANK.get(status, 9)
        hit = SearchHit(
            type="issue",
            id=hit_id,
            title=title,
            subtitle=_issue_subtitle(
                check_id=check_id,
                status=status,
                master=master,
            ),
            href=f"/data-consistency?check={check_id}",
            meta={
                "check_id": check_id,
                "status": status,
                "dimension": (
                    master.dimension.name
                    if master is not None and master.dimension is not None
                    else None
                ),
                "run_id": run_id,
            },
        )
        hits.append(((rank_bias, status_rank, exact, check_id), hit))

    if domain_run_id:
        try:
            parsed_run_id = uuid.UUID(str(domain_run_id))
        except (ValueError, TypeError):
            parsed_run_id = None
        if parsed_run_id is not None:
            for issue in RunIssue.objects.filter(run_id=parsed_run_id):
                details = issue.details if isinstance(issue.details, dict) else {}
                check_id = str(details.get("check_id") or issue.issue_type)
                status = str(details.get("status") or issue.severity or "")
                add_hit(
                    hit_id=str(issue.id),
                    check_id=check_id,
                    details=details,
                    status=status,
                    run_id=str(domain_run_id),
                    rank_bias=0,
                )

    if not hits:
        for result in payload.get("check_results") or []:
            if not isinstance(result, dict):
                continue
            check_id = result.get("check_id")
            if not isinstance(check_id, str) or not check_id:
                continue
            status = str(result.get("status") or "")
            details = {
                "check_id": check_id,
                "status": status,
                "message": result.get("message"),
                "title": result.get("title"),
            }
            add_hit(
                hit_id=check_id,
                check_id=check_id,
                details=details,
                status=status,
                run_id=str(domain_run_id) if domain_run_id else None,
                rank_bias=1,
            )

    hits.sort(key=lambda item: item[0])
    return [hit for _, hit in hits[:limit]]


def _search_audit(*, company: Company, q: str, limit: int) -> list[SearchHit]:
    hits: list[SearchHit] = []
    queryset = AuditLog.objects.filter(company=company).order_by("-created_at", "-id")
    for entry in queryset[:200]:
        if not _icontains_match(q, entry.summary, entry.action, entry.performed_by):
            continue
        relative = _format_relative_time(entry.created_at)
        subtitle = entry.action
        if relative:
            subtitle = f"{entry.action} · {relative}"
        hits.append(
            SearchHit(
                type="audit",
                id=str(entry.id),
                title=entry.summary,
                subtitle=subtitle,
                href="/activity",
                meta={
                    "action": entry.action,
                    "tone": entry.tone,
                },
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _search_connectors(*, company: Company, q: str, limit: int) -> list[SearchHit]:
    hits: list[SearchHit] = []
    connectors = Connector.objects.filter(company=company).order_by("name")
    for connector in connectors:
        display_name, account_label, _snapshot = _connector_search_text(connector)
        if not _icontains_match(
            q,
            connector.name,
            display_name,
            account_label,
            connector.external_account_key,
        ):
            continue
        subtitle_parts = [connector.status]
        if account_label:
            subtitle_parts.append(account_label)
        hits.append(
            SearchHit(
                type="connector",
                id=str(connector.id),
                title=display_name,
                subtitle=" · ".join(subtitle_parts),
                href="/integrations",
                meta={
                    "platform": connector.name,
                    "status": connector.status,
                },
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _search_runs(*, company: Company, q: str, limit: int) -> list[SearchHit]:
    hits: list[SearchHit] = []
    queryset = (
        DataRun.objects.filter(
            tenant=company.tenant,
            metadata__kind=DCS_SCORE_KIND,
            metadata__company_id=str(company.id),
        )
        .order_by("-created_at")
    )
    for data_run in queryset[:100]:
        metadata = data_run.metadata if isinstance(data_run.metadata, dict) else {}
        kind = str(metadata.get("kind") or "")
        if not _icontains_match(
            q,
            data_run.name,
            data_run.status,
            str(data_run.id),
            kind,
        ):
            continue
        when = data_run.finished_at or data_run.created_at
        date_label = _format_short_date(when)
        subtitle = data_run.status
        if date_label:
            subtitle = f"{data_run.status} · {date_label}"
        hits.append(
            SearchHit(
                type="run",
                id=str(data_run.id),
                title=data_run.name,
                subtitle=subtitle,
                href="/data-consistency",
                meta={
                    "kind": kind or DCS_SCORE_KIND,
                    "status": data_run.status,
                    "data_run_id": data_run.id,
                },
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _search_workflows(*, q: str, limit: int) -> list[SearchHit]:
    """v1.1 stub — always empty (PRD-FE-05 §6.6)."""
    return []


def parse_search_types(raw: str | None) -> set[str]:
    if not raw:
        return set(V1_SEARCH_TYPES)
    parsed = {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }
    return {item for item in parsed if item in V1_SEARCH_TYPES}


def parse_search_limit(raw: str | None, *, default: int = 6) -> int:
    try:
        limit = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, 10))


def search_company(
    *,
    company: Company,
    q: str,
    types: set[str] | None = None,
    limit: int = 6,
) -> list[SearchHit]:
    """Fan-out company-scoped search across v1 result types."""
    normalized = _normalize_query(q)
    if len(normalized) < 2:
        return []

    requested = set(V1_SEARCH_TYPES) if types is None else types
    active_types = requested & V1_SEARCH_TYPES
    if not active_types:
        return []

    check_master_by_id = _load_check_master_lookup() if "issue" in active_types else {}

    per_type: dict[str, list[SearchHit]] = {}
    if "issue" in active_types:
        per_type["issue"] = _search_issues(
            company=company,
            q=normalized,
            limit=limit,
            check_master_by_id=check_master_by_id,
        )
    if "run" in active_types:
        per_type["run"] = _search_runs(company=company, q=normalized, limit=limit)
    if "connector" in active_types:
        per_type["connector"] = _search_connectors(
            company=company,
            q=normalized,
            limit=limit,
        )
    if "audit" in active_types:
        per_type["audit"] = _search_audit(company=company, q=normalized, limit=limit)
    if "workflow" in (types or set()):
        per_type["workflow"] = _search_workflows(q=normalized, limit=limit)

    ordered: list[SearchHit] = []
    for result_type in TYPE_ORDER:
        ordered.extend(per_type.get(result_type, []))
    return ordered


def serialize_search_hit(hit: SearchHit) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": hit.type,
        "id": hit.id,
        "title": hit.title,
        "subtitle": hit.subtitle,
        "href": hit.href,
    }
    if hit.meta:
        payload["meta"] = hit.meta
    return payload
