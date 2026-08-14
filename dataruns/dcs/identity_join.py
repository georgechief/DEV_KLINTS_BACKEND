"""Excel sheet 06 identity join for DCS scoring snapshot (PRD-DCS-03).

Keeps platform-scoped DB rows intact. Builds canonical people for CI-* checks:
preferred spine person.external_key (CI-05), fallback normalised email.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from dataruns.models import Contact, Order
from tenants.models import Company

_PLUS_ALIAS_RE = re.compile(r"^([^@+]+)\+[^@]+@(.+)$")
_WHITESPACE_RE = re.compile(r"\s+")


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


def build_identity_snapshot(*, company: Company) -> dict[str, Any]:
    """
    Build contacts[] / orders[] / identity summary for run_snapshot.

    Does not merge DB rows — only joins for scoring (Excel Phase 2).
    """
    shopify_contacts = list(
        Contact.objects.filter(company=company, source="shopify").values(
            "id", "external_id", "email", "phone", "link_key", "created_at"
        )
    )
    manago_contacts = list(
        Contact.objects.filter(company=company, source="manago_ai").values(
            "id", "external_id", "email", "phone", "link_key", "created_at"
        )
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
        key = external_key or email or f"{source}:{manago_contact_id or shopify_customer_id}"
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
        link = str(m0.get("link_key") or "").strip() or str(s0.get("external_id") or "")
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
    shopify_count = len(shopify_contacts)
    manago_count = len(manago_contacts)
    order_count = len(shopify_orders)

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
            "link_key_reused": reused_links[:50],
            "duplicate_clusters": {
                "email": dup_email_clusters[:50],
                "phone": dup_phone_clusters[:50],
                "externalId": dup_link_clusters[:50],
            },
        },
    }
