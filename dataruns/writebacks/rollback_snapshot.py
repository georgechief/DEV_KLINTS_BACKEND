"""Refresh rollback snapshots from latest snapshot before mutate."""

from __future__ import annotations

from dataruns.writebacks.snapshot import (
    contact_detail_value,
    contact_has_tag,
    find_manago_contact,
)
from dataruns.writebacks.types import WriteIntent
from tenants.models import Company


def refresh_rollback_snapshot(company: Company, intent: WriteIntent) -> None:
    """Capture live-ish state immediately before execute (PRD-WB-01 §10.1)."""
    payload = intent.payload or {}
    email = str(payload.get("email") or "").strip() or None
    contact_id = str(payload.get("contactId") or "").strip() or None
    contact = find_manago_contact(company, email=email, contact_id=contact_id)

    if intent.op_kind == "detail_set":
        props = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
        detail_key = next(iter(props.keys()), "")
        intent.rollback_snapshot = {
            detail_key: contact_detail_value(contact, detail_key) if contact else None,
        }
        return

    if intent.op_kind == "tag_add":
        tag = str(payload.get("tag") or "")
        intent.rollback_snapshot = {
            "tag": tag,
            "present": contact_has_tag(contact, tag) if contact else False,
        }
        return

    if intent.op_kind == "contact_upsert":
        intent.rollback_snapshot = {
            "email": email or intent.entity_key,
            "existed": contact is not None,
            "contactId": (contact or {}).get("contactId") or (contact or {}).get("id"),
        }
        return

    if intent.op_kind == "event_ingest":
        intent.rollback_snapshot = {
            "externalId": str(payload.get("externalId") or ""),
            "event_exists": False,
        }
