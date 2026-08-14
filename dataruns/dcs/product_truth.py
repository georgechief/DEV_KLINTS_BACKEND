"""Excel sheet 02/06 PT-04 net vs gross transaction truth per contact.

Per linked identity: Manago lifetime PURCHASE value vs Shopify net revenue
(orders − refunds). Quantifies refund-blindness (depends on LE-09 returns).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from dataruns.dcs.identity_join import normalize_email
from dataruns.dcs.lifecycle_join import (
    _float_or_none,
    _latest_connector_raw,
    _PAID_FINANCIAL,
    _REFUND_FINANCIAL,
    _CANCEL_FINANCIAL,
    _PURCHASE_TYPES,
)
from tenants.models import Company

PT_SAMPLE = 50
# Sheet 02 qualitative; MVP1 uses 2% relative overstatement band (align LE-01).
PT04_DELTA_FAIL = 0.02


def build_product_truth_snapshot(*, company: Company) -> dict[str, Any]:
    shopify_raw = _latest_connector_raw(company=company, platform="shopify")
    manago_raw = _latest_connector_raw(company=company, platform="manago_ai")
    customers = [
        c for c in (shopify_raw.get("customers") or []) if isinstance(c, dict)
    ]
    orders = [o for o in (shopify_raw.get("orders") or []) if isinstance(o, dict)]
    contacts = [
        c for c in (manago_raw.get("contacts") or []) if isinstance(c, dict)
    ]
    transactions = [
        t for t in (manago_raw.get("transactions") or []) if isinstance(t, dict)
    ]
    shopify_from_raw = bool(customers) or bool(orders)
    manago_from_raw = bool(contacts) or bool(transactions)

    # Shopify per-customer gross paid + refunded amounts.
    shopify_paid: dict[str, float] = defaultdict(float)
    shopify_refunded: dict[str, float] = defaultdict(float)
    shopify_email: dict[str, str] = {}
    for cust in customers:
        cid = cust.get("id")
        if cid is None:
            continue
        shopify_email[str(cid)] = normalize_email(cust.get("email"))

    for order in orders:
        if order.get("test") is True:
            continue
        customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
        cid = customer.get("id")
        if cid is None:
            continue
        sid = str(cid)
        amount = _float_or_none(order.get("total_price")) or 0.0
        financial = str(order.get("financial_status") or "").lower()
        cancelled = bool(order.get("cancelled_at")) or financial in _CANCEL_FINANCIAL
        if financial in _PAID_FINANCIAL and not cancelled:
            shopify_paid[sid] += amount
        if financial in _REFUND_FINANCIAL or cancelled:
            shopify_refunded[sid] += amount
        if sid not in shopify_email:
            shopify_email[sid] = normalize_email(
                customer.get("email") or order.get("email")
            )

    # Manago lifetime PURCHASE value per contact, deduped by externalId (LE-04).
    manago_by_id: dict[str, dict[str, Any]] = {}
    for contact in contacts:
        mid = str(contact.get("contactId") or contact.get("id") or "")
        if not mid:
            continue
        manago_by_id[mid] = {
            "manago_contact_id": mid,
            "person.external_key": str(contact.get("externalId") or "").strip(),
            "person.email": normalize_email(contact.get("email")),
        }

    purchase_by_contact: dict[str, dict[str, float]] = defaultdict(
        lambda: {"gross_all": 0.0, "deduped": 0.0}
    )
    seen_ext_per_contact: dict[str, set[str]] = defaultdict(set)
    for event in transactions:
        event_type = str(event.get("contactExtEventType") or "").upper()
        if event_type not in _PURCHASE_TYPES:
            continue
        mid = str(event.get("contactId") or "")
        if not mid:
            continue
        value = _float_or_none(event.get("value")) or 0.0
        purchase_by_contact[mid]["gross_all"] += value
        # Prefer externalId / transactionId (LE-04); else contact+date+value so
        # events with no join key are not double-counted in deduped totals.
        ext = str(event.get("externalId") or event.get("transactionId") or "").strip()
        if ext:
            dedupe_key = f"ext:{ext}"
        else:
            day = str(event.get("date") or event.get("eventDate") or "")[:10]
            dedupe_key = f"heur:{mid}|{day}|{value:.2f}"
        if dedupe_key in seen_ext_per_contact[mid]:
            continue
        seen_ext_per_contact[mid].add(dedupe_key)
        purchase_by_contact[mid]["deduped"] += value

    # Link Manago → Shopify.
    shopify_by_email = {
        email: sid for sid, email in shopify_email.items() if email
    }
    per_contact: list[dict[str, Any]] = []
    for mid, meta in manago_by_id.items():
        shopify_id = None
        link_kind = None
        link = meta["person.external_key"]
        if link and (
            link in shopify_email or link in shopify_paid or link in shopify_refunded
        ):
            shopify_id = link
            link_kind = "external_key"
        if shopify_id is None and meta["person.email"]:
            shopify_id = shopify_by_email.get(meta["person.email"])
            if shopify_id:
                link_kind = "email"
        if not shopify_id:
            continue
        paid = float(shopify_paid.get(shopify_id) or 0)
        refunded = float(shopify_refunded.get(shopify_id) or 0)
        net = paid - refunded
        manago_all = float(purchase_by_contact[mid]["gross_all"])
        manago_deduped = float(purchase_by_contact[mid]["deduped"])
        # Compare Manago lifetime (deduped) to Shopify net — Excel PT-04.
        denom = max(abs(net), abs(manago_deduped), 1.0)
        delta_vs_net = abs(manago_deduped - net) / denom
        # Refund-blindness: Manago vs Shopify gross paid (ignoring refunds).
        denom_g = max(abs(paid), abs(manago_deduped), 1.0)
        delta_vs_gross = abs(manago_deduped - paid) / denom_g
        refund_blind = refunded > 0 and manago_deduped > net + 0.01
        per_contact.append(
            {
                "person.email": meta["person.email"],
                "person.external_key": link,
                "manago_contact_id": mid,
                "shopify_customer_id": shopify_id,
                "link_kind": link_kind,
                "shopify_paid_gross": round(paid, 4),
                "shopify_refunded": round(refunded, 4),
                "shopify_net": round(net, 4),
                "manago_purchase_value_all": round(manago_all, 4),
                "manago_purchase_value_deduped": round(manago_deduped, 4),
                "delta_vs_net": round(delta_vs_net, 6),
                "delta_vs_gross": round(delta_vs_gross, 6),
                "refund_blind": refund_blind,
                "overstatement": round(max(manago_deduped - net, 0.0), 4),
            }
        )

    failing = [r for r in per_contact if r["delta_vs_net"] > PT04_DELTA_FAIL]
    refund_blind_rows = [r for r in per_contact if r["refund_blind"]]
    total_overstatement = sum(r["overstatement"] for r in per_contact)

    return {
        "product_truth_rows": per_contact[:500],
        "product_truth": {
            "linked_contacts": len(per_contact),
            "contacts_over_delta": len(failing),
            "contacts_refund_blind": len(refund_blind_rows),
            "total_overstatement": round(total_overstatement, 4),
            "fail_delta": PT04_DELTA_FAIL,
            "failing_sample": failing[:PT_SAMPLE],
            "refund_blind_sample": refund_blind_rows[:PT_SAMPLE],
            "raw_enrichment": {
                "shopify_from_raw": shopify_from_raw,
                "manago_from_raw": manago_from_raw,
            },
        },
    }
