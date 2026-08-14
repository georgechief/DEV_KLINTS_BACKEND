"""Derive FD-07 VISIT / smclient / tracking signals from Manago recentActivity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any
from urllib.parse import urlparse

from django.utils import timezone

_DEFAULT_LOOKBACK_DAYS = 7
_VISIT_LIST_KEYS = (
    "customers",
    "partners",
    "prospects",
    "anonymous",
    "allVisits",
)


@dataclass
class ManagoTrackingEvidence:
    """Sheet-02 style tracking inputs for ConnectorGateInput / FD-07."""

    visit_events_recent: bool | None = None
    smclient_cookie_seen: bool | None = None
    tracking_active: bool | None = None
    tracking_measurable: bool = False
    storefront_domains: list[str] | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "visit_events_recent": self.visit_events_recent,
            "smclient_cookie_seen": self.smclient_cookie_seen,
            "tracking_active": self.tracking_active,
            "tracking_measurable": self.tracking_measurable,
            "storefront_domains": self.storefront_domains,
        }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _host_from_url_or_host(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if "://" not in raw and "/" not in raw and " " not in raw:
        host = raw.lower().rstrip(".")
        return host or None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().rstrip(".")
    return host or None


def _collect_visits(block: dict[str, Any]) -> list[dict[str, Any]]:
    visits: list[dict[str, Any]] = []
    for key in _VISIT_LIST_KEYS:
        for item in _as_list(block.get(key)):
            if isinstance(item, dict):
                visits.append(item)
    return visits


def _visit_stat_total(block: dict[str, Any]) -> int:
    total = 0
    for row in _as_list(block.get("visitStats")):
        if not isinstance(row, dict):
            continue
        for key in (
            "partnersVisits",
            "prospectsVisits",
            "customersVisits",
            "otherVisits",
        ):
            value = row.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total += int(value)
    return total


def _domains_from_visits(visits: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for visit in visits:
        candidates = [
            visit.get("url"),
            visit.get("visitSourceHost"),
            visit.get("host"),
        ]
        for nested in _as_list(visit.get("contactVisits")):
            if isinstance(nested, dict):
                candidates.extend(
                    [nested.get("url"), nested.get("host"), nested.get("visitSourceHost")]
                )
        for candidate in candidates:
            host = _host_from_url_or_host(candidate)
            if host and host not in seen and host not in {"localhost", "127.0.0.1"}:
                seen.add(host)
                found.append(host)
    return found


def derive_tracking_from_recent_activity(
    response: dict[str, Any] | None,
) -> ManagoTrackingEvidence:
    """
    Map Manago recentActivity JSON → FD-07 boolean signals.

    Proxies (Excel VISIT / smclient without browser cookies):
    - visit_events_recent: any visit rows or visitStats totals > 0
    - smclient_cookie_seen: monitoredContacts > 0, or identified visit (contactId)
    - tracking_active: either of the above
    """
    if not isinstance(response, dict):
        return ManagoTrackingEvidence(
            tracking_measurable=False,
            detail={"error": "empty_response"},
        )

    if response.get("success") is False:
        return ManagoTrackingEvidence(
            tracking_measurable=False,
            detail={
                "error": "manago_success_false",
                "message": response.get("message"),
            },
        )

    block = _as_dict(
        response.get("recentActivities") or response.get("recentActivity")
    )
    if not block and "monitoredContacts" in response:
        block = response

    visits = _collect_visits(block)
    visit_count = len(visits)
    stats_total = _visit_stat_total(block)
    monitored_raw = block.get("monitoredContacts")
    monitored = (
        int(monitored_raw)
        if isinstance(monitored_raw, (int, float)) and not isinstance(monitored_raw, bool)
        else 0
    )
    identified = sum(
        1
        for visit in visits
        if visit.get("contactId") or visit.get("cid") or visit.get("email")
    )

    visit_events_recent = visit_count > 0 or stats_total > 0
    smclient_cookie_seen = monitored > 0 or identified > 0
    tracking_active = visit_events_recent or smclient_cookie_seen
    domains = _domains_from_visits(visits)

    return ManagoTrackingEvidence(
        visit_events_recent=visit_events_recent,
        smclient_cookie_seen=smclient_cookie_seen,
        tracking_active=tracking_active,
        tracking_measurable=True,
        storefront_domains=domains or None,
        detail={
            "visit_count": visit_count,
            "visit_stats_total": stats_total,
            "monitored_contacts": monitored,
            "identified_visits": identified,
            "total_contacts": block.get("totalContacts"),
            "from": block.get("from"),
            "to": block.get("to"),
        },
    )


def load_manago_tracking_evidence(
    *,
    config: dict[str, Any],
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    timeout: float = 20.0,
    now: datetime | None = None,
    fetch_recent_activity: Any | None = None,
) -> ManagoTrackingEvidence:
    """
    Call Manago recentActivity and derive FD-07 signals.

    On API / credential failure → measurable=False and signals None (FD-07 UNKNOWN).
    """
    from tenants.manago_fetch import ManagoFetchError, fetch_recent_activity as _fetch

    fetch = fetch_recent_activity or _fetch
    end = now or timezone.now()
    if timezone.is_naive(end):
        end = timezone.make_aware(end, timezone=dt_timezone.utc)
    days = max(1, int(lookback_days))
    start = end - timedelta(days=days)

    try:
        response = fetch(
            config=config,
            window_start=start,
            window_end=end,
            timeout=timeout,
            all_visits=True,
        )
    except ManagoFetchError as exc:
        return ManagoTrackingEvidence(
            tracking_measurable=False,
            detail={"error": str(exc)},
        )
    except Exception as exc:  # noqa: BLE001 — gate must not crash DCS run
        return ManagoTrackingEvidence(
            tracking_measurable=False,
            detail={"error": f"unexpected:{exc}"},
        )

    return derive_tracking_from_recent_activity(response)
