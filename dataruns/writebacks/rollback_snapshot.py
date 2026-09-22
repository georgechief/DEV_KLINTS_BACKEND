"""Refresh rollback snapshots from latest snapshot before mutate."""

from __future__ import annotations

from typing import Any

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
        rename = payload.get("_rename") if isinstance(payload.get("_rename"), dict) else None
        snapshot: dict[str, Any] = {}
        for detail_key in props.keys():
            if str(detail_key).startswith("_"):
                continue
            snapshot[str(detail_key)] = (
                contact_detail_value(contact, str(detail_key)) if contact else None
            )
        if rename:
            snapshot["rename"] = {
                **rename,
                "prior_from_value": (
                    contact_detail_value(contact, str(rename.get("from") or ""))
                    if contact
                    else rename.get("prior_from_value")
                ),
                "prior_to_value": (
                    contact_detail_value(contact, str(rename.get("to") or ""))
                    if contact
                    else rename.get("prior_to_value")
                ),
            }
        intent.rollback_snapshot = snapshot
        return

    if intent.op_kind == "tag_add":
        tag = str(payload.get("tag") or "")
        rename = payload.get("_rename") if isinstance(payload.get("_rename"), dict) else None
        snapshot = {
            "tag": tag,
            "present": contact_has_tag(contact, tag) if contact else False,
        }
        remove_tag = str(payload.get("_remove_tag") or "").strip()
        if remove_tag:
            snapshot["remove_tag"] = remove_tag
            snapshot["remove_present"] = (
                contact_has_tag(contact, remove_tag) if contact else False
            )
        if rename:
            snapshot["rename"] = {
                **rename,
                "prior_from_present": (
                    contact_has_tag(contact, str(rename.get("from") or ""))
                    if contact
                    else rename.get("prior_from_present")
                ),
                "prior_to_present": (
                    contact_has_tag(contact, str(rename.get("to") or ""))
                    if contact
                    else rename.get("prior_to_present")
                ),
            }
        intent.rollback_snapshot = snapshot
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
