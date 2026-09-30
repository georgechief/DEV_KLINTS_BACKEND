"""Excel sheet 06 identity join for DCS scoring snapshot (PRD-DCS-03).

Preferred spine: person.external_key (CI-05), fallback normalised email.

Contact universe for CI-01/03/05 prefers the **fresh ConnectorSnapshot** from the
DCS import (same pin path as lifecycle/consent) so post-writeback re-scores
reflect live Manago/Shopify — not accumulated Contact DB ghosts.

DB Contact rows remain the fallback when no snapshot exists (tests / cold).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from django.db.models import Count, Q

from dataruns.connectors.bootstrap_health import load_snapshot_data
from dataruns.models import Contact, DataRun, Order, RunConnector
from tenants.models import Company, Connector, ConnectorSnapshot

_PLUS_ALIAS_RE = re.compile(r"^([^@+]+)\+[^@]+@(.+)$")
_WHITESPACE_RE = re.compile(r"\s+")

SourceRunIds = dict[str, int | None] | None
PinnedSnapshotIds = dict[str, str | None] | None

CI_MISMATCH_SAMPLE = 50


def normalize_email(value: str | None) -> str:
    """Sheet 06: normalised lowercase; strip plus-aliases for near-dup detection."""
    if not value or not str(value).strip():
        return ""
    email = _WHITESPACE_RE.sub("", str(value).strip().lower())
    match = _PLUS_ALIAS_RE.match(email)
    if match:
        return f"{match.group(1)}@{match.group(2)}"
    return email


def _is_guest_contact(external_id: str) -> bool:
    return str(external_id or "").startswith("email:")


def _raw_from_snapshot_data(snapshot_data: dict[str, Any]) -> dict[str, Any]:
    raw = snapshot_data.get("raw")
    return raw if isinstance(raw, dict) else {}


def _snapshot_data_for_snapshot_id(
    *,
    snapshot_id: str | None,
    company: Company,
    platform: str,
) -> dict[str, Any] | None:
    if snapshot_id is None or not str(snapshot_id).strip():
        return None
    try:
        snapshot = ConnectorSnapshot.objects.select_related("connector").get(
            pk=snapshot_id
        )
    except ConnectorSnapshot.DoesNotExist:
        return None
    connector = snapshot.connector
    if str(connector.company_id) != str(company.id):
        return None
    if connector.name != platform:
        return None
    snap_data = snapshot.snapshot_data
    return snap_data if isinstance(snap_data, dict) else {}


def _snapshot_data_for_import_data_run(
    data_run_id: int | None,
    *,
    company: Company,
    platform: str,
) -> dict[str, Any] | None:
    if data_run_id is None:
        return None
    try:
        data_run = DataRun.objects.get(pk=data_run_id)
    except DataRun.DoesNotExist:
        return None
    metadata = data_run.metadata or {}
    if str(metadata.get("company_id") or "") != str(company.id):
        return None
    if metadata.get("platform") != platform:
        return None
    snapshot_id = metadata.get("snapshot_id")
    if snapshot_id:
        pinned = _snapshot_data_for_snapshot_id(
            snapshot_id=str(snapshot_id),
            company=company,
            platform=platform,
        )
        if pinned is not None:
            return pinned
        loaded = load_snapshot_data(str(snapshot_id))
        if loaded:
            return loaded
    run_id = metadata.get("run_id")
    if run_id:
        link = (
            RunConnector.objects.filter(run_id=run_id)
            .select_related("connector_snapshot")
            .order_by("-connector_snapshot__version")
            .first()
        )
        if link and link.connector_snapshot is not None:
            snap_data = link.connector_snapshot.snapshot_data
            if isinstance(snap_data, dict):
                return snap_data
    return None


def _latest_snapshot_data(*, company: Company, platform: str) -> dict[str, Any]:
    try:
        connector = Connector.objects.get(company=company, name=platform)
    except Connector.DoesNotExist:
        return {}
    snap = (
        ConnectorSnapshot.objects.filter(connector=connector)
        .order_by("-version")
        .first()
    )
    if snap is None:
        return {}
    data = snap.snapshot_data
    return data if isinstance(data, dict) else {}


def _snapshot_data_for_platform(
    *,
    company: Company,
    platform: str,
    source_run_id: int | None = None,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    if snapshot_id:
        pinned = _snapshot_data_for_snapshot_id(
            snapshot_id=str(snapshot_id),
            company=company,
            platform=platform,
        )
        if pinned is not None:
            return pinned
    if source_run_id is not None:
        pinned = _snapshot_data_for_import_data_run(
            source_run_id,
            company=company,
            platform=platform,
        )
        if pinned is not None:
            return pinned
    return _latest_snapshot_data(company=company, platform=platform)


def _row_from_normalized_contact(record: dict[str, Any]) -> dict[str, Any] | None:
    external_id = str(record.get("external_id") or "").strip()
    if not external_id:
        return None
    return {
        "id": external_id,
        "external_id": external_id,
        "email": str(record.get("email") or ""),
        "phone": str(record.get("phone") or ""),
        "link_key": str(record.get("link_key") or "").strip(),
        "created_at": record.get("created_at"),
    }


def _contacts_from_manago_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in raw.get("contacts") or []:
        if not isinstance(item, dict):
            continue
        external_id = str(
            item.get("contactId") or item.get("id") or item.get("external_id") or ""
        ).strip()
        if not external_id:
            continue
        rows.append(
            {
                "id": external_id,
                "external_id": external_id,
                "email": str(item.get("email") or ""),
                "phone": str(item.get("phone") or ""),
                "link_key": str(item.get("externalId") or item.get("link_key") or "").strip(),
                "created_at": item.get("createdOn") or item.get("created_at"),
            }
        )
    return rows


def _contacts_from_shopify_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in raw.get("customers") or []:
        if not isinstance(item, dict):
            continue
        external_id = str(item.get("id") or item.get("external_id") or "").strip()
        if not external_id:
            continue
        rows.append(
            {
                "id": external_id,
                "external_id": external_id,
                "email": str(item.get("email") or ""),
                "phone": str(item.get("phone") or ""),
                "link_key": "",
                "created_at": item.get("created_at"),
            }
        )
    return rows


def _contacts_from_snapshot_data(
    *,
    snapshot_data: dict[str, Any],
    platform: str,
) -> list[dict[str, Any]]:
    """Prefer snapshot normalized.contacts; else map from raw."""
    normalized = snapshot_data.get("normalized")
    if isinstance(normalized, dict):
        contacts = normalized.get("contacts")
        if isinstance(contacts, list) and contacts:
            rows: list[dict[str, Any]] = []
            for record in contacts:
                if not isinstance(record, dict):
                    continue
                row = _row_from_normalized_contact(record)
                if row is not None:
                    rows.append(row)
            if rows:
                return rows
    raw = _raw_from_snapshot_data(snapshot_data)
    if platform == "manago_ai":
        return _contacts_from_manago_raw(raw)
    if platform == "shopify":
        return _contacts_from_shopify_raw(raw)
    return []


def _contacts_from_db(*, company: Company, platform: str) -> list[dict[str, Any]]:
    return list(
        Contact.objects.filter(company=company, source=platform, excluded=False).values(
            "id", "external_id", "email", "phone", "link_key", "created_at"
        )
    )


def _load_platform_contacts(
    *,
    company: Company,
    platform: str,
    source_run_id: int | None,
    snapshot_id: str | None,
) -> tuple[list[dict[str, Any]], str]:
    """Return (contacts, source) where source is fresh_snapshot|db."""
    snap = _snapshot_data_for_platform(
        company=company,
        platform=platform,
        source_run_id=source_run_id,
        snapshot_id=snapshot_id,
    )
    if snap:
        rows = _contacts_from_snapshot_data(snapshot_data=snap, platform=platform)
        # Empty fresh snapshot is authoritative for this pin (platform wiped).
        if rows or snap.get("raw") is not None or snap.get("normalized") is not None:
            return rows, "fresh_snapshot"
    return _contacts_from_db(company=company, platform=platform), "db"


def build_identity_snapshot(
    *,
    company: Company,
    source_run_ids: SourceRunIds = None,
    pinned_snapshot_ids: PinnedSnapshotIds = None,
) -> dict[str, Any]:
    """
    Build contacts[] / orders[] / identity summary for run_snapshot.

    When DCS passes fresh-import pins (or latest snapshots exist), CI-* contact
    universes come from that fetch — not stale Contact DB accumulation.
    """
    ids = source_run_ids or {}
    snaps = pinned_snapshot_ids or {}

    shopify_contacts, shopify_source = _load_platform_contacts(
        company=company,
        platform="shopify",
        source_run_id=ids.get("shopify"),
        snapshot_id=snaps.get("shopify"),
    )
    manago_contacts, manago_source = _load_platform_contacts(
        company=company,
        platform="manago_ai",
        source_run_id=ids.get("manago_ai"),
        snapshot_id=snaps.get("manago_ai"),
    )
    shopify_orders = list(
        Order.objects.filter(company=company, source="shopify").select_related(
            "contact"
        )
    )

    shopify_by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    shopify_by_id: dict[str, dict[str, Any]] = {}
    for row in shopify_contacts:
        email = normalize_email(row.get("email"))
        ext = str(row.get("external_id") or "")
        shopify_by_id[ext] = row
        if email:
            shopify_by_email[email].append(row)

    manago_by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    manago_by_link: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in manago_contacts:
        email = normalize_email(row.get("email"))
        link = str(row.get("link_key") or "").strip()
        if email:
            manago_by_email[email].append(row)
        if link:
            manago_by_link[link].append(row)

    # Preferred spine: Manago link_key (= Shopify customers.id) when present.
    linked_shopify_ids: set[str] = set()
    linked_manago_ids: set[str] = set()
    dangling_links: list[str] = []
    reused_links: list[str] = []

    for link, rows in manago_by_link.items():
        if len(rows) > 1:
            reused_links.append(link)
        if link in shopify_by_id:
            linked_shopify_ids.add(link)
            for row in rows:
                linked_manago_ids.add(str(row["external_id"]))
        else:
            dangling_links.append(link)

    # Email fallback join for universe overlap (CI-01).
    emails_shopify = set(shopify_by_email)
    emails_manago = set(manago_by_email)
    emails_both = emails_shopify & emails_manago
    emails_manago_only = emails_manago - emails_shopify
    emails_shopify_only = emails_shopify - emails_manago

    canonical_contacts: list[dict[str, Any]] = []
    seen_person_keys: set[str] = set()

    def _append_person(
        *,
        email: str,
        source: str,
        shopify_customer_id: str = "",
        manago_contact_id: str = "",
        phone: str = "",
        external_key: str = "",
        is_guest: bool = False,
    ) -> None:
        key = (
            external_key
            or email
            or f"{source}:{manago_contact_id or shopify_customer_id}"
        )
        if not key or key in seen_person_keys:
            return
        seen_person_keys.add(key)
        canonical_contacts.append(
            {
                "person.email": email,
                "person.external_key": external_key,
                "person.phone": phone,
                "source": source,
                "shopify_customer_id": shopify_customer_id,
                "manago_contact_id": manago_contact_id,
                "is_guest_order_identity": is_guest,
            }
        )

    for email in sorted(emails_both):
        s_rows = shopify_by_email[email]
        m_rows = manago_by_email[email]
        s0 = s_rows[0]
        m0 = m_rows[0]
        link = str(m0.get("link_key") or "").strip() or str(
            s0.get("external_id") or ""
        )
        _append_person(
            email=email,
            source="both",
            shopify_customer_id=str(s0.get("external_id") or ""),
            manago_contact_id=str(m0.get("external_id") or ""),
            phone=str(m0.get("phone") or s0.get("phone") or ""),
            external_key=link,
            is_guest=_is_guest_contact(str(s0.get("external_id") or "")),
        )

    for email in sorted(emails_manago_only):
        m0 = manago_by_email[email][0]
        _append_person(
            email=email,
            source="manago_ai",
            manago_contact_id=str(m0.get("external_id") or ""),
            phone=str(m0.get("phone") or ""),
            external_key=str(m0.get("link_key") or "").strip(),
        )

    for email in sorted(emails_shopify_only):
        s0 = shopify_by_email[email][0]
        _append_person(
            email=email,
            source="shopify",
            shopify_customer_id=str(s0.get("external_id") or ""),
            phone=str(s0.get("phone") or ""),
            external_key=str(s0.get("external_id") or ""),
            is_guest=_is_guest_contact(str(s0.get("external_id") or "")),
        )

    # Contacts without email still count for platform totals.
    for row in shopify_contacts:
        if normalize_email(row.get("email")):
            continue
        ext = str(row.get("external_id") or "")
        _append_person(
            email="",
            source="shopify",
            shopify_customer_id=ext,
            external_key=ext,
            is_guest=_is_guest_contact(ext),
        )
    for row in manago_contacts:
        if normalize_email(row.get("email")):
            continue
        ext = str(row.get("external_id") or "")
        _append_person(
            email="",
            source="manago_ai",
            manago_contact_id=ext,
            external_key=str(row.get("link_key") or "").strip(),
        )

    order_rows: list[dict[str, Any]] = []
    guest_orders = 0
    guest_with_email = 0
    for order in shopify_orders:
        contact = order.contact
        is_guest = _is_guest_contact(contact.external_id if contact else "")
        email = normalize_email(contact.email if contact else "")
        if is_guest:
            guest_orders += 1
            if email:
                guest_with_email += 1
        order_rows.append(
            {
                "order.id": order.external_id,
                "person.email": email,
                "person.external_key": contact.external_id if contact else "",
                "amount_gross": float(order.amount),
                "currency": order.currency,
                "status": order.status,
                "ordered_at": order.created_at.isoformat().replace("+00:00", "Z")
                if order.created_at
                else None,
                "source": "shopify",
                "is_guest_order_identity": is_guest,
            }
        )

    # CI-03 duplicate clusters on Manago (email / phone / link_key).
    dup_email_clusters = [
        {"key": "email", "value": email, "count": len(rows)}
        for email, rows in manago_by_email.items()
        if email and len(rows) > 1
    ]
    phone_groups: dict[str, list[str]] = defaultdict(list)
    for row in manago_contacts:
        phone = str(row.get("phone") or "").strip()
        if phone:
            phone_groups[phone].append(str(row["external_id"]))
    dup_phone_clusters = [
        {"key": "phone", "value": phone, "count": len(ids)}
        for phone, ids in phone_groups.items()
        if len(ids) > 1
    ]
    dup_link_clusters = [
        {"key": "externalId", "value": link, "count": len(rows)}
        for link, rows in manago_by_link.items()
        if link and len(rows) > 1
    ]

    manago_with_link = sum(
        1 for row in manago_contacts if str(row.get("link_key") or "").strip()
    )
    missing_link_key = _missing_link_key_rows(
        manago_by_email=manago_by_email,
        shopify_by_email=shopify_by_email,
        manago_by_link=manago_by_link,
    )
    dangling_rows = _dangling_link_key_rows(
        manago_by_link=manago_by_link,
        shopify_by_id=shopify_by_id,
    )
    shopify_count = len(shopify_contacts)
    manago_count = len(manago_contacts)
    order_count = len(shopify_orders)

    # Uncapped totals for CI-03 scoring honesty (sample lists stay capped).
    dup_email_all = dup_email_clusters
    dup_phone_all = dup_phone_clusters
    dup_link_all = dup_link_clusters

    return {
        "contacts": canonical_contacts,
        "orders": order_rows,
        "identity": {
            "shopify_customers": shopify_count,
            "manago_contacts": manago_count,
            "in_both": len(emails_both),
            "manago_only": len(emails_manago_only),
            "shopify_only": len(emails_shopify_only),
            "emails_shopify": len(emails_shopify),
            "emails_manago": len(emails_manago),
            "guest_orders": guest_orders,
            "guest_orders_with_email": guest_with_email,
            "shopify_orders": order_count,
            "manago_with_link_key": manago_with_link,
            "link_key_matched": len(linked_shopify_ids),
            "link_key_dangling": dangling_links[:50],
            "link_key_dangling_count": len(dangling_links),
            "link_key_dangling_rows": dangling_rows,
            "link_key_reused": reused_links[:50],
            "link_key_reused_count": len(reused_links),
            "missing_link_key": missing_link_key,
            "missing_link_key_count": len(missing_link_key),
            "duplicate_clusters": {
                "email": dup_email_all[:50],
                "phone": dup_phone_all[:50],
                "externalId": dup_link_all[:50],
            },
            "duplicate_cluster_counts": {
                "email": len(dup_email_all),
                "phone": len(dup_phone_all),
                "externalId": len(dup_link_all),
            },
            "duplicate_extra_contacts_total": sum(
                max(int(c.get("count") or 0) - 1, 0)
                for group in (dup_email_all, dup_phone_all, dup_link_all)
                for c in group
            ),
            "merge_candidates": _merge_candidate_rows(
                company=company,
                manago_by_email=manago_by_email,
                manago_by_link=manago_by_link,
                phone_groups=phone_groups,
                manago_contacts=manago_contacts,
                shopify_by_email=shopify_by_email,
            ),
            "contacts_source": {
                "shopify": shopify_source,
                "manago_ai": manago_source,
            },
        },
    }


def _parse_created_at(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _created_at_iso(value: Any) -> str:
    parsed = _parse_created_at(value)
    if parsed is None:
        return ""
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _manago_order_stats_by_uuid(
    *, company: Company, uuids: set[str]
) -> dict[str, dict[str, Any]]:
    """Per-UUID Order counts (PRD-WB-16 §3.4.1 primary source).

    ``in_db`` is True when a Manago Contact row exists for the UUID — without it,
    Order counts cannot be joined and event visibility is incomplete.
    """
    stats: dict[str, dict[str, Any]] = {
        uid: {
            "event_count": 0,
            "purchase_count": 0,
            "in_db": False,
            "created_at": None,
        }
        for uid in uuids
        if uid
    }
    if not stats:
        return stats

    for contact in Contact.objects.filter(
        company=company,
        source="manago_ai",
        external_id__in=list(stats.keys()),
        excluded=False,
    ).only("external_id", "created_at"):
        uid = str(contact.external_id or "").strip()
        if uid not in stats:
            continue
        stats[uid]["in_db"] = True
        stats[uid]["created_at"] = contact.created_at

    order_rows = (
        Order.objects.filter(
            company=company,
            source="manago_ai",
            contact__external_id__in=list(stats.keys()),
        )
        .values("contact__external_id")
        .annotate(
            event_count=Count("id"),
            purchase_count=Count("id", filter=Q(status="paid")),
        )
    )
    for row in order_rows:
        uid = str(row.get("contact__external_id") or "").strip()
        if uid not in stats:
            continue
        stats[uid]["event_count"] = int(row.get("event_count") or 0)
        stats[uid]["purchase_count"] = int(row.get("purchase_count") or 0)
    return stats


def _pick_survivor(
    members: list[dict[str, Any]],
    *,
    stats: dict[str, dict[str, Any]],
    cluster_kind: str,
    shopify_by_email: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Event-spine first — never hard-code keep-oldest (PRD-WB-16 §3.4)."""

    def _key(row: dict[str, Any]) -> tuple:
        uid = str(row.get("external_id") or "").strip()
        st = stats.get(uid) or {}
        purchase = int(st.get("purchase_count") or 0)
        events = int(st.get("event_count") or 0)
        email = normalize_email(row.get("email"))
        link = str(row.get("link_key") or "").strip()
        shopify_match = 0
        if email and link:
            for shop in shopify_by_email.get(email) or []:
                if str(shop.get("external_id") or "").strip() == link:
                    shopify_match = 1
                    break
        created = _parse_created_at(st.get("created_at") or row.get("created_at"))
        created_ts = created.timestamp() if created is not None else float("-inf")
        return (purchase, events, shopify_match, created_ts, uid)

    return max(members, key=_key)


def _classify_merge_cluster(
    *,
    cluster_kind: str,
    cluster_key: str,
    members: list[dict[str, Any]],
    survivor: dict[str, Any],
    losers: list[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
    events_incomplete: bool,
) -> tuple[str, str]:
    size = len(members)
    if cluster_kind == "phone":
        return "QUARANTINE", "phone_only_cluster"
    if size >= 3:
        return "QUARANTINE", "cluster_size_ge_3"
    if size != 2 or len(losers) != 1:
        return "QUARANTINE", "cluster_size_not_2"
    if events_incomplete:
        return "UNSAFE", "incomplete_event_visibility"

    loser = losers[0]
    loser_id = str(loser.get("external_id") or "").strip()
    survivor_id = str(survivor.get("external_id") or "").strip()
    loser_st = stats.get(loser_id) or {}
    survivor_st = stats.get(survivor_id) or {}
    loser_events = int(loser_st.get("event_count") or 0)
    loser_purchases = int(loser_st.get("purchase_count") or 0)

    if cluster_kind == "email":
        emails = {normalize_email(m.get("email")) for m in members}
        emails.discard("")
        if len(emails) != 1:
            return "QUARANTINE", "conflicting_emails"

    survivor_link = str(survivor.get("link_key") or "").strip()
    loser_link = str(loser.get("link_key") or "").strip()
    if survivor_link and loser_link and survivor_link != loser_link:
        return "QUARANTINE", "conflicting_link_keys"

    if loser_events > 0 or loser_purchases > 0:
        return (
            "MIGRATE_THEN_DELETE",
            "loser_has_events_or_purchases",
        )

    survivor_events = int(survivor_st.get("event_count") or 0)
    survivor_purchases = int(survivor_st.get("purchase_count") or 0)
    if survivor_link:
        reason = "loser_events_0_survivor_holds_link_key"
    elif survivor_purchases > 0 or survivor_events > 0:
        reason = "loser_events_0_survivor_holds_events"
    else:
        reason = "loser_events_0_survivor_selected"
    return "SAFE_DELETE", reason


def _merge_candidate_from_members(
    *,
    cluster_kind: str,
    cluster_key: str,
    members: list[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
    shopify_by_email: dict[str, list[dict[str, Any]]],
    ci05_reused: bool,
) -> dict[str, Any] | None:
    clean = [m for m in members if str(m.get("external_id") or "").strip()]
    if len(clean) < 2:
        return None

    uuids = [str(m.get("external_id") or "").strip() for m in clean]
    events_incomplete = any(not (stats.get(uid) or {}).get("in_db") for uid in uuids)

    survivor = _pick_survivor(
        clean,
        stats=stats,
        cluster_kind=cluster_kind,
        shopify_by_email=shopify_by_email,
    )
    survivor_id = str(survivor.get("external_id") or "").strip()
    losers = [m for m in clean if str(m.get("external_id") or "").strip() != survivor_id]
    if not losers:
        return None

    safety_class, safety_reason = _classify_merge_cluster(
        cluster_kind=cluster_kind,
        cluster_key=cluster_key,
        members=clean,
        survivor=survivor,
        losers=losers,
        stats=stats,
        events_incomplete=events_incomplete,
    )

    loser_ids = [str(m.get("external_id") or "").strip() for m in losers]
    primary_loser = losers[0]
    survivor_st = stats.get(survivor_id) or {}
    loser_st = stats.get(loser_ids[0]) or {}
    email = normalize_email(survivor.get("email")) or normalize_email(
        primary_loser.get("email")
    )
    if cluster_kind == "externalId":
        link_key = str(cluster_key or "").strip()
    else:
        link_key = str(survivor.get("link_key") or "").strip()

    recommended = {
        "SAFE_DELETE": (
            "In Manago UI delete loser by contact id; then tombstone Klints DB "
            "(excluded) or wait Phase B"
        ),
        "MIGRATE_THEN_DELETE": (
            "Move/re-create events onto survivor first; only then delete loser"
        ),
        "QUARANTINE": "Manual review — do not bulk delete",
        "UNSAFE": "Manual review — incomplete or unsafe; do not bulk delete",
    }.get(safety_class, "Manual review")

    return {
        "side": "merge_candidate",
        "cluster_kind": cluster_kind,
        "cluster_key": cluster_key,
        "cluster_size": len(clean),
        "survivor_manago_id": survivor_id,
        "loser_manago_ids": loser_ids,
        "person.email": email,
        "survivor_created_at": _created_at_iso(
            survivor_st.get("created_at") or survivor.get("created_at")
        ),
        "loser_created_at": _created_at_iso(
            loser_st.get("created_at") or primary_loser.get("created_at")
        ),
        "survivor_event_count": int(survivor_st.get("event_count") or 0),
        "loser_event_count": int(loser_st.get("event_count") or 0),
        "survivor_purchase_count": int(survivor_st.get("purchase_count") or 0),
        "loser_purchase_count": int(loser_st.get("purchase_count") or 0),
        "safety_class": safety_class,
        "safety_reason": safety_reason,
        "link_key": link_key,
        "ci05_reused": bool(ci05_reused),
        "klints_db_action_required": "tombstone_loser",
        "recommended_manago_ui_action": recommended,
        "events_source": "order_proxy",
    }


def _merge_candidate_rows(
    *,
    company: Company,
    manago_by_email: dict[str, list[dict[str, Any]]],
    manago_by_link: dict[str, list[dict[str, Any]]],
    phone_groups: dict[str, list[str]],
    manago_contacts: list[dict[str, Any]],
    shopify_by_email: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """PRD-WB-16: merge plan rows — externalId first, then email, phone quarantine."""
    manago_by_id = {
        str(row.get("external_id") or "").strip(): row
        for row in manago_contacts
        if str(row.get("external_id") or "").strip()
    }

    cluster_specs: list[tuple[str, str, list[dict[str, Any]], bool]] = []
    for link, rows in sorted(manago_by_link.items()):
        if link and len(rows) > 1:
            cluster_specs.append(("externalId", link, list(rows), True))
    for email, rows in sorted(manago_by_email.items()):
        if email and len(rows) > 1:
            cluster_specs.append(("email", email, list(rows), False))
    for phone, ids in sorted(phone_groups.items()):
        if phone and len(ids) > 1:
            members = [manago_by_id[i] for i in ids if i in manago_by_id]
            if len(members) > 1:
                cluster_specs.append(("phone", phone, members, False))

    all_uuids: set[str] = set()
    for _kind, _key, members, _reused in cluster_specs:
        for row in members:
            uid = str(row.get("external_id") or "").strip()
            if uid:
                all_uuids.add(uid)
    stats = _manago_order_stats_by_uuid(company=company, uuids=all_uuids)

    covered_uuids: set[str] = set()
    out: list[dict[str, Any]] = []
    for kind, key, members, ci05_reused in cluster_specs:
        member_ids = {
            str(m.get("external_id") or "").strip()
            for m in members
            if str(m.get("external_id") or "").strip()
        }
        if kind == "email" and member_ids & covered_uuids:
            continue
        if kind == "phone" and member_ids & covered_uuids:
            # Still emit phone-only as quarantine when not covered? PRD: phone →
            # QUARANTINE only; skip if already covered by externalId/email plan.
            continue
        candidate = _merge_candidate_from_members(
            cluster_kind=kind,
            cluster_key=key,
            members=members,
            stats=stats,
            shopify_by_email=shopify_by_email,
            ci05_reused=ci05_reused or kind == "externalId",
        )
        if candidate is None:
            continue
        out.append(candidate)
        covered_uuids.update(member_ids)
        if len(out) >= CI_MISMATCH_SAMPLE:
            break
    return out


def _dangling_link_key_rows(
    *,
    manago_by_link: dict[str, list[dict[str, Any]]],
    shopify_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-contact dangling externalId rows for Fix evidence (manual clear).

    Not writeable by CI-05 Approve (WB-15 missing-only). Cap at CI_MISMATCH_SAMPLE.
    """
    rows: list[dict[str, Any]] = []
    for link in sorted(manago_by_link.keys()):
        if not link or link in shopify_by_id:
            continue
        for manago in manago_by_link.get(link) or []:
            manago_id = str(manago.get("external_id") or "").strip()
            if not manago_id:
                continue
            rows.append(
                {
                    "side": "link_key_dangling",
                    "person.email": normalize_email(manago.get("email")),
                    "manago_contact_id": manago_id,
                    "dangling_external_id": link,
                    "manual_fix": (
                        "Clear Manago contact.externalId - Shopify customer id "
                        "not found in current Shopify"
                    ),
                }
            )
            if len(rows) >= CI_MISMATCH_SAMPLE:
                return rows
    return rows


def _missing_link_key_rows(
    *,
    manago_by_email: dict[str, list[dict[str, Any]]],
    shopify_by_email: dict[str, list[dict[str, Any]]],
    manago_by_link: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """PRD-WB-15 — clean 1:1 email pairs with empty Manago link_key.

    Skip ambiguous email (multi Manago or multi Shopify), and Shopify ids
    already held as any Manago link_key (bijection precheck).
    """
    used_links = {str(k).strip() for k in manago_by_link if str(k).strip()}
    rows: list[dict[str, Any]] = []
    for email in sorted(manago_by_email.keys()):
        if not email:
            continue
        manago_rows = manago_by_email.get(email) or []
        # Prefer real Shopify customers.id — exclude guest email: placeholders.
        shopify_rows = [
            r
            for r in (shopify_by_email.get(email) or [])
            if not _is_guest_contact(str(r.get("external_id") or ""))
        ]
        if len(manago_rows) != 1 or len(shopify_rows) != 1:
            continue
        manago = manago_rows[0]
        if str(manago.get("link_key") or "").strip():
            continue
        shopify_id = str(shopify_rows[0].get("external_id") or "").strip()
        if not shopify_id or shopify_id in used_links:
            continue
        manago_id = str(manago.get("external_id") or "").strip()
        if not manago_id:
            continue
        rows.append(
            {
                "side": "missing_link_key",
                "person.email": email,
                "manago_contact_id": manago_id,
                "shopify_customer_id": shopify_id,
                "prior_external_id": "",
            }
        )
        if len(rows) >= CI_MISMATCH_SAMPLE:
            break
    return rows
