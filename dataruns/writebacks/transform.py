"""Evidence rows → WriteIntent list (PRD-WB-01 §3–4)."""

from __future__ import annotations

from typing import Any

from dataruns.connectors.mapping import UnmappedFieldError, reverse_map_record
from dataruns.dcs.segment_join import (
    is_klints_owned_detail,
    is_klints_owned_tag,
    legacy_namespace_rename,
)
from dataruns.dcs.worklist import WorklistDetailNotFound, build_worklist_detail
from dataruns.writebacks.guards import apply_guards
from dataruns.writebacks.snapshot import (
    _snapshot_contacts,
    contact_detail_value,
    contact_has_tag,
    find_manago_contact,
)
from dataruns.writebacks.types import WriteIntent
from tenants.models import Company


def collect_evidence_rows(
    *,
    company: Company,
    check_id: str,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    normalized = (check_id or "").strip().upper()
    if normalized == "WB-SHOP-01":
        return _shopify_sandbox_evidence_rows(company=company, max_rows=max_rows)

    rows = (
        _worklist_evidence_rows_merged(company=company, check_id=check_id)
        if normalized == "SP-07"
        else _worklist_evidence_rows(company=company, check_id=check_id)
    )
    if normalized == "CC-03":
        rows = _cc03_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "LE-01":
        rows = _le01_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "LE-09":
        rows = _le09_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "PT-04":
        rows = _pt04_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "SP-07":
        rows = _sp07_evidence_rows(company=company, rows=rows, max_rows=max_rows)

    if max_rows is not None and max_rows >= 0:
        return rows[:max_rows]
    return rows


def _worklist_evidence_rows(*, company: Company, check_id: str) -> list[dict[str, Any]]:
    try:
        detail = build_worklist_detail(company=company, check_id=check_id)
    except WorklistDetailNotFound:
        return []

    rows: list[dict[str, Any]] = []
    for key in ("mismatches", "evidence", "matches"):
        candidates = detail.get(key)
        if isinstance(candidates, list) and candidates:
            for item in candidates:
                if isinstance(item, dict):
                    rows.append(item)
            break
    return rows


def _worklist_evidence_rows_merged(
    *, company: Company, check_id: str
) -> list[dict[str, Any]]:
    """SP-07: union mismatches + evidence so collision lists are not dropped.

    Provenance mismatches carry per-key sides; evidence carries aggregate
    ``klints_*_collisions`` arrays. Taking only the first list misses one shape.
    """
    try:
        detail = build_worklist_detail(company=company, check_id=check_id)
    except WorklistDetailNotFound:
        return []

    rows: list[dict[str, Any]] = []
    for key in ("mismatches", "evidence", "matches"):
        candidates = detail.get(key)
        if not isinstance(candidates, list):
            continue
        for item in candidates:
            if isinstance(item, dict):
                rows.append(item)
    return rows

def _evidence_side(row: dict[str, Any]) -> str:
    side = row.get("side")
    if side:
        return str(side)
    value = row.get("value")
    if isinstance(value, dict) and value.get("side"):
        return str(value.get("side"))
    return ""


def _flatten_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    """Lift nested worklist ``value`` fields to top-level (DCS mismatch shape)."""
    out = dict(row)
    value = row.get("value")
    if isinstance(value, dict):
        for key, item in value.items():
            out.setdefault(key, item)
    return out


def _cc03_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Prefer DCS shopify_holds_evidence; sandbox falls back to a Manago contact.

    Worklist detail is FAIL/WARN only. A PASS CC-03 on a sandbox tenant yields
    zero rows, which made execute create a failed job that cannot be rolled back.
    """
    matched = [row for row in rows if _evidence_side(row) == "shopify_holds_evidence"]
    if matched:
        return matched
    from dataruns.writebacks.gates import is_writeback_execute_enabled

    if is_writeback_execute_enabled(company):
        return _cc03_sandbox_evidence_rows(company=company, max_rows=max_rows)
    return []


def _cc03_sandbox_evidence_rows(
    *,
    company: Company,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Build synthetic CC-03 evidence from Manago Contact rows (PRD-WB-01B §4).

    Prefer contacts that do not already have klints_consent_evidence=shopify_verified
    so sandbox preview does not re-target a contact that was already written.
    """
    from dataruns.models import Contact

    limit = 1 if max_rows is None else max(0, max_rows)
    qs = (
        Contact.objects.filter(company=company, source=Contact.Source.MANAGO_AI)
        .exclude(external_id="")
        .exclude(email="")
        .order_by("id")
    )
    rows: list[dict[str, Any]] = []
    for contact in qs[: max(limit * 20, limit)]:
        if len(rows) >= limit:
            break
        email = str(contact.email or "").strip()
        if "@" not in email:
            continue
        manago = find_manago_contact(
            company,
            email=email,
            contact_id=str(contact.external_id or "").strip() or None,
        )
        existing = (
            contact_detail_value(manago, "klints_consent_evidence") if manago else None
        )
        if existing == "shopify_verified":
            continue
        rows.append(
            {
                "side": "shopify_holds_evidence",
                "person.email": email,
                "manago_contact_id": str(contact.external_id),
                "note": "Sandbox proof fallback — CC-03 not on FAIL/WARN worklist",
            }
        )
    return rows


def _shopify_sandbox_evidence_rows(
    *,
    company: Company,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Build synthetic evidence from Shopify Contact rows (PRD-WB-01B §4)."""
    from dataruns.models import Contact

    limit = 1 if max_rows is None else max(0, max_rows)
    qs = (
        Contact.objects.filter(company=company, source=Contact.Source.SHOPIFY)
        .exclude(external_id="")
        .order_by("id")
    )
    rows: list[dict[str, Any]] = []
    for contact in qs[:limit]:
        customer_id = _normalize_shopify_customer_id(str(contact.external_id or ""))
        if not customer_id:
            continue
        email = str(contact.email or "").strip()
        rows.append(
            {
                "side": "sandbox_customer_note",
                "email": email or f"customer-{customer_id}@sandbox.invalid",
                "shopify_customer_id": customer_id,
            }
        )
    return rows


def _sp07_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Fan out account-level SP-07 collisions to per-contact rename rows (WB-09)."""
    detail_keys, tag_names = _sp07_collision_catalog(rows)
    if not detail_keys and not tag_names:
        return []

    expanded: list[dict[str, Any]] = []
    for contact in _snapshot_contacts(company):
        email = str(contact.get("email") or "").strip()
        contact_id = str(contact.get("contactId") or contact.get("id") or "").strip()
        if not email and not contact_id:
            continue
        # Never invent a fake email — Manago upsert must use real email or contactId.
        entity_key = email or contact_id

        for key in detail_keys:
            if is_klints_owned_detail(key):
                continue
            value = contact_detail_value(contact, key)
            if value is None:
                continue
            rename_to = legacy_namespace_rename(key)
            target_existing = contact_detail_value(contact, rename_to)
            row: dict[str, Any] = {
                "side": "klints_detail_collision",
                "key": key,
                "rename_to": rename_to,
                "detail_value": value,
                "entity_key": entity_key,
                "person.email": email or None,
                "manago_contact_id": contact_id or None,
                "locator": f"sp07.detail:{key}:{contact_id or email}",
            }
            if target_existing is not None and target_existing != value:
                row["rename_target_conflict"] = True
            expanded.append(row)

        for tag in tag_names:
            if is_klints_owned_tag(tag):
                continue
            if not contact_has_tag(contact, tag):
                continue
            rename_to = legacy_namespace_rename(tag)
            row = {
                "side": "klints_tag_collision",
                "tag": tag,
                "rename_to": rename_to,
                "entity_key": entity_key,
                "person.email": email or None,
                "manago_contact_id": contact_id or None,
                "locator": f"sp07.tag:{tag}:{contact_id or email}",
            }
            if contact_has_tag(contact, rename_to) and rename_to != tag:
                row["rename_target_conflict"] = True
            expanded.append(row)

        if max_rows is not None and max_rows >= 0 and len(expanded) >= max_rows:
            return expanded[:max_rows]

    if max_rows is not None and max_rows >= 0:
        return expanded[:max_rows]
    return expanded


def _sp07_collision_catalog(
    rows: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    detail_keys: list[str] = []
    tag_names: list[str] = []
    seen_detail: set[str] = set()
    seen_tag: set[str] = set()

    def _add_detail(key: Any) -> None:
        text = str(key or "").strip()
        if not text or text.lower() in seen_detail or is_klints_owned_detail(text):
            return
        if not text.lower().startswith("klints_"):
            return
        seen_detail.add(text.lower())
        detail_keys.append(text)

    def _add_tag(tag: Any) -> None:
        text = str(tag or "").strip()
        if not text or text.lower() in seen_tag or is_klints_owned_tag(text):
            return
        if not text.lower().startswith("klints:"):
            return
        seen_tag.add(text.lower())
        tag_names.append(text)

    for row in rows:
        flat = _flatten_evidence_row(row)
        side = _evidence_side(flat)
        if side == "klints_detail_collision":
            _add_detail(flat.get("key"))
        elif side == "klints_tag_collision":
            _add_tag(flat.get("tag"))

        for key in flat.get("klints_detail_collisions") or []:
            _add_detail(key)
        for tag in flat.get("klints_tag_collisions") or []:
            _add_tag(tag)

        value = flat.get("value")
        if isinstance(value, dict):
            for key in value.get("klints_detail_collisions") or []:
                _add_detail(key)
            for tag in value.get("klints_tag_collisions") or []:
                _add_tag(tag)

    return detail_keys, tag_names


def _le01_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Enrich LE-01 shopify_only gaps; sandbox only when worklist has no rows.

    DCS mismatches only carry ``order.id``. event_ingest needs email/contactId,
    so resolve Order/Contact (+ Manago snapshot) before mapping bind (WB-08 P0).

    If the worklist returns aggregate FAIL evidence without ``shopify_only`` gap
    rows, return empty — do not invent unrelated sandbox orders.
    """
    matched = [row for row in rows if _evidence_side(row) == "shopify_only"]
    enriched = [_enrich_le01_row(company, row) for row in matched]
    if enriched:
        if max_rows is not None and max_rows >= 0:
            return enriched[:max_rows]
        return enriched

    # Worklist had content but no actionable shopify_only gaps (e.g. monthly
    # delta FAIL with empty gap sample) — stay empty; do not substitute sandbox.
    if rows:
        return []

    from dataruns.writebacks.gates import is_writeback_execute_enabled

    if is_writeback_execute_enabled(company):
        return _le01_sandbox_evidence_rows(company=company, max_rows=max_rows)
    return []


def _enrich_le01_row(company: Company, row: dict[str, Any]) -> dict[str, Any]:
    """Attach person.email / manago_contact_id / amount_gross when resolvable.

    Worklist detail normalizes bare mismatch rows into ``value`` (side + order.id).
    Flatten first so enrichment sees the same keys DCS executors emit.
    """
    out = _flatten_evidence_row(row)
    order_id = str(out.get("order.id") or "").strip()
    if not order_id:
        return out

    email = str(out.get("person.email") or "").strip()
    amount = out.get("amount_gross")
    manago_id = str(out.get("manago_contact_id") or "").strip()

    if not email or amount is None or not manago_id:
        from dataruns.models import Order

        order = (
            Order.objects.filter(
                company=company,
                source=Order.Source.SHOPIFY,
                external_id=order_id,
            )
            .select_related("contact")
            .first()
        )
        if order is not None:
            if not email:
                email = str(order.contact.email or "").strip()
            if amount is None:
                amount = float(order.amount)
            if not manago_id and email:
                manago = find_manago_contact(company, email=email)
                if manago:
                    manago_id = str(
                        manago.get("contactId") or manago.get("id") or ""
                    ).strip()

    if email:
        out["person.email"] = email
    if amount is not None:
        out["amount_gross"] = amount
    if manago_id:
        out["manago_contact_id"] = manago_id
    return out


def _le01_sandbox_evidence_rows(
    *,
    company: Company,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Synthetic shopify_only rows from DB when LE-01 is not on FAIL worklist."""
    from dataruns.models import Order

    limit = 1 if max_rows is None else max(0, max_rows)
    qs = (
        Order.objects.filter(company=company, source=Order.Source.SHOPIFY)
        .exclude(external_id="")
        .select_related("contact")
        .order_by("id")
    )
    rows: list[dict[str, Any]] = []
    for order in qs[: max(limit * 20, limit)]:
        if len(rows) >= limit:
            break
        email = str(order.contact.email or "").strip()
        if "@" not in email:
            continue
        manago = find_manago_contact(company, email=email)
        manago_id = ""
        if manago:
            manago_id = str(manago.get("contactId") or manago.get("id") or "").strip()
        rows.append(
            {
                "side": "shopify_only",
                "order.id": str(order.external_id),
                "person.email": email,
                "manago_contact_id": manago_id or None,
                "amount_gross": float(order.amount),
                "note": "Sandbox proof fallback — LE-01 not on FAIL/WARN worklist",
            }
        )
    return rows


_LE09_REFUND_FINANCIAL = frozenset({"refunded", "partially_refunded"})
_LE09_CANCEL_FINANCIAL = frozenset({"voided", "cancelled", "canceled"})


def _le09_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Enrich LE-09 shopify_only_return gaps only (PRD-WB-10).

    No sandbox fallback — live FAIL/WARN mismatch rows only. Ignore
    ``manago_only_return`` and aggregate-only evidence without that side.
    """
    matched = [row for row in rows if _evidence_side(row) == "shopify_only_return"]
    enriched = [_enrich_le09_row(company, row) for row in matched]
    if max_rows is not None and max_rows >= 0:
        return enriched[:max_rows]
    return enriched


def _pt04_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Enrich PT-04 net_overstatement rows for klints_net_ltv stamp (WB-11).

    No sandbox — live FAIL mismatches only. Skip rows without shopify_net or
    without email/contactId. Never invent emails.
    """
    matched: list[dict[str, Any]] = []
    for row in rows:
        if _evidence_side(row) != "net_overstatement":
            continue
        enriched = _enrich_pt04_row(company, row)
        if enriched is not None:
            matched.append(enriched)
    if max_rows is not None and max_rows >= 0:
        return matched[:max_rows]
    return matched


def _enrich_pt04_row(company: Company, row: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten, resolve identity, set write_entity_key from email or contactId."""
    out = _flatten_evidence_row(row)
    email = str(out.get("person.email") or "").strip()
    manago_id = str(out.get("manago_contact_id") or "").strip()
    shopify_net = out.get("shopify_net")

    if shopify_net is None or shopify_net == "":
        return None
    try:
        float(shopify_net)
    except (TypeError, ValueError):
        return None

    # Worklist detail PII-masks emails (a***@x.com). Never upsert the mask —
    # re-resolve from snapshot / Contact DB when we have manago_contact_id.
    if email and "***" in email:
        email = ""

    if not _pt04_email_usable(email) or not manago_id:
        contact = find_manago_contact(
            company,
            email=email if _pt04_email_usable(email) else None,
            contact_id=manago_id or None,
        )
        if contact:
            resolved_email = str(contact.get("email") or "").strip()
            if _pt04_email_usable(resolved_email):
                email = resolved_email
            if not manago_id:
                manago_id = str(
                    contact.get("contactId") or contact.get("id") or ""
                ).strip()

    if not _pt04_email_usable(email) or not manago_id:
        email, manago_id = _pt04_resolve_from_contact_db(
            company, email=email, manago_id=manago_id
        )

    if not _pt04_email_usable(email) and not manago_id:
        return None

    write_entity_key = email if _pt04_email_usable(email) else manago_id
    if not write_entity_key:
        return None

    out["side"] = "net_overstatement"
    out["person.email"] = email if _pt04_email_usable(email) else None
    out["manago_contact_id"] = manago_id or None
    out["write_entity_key"] = write_entity_key
    out["shopify_net"] = shopify_net
    return out


def _pt04_email_usable(email: str) -> bool:
    text = (email or "").strip()
    return bool(text) and "@" in text and "***" not in text


def _pt04_resolve_from_contact_db(
    company: Company, *, email: str, manago_id: str
) -> tuple[str, str]:
    from dataruns.models import Contact

    qs = Contact.objects.filter(company=company, source=Contact.Source.MANAGO_AI)
    contact = None
    if manago_id:
        contact = qs.filter(external_id=manago_id).first()
    if contact is None and _pt04_email_usable(email):
        contact = qs.filter(email__iexact=email).exclude(email="").first()
    if contact is None:
        return email, manago_id
    resolved_email = str(contact.email or "").strip()
    if _pt04_email_usable(resolved_email):
        email = resolved_email
    if not manago_id:
        manago_id = str(contact.external_id or "").strip()
    return email, manago_id


def _enrich_le09_row(company: Company, row: dict[str, Any]) -> dict[str, Any]:
    """Attach email / contactId / amount_gross / event_type for RETURN|CANCELLATION."""
    out = _flatten_evidence_row(row)
    order_id = str(out.get("order.id") or "").strip()
    if not order_id:
        return out

    email = str(out.get("person.email") or "").strip()
    amount = out.get("amount_gross")
    manago_id = str(out.get("manago_contact_id") or "").strip()
    event_type = _normalize_le09_event_type(out.get("event_type"))

    order = None
    raw_order = None
    need_identity = not email or amount is None or not manago_id
    need_type = not event_type

    if need_identity or need_type:
        from dataruns.models import Order

        order = (
            Order.objects.filter(
                company=company,
                source=Order.Source.SHOPIFY,
                external_id=order_id,
            )
            .select_related("contact")
            .first()
        )
        if order is not None:
            if not email:
                email = str(order.contact.email or "").strip()
            if amount is None:
                amount = float(order.amount)
            if not manago_id and email:
                manago = find_manago_contact(company, email=email)
                if manago:
                    manago_id = str(
                        manago.get("contactId") or manago.get("id") or ""
                    ).strip()

    # Raw preferred for cancelled_at vs refunded (PRD §5.3 both → CANCELLATION).
    if need_type or event_type == "RETURN":
        raw_order = _le09_shopify_raw_order(company, order_id)
        if raw_order is not None:
            if amount is None:
                raw_price = raw_order.get("total_price")
                if raw_price is not None and str(raw_price).strip() != "":
                    try:
                        amount = float(raw_price)
                    except (TypeError, ValueError):
                        pass
            if not email:
                customer = (
                    raw_order.get("customer")
                    if isinstance(raw_order.get("customer"), dict)
                    else {}
                )
                email = str(
                    customer.get("email") or raw_order.get("email") or ""
                ).strip()
                if email and not manago_id:
                    manago = find_manago_contact(company, email=email)
                    if manago:
                        manago_id = str(
                            manago.get("contactId") or manago.get("id") or ""
                        ).strip()

    event_type = _resolve_le09_event_type(
        existing=event_type,
        order=order,
        raw_order=raw_order,
    )

    if email:
        out["person.email"] = email
    if amount is not None:
        out["amount_gross"] = amount
    if manago_id:
        out["manago_contact_id"] = manago_id
    out["event_type"] = event_type
    return out


def _normalize_le09_event_type(value: Any) -> str:
    upper = str(value or "").strip().upper()
    if upper in {"RETURN", "CANCELLATION"}:
        return upper
    if upper in {"CANCEL", "CANCELLED", "CANCELED"}:
        return "CANCELLATION"
    return ""


def _resolve_le09_event_type(
    *,
    existing: str,
    order: Any,
    raw_order: dict[str, Any] | None,
) -> str:
    """PRD: refunded→RETURN; cancelled→CANCELLATION; both→CANCELLATION; else RETURN.

    Cancel signals win over refund signals (Order FAILED or raw cancelled_at /
    cancel financial), even when the other surface still looks refunded.
    """
    from_order = _le09_event_type_from_order(order) if order is not None else ""
    from_raw = _le09_event_type_from_raw(raw_order) if raw_order is not None else ""

    if from_raw == "CANCELLATION" or from_order == "CANCELLATION":
        return "CANCELLATION"
    if existing == "CANCELLATION":
        return "CANCELLATION"
    if from_raw == "RETURN" or from_order == "RETURN" or existing == "RETURN":
        return "RETURN"
    return "RETURN"


def _le09_event_type_from_order(order: Any) -> str:
    from dataruns.models import Order

    status = str(getattr(order, "status", "") or "").lower()
    if status == Order.Status.FAILED:
        return "CANCELLATION"
    if status == Order.Status.REFUNDED:
        return "RETURN"
    return ""


def _le09_event_type_from_raw(order: dict[str, Any]) -> str:
    cancelled_at = order.get("cancelled_at")
    financial = str(order.get("financial_status") or "").lower()
    if cancelled_at or financial in _LE09_CANCEL_FINANCIAL:
        return "CANCELLATION"
    if financial in _LE09_REFUND_FINANCIAL:
        return "RETURN"
    return "RETURN"


def _le09_shopify_raw_order(company: Company, order_id: str) -> dict[str, Any] | None:
    """Best-effort raw Shopify order for event_type / amount when DB is thin."""
    try:
        from dataruns.dcs.lifecycle_join import _latest_connector_raw
    except Exception:
        return None

    raw = _latest_connector_raw(company=company, platform="shopify")
    if not raw:
        return None
    for order in raw.get("orders") or []:
        if not isinstance(order, dict):
            continue
        if str(order.get("id") or "").strip() == order_id:
            return order
    return None


def _normalize_shopify_customer_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "/Customer/" in raw:
        return raw.rsplit("/", 1)[-1].strip()
    return raw


def build_intents_from_mapping(
    *,
    company: Company,
    mapping: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> list[WriteIntent]:
    check_id = str(mapping.get("check_id") or "")
    template_id = mapping.get("template_id")
    rollback_block = mapping.get("rollback")
    rollback_strategy = (
        str(rollback_block.get("strategy"))
        if isinstance(rollback_block, dict) and rollback_block.get("strategy")
        else None
    )
    intents: list[WriteIntent] = []

    for operation in mapping.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        for index, row in enumerate(evidence_rows):
            intent = _intent_from_operation(
                company=company,
                check_id=check_id,
                template_id=template_id,
                operation=operation,
                row=row,
                row_index=index,
                rollback_strategy=rollback_strategy,
            )
            if intent is not None:
                intents.append(intent)
    return intents


def _intent_from_operation(
    *,
    company: Company,
    check_id: str,
    template_id: Any,
    operation: dict[str, Any],
    row: dict[str, Any],
    row_index: int,
    rollback_strategy: str | None = None,
) -> WriteIntent | None:
    from_evidence = operation.get("from_evidence")
    if not isinstance(from_evidence, dict):
        return None

    context = _evidence_context(row)
    if not _match_evidence(from_evidence.get("match"), context):
        return None

    fields = _resolve_fields(from_evidence.get("fields"), context)
    entity_key = _resolve_path_value(from_evidence.get("entity_key"), context)
    entity_key = "" if entity_key is None else str(entity_key)

    op_kind = str(operation.get("op_kind") or "")
    target = str(operation.get("target") or "manago")
    namespace = str(operation.get("namespace") or "")
    operation_id = str(operation.get("operation_id") or f"{target}.{op_kind}")
    entity_type = str(operation.get("entity_type") or "contact")
    capability_id = operation.get("capability_id")
    guards = [str(g) for g in (operation.get("guards") or []) if g]

    # LE-09 must never fall through to event_ingest's PURCHASE default.
    if str(check_id).upper() == "LE-09" and op_kind == "event_ingest":
        fields["event_type"] = _normalize_le09_event_type(fields.get("event_type")) or "RETURN"

    if context.get("rename_target_conflict"):
        return WriteIntent(
            check_id=check_id,
            op_kind=op_kind,
            operation=operation_id,
            target_system=target,
            entity_type=entity_type,
            entity_key=entity_key,
            namespace=namespace,
            template_id=str(template_id) if template_id else None,
            source_evidence_ref=str(row.get("locator") or row_index),
            status="error",
            error_reason="rename_target_conflict",
            capability_id=str(capability_id) if capability_id else None,
            rollback_strategy=rollback_strategy,
        )

    guard_reason = apply_guards(
        guards=guards,
        entity_key=entity_key,
        namespace=namespace,
        fields=fields,
    )
    if guard_reason:
        return WriteIntent(
            check_id=check_id,
            op_kind=op_kind,
            operation=operation_id,
            target_system=target,
            entity_type=entity_type,
            entity_key=entity_key,
            namespace=namespace,
            template_id=str(template_id) if template_id else None,
            source_evidence_ref=str(row.get("locator") or row_index),
            status="error",
            error_reason=guard_reason,
            capability_id=str(capability_id) if capability_id else None,
        )

    try:
        payload, before, after, rollback = _build_payload_and_state(
            company=company,
            op_kind=op_kind,
            target=target,
            fields=fields,
            entity_key=entity_key,
            context=context,
            mark_klints_backfill=bool(operation.get("mark_klints_backfill")),
            extras=operation.get("extras") if isinstance(operation.get("extras"), dict) else None,
        )
    except UnmappedFieldError as exc:
        return WriteIntent(
            check_id=check_id,
            op_kind=op_kind,
            operation=operation_id,
            target_system=target,
            entity_type=entity_type,
            entity_key=entity_key,
            namespace=namespace,
            template_id=str(template_id) if template_id else None,
            source_evidence_ref=str(row.get("locator") or row_index),
            status="error",
            error_reason=str(exc),
            capability_id=str(capability_id) if capability_id else None,
        )

    if op_kind == "event_ingest" and not str(
        payload.get("email") or payload.get("contactId") or ""
    ).strip():
        return WriteIntent(
            check_id=check_id,
            op_kind=op_kind,
            operation=operation_id,
            target_system=target,
            entity_type=entity_type,
            entity_key=entity_key,
            namespace=namespace,
            template_id=str(template_id) if template_id else None,
            payload=payload,
            before=before,
            after=after,
            rollback_snapshot=rollback,
            source_evidence_ref=str(row.get("locator") or row_index),
            status="error",
            error_reason="missing_contact_reference",
            capability_id=str(capability_id) if capability_id else None,
            rollback_strategy=rollback_strategy,
        )

    if operation.get("mark_klints_backfill") and not payload.get("_mark_klints_backfill"):
        payload["_mark_klints_backfill"] = True

    # Manago already has the target value (e.g. prior CC-03 Approve) — do not
    # advertise a no-op as Ready.
    already_applied = _before_equals_after(before, after)
    return WriteIntent(
        check_id=check_id,
        op_kind=op_kind,
        operation=operation_id,
        target_system=target,
        entity_type=entity_type,
        entity_key=entity_key,
        namespace=namespace,
        template_id=str(template_id) if template_id else None,
        payload=payload,
        before=before,
        after=after,
        rollback_snapshot=rollback,
        source_evidence_ref=str(row.get("locator") or row_index),
        status="skipped" if already_applied else "ready",
        error_reason="already_at_target" if already_applied else None,
        capability_id=str(capability_id) if capability_id else None,
        rollback_strategy=rollback_strategy,
    )


def _before_equals_after(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    if not after:
        return False
    if before == after:
        return True
    # PT-04 / numeric details: Manago often stores strings ("123.45") while
    # evidence shopify_net is float — treat numeric-equal as already_at_target.
    if set(before.keys()) != set(after.keys()):
        return False
    return all(_detail_values_equivalent(before.get(k), after.get(k)) for k in after)


def _detail_values_equivalent(left: Any, right: Any) -> bool:
    if left == right:
        return True
    if left is None or right is None:
        return False
    if left == "" or right == "":
        return False
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False


def _evidence_context(row: dict[str, Any]) -> dict[str, Any]:
    context = _flatten_evidence_row(row)
    value = row.get("value")
    context["value"] = value
    return context


def _match_evidence(rule: Any, context: dict[str, Any]) -> bool:
    if rule is None:
        return True
    if not isinstance(rule, dict):
        return True
    path = rule.get("path")
    if isinstance(path, str) and "const" in rule:
        return _get_path(context, path) == rule.get("const")
    if "const" in rule:
        return True
    if isinstance(path, str):
        return _get_path(context, path) is not None
    return True


def _resolve_fields(spec: Any, context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        return {}
    resolved: dict[str, Any] = {}
    for key, rule in spec.items():
        resolved[key] = _resolve_path_value(rule, context)
    return resolved


def _resolve_path_value(rule: Any, context: dict[str, Any]) -> Any:
    if not isinstance(rule, dict):
        return rule
    if "const" in rule:
        return rule.get("const")
    path = rule.get("path")
    if not isinstance(path, str):
        return None
    return _get_path(context, path)


def _get_path(context: dict[str, Any], path: str) -> Any:
    if path in context:
        return context[path]
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _build_payload_and_state(
    *,
    company: Company,
    op_kind: str,
    target: str,
    fields: dict[str, Any],
    entity_key: str,
    context: dict[str, Any],
    mark_klints_backfill: bool = False,
    extras: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if op_kind == "contact_upsert" and target == "manago":
        return _contact_upsert_payload(
            company=company,
            fields=fields,
            entity_key=entity_key,
            mark_klints_backfill=mark_klints_backfill,
            extras=extras,
        )
    if op_kind == "detail_set" and target == "manago":
        return _detail_set_payload(company=company, fields=fields, entity_key=entity_key)
    if op_kind == "tag_add" and target == "manago":
        return _tag_add_payload(company=company, fields=fields, entity_key=entity_key)
    if op_kind == "event_ingest" and target == "manago":
        payload, before, after, rollback = _event_ingest_payload(
            fields=fields,
            entity_key=entity_key,
            context=context,
        )
        if extras:
            payload.update(extras)
            after = {**after, **extras}
        return payload, before, after, rollback
    if op_kind == "shopify_customer_update" and target == "shopify":
        return _shopify_customer_update_payload(
            fields=fields,
            entity_key=entity_key,
            extras=extras,
        )
    raise ValueError(f"unsupported_op_kind:{op_kind}")


def _shopify_customer_update_payload(
    *,
    fields: dict[str, Any],
    entity_key: str,
    extras: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    customer_id = _normalize_shopify_customer_id(
        str(fields.get("customer_id") or entity_key or "")
    )
    note = fields.get("note")
    email = str(fields.get("email") or (entity_key if "@" in entity_key else "") or "").strip()
    payload: dict[str, Any] = {
        "id": customer_id,
        "note": note,
    }
    if email:
        payload["email"] = email
    if extras:
        for key, value in extras.items():
            if value is not None:
                payload[key] = value
    before = {"note": None, "id": customer_id}
    after = {"note": note, "id": customer_id}
    rollback = {"id": customer_id, "note": None}
    return payload, before, after, rollback


def _contact_upsert_payload(
    *,
    company: Company,
    fields: dict[str, Any],
    entity_key: str,
    mark_klints_backfill: bool = False,
    extras: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    email = str(fields.get("email") or entity_key or "").strip()
    db_record = {
        "email": email,
    }
    link_key = fields.get("link_key")
    if link_key:
        db_record["link_key"] = str(link_key)
    payload = reverse_map_record(
        db_record,
        platform="manago_ai",
        entity="contact",
        extras=extras,
    )
    if mark_klints_backfill:
        props = payload.get("properties")
        if not isinstance(props, dict):
            props = {}
            payload["properties"] = props
        props.setdefault("klints_backfill", "true")
        payload["_mark_klints_backfill"] = True
    contact = find_manago_contact(company, email=email)
    before = {"email": email, "present_in_manago": contact is not None}
    after = dict(payload)
    rollback = {"email": email, "existed": contact is not None}
    return payload, before, after, rollback


def _detail_set_payload(
    *,
    company: Company,
    fields: dict[str, Any],
    entity_key: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    detail_key = str(fields.get("detail_key") or "")
    detail_value = fields.get("detail_value")
    clear_detail_key = str(fields.get("clear_detail_key") or "").strip()
    contact_id = str(fields.get("contact_id") or "").strip()
    email = str(fields.get("email") or "").strip()
    if not email and "@" in str(entity_key or ""):
        email = str(entity_key).strip()
    contact = find_manago_contact(company, email=email or None, contact_id=contact_id or None)
    before_value = contact_detail_value(contact, detail_key) if contact else None
    clear_before = (
        contact_detail_value(contact, clear_detail_key) if contact and clear_detail_key else None
    )
    resolved_email = email or str((contact or {}).get("email") or "").strip()
    resolved_id = (
        contact_id
        or (contact or {}).get("contactId")
        or (contact or {}).get("id")
        or (entity_key if entity_key and "@" not in entity_key else "")
    )
    properties: dict[str, Any] = {detail_key: detail_value}
    if clear_detail_key and clear_detail_key != detail_key:
        # Empty string clears Manago standard detail (null is a no-op).
        properties[clear_detail_key] = ""
    payload: dict[str, Any] = {
        "email": resolved_email or None,
        "contactId": resolved_id or None,
        "properties": properties,
    }
    before: dict[str, Any] = {detail_key: before_value}
    after: dict[str, Any] = {detail_key: detail_value}
    rollback: dict[str, Any] = {detail_key: before_value}
    if clear_detail_key and clear_detail_key != detail_key:
        before[clear_detail_key] = clear_before
        after[clear_detail_key] = None
        rollback[clear_detail_key] = clear_before
        payload["_rename"] = {
            "from": clear_detail_key,
            "to": detail_key,
            "op": "detail",
            "prior_from_value": clear_before,
            "prior_to_value": before_value,
        }
        rollback["rename"] = payload["_rename"]
    return payload, before, after, rollback


def _tag_add_payload(
    *,
    company: Company,
    fields: dict[str, Any],
    entity_key: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    tag = str(fields.get("tag") or "")
    remove_tag = str(fields.get("remove_tag") or "").strip()
    email = str(fields.get("email") or "").strip()
    if not email and "@" in str(entity_key or ""):
        email = str(entity_key).strip()
    contact_id = str(fields.get("contact_id") or "").strip()
    if not contact_id and entity_key and "@" not in entity_key:
        contact_id = str(entity_key).strip()
    contact = find_manago_contact(
        company,
        email=email or None,
        contact_id=contact_id or None,
    )
    had_tag = contact_has_tag(contact, tag) if contact else False
    had_remove = contact_has_tag(contact, remove_tag) if contact and remove_tag else False
    resolved_id = contact_id or (contact or {}).get("contactId") or (contact or {}).get("id")
    payload: dict[str, Any] = {
        "email": email or None,
        "contactId": resolved_id,
        "tag": tag,
        "order_id": fields.get("order_id"),
    }
    before: dict[str, Any] = {"tag": tag, "present": had_tag}
    after: dict[str, Any] = {"tag": tag, "present": True}
    rollback: dict[str, Any] = {"tag": tag, "present": had_tag}
    if remove_tag and remove_tag != tag:
        payload["_remove_tag"] = remove_tag
        before["remove_tag"] = remove_tag
        before["remove_present"] = had_remove
        after["remove_tag"] = remove_tag
        after["remove_present"] = False
        payload["_rename"] = {
            "from": remove_tag,
            "to": tag,
            "op": "tag",
            "prior_from_present": had_remove,
            "prior_to_present": had_tag,
        }
        rollback["rename"] = payload["_rename"]
        rollback["remove_tag"] = remove_tag
        rollback["remove_present"] = had_remove
    return payload, before, after, rollback


def _event_ingest_payload(
    *,
    fields: dict[str, Any],
    entity_key: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    order_id = str(fields.get("order_id") or entity_key or "")
    email = fields.get("email") or (entity_key if "@" in str(entity_key) else None)
    contact_id = fields.get("contact_id")
    payload = {
        "externalId": order_id,
        "contactExtEventType": str(fields.get("event_type") or "PURCHASE"),
        "value": fields.get("value")
        or context.get("amount_gross")
        or context.get("representative_value")
        or context.get("count"),
    }
    if email:
        payload["email"] = str(email)
    if contact_id:
        payload["contactId"] = str(contact_id)
    before = {"externalId": order_id, "event_exists": False}
    after = dict(payload)
    rollback = {"externalId": order_id}
    return payload, before, after, rollback
