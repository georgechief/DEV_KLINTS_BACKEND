"""Excel sheet 02/06 lifecycle join for DCS scoring snapshot (PRD-DCS-03/04).

Authoritative surfaces (sheet 02/06):
- Shopify: paid non-test orders (``financial_status``, ``test=false``),
  refunds / ``cancelled_at`` (LE-09), ``total_price`` / ``subtotal_price`` (LE-02).
- Manago: External Event PURCHASE / RETURN / CANCELLATION;
  join spine ``event.externalId`` ↔ ``orders.id`` (LE-03/05);
  fallback heuristic date+value when externalId absent (LE-05).

Prefers latest ConnectorSnapshot ``raw`` when present; DB Order rows are fallback.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.identity_join import normalize_email
from dataruns.models import Order
from tenants.models import Company, Connector, ConnectorSnapshot

LE_GAP_SAMPLE = 50
_PAID_FINANCIAL = frozenset({"paid", "partially_paid"})
_REFUND_FINANCIAL = frozenset({"refunded", "partially_refunded"})
_CANCEL_FINANCIAL = frozenset({"voided", "cancelled", "canceled"})
_PURCHASE_TYPES = frozenset({"PURCHASE", "TRANSACTION"})
_RETURN_TYPES = frozenset({"RETURN", "CANCELLATION", "CANCEL", "CANCELLED"})


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    return str(dt)


def _month_key(iso_or_none: str | None, fallback_dt=None) -> str:
    raw = iso_or_none or (_iso(fallback_dt) if fallback_dt else None) or ""
    if len(raw) >= 7 and raw[4] == "-":
        return raw[:7]
    if fallback_dt is not None and hasattr(fallback_dt, "strftime"):
        return fallback_dt.strftime("%Y-%m")
    return "unknown"


def _day_key(iso_or_none: str | None) -> str:
    raw = iso_or_none or ""
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    return ""


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ms_to_iso(ms: Any) -> str | None:
    if not isinstance(ms, (int, float)):
        return None
    try:
        dt = datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return _iso(dt)


def _latest_connector_raw(*, company: Company, platform: str) -> dict[str, Any]:
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
    data = snap.snapshot_data if isinstance(snap.snapshot_data, dict) else {}
    raw = data.get("raw")
    return raw if isinstance(raw, dict) else {}


def _normalize_return_type(event_type: str) -> str:
    upper = event_type.upper()
    if upper in {"CANCEL", "CANCELLED", "CANCELLATION"}:
        return "CANCELLATION"
    if upper == "RETURN":
        return "RETURN"
    return upper


def _shopify_orders_from_raw(raw: dict[str, Any]) -> tuple[list[dict], list[dict], int]:
    """
    Excel LE-01/09: paid non-test orders + refunds/cancels from Shopify raw.

    Returns (paid_orders, refund_cancel_orders, excluded_test_count).
    """
    paid: list[dict[str, Any]] = []
    refund_cancel: list[dict[str, Any]] = []
    excluded_test = 0
    for order in raw.get("orders") or []:
        if not isinstance(order, dict):
            continue
        oid = order.get("id")
        if oid is None:
            continue
        if order.get("test") is True:
            excluded_test += 1
            continue
        customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
        email = normalize_email(
            customer.get("email") or order.get("email") or ""
        )
        person_key = str(customer.get("id") or "").strip()
        amount_gross = _float_or_none(order.get("total_price")) or 0.0
        amount_net = _float_or_none(order.get("subtotal_price"))
        currency = str(order.get("currency") or "")
        ordered_at = str(order.get("created_at") or "") or None
        financial = str(order.get("financial_status") or "").lower()
        cancelled_at = order.get("cancelled_at")
        row = {
            "order.id": str(oid),
            "order_number": str(order.get("order_number") or order.get("name") or ""),
            "person.email": email,
            "person.external_key": person_key,
            "amount_gross": amount_gross,
            "amount_net": amount_net,
            "currency": currency,
            "financial_status": financial,
            "cancelled_at": str(cancelled_at) if cancelled_at else None,
            "ordered_at": ordered_at,
            "source": "shopify",
            "month": _month_key(ordered_at),
            "from_raw": True,
        }
        is_cancelled = bool(cancelled_at) or financial in _CANCEL_FINANCIAL
        is_refunded = financial in _REFUND_FINANCIAL
        is_paid = financial in _PAID_FINANCIAL and not is_cancelled
        if is_paid:
            row["status"] = "paid"
            paid.append(row)
        elif is_refunded or is_cancelled:
            row["status"] = "refunded" if is_refunded else "cancelled"
            refund_cancel.append(row)
    return paid, refund_cancel, excluded_test


def _shopify_orders_from_db(
    company: Company,
) -> tuple[list[dict], list[dict], int]:
    """DB fallback when Shopify raw is missing (test filter cannot apply)."""
    paid: list[dict[str, Any]] = []
    refund_cancel: list[dict[str, Any]] = []
    for order in Order.objects.filter(company=company, source="shopify").select_related(
        "contact"
    ):
        contact = order.contact
        email = normalize_email(contact.email if contact else "")
        row = {
            "order.id": str(order.external_id),
            "order_number": "",
            "person.email": email,
            "person.external_key": contact.external_id if contact else "",
            "amount_gross": float(order.amount),
            "amount_net": None,
            "currency": order.currency,
            "financial_status": order.status,
            "cancelled_at": None,
            "ordered_at": _iso(order.created_at),
            "source": "shopify",
            "month": _month_key(_iso(order.created_at), order.created_at),
            "from_raw": False,
            "status": order.status,
        }
        if order.status == Order.Status.PAID:
            paid.append(row)
        elif order.status in {Order.Status.REFUNDED, Order.Status.FAILED}:
            if order.status == Order.Status.FAILED:
                row["status"] = "cancelled"
            refund_cancel.append(row)
    return paid, refund_cancel, 0


def _manago_purchases_from_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """
    PURCHASE events from Manago raw transactions.

    ``has_external_id`` is True only when the payload carried ``externalId``
    (Excel LE-03) — not merely transactionId.
    Join key prefers externalId, else transactionId (weaker spine).
    """
    rows: list[dict[str, Any]] = []
    for event in raw.get("transactions") or []:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("contactExtEventType") or "").upper()
        if event_type not in _PURCHASE_TYPES:
            continue
        ext_raw = event.get("externalId")
        has_external_id = ext_raw is not None and str(ext_raw).strip() != ""
        txn = event.get("transactionId")
        if has_external_id:
            order_id = str(ext_raw).strip()
            join_key_source = "externalId"
        elif txn is not None and str(txn).strip():
            order_id = str(txn).strip()
            join_key_source = "transactionId"
        else:
            order_id = ""
            join_key_source = "none"
        occurred_at = _ms_to_iso(event.get("date"))
        rows.append(
            {
                "type": "PURCHASE",
                "order.id": order_id,
                "person.email": normalize_email(
                    event.get("email") or event.get("contactEmail")
                ),
                "person.external_key": str(event.get("contactId") or "").strip(),
                "value": _float_or_none(event.get("value")),
                "currency": str(event.get("currency") or ""),
                "occurred_at": occurred_at,
                "source": "manago_ai",
                "has_external_id": has_external_id,
                "join_key_source": join_key_source,
                "month": _month_key(occurred_at),
                "from_raw": True,
            }
        )
    return rows


def _manago_purchases_from_db(company: Company) -> list[dict[str, Any]]:
    """DB fallback — externalId presence unknown (LE-03 → UNKNOWN without raw)."""
    rows: list[dict[str, Any]] = []
    for order in Order.objects.filter(
        company=company, source="manago_ai", status=Order.Status.PAID
    ).select_related("contact"):
        contact = order.contact
        oid = str(order.external_id)
        rows.append(
            {
                "type": "PURCHASE",
                "order.id": oid,
                "person.email": normalize_email(contact.email if contact else ""),
                "person.external_key": str(
                    (contact.link_key if contact else "") or ""
                ).strip(),
                "value": float(order.amount),
                "currency": order.currency,
                "occurred_at": _iso(order.created_at),
                "source": "manago_ai",
                "has_external_id": None,  # unknown without raw
                "join_key_source": "db_external_id",
                "month": _month_key(_iso(order.created_at), order.created_at),
                "from_raw": False,
            }
        )
    return rows


def _manago_return_cancel_from_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for collection in ("events", "transactions"):
        for event in raw.get(collection) or []:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("contactExtEventType") or "").upper()
            if event_type not in _RETURN_TYPES:
                continue
            event_type = _normalize_return_type(event_type)
            ext_raw = event.get("externalId")
            has_external_id = ext_raw is not None and str(ext_raw).strip() != ""
            txn = event.get("transactionId")
            order_id = str(ext_raw or txn or "").strip()
            occurred_at = _ms_to_iso(event.get("date"))
            rows.append(
                {
                    "type": event_type,
                    "order.id": order_id,
                    "person.email": normalize_email(
                        event.get("email") or event.get("contactEmail")
                    ),
                    "person.external_key": str(event.get("contactId") or "").strip(),
                    "value": _float_or_none(event.get("value")),
                    "currency": str(event.get("currency") or ""),
                    "occurred_at": occurred_at,
                    "source": "manago_ai",
                    "has_external_id": has_external_id,
                    "join_key_source": "externalId" if has_external_id else "transactionId",
                    "month": _month_key(occurred_at),
                    "from_raw": True,
                }
            )
    return rows


def _manago_return_cancel_from_db(company: Company) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order in Order.objects.filter(company=company, source="manago_ai").exclude(
        status=Order.Status.PAID
    ).select_related("contact"):
        if order.status == Order.Status.REFUNDED:
            event_type = "RETURN"
        elif order.status == Order.Status.FAILED:
            event_type = "CANCELLATION"
        else:
            continue
        contact = order.contact
        rows.append(
            {
                "type": event_type,
                "order.id": str(order.external_id),
                "person.email": normalize_email(contact.email if contact else ""),
                "person.external_key": str(
                    (contact.link_key if contact else "") or ""
                ).strip(),
                "value": float(order.amount),
                "currency": order.currency,
                "occurred_at": _iso(order.created_at),
                "source": "manago_ai",
                "has_external_id": None,
                "join_key_source": "db_external_id",
                "month": _month_key(_iso(order.created_at), order.created_at),
                "from_raw": False,
            }
        )
    return rows


def _reconcile_order_events(
    *,
    paid_shopify: list[dict[str, Any]],
    purchase_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Excel LE-05: match by externalId first; fallback email+date+value heuristic.
    """
    shopify_by_id = {o["order.id"]: o for o in paid_shopify if o.get("order.id")}
    # Also index order_number → id for Manago events that store order_number.
    order_number_to_id: dict[str, str] = {}
    for o in paid_shopify:
        num = str(o.get("order_number") or "").strip()
        if num:
            order_number_to_id[num] = o["order.id"]

    matched_ids: set[str] = set()
    match_kinds: dict[str, str] = {}
    unmatched_events: list[dict[str, Any]] = []

    for event in purchase_events:
        key = str(event.get("order.id") or "").strip()
        shopify_id = None
        kind = None
        if key and key in shopify_by_id:
            shopify_id = key
            kind = (
                "external_id"
                if event.get("has_external_id") is True
                or event.get("join_key_source") == "externalId"
                else "id"
            )
        elif key and key in order_number_to_id:
            shopify_id = order_number_to_id[key]
            kind = "order_number"
        if shopify_id:
            matched_ids.add(shopify_id)
            match_kinds[shopify_id] = kind or "id"
            event["matched_order.id"] = shopify_id
            event["match_kind"] = kind
        else:
            unmatched_events.append(event)

    shopify_only = [
        o for o in paid_shopify if o["order.id"] not in matched_ids
    ]
    heuristic_matches: list[dict[str, Any]] = []
    still_unmatched: list[dict[str, Any]] = []
    used_event_idx: set[int] = set()

    for order in shopify_only:
        day = _day_key(order.get("ordered_at"))
        email = order.get("person.email") or ""
        amount = float(order.get("amount_gross") or 0)
        found_idx = None
        for idx, event in enumerate(unmatched_events):
            if idx in used_event_idx:
                continue
            if not email or email != (event.get("person.email") or ""):
                continue
            if day and day != _day_key(event.get("occurred_at")):
                continue
            ev = event.get("value")
            if ev is None:
                continue
            if abs(float(ev) - amount) > 0.01:
                continue
            found_idx = idx
            break
        if found_idx is None:
            continue
        used_event_idx.add(found_idx)
        event = unmatched_events[found_idx]
        matched_ids.add(order["order.id"])
        match_kinds[order["order.id"]] = "heuristic_email_date_value"
        event["matched_order.id"] = order["order.id"]
        event["match_kind"] = "heuristic_email_date_value"
        heuristic_matches.append(
            {
                "order.id": order["order.id"],
                "event_order.id": event.get("order.id"),
                "email": email,
                "day": day,
                "amount": amount,
            }
        )

    for idx, event in enumerate(unmatched_events):
        if idx not in used_event_idx:
            still_unmatched.append(event)

    shopify_only_final = [
        o["order.id"] for o in paid_shopify if o["order.id"] not in matched_ids
    ]
    # Unmatched Manago events that still carry an order.id (joinable gaps).
    # Events with no order.id are counted separately as manago_events_without_order_id.
    manago_only_ids = [
        str(e.get("order.id") or "").strip()
        for e in still_unmatched
        if str(e.get("order.id") or "").strip()
    ]

    shopify_only_all = sorted({str(x) for x in shopify_only_final if x})
    manago_only_all = sorted(set(manago_only_ids))

    return {
        "matched_ids": matched_ids,
        "match_kinds": match_kinds,
        "heuristic_matches": heuristic_matches[:LE_GAP_SAMPLE],
        "heuristic_match_count": len(heuristic_matches),
        "shopify_only_all": shopify_only_all,
        "manago_only_all": manago_only_all,
        "in_both": len(matched_ids),
    }


def build_lifecycle_snapshot(*, company: Company) -> dict[str, Any]:
    """Build lifecycle orders/events + summary for LE-* checks."""
    shopify_raw = _latest_connector_raw(company=company, platform="shopify")
    manago_raw = _latest_connector_raw(company=company, platform="manago_ai")

    shopify_raw_orders = shopify_raw.get("orders")
    shopify_from_raw = isinstance(shopify_raw_orders, list) and len(shopify_raw_orders) > 0
    if shopify_from_raw:
        paid_shopify, refund_cancel_shopify, excluded_test = _shopify_orders_from_raw(
            shopify_raw
        )
        test_filter_applied = True
    else:
        paid_shopify, refund_cancel_shopify, excluded_test = _shopify_orders_from_db(
            company
        )
        test_filter_applied = False

    manago_raw_txns = manago_raw.get("transactions")
    manago_from_raw = isinstance(manago_raw_txns, list) and len(manago_raw_txns) > 0
    if manago_from_raw:
        purchase_events = _manago_purchases_from_raw(manago_raw)
        external_id_known = True
    else:
        purchase_events = _manago_purchases_from_db(company)
        external_id_known = False

    return_from_raw = _manago_return_cancel_from_raw(manago_raw)
    return_from_db = _manago_return_cancel_from_db(company)
    # Prefer raw RETURN/CANCELLATION; union DB rows whose order.id not already present.
    seen_return_keys: set[str] = set()
    return_cancel_events: list[dict[str, Any]] = []
    for event in return_from_raw + return_from_db:
        key = f"{event.get('type')}:{event.get('order.id')}"
        if key in seen_return_keys:
            continue
        seen_return_keys.add(key)
        return_cancel_events.append(event)
    return_events_from_raw = bool(return_from_raw)

    reconcile = _reconcile_order_events(
        paid_shopify=paid_shopify,
        purchase_events=purchase_events,
    )
    shopify_only_all = reconcile["shopify_only_all"]
    manago_only_all = reconcile["manago_only_all"]
    shopify_only = shopify_only_all[:LE_GAP_SAMPLE]
    manago_only = manago_only_all[:LE_GAP_SAMPLE]
    gaps_truncated = (
        len(shopify_only_all) > LE_GAP_SAMPLE or len(manago_only_all) > LE_GAP_SAMPLE
    )

    # Duplicate PURCHASE: by externalId when present; else contact+date+value (LE-04).
    by_ext: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_heuristic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in purchase_events:
        if event.get("has_external_id") and event.get("order.id"):
            by_ext[str(event["order.id"])].append(event)
        else:
            hkey = "|".join(
                [
                    str(event.get("person.email") or ""),
                    _day_key(event.get("occurred_at")),
                    f"{float(event.get('value') or 0):.2f}",
                ]
            )
            if hkey != "||0.00":
                by_heuristic[hkey].append(event)
    def _dup_cluster_row(
        *,
        rows: list[dict[str, Any]],
        order_id: str,
        dup_key: str,
        heuristic_key: str | None = None,
    ) -> dict[str, Any]:
        # Representative value = earliest event (PRD-DCS-08 §6.4).
        ordered = sorted(
            rows,
            key=lambda r: str(r.get("occurred_at") or ""),
        )
        rep = float(ordered[0].get("value") or 0) if ordered else 0.0
        count = len(rows)
        impact = max(count - 1, 0) * rep
        row: dict[str, Any] = {
            "order.id": order_id,
            "count": count,
            "values": [r.get("value") for r in ordered[:5]],
            "dup_key": dup_key,
            "representative_value": round(rep, 4),
            "cluster_impact": round(impact, 4),
        }
        if heuristic_key is not None:
            row["heuristic_key"] = heuristic_key
        return row

    dup_clusters = [
        _dup_cluster_row(rows=rows, order_id=oid, dup_key="externalId")
        for oid, rows in sorted(by_ext.items(), key=lambda x: x[0])
        if len(rows) > 1
    ]
    for hkey, rows in sorted(by_heuristic.items(), key=lambda x: x[0]):
        if len(rows) <= 1:
            continue
        dup_clusters.append(
            _dup_cluster_row(
                rows=rows,
                order_id="",
                dup_key="email_date_value",
                heuristic_key=hkey,
            )
        )
    duplicate_purchase_gmv = sum(
        float(c.get("cluster_impact") or 0) for c in dup_clusters
    )

    if external_id_known:
        with_ext = sum(1 for e in purchase_events if e.get("has_external_id") is True)
        without_ext = sum(
            1 for e in purchase_events if e.get("has_external_id") is False
        )
    else:
        with_ext = 0
        without_ext = 0

    # Monthly + LE-02 value decomposition helpers.
    shopify_by_month: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "value_gross": 0.0, "value_net": 0.0}
    )
    manago_by_month: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "value": 0.0}
    )
    for row in paid_shopify:
        m = row["month"]
        shopify_by_month[m]["count"] += 1
        shopify_by_month[m]["value_gross"] += float(row.get("amount_gross") or 0)
        net = row.get("amount_net")
        shopify_by_month[m]["value_net"] += float(
            net if net is not None else row.get("amount_gross") or 0
        )
    for event in purchase_events:
        m = event["month"]
        manago_by_month[m]["count"] += 1
        manago_by_month[m]["value"] += float(event.get("value") or 0)

    months = sorted(set(shopify_by_month) | set(manago_by_month))
    monthly: list[dict[str, Any]] = []
    for month in months:
        s = shopify_by_month[month]
        m = manago_by_month[month]
        denom_c = max(s["count"], m["count"], 1.0)
        denom_v = max(s["value_gross"], m["value"], 1.0)
        monthly.append(
            {
                "month": month,
                "shopify_orders": int(s["count"]),
                "manago_purchases": int(m["count"]),
                "shopify_value_gross": round(s["value_gross"], 4),
                "shopify_value_net": round(s["value_net"], 4),
                "manago_value": round(m["value"], 4),
                "shopify_value": round(s["value_gross"], 4),
                "count_delta": round(abs(s["count"] - m["count"]) / denom_c, 6),
                "value_delta": round(abs(s["value_gross"] - m["value"]) / denom_v, 6),
                "value_delta_vs_net": round(
                    abs(s["value_net"] - m["value"]) / max(s["value_net"], m["value"], 1.0),
                    6,
                ),
            }
        )

    shopify_by_id = {o["order.id"]: o for o in paid_shopify}
    missing_events_value = sum(
        float(shopify_by_id[oid].get("amount_gross") or 0)
        for oid in shopify_only_all
        if oid in shopify_by_id
    )
    manago_only_set = set(manago_only_all)
    extra_events_value = sum(
        float(e.get("value") or 0)
        for e in purchase_events
        if str(e.get("order.id") or "") in manago_only_set
    )
    events_without_order_id = sum(
        1 for e in purchase_events if not str(e.get("order.id") or "").strip()
    )
    # Matched pairs: compare gross vs event value where not heuristic-only.
    matched_gross = 0.0
    matched_event_value = 0.0
    matched_net = 0.0
    for oid, kind in reconcile["match_kinds"].items():
        if kind == "heuristic_email_date_value":
            continue
        order = shopify_by_id.get(oid)
        if not order:
            continue
        matched_gross += float(order.get("amount_gross") or 0)
        net = order.get("amount_net")
        matched_net += float(net if net is not None else order.get("amount_gross") or 0)
    for event in purchase_events:
        if event.get("matched_order.id") and event.get("match_kind") != "heuristic_email_date_value":
            matched_event_value += float(event.get("value") or 0)

    shopify_value_gross = sum(float(o.get("amount_gross") or 0) for o in paid_shopify)
    shopify_value_net = sum(
        float(
            o["amount_net"] if o.get("amount_net") is not None else o.get("amount_gross") or 0
        )
        for o in paid_shopify
    )
    manago_value = sum(float(e.get("value") or 0) for e in purchase_events)

    refund_shopify_ids = {
        o["order.id"] for o in refund_cancel_shopify if o.get("order.id")
    }
    return_manago_ids = {
        str(e.get("order.id") or "")
        for e in return_cancel_events
        if e.get("order.id")
    }
    shopify_only_return_ids = refund_shopify_ids - return_manago_ids
    refund_by_id = {
        o["order.id"]: o for o in refund_cancel_shopify if o.get("order.id")
    }
    shopify_return_value = sum(
        float(o.get("amount_gross") or 0) for o in refund_cancel_shopify
    )
    # Full-set Σ (not sample-truncated) for PRD-DCS-08 LE-09.
    shopify_only_returns_value = sum(
        float(refund_by_id[oid].get("amount_gross") or 0)
        for oid in shopify_only_return_ids
        if oid in refund_by_id
    )
    manago_return_value = sum(
        float(e.get("value") or 0) for e in return_cancel_events if e.get("value") is not None
    )
    # Shop primary currency (Shopify is single-currency per shop for MVP1).
    primary_currency = ""
    for o in paid_shopify + refund_cancel_shopify:
        cur = str(o.get("currency") or "").strip()
        if cur:
            primary_currency = cur
            break

    events = purchase_events + return_cancel_events

    return {
        "orders": paid_shopify,
        "events": events,
        "lifecycle": {
            "shopify_paid_orders": len(paid_shopify),
            "shopify_excluded_test_orders": excluded_test,
            "test_filter_applied": test_filter_applied,
            "manago_purchase_events": len(purchase_events),
            "manago_return_cancel_events": len(return_cancel_events),
            "shopify_refund_cancel_orders": len(refund_cancel_shopify),
            "shopify_order_value": round(shopify_value_gross, 4),
            "shopify_order_value_gross": round(shopify_value_gross, 4),
            "shopify_order_value_net": round(shopify_value_net, 4),
            "manago_purchase_value": round(manago_value, 4),
            "value_composition": {
                "shopify_field": "total_price (gross)" if shopify_from_raw else "Order.amount",
                "shopify_net_field": "subtotal_price" if shopify_from_raw else None,
                "manago_field": "PURCHASE event value",
                "note": "LE-02 Excel: decide gross vs net; MVP1 compares gross + reports net delta",
            },
            "value_decomposition": {
                "missing_events_value": round(missing_events_value, 4),
                "extra_events_value": round(extra_events_value, 4),
                "matched_shopify_gross": round(matched_gross, 4),
                "matched_shopify_net": round(matched_net, 4),
                "matched_manago_value": round(matched_event_value, 4),
                "matched_gross_delta": round(abs(matched_gross - matched_event_value), 4),
                "matched_net_delta": round(abs(matched_net - matched_event_value), 4),
            },
            "in_both": reconcile["in_both"],
            "shopify_only": shopify_only,
            "manago_only": manago_only,
            "shopify_only_count": len(shopify_only_all),
            "manago_only_count": len(manago_only_all),
            "manago_events_without_order_id": events_without_order_id,
            "gaps_truncated": gaps_truncated,
            "heuristic_matches": reconcile["heuristic_matches"],
            "heuristic_match_count": reconcile["heuristic_match_count"],
            "purchase_with_external_id": with_ext,
            "purchase_without_external_id": without_ext,
            "external_id_known": external_id_known,
            "duplicate_purchase_clusters": dup_clusters[:LE_GAP_SAMPLE],
            "duplicate_extra_events": sum(
                max(int(c.get("count") or 0) - 1, 0) for c in dup_clusters
            ),
            "duplicate_purchase_gmv": round(duplicate_purchase_gmv, 4),
            "primary_currency": primary_currency or None,
            "monthly": monthly,
            "return_coverage": {
                "shopify_refund_cancel_ids": sorted(refund_shopify_ids)[:LE_GAP_SAMPLE],
                "manago_return_cancel_ids": sorted(return_manago_ids)[:LE_GAP_SAMPLE],
                "shopify_only_returns": sorted(shopify_only_return_ids)[:LE_GAP_SAMPLE],
                "manago_only_returns": sorted(
                    return_manago_ids - refund_shopify_ids
                )[:LE_GAP_SAMPLE],
                "shopify_only_returns_count": len(shopify_only_return_ids),
                "manago_only_returns_count": len(
                    return_manago_ids - refund_shopify_ids
                ),
                "shopify_return_value": round(shopify_return_value, 4),
                "shopify_only_returns_value": round(shopify_only_returns_value, 4),
                "manago_return_value": round(manago_return_value, 4),
                "return_value_delta": round(
                    abs(shopify_return_value - manago_return_value)
                    / max(shopify_return_value, manago_return_value, 1.0),
                    6,
                ),
            },
            "shopify_refund_cancel_orders_detail": refund_cancel_shopify[:LE_GAP_SAMPLE],
            "raw_enrichment": {
                "shopify_raw_present": bool(shopify_raw),
                "manago_raw_present": bool(manago_raw),
                "shopify_orders_from_raw": shopify_from_raw,
                "manago_purchases_from_raw": manago_from_raw,
                "return_events_from_raw": return_events_from_raw,
                "external_id_from_raw": external_id_known,
                "test_filter_applied": test_filter_applied,
            },
        },
    }
