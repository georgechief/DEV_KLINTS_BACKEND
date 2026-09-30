"""Evidence rows → WriteIntent list (PRD-WB-01 §3–4)."""

from __future__ import annotations

from typing import Any

from dataruns.connectors.mapping import UnmappedFieldError, reverse_map_record
from dataruns.dcs.segment_join import (
    _classify_value,
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
    elif normalized == "LE-05":
        rows = _le05_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "LE-02":
        rows = _le02_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "LE-09":
        rows = _le09_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "PT-04":
        rows = _pt04_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "CI-05":
        rows = _ci05_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "CI-03":
        rows = _ci03_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "CC-01":
        rows = _cc01_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "CC-02":
        rows = _cc02_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "SP-03":
        rows = _sp03_evidence_rows(company=company, rows=rows, max_rows=max_rows)
    elif normalized == "PT-03":
        rows = _pt03_evidence_rows(company=company, rows=rows, max_rows=max_rows)
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
    """Prefer DCS shopify_holds_evidence; legacy Allow-writebacks fallback to a Manago contact.

    Worklist detail is FAIL/WARN only. A PASS CC-03 with Allow writebacks ON and no
    FAIL rows used to fail execute with an empty job — PRD-WB-01B invented contact
    rows for proof. PRD-WB-21 Phase D: keep this legacy path; do not add new invent
    fallbacks for other checks. Prefer real DCS FAIL/WARN evidence in product use.
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

    Legacy Allow-writebacks proof fallback (PRD-WB-21 Phase D — do not extend).
    Prefer contacts that do not already have klints_consent_evidence=shopify_verified
    so proof preview does not re-target a contact that was already written.
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


def _pt03_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """PRD-WB-20: expand catalog missing/surplus → product reconcile rows."""
    from dataruns.writebacks.registry import get_check_mapping

    mapping = get_check_mapping("PT-03")
    archive_enabled = (
        bool(mapping.get("archive_enabled")) if isinstance(mapping, dict) else False
    )

    live = _pt03_live_catalog_state(company=company)
    if live is None:
        return _pt03_rows_from_worklist(
            rows=rows,
            max_rows=max_rows,
            archive_enabled=archive_enabled,
            shopify_by_id={},
            manago_by_id={},
            catalog_id=None,
        )

    shopify_by_id = live["shopify_by_id"]
    manago_by_id = live["manago_by_id"]
    catalog_id = live.get("catalog_id")
    needs_catalog_id = bool(live.get("needs_catalog_id"))
    missing_ids = live["missing_ids"]
    surplus_ids = live["surplus_ids"]

    if not missing_ids and not surplus_ids:
        return _pt03_rows_from_worklist(
            rows=rows,
            max_rows=max_rows,
            archive_enabled=archive_enabled,
            shopify_by_id=shopify_by_id,
            manago_by_id=manago_by_id,
            catalog_id=catalog_id,
            needs_catalog_id=needs_catalog_id,
        )

    expanded: list[dict[str, Any]] = []
    for pid in missing_ids:
        shop = shopify_by_id.get(pid) or {}
        missing_gate = "needs_catalog_id" if needs_catalog_id else "pins_rebuild"
        expanded.append(
            {
                "side": "missing_in_manago",
                "product_id": pid,
                "write_entity_key": pid,
                "shopify_title": shop.get("title") or "",
                "shopify_sku": shop.get("sku") or "",
                "catalog_id": catalog_id,
                "proposed_action": "UPSERT_FROM_SHOPIFY",
                "evidence_gate": missing_gate,
                "locator": f"pt03:missing:{pid}",
            }
        )
        if max_rows is not None and max_rows >= 0 and len(expanded) >= max_rows:
            return expanded[:max_rows]

    for pid in surplus_ids:
        man = manago_by_id.get(pid) or {}
        gate = "archive_loom" if archive_enabled else "archive_semantics_unknown"
        expanded.append(
            {
                "side": "surplus_in_manago",
                "product_id": pid,
                "write_entity_key": pid,
                "manago_name": man.get("name") or "",
                "manago_sku": man.get("sku") or "",
                "manago_active": man.get("active"),
                "catalog_id": catalog_id,
                "proposed_action": "ARCHIVE_FLAG",
                "evidence_gate": gate,
                "locator": f"pt03:surplus:{pid}",
            }
        )
        if max_rows is not None and max_rows >= 0 and len(expanded) >= max_rows:
            return expanded[:max_rows]

    if max_rows is not None and max_rows >= 0:
        return expanded[:max_rows]
    return expanded


def _pt03_live_catalog_state(company: Company) -> dict[str, Any] | None:
    try:
        from dataruns.dcs.catalog_join import build_catalog_snapshot
        from dataruns.dcs.lifecycle_join import _connector_raw_for_platform
        from dataruns.dcs.pins import resolve_scoring_pins
    except Exception:
        return None

    source_run_ids, pinned_snapshot_ids, _run = resolve_scoring_pins(company=company)
    snap = build_catalog_snapshot(
        company=company,
        source_run_ids=source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    catalog = snap.get("catalog") if isinstance(snap, dict) else {}
    if not isinstance(catalog, dict) or not catalog.get("manago_catalog_available"):
        return None
    pt03 = catalog.get("pt03") if isinstance(catalog.get("pt03"), dict) else {}

    shopify_by_id: dict[str, dict[str, Any]] = {}
    for row in snap.get("products") or []:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("product_id") or "").strip()
        if pid:
            shopify_by_id[pid] = row

    manago_raw = _connector_raw_for_platform(
        company=company,
        platform="manago_ai",
        source_run_id=source_run_ids.get("manago_ai") if source_run_ids else None,
        snapshot_id=pinned_snapshot_ids.get("manago_ai") if pinned_snapshot_ids else None,
    )
    manago_by_id: dict[str, dict[str, Any]] = {}
    for prod in manago_raw.get("products") or []:
        if not isinstance(prod, dict):
            continue
        pid = (
            prod.get("productId")
            or prod.get("product_id")
            or prod.get("id")
            or prod.get("sku")
        )
        if pid is None:
            continue
        key = str(pid)
        manago_by_id[key] = {
            "product_id": key,
            "name": prod.get("name") or prod.get("title") or "",
            "sku": prod.get("sku") or "",
            "active": prod.get("active") if prod.get("active") is not None else True,
        }

    catalog_id = None
    needs_catalog_id = False
    catalogs = [
        c for c in (catalog.get("manago_catalogs") or []) if isinstance(c, dict)
    ]
    for c in catalogs:
        if c.get("setAsDefault") is True:
            catalog_id = c.get("catalogId") or c.get("id")
            break
    if catalog_id is None:
        if len(catalogs) == 1:
            catalog_id = catalogs[0].get("catalogId") or catalogs[0].get("id")
        elif len(catalogs) > 1:
            # PRD-WB-20 §2.3 — multi-catalog with no default → honest skip.
            needs_catalog_id = True

    return {
        "shopify_by_id": shopify_by_id,
        "manago_by_id": manago_by_id,
        "catalog_id": str(catalog_id).strip() if catalog_id else None,
        "needs_catalog_id": needs_catalog_id,
        "missing_ids": [str(x) for x in (pt03.get("missing_sample") or []) if x],
        "surplus_ids": [str(x) for x in (pt03.get("surplus_sample") or []) if x],
    }


def _pt03_rows_from_worklist(
    *,
    rows: list[dict[str, Any]],
    max_rows: int | None,
    archive_enabled: bool,
    shopify_by_id: dict[str, dict[str, Any]],
    manago_by_id: dict[str, dict[str, Any]],
    catalog_id: str | None,
    needs_catalog_id: bool = False,
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for row in rows:
        flat = _flatten_evidence_row(row) if isinstance(row, dict) else {}
        side = str(flat.get("side") or "").strip()
        if side not in ("missing_in_manago", "surplus_in_manago"):
            continue
        pid = str(flat.get("product_id") or "").strip()
        if not pid:
            continue
        if side == "missing_in_manago":
            shop = shopify_by_id.get(pid) or {}
            existing_gate = str(flat.get("evidence_gate") or "").strip()
            if existing_gate == "needs_catalog_id" or needs_catalog_id:
                missing_gate = "needs_catalog_id"
            elif existing_gate:
                missing_gate = existing_gate
            else:
                missing_gate = "worklist"
            expanded.append(
                {
                    "side": side,
                    "product_id": pid,
                    "write_entity_key": pid,
                    "shopify_title": shop.get("title")
                    or flat.get("shopify_title")
                    or "",
                    "shopify_sku": shop.get("sku") or flat.get("shopify_sku") or "",
                    "catalog_id": catalog_id,
                    "proposed_action": "UPSERT_FROM_SHOPIFY",
                    "evidence_gate": missing_gate,
                    "locator": flat.get("locator") or f"pt03:missing:{pid}",
                }
            )
        else:
            man = manago_by_id.get(pid) or {}
            gate = "archive_loom" if archive_enabled else "archive_semantics_unknown"
            expanded.append(
                {
                    "side": side,
                    "product_id": pid,
                    "write_entity_key": pid,
                    "manago_name": man.get("name") or "",
                    "manago_sku": man.get("sku") or "",
                    "manago_active": man.get("active"),
                    "catalog_id": catalog_id,
                    "proposed_action": "ARCHIVE_FLAG",
                    "evidence_gate": gate,
                    "locator": flat.get("locator") or f"pt03:surplus:{pid}",
                }
            )
        if max_rows is not None and max_rows >= 0 and len(expanded) >= max_rows:
            return expanded[:max_rows]
    if max_rows is not None and max_rows >= 0:
        return expanded[:max_rows]
    return expanded


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


def _sp03_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """PRD-WB-19: expand inconsistent detail keys → per-contact normalise rows."""
    from dataruns.writebacks.registry import get_check_mapping

    mapping = get_check_mapping("SP-03")
    contract = mapping.get("format_contract") if isinstance(mapping, dict) else {}
    if not isinstance(contract, dict):
        contract = {}

    # Prefer live pin-aligned catalog (format_distribution) over thin/contact-only worklist.
    catalog = _sp03_live_inconsistent_key_catalog(company=company)
    if not catalog:
        catalog = _sp03_inconsistent_key_catalog(rows)
    if not catalog:
        return []

    expanded: list[dict[str, Any]] = []
    for contact in _sp03_pinned_contacts(company):
        email = str(contact.get("email") or "").strip()
        contact_id = str(contact.get("contactId") or contact.get("id") or "").strip()
        if not email and not contact_id:
            continue
        write_entity_key = email if ("@" in email and "***" not in email) else contact_id
        if not write_entity_key:
            continue

        for key, meta in catalog.items():
            value = contact_detail_value(contact, key)
            if value is None:
                continue
            fmt_before = _classify_value(value)
            target, coerce, gate = _sp03_resolve_target(
                key=key,
                format_distribution=meta.get("format_distribution") or {},
                samples=meta.get("samples") or [],
                contract=contract,
            )
            row_base = {
                "side": "inconsistent_detail_format",
                "key": key,
                "person.email": email or None,
                "manago_contact_id": contact_id or None,
                "write_entity_key": write_entity_key,
                "value_before": value,
                "fmt_before": fmt_before,
                "target_format": target,
                "locator": f"sp03:{key}:{contact_id or email}",
            }
            if target is None:
                expanded.append(
                    {
                        **row_base,
                        "value_after": value,
                        "fmt_after": fmt_before,
                        "proposed_action": "SKIP_NEEDS_CONTRACT",
                        "evidence_gate": gate or "needs_contract",
                    }
                )
            else:
                value_after = _sp03_coerce_value(
                    value, target_format=target, coerce=coerce or "identity"
                )
                if value_after is None:
                    expanded.append(
                        {
                            **row_base,
                            "value_after": value,
                            "fmt_after": fmt_before,
                            "proposed_action": "SKIP_NEEDS_CONTRACT",
                            "evidence_gate": "coerce_failed",
                        }
                    )
                else:
                    fmt_after = _classify_value(value_after)
                    if fmt_after != target:
                        expanded.append(
                            {
                                **row_base,
                                "value_after": value_after,
                                "fmt_after": fmt_after,
                                "proposed_action": "SKIP_NEEDS_CONTRACT",
                                "evidence_gate": "classify_mismatch_after_coerce",
                            }
                        )
                    elif fmt_before == target and value_after == value:
                        continue
                    else:
                        expanded.append(
                            {
                                **row_base,
                                "value_after": value_after,
                                "fmt_after": fmt_after,
                                "proposed_action": "NORMALIZE_DETAIL",
                                "evidence_gate": gate,
                            }
                        )

            if max_rows is not None and max_rows >= 0 and len(expanded) >= max_rows:
                return expanded[:max_rows]

    if max_rows is not None and max_rows >= 0:
        return expanded[:max_rows]
    return expanded


def _sp03_pinned_contacts(company: Company) -> list[dict[str, Any]]:
    """Manago contacts from scoring pins (fallback: latest snapshot)."""
    try:
        from dataruns.dcs.lifecycle_join import _connector_raw_for_platform
        from dataruns.dcs.pins import resolve_scoring_pins
    except Exception:
        return _snapshot_contacts(company)

    source_run_ids, pinned_snapshot_ids, _run = resolve_scoring_pins(company=company)
    raw = _connector_raw_for_platform(
        company=company,
        platform="manago_ai",
        source_run_id=source_run_ids.get("manago_ai") if source_run_ids else None,
        snapshot_id=pinned_snapshot_ids.get("manago_ai") if pinned_snapshot_ids else None,
    )
    contacts = raw.get("contacts") if isinstance(raw, dict) else None
    if isinstance(contacts, list) and contacts:
        return [c for c in contacts if isinstance(c, dict)]
    return _snapshot_contacts(company)


def _sp03_inconsistent_key_catalog(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for row in rows:
        flat = _flatten_evidence_row(row)
        side = _evidence_side(flat)
        if side == "inconsistent_detail_format":
            key = str(flat.get("key") or "").strip()
            if key:
                catalog[key] = {
                    "format_distribution": flat.get("format_distribution") or {},
                    "samples": list(flat.get("samples") or []),
                }
        samples = flat.get("inconsistent_sample")
        if isinstance(samples, list):
            for item in samples:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if not key:
                    continue
                catalog[key] = {
                    "format_distribution": item.get("format_distribution") or {},
                    "samples": list(item.get("samples") or []),
                }
        value = flat.get("value")
        if isinstance(value, dict):
            for item in value.get("inconsistent_sample") or []:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if not key:
                    continue
                catalog[key] = {
                    "format_distribution": item.get("format_distribution") or {},
                    "samples": list(item.get("samples") or []),
                }
    return catalog


def _sp03_live_inconsistent_key_catalog(
    *,
    company: Company,
) -> dict[str, dict[str, Any]]:
    from dataruns.dcs.pins import resolve_scoring_pins
    from dataruns.dcs.segment_join import build_segment_snapshot

    source_run_ids, pinned_snapshot_ids, _run = resolve_scoring_pins(company=company)
    snap = build_segment_snapshot(
        company=company,
        source_run_ids=source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    segment = snap.get("segment") if isinstance(snap, dict) else {}
    if not isinstance(segment, dict):
        return {}
    catalog: dict[str, dict[str, Any]] = {}
    for item in segment.get("inconsistent_sample") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        catalog[key] = {
            "format_distribution": item.get("format_distribution") or {},
            "samples": list(item.get("samples") or []),
        }
    return catalog


def _sp03_contract_entry(contract: dict[str, Any], key: str) -> dict[str, Any] | None:
    if key in contract and isinstance(contract[key], dict):
        return contract[key]
    upper = key.upper()
    for ck, cv in contract.items():
        if str(ck).upper() == upper and isinstance(cv, dict):
            return cv
    return None


def _sp03_is_01_like(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) in (0.0, 1.0)
    text = str(value).strip().lower()
    return text in {"0", "1", "0.0", "1.0", "true", "false"}


def _sp03_resolve_target(
    *,
    key: str,
    format_distribution: dict[str, Any],
    samples: list[Any],
    contract: dict[str, Any],
) -> tuple[str | None, str | None, str]:
    """Return (target_format, coerce, evidence_gate)."""
    entry = _sp03_contract_entry(contract, key)
    if entry:
        target = str(entry.get("target_format") or "").strip()
        coerce = str(entry.get("coerce") or "identity").strip() or "identity"
        if target:
            return target, coerce, "contract"

    non_empty = {
        str(k): v
        for k, v in (format_distribution or {}).items()
        if str(k) != "empty" and int(v or 0) > 0
    }
    if set(non_empty.keys()) <= {"numeric", "boolean"} and non_empty:
        bool_samples = [s for s in samples if _classify_value(s) == "boolean"]
        if bool_samples and all(_sp03_is_01_like(s) for s in bool_samples):
            return "numeric", "decimal_string_if_01", "heuristic_numeric_from_01"
        if "boolean" in non_empty and "numeric" in non_empty:
            if not bool_samples or all(_sp03_is_01_like(s) for s in bool_samples):
                return "numeric", "decimal_string_if_01", "heuristic_numeric_from_01"
        if len(non_empty) == 1:
            only = next(iter(non_empty.keys()))
            return only, "identity", "single_format"
        return None, None, "needs_contract"

    if len(non_empty) == 1:
        only = next(iter(non_empty.keys()))
        return only, "identity", "single_format"
    return None, None, "needs_contract"


def _sp03_coerce_value(
    value: Any,
    *,
    target_format: str,
    coerce: str,
) -> Any | None:
    if coerce in ("", "identity"):
        if _classify_value(value) == target_format:
            return value
        return None

    if coerce == "decimal_string_if_01" and target_format == "numeric":
        if isinstance(value, bool):
            return "1.0" if value else "0.0"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if float(value) == 1.0:
                return "1.0"
            if float(value) == 0.0:
                return "0.0"
            if float(value) == int(float(value)):
                return str(int(float(value)))
            return str(value)
        text = str(value).strip()
        low = text.lower()
        if low in ("1", "1.0", "true"):
            return "1.0"
        if low in ("0", "0.0", "false"):
            return "0.0"
        try:
            parsed = float(text.replace(",", ""))
        except ValueError:
            return None
        if parsed == 1.0:
            return "1.0"
        if parsed == 0.0:
            return "0.0"
        if parsed == int(parsed):
            return str(int(parsed))
        return str(parsed)

    return None


def _le01_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Enrich LE-01 shopify_only gaps; legacy Allow-writebacks invent only when worklist empty.

    DCS mismatches only carry ``order.id``. event_ingest needs email/contactId,
    so resolve Order/Contact (+ Manago snapshot) before mapping bind (WB-08 P0).

    If the worklist returns aggregate FAIL evidence without ``shopify_only`` gap
    rows, return empty — do not invent unrelated orders.

    PRD-WB-21 Phase D: keep empty-worklist invent as legacy proof only; prefer
    real shopify_only FAIL rows. Do not add invent fallbacks for other checks.
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

    Worklist may PII-mask emails (``a***@x.com``). Never write the mask — treat as
    missing and re-resolve from Order / Manago (same honesty as PT-04 enrich).
    """
    out = _flatten_evidence_row(row)
    order_id = str(out.get("order.id") or "").strip()
    if not order_id:
        return out

    email = str(out.get("person.email") or "").strip()
    if email and "***" in email:
        email = ""
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
            if not manago_id and email and "***" not in email:
                manago = find_manago_contact(company, email=email)
                if manago:
                    manago_id = str(
                        manago.get("contactId") or manago.get("id") or ""
                    ).strip()

    if email and "***" not in email:
        out["person.email"] = email
    elif "person.email" in out and "***" in str(out.get("person.email") or ""):
        out.pop("person.email", None)
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


def _le05_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Enrich LE-05 shopify_only order gaps only (PRD-WB-13).

    No sandbox fallback — live FAIL/WARN mismatch rows only. Ignore
    ``manago_only`` and aggregate-only evidence without shopify_only.
    Reuse LE-01 enrich (same order.id → email/contactId/amount path).

    When worklist falls back to aggregate evidence (``value.gap_sample``) instead
    of flat provenance mismatches, expand that sample so Approve still sees gaps.
    """
    matched: list[dict[str, Any]] = []
    for row in rows:
        if _evidence_side(row) == "shopify_only":
            matched.append(row)
            continue
        flat = _flatten_evidence_row(row)
        gap_sample = flat.get("gap_sample")
        if not isinstance(gap_sample, list):
            continue
        for item in gap_sample:
            if isinstance(item, dict) and _evidence_side(item) == "shopify_only":
                matched.append(item)

    enriched = [_enrich_le01_row(company, row) for row in matched]
    if max_rows is not None and max_rows >= 0:
        return enriched[:max_rows]
    return enriched


def _le02_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Enrich LE-02 value_mismatch rows only (PRD-WB-14).

    No sandbox invent. Ignore driver-only rows and gap sides.
    """
    matched: list[dict[str, Any]] = []
    for row in rows:
        if _evidence_side(row) != "value_mismatch":
            continue
        enriched = _enrich_le02_row(company, row)
        if enriched is not None:
            matched.append(enriched)
    if max_rows is not None and max_rows >= 0:
        return matched[:max_rows]
    return matched


def _enrich_le02_row(company: Company, row: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten value_mismatch; resolve identity; keep shopify_gross as write value."""
    out = _flatten_evidence_row(row)
    shopify_oid = str(out.get("order.id") or "").strip()
    event_ext = str(out.get("event_external_id") or "").strip() or shopify_oid
    if not event_ext:
        return None

    raw_gross = out.get("shopify_gross")
    need_amount = raw_gross is None or raw_gross == ""
    shopify_gross: float | None = None
    if not need_amount:
        try:
            shopify_gross = round(float(raw_gross), 2)
        except (TypeError, ValueError):
            return None

    email = str(out.get("person.email") or "").strip()
    manago_id = str(out.get("manago_contact_id") or "").strip()
    if email and "***" in email:
        email = ""

    if not email or not manago_id or need_amount:
        from dataruns.models import Order

        # Resolve identity / missing amount from commerce order id (Shopify spine).
        # Never overwrite an already-bound mismatch shopify_gross (DCS SoT).
        lookup_id = shopify_oid or event_ext
        order = (
            Order.objects.filter(
                company=company,
                source=Order.Source.SHOPIFY,
                external_id=lookup_id,
            )
            .select_related("contact")
            .first()
        )
        if order is not None:
            if not email:
                email = str(order.contact.email or "").strip()
            if need_amount and order.amount is not None:
                try:
                    shopify_gross = round(float(order.amount), 2)
                    need_amount = False
                except (TypeError, ValueError):
                    pass
            if not manago_id and email and "***" not in email:
                manago = find_manago_contact(company, email=email)
                if manago:
                    manago_id = str(
                        manago.get("contactId") or manago.get("id") or ""
                    ).strip()

    if shopify_gross is None:
        return None

    if email and "***" in email:
        email = ""
    if not email and not manago_id:
        return None

    if email:
        out["person.email"] = email
    elif "person.email" in out and "***" in str(out.get("person.email") or ""):
        out.pop("person.email", None)
    if manago_id:
        out["manago_contact_id"] = manago_id
    out["side"] = "value_mismatch"
    out["order.id"] = shopify_oid or event_ext
    out["event_external_id"] = event_ext
    out["shopify_gross"] = shopify_gross
    return out


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


def _ci05_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """PRD-WB-15: missing_link_key only; bijection + email uniqueness recheck.

    Never invent sandbox rows. Driver tags (reused/dangling/coverage) are dropped.
    Resolves PII-masked emails via manago_contact_id; skips Shopify guest ids.

    When the latest DCS score predates WB-15 (no missing_link_key in provenance),
    rebuild candidates from live Contact DB using the same identity_join rules —
    not sandbox invent; identical emit criteria as a fresh score.
    """
    matched = _ci05_filter_missing_rows(
        company=company, rows=rows, max_rows=max_rows
    )
    if matched:
        return matched
    # Stale score / reused-only provenance: rebuild from live join.
    live_rows = _ci05_live_missing_link_key_rows(company=company, max_rows=max_rows)
    if not live_rows:
        return []
    return _ci05_filter_missing_rows(
        company=company, rows=live_rows, max_rows=max_rows
    )


def _ci03_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """PRD-WB-16: merge_candidate plan rows only; drop drivers.

    Never invent sandbox rows. When score provenance lacks merge_candidate
    (pre-WB-16 scores), rebuild from live identity_join.
    """
    matched = _ci03_filter_merge_rows(rows=rows, max_rows=max_rows)
    if matched:
        return matched
    live_rows = _ci03_live_merge_candidate_rows(company=company, max_rows=max_rows)
    if not live_rows:
        return []
    return _ci03_filter_merge_rows(rows=live_rows, max_rows=max_rows)


def _ci03_live_merge_candidate_rows(
    *,
    company: Company,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    from dataruns.dcs.identity_join import build_identity_snapshot
    from dataruns.dcs.pins import resolve_scoring_pins

    source_run_ids, pinned_snapshot_ids, _run = resolve_scoring_pins(company=company)
    identity = build_identity_snapshot(
        company=company,
        source_run_ids=source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    ).get("identity") or {}
    rows = identity.get("merge_candidates")
    if not isinstance(rows, list):
        return []
    out = [r for r in rows if isinstance(r, dict)]
    if max_rows is not None and max_rows >= 0:
        return out[:max_rows]
    return out


def _ci03_filter_merge_rows(
    *,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for row in rows:
        if _evidence_side(row) != "merge_candidate":
            continue
        out = _flatten_evidence_row(row)
        survivor = str(out.get("survivor_manago_id") or "").strip()
        if not survivor:
            continue
        losers = out.get("loser_manago_ids")
        if not isinstance(losers, list) or not any(str(x or "").strip() for x in losers):
            continue
        matched.append(out)
        if max_rows is not None and max_rows >= 0 and len(matched) >= max_rows:
            break
    return matched


def _cc01_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """PRD-WB-17 Phase A: out_in / in_out plan rows with proposed_action.

    Never invent sandbox rows. When score provenance lacks enrich fields,
    rebuild from pinned consent_join mismatch list.
    """
    matched = _cc01_filter_plan_rows(company=company, rows=rows, max_rows=max_rows)
    if matched:
        return matched
    live_rows = _cc01_live_mismatch_rows(company=company, max_rows=max_rows)
    if not live_rows:
        return []
    return _cc01_filter_plan_rows(company=company, rows=live_rows, max_rows=max_rows)


def _cc01_live_mismatch_rows(
    *,
    company: Company,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    from dataruns.dcs.consent_join import build_consent_snapshot
    from dataruns.dcs.pins import resolve_scoring_pins

    source_run_ids, pinned_snapshot_ids, _run = resolve_scoring_pins(company=company)
    snap = build_consent_snapshot(
        company=company,
        source_run_ids=source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    raw = snap.get("consent_mismatch_email")
    if not isinstance(raw, list):
        raw = []
    out: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        q = str(r.get("email_quadrant") or "").strip()
        if q not in ("out_in", "in_out"):
            continue
        opted = r.get("optedOut")
        out.append(
            {
                "side": q,
                "person.email": r.get("person.email"),
                "shopify_customer_id": r.get("shopify_customer_id"),
                "manago_contact_id": r.get("manago_contact_id"),
                "channel": "email",
                "shopify_email_opt_in_level": r.get("shopify_email_opt_in_level"),
                "shopify_email_consent_updated_at": r.get(
                    "shopify_email_consent_updated_at"
                ),
                "manago_modified_on": r.get("modified_on"),
                "provenance_ok": r.get("provenance_ok"),
                "provenance_weak": r.get("provenance_weak"),
                "provenance_note": r.get("provenance_note"),
                "optedOut": opted,
                "prior_optedOut": opted,
                "manago_email_in": r.get("manago_email_in"),
                "shopify_email_in": r.get("shopify_email_in"),
                "link_kind": r.get("link_kind"),
            }
        )
        if max_rows is not None and max_rows >= 0 and len(out) >= max_rows:
            break
    return out


def _cc01_evidence_gate_pass(row: dict[str, Any]) -> tuple[bool, str]:
    """PRD-WB-17 §2.1 / §5.2 — any alternate proof unlocks FORCE_OPT_IN."""
    if row.get("provenance_ok") is True:
        return True, "provenance_ok"
    evidence = str(row.get("klints_consent_evidence") or "").strip()
    if evidence == "shopify_verified":
        return True, "klints_consent_evidence"
    level = str(row.get("shopify_email_opt_in_level") or "").strip()
    ts = row.get("shopify_email_consent_updated_at")
    if level and level.lower() not in ("", "unknown") and ts:
        return True, "shopify_opt_in_level+ts"
    return False, "fail"


def _cc01_filter_plan_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for row in rows:
        side = _evidence_side(row)
        if side not in ("out_in", "in_out"):
            continue
        out = _flatten_evidence_row(row)
        out["side"] = side
        email = str(out.get("person.email") or "").strip()
        if "@" not in email:
            continue
        if "prior_optedOut" not in out and "optedOut" in out:
            out["prior_optedOut"] = out.get("optedOut")

        # Transform-time CC-03 stamp lookup for in_out gate.
        if side == "in_out" and not out.get("klints_consent_evidence"):
            manago = find_manago_contact(
                company,
                email=email,
                contact_id=str(out.get("manago_contact_id") or "").strip() or None,
            )
            if manago:
                stamp = contact_detail_value(manago, "klints_consent_evidence")
                if stamp:
                    out["klints_consent_evidence"] = stamp

        if side == "out_in":
            out["proposed_action"] = "FORCE_OPT_OUT"
            out["evidence_gate"] = "opt_out_wins"
        else:
            ok, gate = _cc01_evidence_gate_pass(out)
            if ok:
                out["proposed_action"] = "FORCE_OPT_IN"
                out["evidence_gate"] = gate
            else:
                out["proposed_action"] = "SKIP_UNEVIDENCED"
                out["evidence_gate"] = "fail"

        matched.append(out)
        if max_rows is not None and max_rows >= 0 and len(matched) >= max_rows:
            break
    return matched


def _cc02_evidence_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """PRD-WB-18 Phase A: SMS out_in / in_out plan rows with proposed_action."""
    matched = _cc02_filter_plan_rows(company=company, rows=rows, max_rows=max_rows)
    if matched:
        return matched
    live_rows = _cc02_live_mismatch_rows(company=company, max_rows=max_rows)
    if not live_rows:
        return []
    return _cc02_filter_plan_rows(company=company, rows=live_rows, max_rows=max_rows)


def _cc02_live_mismatch_rows(
    *,
    company: Company,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    from dataruns.dcs.consent_join import build_consent_snapshot
    from dataruns.dcs.pins import resolve_scoring_pins

    source_run_ids, pinned_snapshot_ids, _run = resolve_scoring_pins(company=company)
    snap = build_consent_snapshot(
        company=company,
        source_run_ids=source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    raw = snap.get("consent_mismatch_sms")
    if not isinstance(raw, list):
        raw = []
    out: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        q = str(r.get("sms_quadrant") or "").strip()
        if q not in ("out_in", "in_out"):
            continue
        opted_phone = r.get("optedOutPhone")
        out.append(
            {
                "side": q,
                "person.email": r.get("person.email"),
                "person.phone": r.get("person.phone"),
                "phone_valid": r.get("phone_valid"),
                "shopify_customer_id": r.get("shopify_customer_id"),
                "manago_contact_id": r.get("manago_contact_id"),
                "channel": "sms",
                "shopify_sms_opt_in_level": r.get("shopify_sms_opt_in_level"),
                "shopify_sms_consent_updated_at": r.get(
                    "shopify_sms_consent_updated_at"
                ),
                "manago_modified_on": r.get("modified_on"),
                "provenance_ok": r.get("provenance_ok"),
                "provenance_weak": r.get("provenance_weak"),
                "provenance_note": r.get("provenance_note"),
                "optedOutPhone": opted_phone,
                "prior_optedOutPhone": opted_phone,
                "manago_sms_in": r.get("manago_sms_in"),
                "shopify_sms_in": r.get("shopify_sms_in"),
                "link_kind": r.get("link_kind"),
            }
        )
        if max_rows is not None and max_rows >= 0 and len(out) >= max_rows:
            break
    return out


def _cc02_evidence_gate_pass(row: dict[str, Any]) -> tuple[bool, str]:
    """PRD-WB-18 §2 — SMS fields only (not email opt_in_level)."""
    if row.get("provenance_ok") is True:
        return True, "provenance_ok"
    evidence = str(row.get("klints_consent_evidence") or "").strip()
    if evidence == "shopify_verified":
        return True, "klints_consent_evidence"
    level = str(row.get("shopify_sms_opt_in_level") or "").strip()
    ts = row.get("shopify_sms_consent_updated_at")
    if level and level.lower() not in ("", "unknown") and ts:
        return True, "shopify_sms_opt_in_level+ts"
    return False, "fail"


def _cc02_filter_plan_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for row in rows:
        out = _flatten_evidence_row(row)
        # PRD-WB-18 lock 15: side from sms_quadrant only — never email_quadrant.
        sms_q = str(out.get("sms_quadrant") or "").strip()
        channel = str(out.get("channel") or "").strip().lower()
        if sms_q:
            if sms_q not in ("out_in", "in_out"):
                continue
            side = sms_q
        elif channel == "sms":
            side = _evidence_side(out) or _evidence_side(row)
            if side not in ("out_in", "in_out"):
                continue
        else:
            # Missing SMS identity (email-only / unreachable / mixed) — never plan.
            continue
        out["side"] = side
        out["channel"] = "sms"
        email = str(out.get("person.email") or "").strip()
        if "@" not in email:
            continue
        if "prior_optedOutPhone" not in out and "optedOutPhone" in out:
            out["prior_optedOutPhone"] = out.get("optedOutPhone")

        if side == "in_out" and not out.get("klints_consent_evidence"):
            manago = find_manago_contact(
                company,
                email=email,
                contact_id=str(out.get("manago_contact_id") or "").strip() or None,
            )
            if manago:
                stamp = contact_detail_value(manago, "klints_consent_evidence")
                if stamp:
                    out["klints_consent_evidence"] = stamp

        if side == "out_in":
            out["proposed_action"] = "FORCE_PHONE_OPT_OUT"
            out["evidence_gate"] = "opt_out_wins"
        else:
            ok, gate = _cc02_evidence_gate_pass(out)
            if ok:
                out["proposed_action"] = "FORCE_PHONE_OPT_IN"
                out["evidence_gate"] = gate
            else:
                out["proposed_action"] = "SKIP_UNEVIDENCED"
                out["evidence_gate"] = "fail"

        matched.append(out)
        if max_rows is not None and max_rows >= 0 and len(matched) >= max_rows:
            break
    return matched


def _ci05_live_missing_link_key_rows(
    *,
    company: Company,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Same emit as identity_join._missing_link_key_rows against pinned DCS snap."""
    from dataruns.dcs.identity_join import build_identity_snapshot
    from dataruns.dcs.pins import resolve_scoring_pins

    source_run_ids, pinned_snapshot_ids, _run = resolve_scoring_pins(company=company)
    identity = build_identity_snapshot(
        company=company,
        source_run_ids=source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    ).get("identity") or {}
    rows = identity.get("missing_link_key")
    if not isinstance(rows, list):
        return []
    out = [r for r in rows if isinstance(r, dict)]
    if max_rows is not None and max_rows >= 0:
        return out[:max_rows]
    return out


def _ci05_filter_missing_rows(
    *,
    company: Company,
    rows: list[dict[str, Any]],
    max_rows: int | None,
) -> list[dict[str, Any]]:
    from dataruns.dcs.identity_join import (
        _is_guest_contact,
        _load_platform_contacts,
        normalize_email,
    )
    from dataruns.dcs.pins import resolve_scoring_pins

    source_run_ids, pinned_snapshot_ids, _run = resolve_scoring_pins(company=company)
    # Same pinned universe as CI-* scoring (not Contact DB ghosts / newer snaps).
    manago_rows, _ = _load_platform_contacts(
        company=company,
        platform="manago_ai",
        source_run_id=(source_run_ids or {}).get("manago_ai"),
        snapshot_id=(pinned_snapshot_ids or {}).get("manago_ai"),
    )
    shopify_rows_raw, _ = _load_platform_contacts(
        company=company,
        platform="shopify",
        source_run_id=(source_run_ids or {}).get("shopify"),
        snapshot_id=(pinned_snapshot_ids or {}).get("shopify"),
    )
    manago_by_id = {
        str(r.get("external_id") or "").strip(): r
        for r in manago_rows
        if str(r.get("external_id") or "").strip()
    }
    existing_links = {
        str(r.get("link_key") or "").strip()
        for r in manago_rows
        if str(r.get("link_key") or "").strip()
    }
    manago_email_rows = [str(r.get("email") or "") for r in manago_rows]
    shopify_rows = [
        {"email": r.get("email"), "external_id": r.get("external_id")}
        for r in shopify_rows_raw
    ]
    claimed: set[str] = set()
    matched: list[dict[str, Any]] = []
    for row in rows:
        if _evidence_side(row) != "missing_link_key":
            continue
        out = _flatten_evidence_row(row)
        manago_id = str(out.get("manago_contact_id") or "").strip()
        shopify_id = str(out.get("shopify_customer_id") or "").strip()
        if not manago_id or not shopify_id:
            continue
        if _is_guest_contact(shopify_id):
            continue

        contact = manago_by_id.get(manago_id)
        if contact is None:
            continue
        if str(contact.get("link_key") or "").strip():
            continue
        raw_email = str(contact.get("email") or "").strip()
        if not raw_email:
            continue
        out["person.email"] = raw_email
        email_norm = normalize_email(raw_email)

        manago_n = sum(
            1 for e in manago_email_rows if normalize_email(e) == email_norm
        )
        if manago_n != 1:
            continue
        shopify_matches = [
            r
            for r in shopify_rows
            if normalize_email(r.get("email")) == email_norm
            and not _is_guest_contact(str(r.get("external_id") or ""))
        ]
        if len(shopify_matches) != 1:
            continue
        live_shopify_id = str(shopify_matches[0].get("external_id") or "").strip()
        if not live_shopify_id:
            continue
        if live_shopify_id != shopify_id:
            shopify_id = live_shopify_id
            out["shopify_customer_id"] = shopify_id
        if shopify_id in existing_links or shopify_id in claimed:
            continue

        out.setdefault("prior_external_id", "")
        claimed.add(shopify_id)
        matched.append(out)
        if max_rows is not None and max_rows >= 0 and len(matched) >= max_rows:
            break
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
        from dataruns.dcs.lifecycle_join import _connector_raw_for_platform
        from dataruns.dcs.pins import resolve_scoring_pins
    except Exception:
        return None

    source_run_ids, pinned_snapshot_ids, _run = resolve_scoring_pins(company=company)
    raw = _connector_raw_for_platform(
        company=company,
        platform="shopify",
        source_run_id=(source_run_ids or {}).get("shopify"),
        snapshot_id=(pinned_snapshot_ids or {}).get("shopify"),
    )
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
            rollback_strategy=rollback_strategy,
        )

    try:
        payload, before, after, rollback = _build_payload_and_state(
            company=company,
            check_id=check_id,
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
            rollback_strategy=rollback_strategy,
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

    if op_kind == "event_correct" and not str(
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

    # PRD-WB-17 / WB-18: SKIP_UNEVIDENCED in Preview/Download but never Ready.
    # PRD-WB-19: SKIP_NEEDS_CONTRACT never Ready.
    proposed = str(
        (payload or {}).get("proposed_action")
        or fields.get("proposed_action")
        or context.get("proposed_action")
        or ""
    ).strip()
    if (
        str(check_id or "").strip().upper() in {"CC-01", "CC-02"}
        and proposed == "SKIP_UNEVIDENCED"
    ):
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
            status="skipped",
            error_reason="skip_unevidenced",
            capability_id=str(capability_id) if capability_id else None,
            rollback_strategy=rollback_strategy,
        )
    if (
        str(check_id or "").strip().upper() == "SP-03"
        and proposed == "SKIP_NEEDS_CONTRACT"
    ):
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
            status="skipped",
            error_reason="skip_needs_contract",
            capability_id=str(capability_id) if capability_id else None,
            rollback_strategy=rollback_strategy,
        )
    if str(check_id or "").strip().upper() == "PT-03":
        gate = str(
            fields.get("evidence_gate")
            or context.get("evidence_gate")
            or ""
        ).strip()
        if proposed == "ARCHIVE_FLAG" and gate == "archive_semantics_unknown":
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
                status="skipped",
                error_reason="archive_semantics_unknown",
                capability_id=str(capability_id) if capability_id else None,
                rollback_strategy=rollback_strategy,
            )
        if gate == "needs_catalog_id":
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
                status="skipped",
                error_reason="needs_catalog_id",
                capability_id=str(capability_id) if capability_id else None,
                rollback_strategy=rollback_strategy,
            )

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
    check_id: str = "",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    # PRD-WB-17 / WB-18 Phase A: plan payload — do not use bare contact_upsert.
    check_norm = str(check_id or "").strip().upper()
    if (
        check_norm == "CC-01"
        and op_kind == "contact_upsert"
        and target == "manago"
    ):
        return _cc01_plan_payload(fields=fields, entity_key=entity_key, context=context)
    if (
        check_norm == "CC-02"
        and op_kind == "contact_upsert"
        and target == "manago"
    ):
        return _cc02_plan_payload(fields=fields, entity_key=entity_key, context=context)
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
    if op_kind == "event_correct" and target == "manago":
        payload, before, after, rollback = _event_correct_payload(
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
    if op_kind == "contact_merge" and target == "manago":
        return _contact_merge_plan_payload(
            fields=fields,
            entity_key=entity_key,
        )
    if op_kind == "product_upsert" and target == "manago":
        return _product_upsert_payload(fields=fields, entity_key=entity_key, context=context)
    raise ValueError(f"unsupported_op_kind:{op_kind}")


def _product_upsert_payload(
    *,
    fields: dict[str, Any],
    entity_key: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """PRD-WB-20 — Manago product upsert wire body (no proposed_action on wire)."""
    product_id = str(
        fields.get("product_id") or entity_key or context.get("product_id") or ""
    ).strip()
    proposed = str(
        fields.get("proposed_action") or context.get("proposed_action") or ""
    ).strip()
    name = fields.get("name")
    if name is None:
        name = context.get("shopify_title")
    sku = fields.get("sku")
    if sku is None:
        sku = context.get("shopify_sku")
    catalog_id = fields.get("catalog_id") or context.get("catalog_id")
    active = True
    if proposed == "ARCHIVE_FLAG":
        active = False
    product: dict[str, Any] = {
        "productId": product_id or None,
        "name": (str(name).strip() if name not in (None, "") else None),
        "sku": (str(sku).strip() if sku not in (None, "") else None),
        "active": active,
    }
    product = {k: v for k, v in product.items() if v is not None}
    payload: dict[str, Any] = {
        "product": product,
        "catalogId": str(catalog_id).strip() if catalog_id else None,
        # Klints-only (stripped before Manago HTTP) — drives skip/ready gates.
        "proposed_action": proposed,
    }
    payload = {k: v for k, v in payload.items() if v is not None or k == "product"}
    before = {
        "productId": product_id,
        "active": context.get("manago_active"),
        "name": context.get("manago_name"),
    }
    after = {"productId": product_id, "active": active, "name": product.get("name")}
    rollback = dict(before)
    return payload, before, after, rollback


def _contact_merge_plan_payload(
    *,
    fields: dict[str, Any],
    entity_key: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """PRD-WB-16 Phase A: plan payload only — no Manago mutate."""
    survivor = str(
        fields.get("survivor_manago_id") or entity_key or ""
    ).strip()
    losers_raw = fields.get("loser_manago_ids")
    if isinstance(losers_raw, list):
        losers = [str(x or "").strip() for x in losers_raw if str(x or "").strip()]
    elif losers_raw:
        losers = [str(losers_raw).strip()]
    else:
        losers = []
    payload: dict[str, Any] = {
        "mode": "plan",
        "survivor_id": survivor,
        "loser_ids": losers,
        "safety_class": str(fields.get("safety_class") or "").strip(),
        "safety_reason": str(fields.get("safety_reason") or "").strip(),
        "cluster_kind": str(fields.get("cluster_kind") or "").strip(),
        "cluster_key": str(fields.get("cluster_key") or "").strip(),
        "email": str(fields.get("email") or "").strip(),
        "link_key": str(fields.get("link_key") or "").strip(),
    }
    before = {
        "survivor_id": survivor,
        "loser_ids": losers,
        "mode": "plan",
    }
    after = dict(payload)
    rollback: dict[str, Any] = {"strategy": "none"}
    return payload, before, after, rollback


def _cc01_plan_payload(
    *,
    fields: dict[str, Any],
    entity_key: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """PRD-WB-17 Phase A: consent reconcile plan — no Manago mutate."""
    email = str(
        fields.get("email")
        or context.get("person.email")
        or entity_key
        or ""
    ).strip()
    contact_id = str(
        fields.get("contact_id") or context.get("manago_contact_id") or ""
    ).strip()
    proposed = str(fields.get("proposed_action") or context.get("proposed_action") or "").strip()
    gate = str(fields.get("evidence_gate") or context.get("evidence_gate") or "").strip()
    prior = fields.get("prior_optedOut")
    if prior is None:
        prior = context.get("prior_optedOut", context.get("optedOut"))
    side = str(context.get("side") or "").strip()
    payload: dict[str, Any] = {
        "mode": "plan",
        "email": email,
        "contactId": contact_id or None,
        "side": side,
        "proposed_action": proposed,
        "evidence_gate": gate,
        "prior_optedOut": prior,
        "shopify_customer_id": str(
            fields.get("shopify_customer_id") or context.get("shopify_customer_id") or ""
        ).strip()
        or None,
    }
    # Current Manago opt state vs proposed reconcile — must differ so FORCE_* stay Ready.
    before = {
        "mode": "plan",
        "email": email,
        "prior_optedOut": prior,
    }
    after = dict(payload)
    rollback: dict[str, Any] = {"strategy": "none"}
    return payload, before, after, rollback


def _cc02_plan_payload(
    *,
    fields: dict[str, Any],
    entity_key: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """PRD-WB-18 Phase A: SMS consent reconcile plan — no Manago mutate."""
    email = str(
        fields.get("email")
        or context.get("person.email")
        or entity_key
        or ""
    ).strip()
    contact_id = str(
        fields.get("contact_id") or context.get("manago_contact_id") or ""
    ).strip()
    proposed = str(fields.get("proposed_action") or context.get("proposed_action") or "").strip()
    gate = str(fields.get("evidence_gate") or context.get("evidence_gate") or "").strip()
    prior = fields.get("prior_optedOutPhone")
    if prior is None:
        prior = context.get("prior_optedOutPhone", context.get("optedOutPhone"))
    side = str(context.get("side") or "").strip()
    phone = str(
        fields.get("phone") or context.get("person.phone") or context.get("phone") or ""
    ).strip()
    payload: dict[str, Any] = {
        "mode": "plan",
        "email": email,
        "contactId": contact_id or None,
        "phone": phone or None,
        "side": side,
        "proposed_action": proposed,
        "evidence_gate": gate,
        "prior_optedOutPhone": prior,
        "shopify_customer_id": str(
            fields.get("shopify_customer_id") or context.get("shopify_customer_id") or ""
        ).strip()
        or None,
    }
    before = {
        "mode": "plan",
        "email": email,
        "prior_optedOutPhone": prior,
    }
    after = dict(payload)
    rollback: dict[str, Any] = {"strategy": "none"}
    return payload, before, after, rollback


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
    contact_id = str(fields.get("contact_id") or "").strip()
    db_record: dict[str, Any] = {
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
    if contact_id:
        payload["contactId"] = contact_id
    if mark_klints_backfill:
        props = payload.get("properties")
        if not isinstance(props, dict):
            props = {}
            payload["properties"] = props
        props.setdefault("klints_backfill", "true")
        payload["_mark_klints_backfill"] = True
    contact = find_manago_contact(
        company, email=email or None, contact_id=contact_id or None
    )
    prior_from_fields = fields.get("prior_external_id")
    prior_external = (
        ""
        if prior_from_fields is None
        else str(prior_from_fields)
    )
    if prior_from_fields is None and contact is not None:
        # Snapshot may store Shopify link as externalId (API) or link_key (DB shape).
        prior_external = str(
            contact.get("externalId")
            or contact.get("link_key")
            or ""
        )
    before = {
        "email": email,
        "present_in_manago": contact is not None,
        "externalId": prior_external,
        "contactId": contact_id
        or (contact or {}).get("contactId")
        or (contact or {}).get("id"),
    }
    after = dict(payload)
    rollback = {
        "email": email,
        "existed": contact is not None,
        "contactId": before.get("contactId"),
        "externalId": prior_external,
        "prior_external_id": prior_external,
    }
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


def _event_correct_payload(
    *,
    fields: dict[str, Any],
    entity_key: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Full-resend update for matched PURCHASE value (PRD-WB-14).

    ``externalId`` on the wire is the Manago event spine (``event_external_id``),
    which equals Shopify order.id only on externalId matches — not always.
    """
    event_ext = str(
        fields.get("order_id")
        or context.get("event_external_id")
        or entity_key
        or context.get("order.id")
        or ""
    )
    email = fields.get("email") or (entity_key if "@" in str(entity_key) else None)
    contact_id = fields.get("contact_id")
    value = fields.get("value")
    if value is None:
        value = context.get("shopify_gross")
    try:
        value = round(float(value), 2)
    except (TypeError, ValueError):
        value = fields.get("value")
    prior_value = fields.get("prior_value")
    if prior_value is None:
        prior_value = context.get("manago_value")

    payload: dict[str, Any] = {
        "externalId": event_ext,
        "contactExtEventType": "PURCHASE",
        "value": value,
    }
    if email:
        payload["email"] = str(email)
    if contact_id:
        payload["contactId"] = str(contact_id)

    # Full resend: include date (Manago ms) + currency when known.
    occurred = fields.get("occurred_at") or context.get("occurred_at")
    date_ms = _occurred_at_to_manago_ms(occurred)
    if date_ms is not None:
        payload["date"] = date_ms
    currency = fields.get("currency") or context.get("currency")
    if currency:
        payload["currency"] = str(currency)

    before = {
        "externalId": event_ext,
        "value": prior_value,
        "contactExtEventType": "PURCHASE",
    }
    after = dict(payload)
    rollback = {"externalId": event_ext, "prior_value": prior_value}
    return payload, before, after, rollback


def _occurred_at_to_manago_ms(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # Already ms or seconds — treat large ints as ms.
        n = int(value)
        return n if n > 10_000_000_000 else n * 1000
    text = str(value).strip()
    if not text:
        return None
    try:
        from datetime import datetime, timezone

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (TypeError, ValueError):
        return None
