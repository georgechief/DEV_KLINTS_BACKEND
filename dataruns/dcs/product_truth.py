"""Excel sheet 02/06 PT-04 net vs gross transaction truth per contact.

Per linked identity: Manago purchase value vs Shopify net revenue
(orders − refunds). Quantifies refund-blindness (depends on LE-09 returns).

WB-12: when Manago ``klints_net_ltv`` ≈ Shopify net, the contact is governed
and does not count toward FAIL / refund_blind (completes Automated writeback loop).

B3 / client M3 — Shopify net definition (Excel SoT + acceptance):
- Successful payments: paid / partially_paid ``total_price`` (and original total on
  refunded / partially_refunded orders that were once paid).
- Refunds: **actual** amounts from ``refunds[]`` / ``total_refunded`` when present;
  full ``refunded`` status without refund rows ⇒ refund equals paid (net 0 for that order).
- Unpaid cancellations / voided-never-paid: **excluded** (contribute 0) — do not subtract.
- History: whatever orders are in the connector snapshot (typically BOOTSTRAP_DAYS import
  window). This is **not** guaranteed Shopify lifetime; evidence labels say import window.
- Currency: single-currency sum per contact when ``currency`` / ``presentment_currency``
  is uniform; mixed currency is flagged and write intents are rejected (no silent stamp).
- Stamp storage: Manago dictionary NUMBER as integer **cents**; VIP thresholds must
  also be expressed in cents (e.g. ``>= 20000`` for $200.00).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from dataruns.dcs.identity_join import normalize_email
from dataruns.dcs.lifecycle_join import (
    PinnedSnapshotIds,
    SourceRunIds,
    _CANCEL_FINANCIAL,
    _connector_raw_for_platform,
    _float_or_none,
    _PAID_FINANCIAL,
    _PURCHASE_TYPES,
    _REFUND_FINANCIAL,
)
from tenants.models import Company

PT_SAMPLE = 50
# Sheet 02 qualitative; MVP1 uses 2% relative overstatement band (align LE-01).
PT04_DELTA_FAIL = 0.02
# Absolute cents parity with writeback already_at_target / refund_blind floor.
PT04_ABS_MATCH = 0.01
KLINTS_NET_LTV_KEY = "klints_net_ltv"


def _iter_contact_detail_pairs(contact: dict[str, Any]) -> list[tuple[str, Any]]:
    """Read Manago detail bags (same shapes as segment_join; no writebacks import)."""
    pairs: list[tuple[str, Any]] = []
    for bag_name in ("properties", "dictionaryProperties", "details", "customFields"):
        bag = contact.get(bag_name)
        if isinstance(bag, dict):
            for k, v in bag.items():
                pairs.append((str(k), v))
        elif isinstance(bag, list):
            for item in bag:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("key") or item.get("property")
                if name is None:
                    continue
                pairs.append((str(name), item.get("value")))
    return pairs


def _contact_detail_value(contact: dict[str, Any], detail_key: str) -> Any:
    want = str(detail_key or "").strip().lower()
    if not want:
        return None
    for key, value in _iter_contact_detail_pairs(contact):
        if str(key).strip().lower() == want:
            return value
    return None


def _dictionary_number_raw(contact: dict[str, Any], detail_key: str) -> Any:
    """Raw NUMBER value from dictionaryProperties only (B3 Phase 3 — cents)."""
    want = str(detail_key or "").strip().lower()
    if not want:
        return None
    bag = contact.get("dictionaryProperties")
    if isinstance(bag, dict):
        for k, v in bag.items():
            if str(k).strip().lower() == want:
                return v
    elif isinstance(bag, list):
        for item in bag:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("key") or item.get("property")
            if str(name or "").strip().lower() != want:
                continue
            return item.get("value")
    return None


def dollars_to_cents(value: Any) -> int | None:
    """Round currency dollars to positive-integer cents (Manago NUMBER)."""
    try:
        dollars = float(value)
    except (TypeError, ValueError):
        return None
    if dollars != dollars:  # NaN
        return None
    return int(round(dollars * 100))


def klints_net_ltv_dollars_from_contact(contact: dict[str, Any]) -> float | None:
    """Read stamp as dollars.

    Prefer dictionaryProperties NUMBER stored as **integer cents** (Phase 3).
    Fall back to legacy ``properties`` float/string dollars.
    """
    cents_raw = _dictionary_number_raw(contact, KLINTS_NET_LTV_KEY)
    if cents_raw is not None and cents_raw != "":
        try:
            return float(int(cents_raw)) / 100.0
        except (TypeError, ValueError):
            parsed = _float_or_none(cents_raw)
            if parsed is not None:
                # Already dollars mistakenly in dict bag — use as-is.
                return parsed
    # Legacy standard detail (dollars).
    for bag_name in ("properties", "details", "customFields"):
        bag = contact.get(bag_name)
        if isinstance(bag, dict):
            for k, v in bag.items():
                if str(k).strip().lower() == KLINTS_NET_LTV_KEY:
                    return _float_or_none(v)
        elif isinstance(bag, list):
            for item in bag:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("key") or item.get("property")
                if str(name or "").strip().lower() != KLINTS_NET_LTV_KEY:
                    continue
                return _float_or_none(item.get("value"))
    return None


def klints_net_ltv_matches_shopify_net(
    *,
    stamped: float | None,
    shopify_net: float,
    rel_fail: float = PT04_DELTA_FAIL,
    abs_match: float = PT04_ABS_MATCH,
) -> bool:
    """WB-12 governed rule: stamp ≈ Shopify net (absolute or relative)."""
    if stamped is None:
        return False
    try:
        stamped_f = float(stamped)
        net = float(shopify_net)
    except (TypeError, ValueError):
        return False
    if stamped_f != stamped_f or net != net:  # NaN guard
        return False
    # Negative stamps (pre-B3 Loom bug) never govern.
    if stamped_f < 0 or net < 0:
        return False
    delta = abs(stamped_f - net)
    if delta <= abs_match:
        return True
    denom = max(abs(net), abs(stamped_f), 1.0)
    return (delta / denom) <= rel_fail


def _money_amount(value: Any) -> float | None:
    """Parse Shopify money fields (scalar, string, or MoneyBag / set dict)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return _float_or_none(value)
    if isinstance(value, dict):
        for key in ("amount", "shop_money", "presentment_money"):
            inner = value.get(key)
            if isinstance(inner, dict):
                amt = _float_or_none(inner.get("amount"))
                if amt is not None:
                    return amt
            amt = _float_or_none(inner)
            if amt is not None:
                return amt
    return None


def _order_currency(order: dict[str, Any]) -> str | None:
    for key in ("currency", "presentment_currency"):
        raw = order.get(key)
        if raw is None:
            continue
        text = str(raw).strip().upper()
        if text:
            return text
    return None


def _actual_refund_amount(order: dict[str, Any]) -> float | None:
    """Sum actual refund amounts when Shopify provides them; else None."""
    refunds = order.get("refunds")
    if isinstance(refunds, list) and refunds:
        total = 0.0
        saw = False
        for ref in refunds:
            if not isinstance(ref, dict):
                continue
            ref_saw = False
            # Prefer transaction amounts (cash that left the shop).
            txns = ref.get("transactions")
            if isinstance(txns, list) and txns:
                for txn in txns:
                    if not isinstance(txn, dict):
                        continue
                    kind = str(txn.get("kind") or "").lower()
                    status = str(txn.get("status") or "").lower()
                    if kind and kind not in ("refund", "change"):
                        continue
                    if status and status not in ("success", "pending", ""):
                        continue
                    amt = _money_amount(txn.get("amount"))
                    if amt is not None:
                        total += abs(amt)
                        saw = True
                        ref_saw = True
            if ref_saw:
                continue
            # Fall through when transactions missing or none usable.
            lines = ref.get("refund_line_items")
            if isinstance(lines, list) and lines:
                line_saw = False
                for line in lines:
                    if not isinstance(line, dict):
                        continue
                    amt = _money_amount(line.get("subtotal"))
                    if amt is None:
                        amt = _money_amount(line.get("total_tax"))
                    if amt is not None:
                        total += abs(amt)
                        saw = True
                        line_saw = True
                if line_saw:
                    continue
            amt = _money_amount(ref.get("amount"))
            if amt is not None:
                total += abs(amt)
                saw = True
        if saw:
            return total

    for key in ("total_refunded", "total_refunded_set"):
        amt = _money_amount(order.get(key))
        if amt is not None:
            return abs(amt)
    return None


def shopify_order_net_contribution(order: dict[str, Any]) -> dict[str, Any]:
    """Per-order paid / refunded / net for PT-04 (B3).

    Returns keys: paid, refunded, net, currency, incomplete_refund_history, skipped_reason.
    """
    empty = {
        "paid": 0.0,
        "refunded": 0.0,
        "net": 0.0,
        "currency": _order_currency(order),
        "incomplete_refund_history": False,
        "skipped_reason": None,
    }
    if order.get("test") is True:
        empty["skipped_reason"] = "test_order"
        return empty

    financial = str(order.get("financial_status") or "").lower()
    cancelled = bool(order.get("cancelled_at")) or financial in _CANCEL_FINANCIAL
    total = _float_or_none(order.get("total_price")) or 0.0
    currency = _order_currency(order)

    # Unpaid cancel / void — never successfully paid → exclude (do not subtract).
    if cancelled and financial in _CANCEL_FINANCIAL and financial not in (
        _PAID_FINANCIAL | _REFUND_FINANCIAL
    ):
        return {
            "paid": 0.0,
            "refunded": 0.0,
            "net": 0.0,
            "currency": currency,
            "incomplete_refund_history": False,
            "skipped_reason": "unpaid_cancellation",
        }

    # Successful payment basis (Excel: orders side of orders − refunds).
    paid = 0.0
    if financial in _PAID_FINANCIAL:
        # partially_paid: prefer captured amount when Shopify exposes outstanding.
        outstanding = _money_amount(order.get("total_outstanding"))
        if financial == "partially_paid" and outstanding is not None and total > 0:
            paid = max(total - outstanding, 0.0)
        else:
            paid = total
    elif financial in _REFUND_FINANCIAL:
        # Was paid then refunded — original order total is the paid basis.
        paid = total

    if paid <= 0 and financial not in _REFUND_FINANCIAL:
        return {
            "paid": 0.0,
            "refunded": 0.0,
            "net": 0.0,
            "currency": currency,
            "incomplete_refund_history": False,
            "skipped_reason": "not_paid",
        }

    refunded = 0.0
    incomplete = False
    actual = _actual_refund_amount(order)
    if actual is not None:
        if paid <= 0:
            # Refund rows without a paid basis — not certifiable (no invent).
            incomplete = True
            refunded = 0.0
        elif actual > paid + 0.01:
            # Refund exceeds paid — do not silently clamp; flag incomplete.
            incomplete = True
            refunded = paid
        else:
            refunded = actual
    elif financial == "refunded":
        # Full refund status, no refund rows → entire paid amount returned.
        refunded = paid
    elif financial == "partially_refunded":
        # Cannot know partial amount without refunds[] / total_refunded.
        incomplete = True
        refunded = 0.0
    elif cancelled and paid > 0:
        # Paid then cancelled: only subtract when refund amounts exist.
        # Without amounts, net is not certifiable — flag incomplete (no invent).
        incomplete = True
        refunded = 0.0

    net = paid - refunded
    if net < 0:
        # Should be unreachable after rules above; fail closed as incomplete.
        incomplete = True
        net = 0.0

    return {
        "paid": round(paid, 4),
        "refunded": round(refunded, 4),
        "net": round(net, 4),
        "currency": currency,
        "incomplete_refund_history": incomplete,
        "skipped_reason": None,
    }


def build_product_truth_snapshot(
    *,
    company: Company,
    source_run_ids: SourceRunIds = None,
    pinned_snapshot_ids: PinnedSnapshotIds = None,
) -> dict[str, Any]:
    ids = source_run_ids or {}
    snaps = pinned_snapshot_ids or {}
    shopify_raw = _connector_raw_for_platform(
        company=company,
        platform="shopify",
        source_run_id=ids.get("shopify"),
        snapshot_id=snaps.get("shopify"),
    )
    manago_raw = _connector_raw_for_platform(
        company=company,
        platform="manago_ai",
        source_run_id=ids.get("manago_ai"),
        snapshot_id=snaps.get("manago_ai"),
    )
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

    # Shopify per-customer paid / refunded / net (B3 — actual refunds, no unpaid cancel).
    shopify_paid: dict[str, float] = defaultdict(float)
    shopify_refunded: dict[str, float] = defaultdict(float)
    shopify_net: dict[str, float] = defaultdict(float)
    shopify_currencies: dict[str, set[str]] = defaultdict(set)
    shopify_incomplete: dict[str, bool] = defaultdict(bool)
    shopify_email: dict[str, str] = {}
    for cust in customers:
        cid = cust.get("id")
        if cid is None:
            continue
        shopify_email[str(cid)] = normalize_email(cust.get("email"))

    for order in orders:
        customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
        cid = customer.get("id")
        if cid is None:
            continue
        sid = str(cid)
        contrib = shopify_order_net_contribution(order)
        shopify_paid[sid] += float(contrib["paid"])
        shopify_refunded[sid] += float(contrib["refunded"])
        shopify_net[sid] += float(contrib["net"])
        if contrib.get("incomplete_refund_history"):
            shopify_incomplete[sid] = True
        cur = contrib.get("currency")
        if cur:
            shopify_currencies[sid].add(str(cur))
        if sid not in shopify_email:
            shopify_email[sid] = normalize_email(
                customer.get("email") or order.get("email")
            )

    # Manago PURCHASE value per contact, deduped by externalId (LE-04).
    # WB-12: also capture klints_net_ltv from contact detail bags.
    manago_by_id: dict[str, dict[str, Any]] = {}
    for contact in contacts:
        mid = str(contact.get("contactId") or contact.get("id") or "")
        if not mid:
            continue
        stamped = klints_net_ltv_dollars_from_contact(contact)
        manago_by_id[mid] = {
            "manago_contact_id": mid,
            "person.external_key": str(contact.get("externalId") or "").strip(),
            "person.email": normalize_email(contact.get("email")),
            "klints_net_ltv": stamped,
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
            link in shopify_email
            or link in shopify_paid
            or link in shopify_refunded
            or link in shopify_net
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
        net = float(shopify_net.get(shopify_id) or 0)
        manago_all = float(purchase_by_contact[mid]["gross_all"])
        manago_deduped = float(purchase_by_contact[mid]["deduped"])
        stamped = meta.get("klints_net_ltv")
        stamped_f = float(stamped) if stamped is not None else None
        governed = klints_net_ltv_matches_shopify_net(
            stamped=stamped_f, shopify_net=net
        )
        currencies = sorted(shopify_currencies.get(shopify_id) or [])
        mixed_currency = len(currencies) > 1
        incomplete_history = bool(shopify_incomplete.get(shopify_id))
        # Compare Manago purchases to Shopify net — Excel PT-04.
        denom = max(abs(net), abs(manago_deduped), 1.0)
        delta_vs_net = abs(manago_deduped - net) / denom
        # Refund-blindness: Manago vs Shopify gross paid (ignoring refunds).
        denom_g = max(abs(paid), abs(manago_deduped), 1.0)
        delta_vs_gross = abs(manago_deduped - paid) / denom_g
        # Incomplete / mixed / negative stamp: never govern — not certifiable.
        if incomplete_history or mixed_currency:
            governed = False
        if stamped_f is not None and stamped_f < 0:
            governed = False
        if governed:
            refund_blind = False
            overstatement = 0.0
        else:
            refund_blind = refunded > 0 and manago_deduped > net + 0.01
            overstatement = max(manago_deduped - net, 0.0)
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
                "overstatement": round(overstatement, 4),
                "klints_net_ltv": (
                    round(stamped_f, 4) if stamped_f is not None else None
                ),
                "governed_by_klints_net_ltv": governed,
                "shopify_currencies": currencies,
                "mixed_currency": mixed_currency,
                "incomplete_refund_history": incomplete_history,
            }
        )

    failing = [
        r
        for r in per_contact
        if (not r["governed_by_klints_net_ltv"])
        and (
            r["delta_vs_net"] > PT04_DELTA_FAIL
            or r["incomplete_refund_history"]
            or r["mixed_currency"]
        )
    ]
    refund_blind_rows = [
        r
        for r in per_contact
        if (not r["governed_by_klints_net_ltv"]) and r["refund_blind"]
    ]
    governed_rows = [r for r in per_contact if r["governed_by_klints_net_ltv"]]
    total_overstatement = sum(r["overstatement"] for r in per_contact)

    return {
        "product_truth_rows": per_contact[:500],
        "product_truth": {
            "linked_contacts": len(per_contact),
            "contacts_over_delta": len(failing),
            "contacts_refund_blind": len(refund_blind_rows),
            "contacts_governed_by_klints_net_ltv": len(governed_rows),
            "total_overstatement": round(total_overstatement, 4),
            "fail_delta": PT04_DELTA_FAIL,
            "failing_sample": failing[:PT_SAMPLE],
            "refund_blind_sample": refund_blind_rows[:PT_SAMPLE],
            # Honest scope: connector snapshot window (often BOOTSTRAP_DAYS), not lifetime.
            "revenue_scope": "shopify_orders_in_import_snapshot",
            "raw_enrichment": {
                "shopify_from_raw": shopify_from_raw,
                "manago_from_raw": manago_from_raw,
            },
        },
    }
