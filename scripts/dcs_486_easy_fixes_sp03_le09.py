#!/usr/bin/env python
"""
DCS 486 easy source-data fixes (synthetic/test only).

Phases 1–6 in one file:
  1. Inspect Manago/Shopify storage + mutation path
  2. Fix SP-03 ORDER_NUMBER via live Manago upsert
  3. Fix LE-09 RETURN/CANCELLATION via live Manago batchAddContactExtEvent
  4. Pre-DCS validation (LE-01/02/05 protected)
  5. PT-04 side-effect estimate
  6. Fresh import + DCS score (optional; --skip-dcs to stop after mutate)

Does NOT modify DCS check code, thresholds, or CI-01/03/05.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.connectors.manago_ai.client import ManagoClientError, _post_manago
from dataruns.dcs.fresh_import import refresh_connected_platforms_for_dcs
from dataruns.dcs.lifecycle_join import (
    _PAID_FINANCIAL,
    _REFUND_FINANCIAL,
    _CANCEL_FINANCIAL,
    _RETURN_TYPES,
    _PURCHASE_TYPES,
)
from dataruns.dcs.segment_join import _BOOL_TOKENS, _classify_value, _iter_detail_pairs
from dataruns.models import DataRun
from dataruns.writebacks.adapters.manago_transport import (
    resolve_manago_write_context,
    upsert_contacts,
)
from tenants.models import Company

COMPANY_ID = "4e72da96-5cf0-4005-a16a-02a9ed91b62a"
EXPORT_DIR = (
    BACKEND
    / "exports"
    / "dcs_fresh_import_raw"
    / "dcs_486_20260916T101306Z"
)
OUT_REPORT = EXPORT_DIR / "DCS_486_easy_fixes_implementation_report.md"
OUT_JSON = EXPORT_DIR / "DCS_486_easy_fixes_implementation.json"
BATCH_SIZE = 25
# Match existing PURCHASE events in Run 486 Manago raw.
DEFAULT_LOCATION = "sm_c1c4c80605e2f31666c999681958b618"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("records", "orders", "contacts", "data"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    raise SystemExit(f"Unexpected JSON shape: {path}")


def _parse_ms(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except ValueError:
            return None
    return None


def _to_numeric_order_number(value: Any) -> int | float:
    """Preserve semantic value; produce a JSON number (not bool-token string)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    text = str(value).strip()
    if text.lower() in _BOOL_TOKENS:
        # "1"/"0"/true/false → numeric 1/0
        if text.lower() in {"1", "true", "yes", "y", "on"}:
            return 1
        if text.lower() in {"0", "false", "no", "n", "off"}:
            return 0
    try:
        num = float(text.replace(",", ""))
        return int(num) if num.is_integer() else num
    except ValueError as exc:
        raise ValueError(f"ORDER_NUMBER not numeric-compatible: {value!r}") from exc


def phase1_inspect(manifest: dict[str, Any]) -> dict[str, Any]:
    manago_sid = manifest["fresh_imports"]["manago_ai"]["snapshot_id"]
    shopify_sid = manifest["fresh_imports"]["shopify"]["snapshot_id"]
    contacts = _load_records(EXPORT_DIR / f"manago_ai_raw_contacts_{manago_sid}.json")
    txs = _load_records(EXPORT_DIR / f"manago_ai_raw_transactions_{manago_sid}.json")
    orders = _load_records(EXPORT_DIR / f"shopify_raw_orders_{shopify_sid}.json")

    order_number_rows: list[dict[str, Any]] = []
    bag_hits: Counter[str] = Counter()
    for contact in contacts:
        cid = str(contact.get("contactId") or contact.get("id") or "")
        for bag_name in ("properties", "dictionaryProperties", "details", "customFields"):
            bag = contact.get(bag_name)
            pairs: list[tuple[str, Any]] = []
            if isinstance(bag, dict):
                pairs = [(str(k), v) for k, v in bag.items()]
            elif isinstance(bag, list):
                for item in bag:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") or item.get("key") or item.get("property")
                    if name is None:
                        continue
                    pairs.append((str(name), item.get("value")))
            for key, value in pairs:
                if key.upper() != "ORDER_NUMBER":
                    continue
                bag_hits[bag_name] += 1
                order_number_rows.append(
                    {
                        "contactId": cid,
                        "email": contact.get("email"),
                        "externalId": str(contact.get("externalId") or ""),
                        "bag": bag_name,
                        "value_before": value,
                        "type_before": type(value).__name__,
                        "fmt_before": _classify_value(value),
                    }
                )

    # Cross-check with segment iterator
    iter_n = sum(
        1
        for c in contacts
        for k, _ in _iter_detail_pairs(c)
        if str(k).upper() == "ORDER_NUMBER"
    )

    refund_cancel: list[dict[str, Any]] = []
    paid_orders: list[dict[str, Any]] = []
    for order in orders:
        if order.get("test") is True:
            continue
        oid = order.get("id")
        if oid is None:
            continue
        financial = str(order.get("financial_status") or "").lower()
        cancelled_at = order.get("cancelled_at")
        is_cancelled = bool(cancelled_at) or financial in _CANCEL_FINANCIAL
        is_refunded = financial in _REFUND_FINANCIAL
        is_paid = financial in _PAID_FINANCIAL and not is_cancelled
        customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
        row = {
            "order_id": str(oid),
            "financial_status": order.get("financial_status"),
            "cancelled_at": cancelled_at,
            "total_price": order.get("total_price"),
            "currency": order.get("currency") or "USD",
            "created_at": order.get("created_at"),
            "email": customer.get("email") or order.get("email"),
            "customer_id": str(customer.get("id") or ""),
        }
        if is_paid:
            paid_orders.append(row)
        elif is_refunded or is_cancelled:
            row["event_type"] = "RETURN" if is_refunded else "CANCELLATION"
            refund_cancel.append(row)

    purchases = [
        e
        for e in txs
        if str(e.get("contactExtEventType") or "").upper() in _PURCHASE_TYPES
    ]
    existing_returns = [
        e
        for e in txs
        if str(e.get("contactExtEventType") or "").upper() in _RETURN_TYPES
    ]
    # also nested on contacts
    nested_returns = 0
    for c in contacts:
        for e in c.get("contactExtEvents") or []:
            if isinstance(e, dict) and str(e.get("contactExtEventType") or "").upper() in _RETURN_TYPES:
                nested_returns += 1

    link_to_contact: dict[str, dict[str, Any]] = {}
    email_to_contact: dict[str, dict[str, Any]] = {}
    for c in contacts:
        link = str(c.get("externalId") or "").strip()
        email = str(c.get("email") or "").strip().lower()
        meta = {
            "contactId": str(c.get("contactId") or c.get("id") or ""),
            "email": c.get("email"),
            "externalId": link,
        }
        if link:
            link_to_contact[link] = meta
        if email:
            email_to_contact[email] = meta

    unmatched = []
    for row in refund_cancel:
        cust = row["customer_id"]
        email = str(row.get("email") or "").strip().lower()
        contact = link_to_contact.get(cust) or email_to_contact.get(email)
        if not contact:
            unmatched.append(row["order_id"])
        else:
            row["manago_contactId"] = contact["contactId"]
            row["manago_email"] = contact["email"]

    return {
        "phase": 1,
        "mutation_mechanism": {
            "SP-03": "live Manago api/contact/upsert via upsert_contacts(properties.ORDER_NUMBER)",
            "LE-09": "live Manago api/contact/batchAddContactExtEvent via batch_add_external_events",
            "survives_fresh_import": True,
            "do_not_edit": [
                "Klints Contact/Order DB",
                "ConnectorSnapshot.raw files",
                "DCS check code",
            ],
            "relevant_files": [
                "dataruns/writebacks/adapters/manago_transport.py",
                "dataruns/connectors/manago_ai/client.py",
                "dataruns/dcs/fresh_import.py",
                "dataruns/dcs/segment_join.py",
                "dataruns/dcs/lifecycle_join.py",
                "tenants/models.py::ConnectorSnapshot",
            ],
            "tables": ["connector_snapshots (read after re-import)", "live Manago API (write)"],
            "import_flow": (
                "dcs-score → fresh_import.run_import → ManagoClient.fetch → "
                "ConnectorSnapshot.snapshot_data.raw → SP-03/LE-09 joins"
            ),
        },
        "contacts_n": len(contacts),
        "orders_n": len(orders),
        "order_number": {
            "count": len(order_number_rows),
            "iterator_count": iter_n,
            "bags": dict(bag_hits),
            "fmt_before": dict(Counter(r["fmt_before"] for r in order_number_rows)),
            "type_before": dict(Counter(r["type_before"] for r in order_number_rows)),
            "value_before": dict(Counter(str(r["value_before"]) for r in order_number_rows)),
            "rows": order_number_rows,
        },
        "shopify_paid": len(paid_orders),
        "manago_purchases": len(purchases),
        "manago_return_events_in_tx_export": len(existing_returns),
        "manago_return_events_nested": nested_returns,
        "shopify_refund_cancel": {
            "count": len(refund_cancel),
            "by_type": dict(Counter(r["event_type"] for r in refund_cancel)),
            "unmatched_to_manago_contact": unmatched,
            "rows": refund_cancel,
        },
        "purchase_event_schema_sample": purchases[:1],
    }


def phase2_fix_sp03(
    ctx,
    inspect: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    rows = inspect["order_number"]["rows"]
    to_fix: list[dict[str, Any]] = []
    for row in rows:
        new_val = _to_numeric_order_number(row["value_before"])
        needs = not (
            isinstance(row["value_before"], (int, float))
            and not isinstance(row["value_before"], bool)
            and _classify_value(row["value_before"]) == "numeric"
            and _classify_value(new_val) == "numeric"
            and float(row["value_before"]) == float(new_val)
            and row["fmt_before"] == "numeric"
        )
        # Always rewrite if currently classified boolean OR not numeric type
        if row["fmt_before"] != "numeric" or not isinstance(row["value_before"], (int, float)) or isinstance(row["value_before"], bool):
            needs = True
        entry = {
            **row,
            "value_after": new_val,
            "fmt_after": _classify_value(new_val),
            "needs_write": needs,
        }
        to_fix.append(entry)

    write_rows = [r for r in to_fix if r["needs_write"]]
    errors: list[dict[str, Any]] = []
    written = 0
    if not dry_run:
        for i, row in enumerate(write_rows, 1):
            contact = {
                "contactId": row["contactId"],
                "email": row.get("email"),
                "properties": {"ORDER_NUMBER": row["value_after"]},
            }
            contact = {k: v for k, v in contact.items() if v is not None and v != ""}
            try:
                upsert_contacts(ctx, [contact])
                written += 1
            except ManagoClientError as exc:
                errors.append({"contactId": row["contactId"], "error": str(exc)})
            if i % 10 == 0:
                time.sleep(0.2)

    fmt_after = Counter(r["fmt_after"] for r in to_fix)
    return {
        "phase": 2,
        "dry_run": dry_run,
        "order_number_total": len(rows),
        "needs_write": len(write_rows),
        "written": written,
        "errors": errors,
        "fmt_after_planned": dict(fmt_after),
        "all_numeric_planned": set(fmt_after) == {"numeric"},
        "rows": to_fix,
    }


def _post_batch_events(ctx, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Manago docs: each item is {contactId|email, contactEvent:{...}}."""
    return _post_manago(
        endpoint=ctx.endpoint,
        path="api/contact/batchAddContactExtEvent",
        client_id=ctx.client_id,
        api_secret=ctx.api_secret,
        payload={"owner": ctx.owner, "events": events},
        timeout=60.0,
    )


def phase3_fix_le09(
    ctx,
    inspect: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    rows = inspect["shopify_refund_cancel"]["rows"]
    # Prefer location from an existing PURCHASE if present
    location = DEFAULT_LOCATION
    sample = (inspect.get("purchase_event_schema_sample") or [{}])[0]
    if sample.get("location"):
        location = str(sample["location"])

    events: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        contact_id = row.get("manago_contactId")
        email = row.get("manago_email") or row.get("email")
        if not contact_id and not email:
            skipped.append({"order_id": row["order_id"], "reason": "no_manago_contact"})
            continue
        date_ms = _parse_ms(row.get("cancelled_at") or row.get("created_at"))
        if date_ms is None:
            skipped.append({"order_id": row["order_id"], "reason": "no_date"})
            continue
        try:
            value_f = float(row.get("total_price")) if row.get("total_price") is not None else 0.0
        except (TypeError, ValueError):
            value_f = 0.0

        contact_event = {
            "date": date_ms,
            "contactExtEventType": row["event_type"],  # RETURN or CANCELLATION
            "value": value_f,
            "externalId": row["order_id"],
            "location": location,
            "detail4": row.get("currency") or "USD",
            "description": f"synthetic LE-09 backfill for Shopify {row['event_type'].lower()} {row['order_id']}",
        }
        # Manago: use ONLY contactId OR email
        wrapper: dict[str, Any] = {"contactEvent": contact_event}
        if contact_id:
            wrapper["contactId"] = contact_id
        else:
            wrapper["email"] = email
        events.append({"source_order": row, "event": wrapper})

    errors: list[dict[str, Any]] = []
    written = 0
    created_amount = 0
    if not dry_run:
        payload_events = [e["event"] for e in events]
        for i in range(0, len(payload_events), BATCH_SIZE):
            chunk = payload_events[i : i + BATCH_SIZE]
            try:
                resp = _post_batch_events(ctx, chunk)
                created = int(resp.get("createdAmount") or 0)
                failed = int(resp.get("failedAmount") or 0)
                if resp.get("success") and failed == 0 and created > 0:
                    created_amount += created
                    written += created
                else:
                    # retry one-by-one for this chunk
                    for ev in chunk:
                        try:
                            r2 = _post_batch_events(ctx, [ev])
                            c2 = int(r2.get("createdAmount") or 0)
                            f2 = int(r2.get("failedAmount") or 0)
                            if r2.get("success") and f2 == 0 and c2 > 0:
                                written += c2
                                created_amount += c2
                            else:
                                errors.append(
                                    {
                                        "externalId": (ev.get("contactEvent") or {}).get(
                                            "externalId"
                                        ),
                                        "error": r2.get("message")
                                        or r2.get("failedContacts")
                                        or r2,
                                    }
                                )
                        except ManagoClientError as exc2:
                            errors.append(
                                {
                                    "externalId": (ev.get("contactEvent") or {}).get(
                                        "externalId"
                                    ),
                                    "error": str(exc2),
                                }
                            )
            except ManagoClientError as exc:
                for ev in chunk:
                    try:
                        r2 = _post_batch_events(ctx, [ev])
                        c2 = int(r2.get("createdAmount") or 0)
                        f2 = int(r2.get("failedAmount") or 0)
                        if r2.get("success") and f2 == 0 and c2 > 0:
                            written += c2
                            created_amount += c2
                        else:
                            errors.append(
                                {
                                    "externalId": (ev.get("contactEvent") or {}).get(
                                        "externalId"
                                    ),
                                    "error": r2.get("message")
                                    or r2.get("failedContacts")
                                    or str(exc),
                                }
                            )
                    except ManagoClientError as exc2:
                        errors.append(
                            {
                                "externalId": (ev.get("contactEvent") or {}).get(
                                    "externalId"
                                ),
                                "error": str(exc2),
                            }
                        )
            time.sleep(0.3)

    return {
        "phase": 3,
        "dry_run": dry_run,
        "shopify_refund_cancel_count": len(rows),
        "events_planned": len(events),
        "events_written": written,
        "created_amount": created_amount,
        "skipped": skipped,
        "errors": errors,
        "by_type": dict(
            Counter(
                e["event"]["contactEvent"]["contactExtEventType"] for e in events
            )
        ),
        "events": events,
        "payload_shape": "{contactId, contactEvent:{date,contactExtEventType,value,externalId,location,...}}",
    }


def phase4_protect(inspect: dict[str, Any], le09: dict[str, Any]) -> dict[str, Any]:
    """Ensure we did not plan/add PURCHASE events; counts stay 82/82."""
    planned_types = Counter(
        e["event"]["contactEvent"]["contactExtEventType"]
        for e in le09.get("events") or []
        if isinstance(e.get("event"), dict) and isinstance(e["event"].get("contactEvent"), dict)
    )
    purchase_types_in_plan = [
        t for t in planned_types if t.upper() in _PURCHASE_TYPES
    ]
    return_only = all(
        t.upper() in _RETURN_TYPES for t in planned_types
    ) if planned_types else True
    return {
        "phase": 4,
        "shopify_paid_unchanged": inspect["shopify_paid"],
        "manago_purchases_unchanged": inspect["manago_purchases"],
        "purchase_parity_ok": inspect["shopify_paid"] == inspect["manago_purchases"] == 82,
        "planned_event_types": dict(planned_types),
        "no_purchase_in_le09_plan": not purchase_types_in_plan,
        "return_types_only": return_only,
        "return_types_constant": sorted(_RETURN_TYPES),
        "purchase_types_constant": sorted(_PURCHASE_TYPES),
    }


def phase5_pt04_estimate(inspect: dict[str, Any], le09: dict[str, Any]) -> dict[str, Any]:
    total_refund_value = 0.0
    for e in le09.get("events") or []:
        ev = e.get("event") or {}
        contact_event = ev.get("contactEvent") if isinstance(ev, dict) else None
        value = None
        if isinstance(contact_event, dict):
            value = contact_event.get("value")
        elif isinstance(ev, dict):
            value = ev.get("value")
        try:
            total_refund_value += float(value or 0)
        except (TypeError, ValueError):
            pass
    return {
        "phase": 5,
        "events_covering_refunds": le09.get("events_planned"),
        "events_written": le09.get("events_written"),
        "total_return_cancel_value_planned": round(total_refund_value, 2),
        "note": (
            "PT-04 overstatement on Run 486 was 27471.81 with refund_blind=71. "
            "If RETURN/CANCELLATION values match Shopify refund/cancel totals "
            "and attach to the same contacts, refund_blind/over_delta should fall."
        ),
        "coverage_vs_95": le09.get("events_planned") == 95,
    }


def phase6_run_dcs(company: Company) -> dict[str, Any]:
    """Enqueue is heavy; create dcs-score via existing enqueue helper if available."""
    from dataruns.dcs.enqueue import enqueue_dcs_score

    # Find an admin/user if needed — enqueue may only need company
    result = enqueue_dcs_score(company=company, triggered_by="dcs_486_easy_fixes")
    return {"phase": 6, "enqueue_result": result if not isinstance(result, dict) else result}


def _try_enqueue_dcs(company: Company) -> dict[str, Any]:
    try:
        from dataruns.dcs.enqueue import enqueue_dcs_score
    except ImportError:
        return {
            "phase": 6,
            "status": "skipped",
            "reason": "enqueue_dcs_score not importable; re-run DCS from UI",
        }

    # Inspect signature
    import inspect as pyinspect

    sig = pyinspect.signature(enqueue_dcs_score)
    kwargs: dict[str, Any] = {}
    params = sig.parameters
    if "company" in params:
        kwargs["company"] = company
    if "company_id" in params:
        kwargs["company_id"] = company.id
    if "triggered_by" in params:
        kwargs["triggered_by"] = "dcs_486_easy_fixes_script"
    try:
        out = enqueue_dcs_score(**kwargs)
        return {"phase": 6, "status": "enqueued", "result": str(out)}
    except TypeError as exc:
        return {
            "phase": 6,
            "status": "enqueue_failed",
            "error": str(exc),
            "hint": "Trigger DCS score manually from the UI for this company.",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "phase": 6,
            "status": "enqueue_failed",
            "error": str(exc),
            "hint": "Trigger DCS score manually from the UI for this company.",
        }


def write_report(payload: dict[str, Any]) -> None:
    p1 = payload["phase1"]
    p2 = payload["phase2"]
    p3 = payload["phase3"]
    p4 = payload["phase4"]
    p5 = payload["phase5"]
    p6 = payload.get("phase6") or {}
    lines = [
        "# DCS 486 — Easy fixes implementation report",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Dry run: **{payload['dry_run']}**",
        f"- Company: `{COMPANY_ID}`",
        f"- Baseline run: **486** (score 63.04)",
        "- Scope: SP-03 ORDER_NUMBER + LE-09 RETURN/CANCELLATION only",
        "- Not touched: CI-01 / CI-03 / CI-05, DCS check code, Shopify orders, PURCHASE events",
        "",
        "## Phase 1 — Inspect",
        "",
        "### Mutation mechanism",
        "",
        "```json",
        json.dumps(p1["mutation_mechanism"], indent=2),
        "```",
        "",
        f"- Manago contacts in Run 486 raw: **{p1['contacts_n']}**",
        f"- Shopify orders in Run 486 raw: **{p1['orders_n']}**",
        f"- ORDER_NUMBER count: **{p1['order_number']['count']}** (iterator={p1['order_number']['iterator_count']})",
        f"- ORDER_NUMBER bags: `{p1['order_number']['bags']}`",
        f"- ORDER_NUMBER formats before: `{p1['order_number']['fmt_before']}`",
        f"- ORDER_NUMBER types before: `{p1['order_number']['type_before']}`",
        f"- ORDER_NUMBER values before: `{p1['order_number']['value_before']}`",
        f"- Shopify paid: **{p1['shopify_paid']}**",
        f"- Manago PURCHASE: **{p1['manago_purchases']}**",
        f"- Shopify refund/cancel: **{p1['shopify_refund_cancel']['count']}** (`{p1['shopify_refund_cancel']['by_type']}`)",
        f"- Existing Manago RETURN/CANCEL in tx export: **{p1['manago_return_events_in_tx_export']}**",
        f"- Unmatched refund orders (no Manago contact): **{len(p1['shopify_refund_cancel']['unmatched_to_manago_contact'])}**",
        "",
        "## Phase 2 — SP-03",
        "",
        f"- Needs write: **{p2['needs_write']}** / {p2['order_number_total']}",
        f"- Written: **{p2['written']}**",
        f"- Planned formats after: `{p2['fmt_after_planned']}` all_numeric={p2['all_numeric_planned']}",
        f"- Errors: **{len(p2['errors'])}**",
        "",
        "## Phase 3 — LE-09",
        "",
        f"- Shopify refund/cancel authoritative count: **{p3['shopify_refund_cancel_count']}**",
        f"- Events planned: **{p3['events_planned']}** (`{p3['by_type']}`)",
        f"- Events written: **{p3['events_written']}**",
        f"- Skipped: **{len(p3['skipped'])}**",
        f"- Errors: **{len(p3['errors'])}**",
        "",
        "## Phase 4 — Protect LE-01/02/05",
        "",
        f"- Shopify paid still **{p4['shopify_paid_unchanged']}**, Manago PURCHASE still **{p4['manago_purchases_unchanged']}**",
        f"- Purchase parity OK (82/82): **{p4['purchase_parity_ok']}**",
        f"- LE-09 plan contains no PURCHASE: **{p4['no_purchase_in_le09_plan']}**",
        f"- Return-types only: **{p4['return_types_only']}** `{p4['planned_event_types']}`",
        "",
        "## Phase 5 — PT-04 estimate",
        "",
        f"- Coverage vs 95: **{p5['coverage_vs_95']}**",
        f"- Planned RETURN/CANCEL value sum: **{p5['total_return_cancel_value_planned']}**",
        f"- Note: {p5['note']}",
        "",
        "## Phase 6 — Fresh import / DCS",
        "",
        "```json",
        json.dumps(p6, indent=2, default=str),
        "```",
        "",
        "## Next step if DCS not auto-enqueued",
        "",
        "Re-run DCS score for this company from the UI. Fresh import will pull live Manago.",
        "Then confirm SP-03 / LE-09 / PT-04 / LE-01 / LE-02 / LE-05 on the new run.",
        "",
    ]
    if p2.get("errors"):
        lines += ["### SP-03 errors", "", "```json", json.dumps(p2["errors"], indent=2), "```", ""]
    if p3.get("errors"):
        lines += ["### LE-09 errors", "", "```json", json.dumps(p3["errors"][:30], indent=2), "```", ""]
    if p3.get("skipped"):
        lines += ["### LE-09 skipped", "", "```json", json.dumps(p3["skipped"], indent=2), "```", ""]

    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Inspect + plan only")
    parser.add_argument("--skip-dcs", action="store_true", help="Do not enqueue DCS after mutate")
    parser.add_argument("--apply", action="store_true", help="Write to live Manago")
    parser.add_argument("--sp03-only", action="store_true")
    parser.add_argument("--le09-only", action="store_true")
    args = parser.parse_args()
    dry_run = args.dry_run or not args.apply

    manifest = json.loads((EXPORT_DIR / "manifest.json").read_text(encoding="utf-8"))
    company = Company.objects.get(id=COMPANY_ID)

    print("=== PHASE 1 INSPECT ===")
    inspect = phase1_inspect(manifest)
    print(
        "ORDER_NUMBER",
        inspect["order_number"]["count"],
        inspect["order_number"]["fmt_before"],
        "refunds",
        inspect["shopify_refund_cancel"]["count"],
        "purchases",
        inspect["manago_purchases"],
        "paid",
        inspect["shopify_paid"],
    )
    if inspect["order_number"]["count"] == 0:
        raise SystemExit("No ORDER_NUMBER found — stop, do not guess bag format.")
    if inspect["shopify_refund_cancel"]["count"] != 95:
        print(
            "WARNING: refund/cancel count is",
            inspect["shopify_refund_cancel"]["count"],
            "not 95",
        )

    ctx = None
    if not dry_run:
        print("=== RESOLVE MANAGO WRITE CONTEXT ===")
        ctx = resolve_manago_write_context(company)

    if args.le09_only:
        sp03 = {
            "phase": 2,
            "dry_run": True,
            "order_number_total": inspect["order_number"]["count"],
            "needs_write": 0,
            "written": 0,
            "errors": [],
            "fmt_after_planned": {"numeric": inspect["order_number"]["count"]},
            "all_numeric_planned": True,
            "rows": [],
            "skipped_reason": "le09-only; SP-03 already applied in prior run",
        }
        print("=== PHASE 2 SP-03 === SKIPPED (--le09-only)")
    else:
        print("=== PHASE 2 SP-03 ===", "DRY" if dry_run else "APPLY")
        sp03 = phase2_fix_sp03(ctx, inspect, dry_run=dry_run)
        print(
            "written",
            sp03["written"],
            "errors",
            len(sp03["errors"]),
            "all_numeric",
            sp03["all_numeric_planned"],
        )

    if args.sp03_only:
        le09 = {
            "phase": 3,
            "dry_run": True,
            "shopify_refund_cancel_count": inspect["shopify_refund_cancel"]["count"],
            "events_planned": 0,
            "events_written": 0,
            "skipped": [],
            "errors": [],
            "by_type": {},
            "events": [],
            "skipped_reason": "sp03-only",
        }
        print("=== PHASE 3 LE-09 === SKIPPED (--sp03-only)")
    else:
        print("=== PHASE 3 LE-09 ===", "DRY" if dry_run else "APPLY")
        le09 = phase3_fix_le09(ctx, inspect, dry_run=dry_run)
        print(
            "written",
            le09["events_written"],
            "planned",
            le09["events_planned"],
            "errors",
            len(le09["errors"]),
        )

    print("=== PHASE 4 PROTECT ===")
    protect = phase4_protect(inspect, le09)
    print(protect)

    print("=== PHASE 5 PT-04 ESTIMATE ===")
    pt04 = phase5_pt04_estimate(inspect, le09)
    print(pt04)

    phase6: dict[str, Any]
    if dry_run or args.skip_dcs:
        phase6 = {
            "phase": 6,
            "status": "skipped",
            "reason": "dry-run or --skip-dcs; trigger DCS manually after apply",
        }
    else:
        print("=== PHASE 6 ENQUEUE DCS ===")
        phase6 = _try_enqueue_dcs(company)
        print(phase6)

    payload = {
        "generated_at": _utc_now(),
        "dry_run": dry_run,
        "company_id": COMPANY_ID,
        "baseline_run": 486,
        "baseline_score": 63.04,
        "phase1": inspect,
        "phase2": sp03,
        "phase3": le09,
        "phase4": protect,
        "phase5": pt04,
        "phase6": phase6,
    }
    # shrink JSON rows for report companion (keep full in separate keys already)
    write_report(payload)
    print("Wrote", OUT_REPORT)
    print("Wrote", OUT_JSON)


if __name__ == "__main__":
    main()
