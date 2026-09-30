"""Sync Contact DB to a ConnectorSnapshot pin (soft tombstone ghosts).

Never hard-delete Contact rows — Order.contact is CASCADE.
"""

from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from dataruns.dcs.identity_join import (
    _contacts_from_snapshot_data,
)
from dataruns.models import Contact
from tenants.models import Company

logger = logging.getLogger(__name__)


def snapshot_has_contact_surface(
    *,
    snapshot_data: dict[str, Any] | None,
    platform: str,
) -> bool:
    """True when the snapshot explicitly carries a contacts/customers list.

    Prevents tombstoning the whole estate when snapshot_data is ``{}`` or
    missing the contact surface (load/parse failure).
    """
    if not isinstance(snapshot_data, dict):
        return False
    normalized = snapshot_data.get("normalized")
    if isinstance(normalized, dict) and isinstance(normalized.get("contacts"), list):
        return True
    raw = snapshot_data.get("raw")
    if not isinstance(raw, dict):
        # Some loaders nest under snapshot_data directly.
        raw = snapshot_data if "contacts" in snapshot_data or "customers" in snapshot_data else None
    if not isinstance(raw, dict):
        return False
    if platform == "manago_ai" and isinstance(raw.get("contacts"), list):
        return True
    if platform == "shopify" and isinstance(raw.get("customers"), list):
        return True
    return False


def contact_external_ids_from_snapshot(
    *,
    snapshot_data: dict[str, Any] | None,
    platform: str,
) -> set[str]:
    if not isinstance(snapshot_data, dict):
        return set()
    rows = _contacts_from_snapshot_data(snapshot_data=snapshot_data, platform=platform)
    return {
        str(r.get("external_id") or "").strip()
        for r in rows
        if str(r.get("external_id") or "").strip()
    }


def sync_contacts_to_snapshot(
    *,
    company: Company,
    platform: str,
    snapshot_data: dict[str, Any] | None,
    snapshot_id: str | None = None,
) -> dict[str, int]:
    """Tombstone Contact rows for ``platform`` not present in the snapshot.

    Also clears ``excluded`` on contacts that reappear in the pin.
    No-ops when the snapshot has no contact surface (avoids wipe on bad load).
    """
    if not snapshot_has_contact_surface(
        snapshot_data=snapshot_data, platform=platform
    ):
        logger.warning(
            "contact_sync skipped (no contact surface) company=%s platform=%s "
            "snapshot_id=%s",
            company.id,
            platform,
            snapshot_id,
        )
        return {"tombstoned": 0, "restored": 0, "live_ids": 0, "skipped": 1}

    live_ids = contact_external_ids_from_snapshot(
        snapshot_data=snapshot_data, platform=platform
    )

    now = timezone.now()
    qs = Contact.objects.filter(company=company, source=platform)

    # Restore previously excluded contacts that are back in the pin.
    restored = 0
    if live_ids:
        restored = qs.filter(excluded=True, external_id__in=live_ids).update(
            excluded=False, excluded_at=None
        )

    # Tombstone ghosts not in the pin (never hard-delete).
    # Empty live_ids with an explicit empty contact list = platform wiped.
    if live_ids:
        tombstoned = (
            qs.filter(excluded=False)
            .exclude(external_id__in=live_ids)
            .update(excluded=True, excluded_at=now)
        )
    else:
        tombstoned = qs.filter(excluded=False).update(excluded=True, excluded_at=now)

    logger.info(
        "contact_sync company=%s platform=%s snapshot_id=%s live=%s "
        "tombstoned=%s restored=%s",
        company.id,
        platform,
        snapshot_id,
        len(live_ids),
        tombstoned,
        restored,
    )
    return {
        "tombstoned": int(tombstoned),
        "restored": int(restored),
        "live_ids": len(live_ids),
        "skipped": 0,
    }
