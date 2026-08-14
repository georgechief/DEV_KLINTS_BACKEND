"""Read Manago contact state from latest connector snapshot for dry-run before/after."""

from __future__ import annotations

from typing import Any

from dataruns.architecture.inventory import _latest_manago_snapshot_data, _snapshot_raw_block
from dataruns.dcs.segment_join import _iter_detail_pairs, _iter_tags
from tenants.models import Company


def _snapshot_contacts(company: Company) -> list[dict[str, Any]]:
    snapshot_data = _latest_manago_snapshot_data(company)
    if not snapshot_data:
        return []
    contacts = snapshot_data.get("contacts")
    if isinstance(contacts, list) and contacts:
        return [c for c in contacts if isinstance(c, dict)]
    raw = _snapshot_raw_block(snapshot_data)
    contacts = raw.get("contacts")
    if isinstance(contacts, list):
        return [c for c in contacts if isinstance(c, dict)]
    return []


def find_manago_contact(
    company: Company,
    *,
    email: str | None = None,
    contact_id: str | None = None,
) -> dict[str, Any] | None:
    email_norm = (email or "").strip().lower()
    contact_id_norm = (contact_id or "").strip()
    for contact in _snapshot_contacts(company):
        cid = str(contact.get("contactId") or contact.get("id") or "")
        row_email = str(contact.get("email") or "").strip().lower()
        if contact_id_norm and cid == contact_id_norm:
            return contact
        if email_norm and row_email == email_norm:
            return contact
    return None


def contact_detail_value(contact: dict[str, Any], detail_key: str) -> Any:
    for key, value in _iter_detail_pairs(contact):
        if key == detail_key:
            return value
    return None


def contact_has_tag(contact: dict[str, Any], tag: str) -> bool:
    return tag in _iter_tags(contact)
