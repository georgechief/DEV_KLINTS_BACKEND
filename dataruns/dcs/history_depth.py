"""FD-05 historical data depth — earliest timestamps per entity / platform."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from django.db.models import Min
from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_datetime

from dataruns.models import Contact, Order
from tenants.models import Company


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    if dj_timezone.is_naive(value):
        value = dj_timezone.make_aware(value, timezone=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _parse_iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if dj_timezone.is_naive(value):
            return dj_timezone.make_aware(value, timezone=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if dj_timezone.is_naive(parsed):
        return dj_timezone.make_aware(parsed, timezone=timezone.utc)
    return parsed.astimezone(timezone.utc)


def compute_history_depth(
    *,
    company: Company,
    platform: str,
    required_days: int = 30,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """
    Excel FD-05: earliest timestamp per entity (contacts, orders) for a platform.

    ``Order.created_at`` is overwritten with platform timestamps on import.
    ``Contact.created_at`` is similarly updated when the mapper supplies it.
    """
    as_of = as_of or _utcnow()
    if dj_timezone.is_naive(as_of):
        as_of = dj_timezone.make_aware(as_of, timezone=timezone.utc)

    earliest: dict[str, str] = {}
    contact_min = (
        Contact.objects.filter(company=company, source=platform)
        .aggregate(m=Min("created_at"))
        .get("m")
    )
    order_min = (
        Order.objects.filter(company=company, source=platform)
        .aggregate(m=Min("created_at"))
        .get("m")
    )
    if contact_min is not None:
        earliest["contacts"] = _to_iso(contact_min)
    if order_min is not None:
        earliest["orders"] = _to_iso(order_min)

    oldest: datetime | None = None
    for iso in earliest.values():
        parsed = _parse_iso(iso)
        if parsed is None:
            continue
        if oldest is None or parsed < oldest:
            oldest = parsed

    depth_days: int | None = None
    if oldest is not None:
        depth_days = max(int((as_of - oldest).total_seconds() // 86400), 0)

    return {
        "platform": platform,
        "earliest": earliest,
        "earliest_any": _to_iso(oldest) if oldest is not None else None,
        "depth_days": depth_days,
        "required_days": required_days,
        "meets_required": depth_days is not None and depth_days >= required_days,
        "as_of": _to_iso(as_of),
    }


def shortest_common_window_days(depths: list[dict[str, Any]]) -> int | None:
    """Cap reconciliations to the shortest platform depth (Excel suggested fix)."""
    values = [
        d.get("depth_days")
        for d in depths
        if isinstance(d.get("depth_days"), int)
    ]
    if not values:
        return None
    return min(values)


def history_earliest_payload(depth: dict[str, Any]) -> dict[str, str]:
    """Shape expected by ``ConnectorGateInput.history_earliest``."""
    earliest = depth.get("earliest")
    if isinstance(earliest, dict):
        return {
            str(k): str(v)
            for k, v in earliest.items()
            if isinstance(v, str) and v.strip()
        }
    return {}
