"""Capability status gate (PRD-WB-01 §10.1)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_ALLOWED_EXECUTE = frozenset({"CONFIRMED_LIVE", "CONFIRMED_LIMITED"})
_CAPABILITIES_PATH = Path(__file__).resolve().parent / "capabilities.json"

_SUPPORTED_OP_KINDS = (
    "contact_upsert",
    "detail_set",
    "tag_add",
    "tag_remove",
    "contact_merge",
    "event_ingest",
    "event_update",
    "event_correct",
    "product_upsert",
    "coupon_sync",
    "consent_reconcile",
    "shopify_customer_update",
    "shopify_metafield_set",
    "erp_attribute_feed",
    "availability_gate",
)
_IMPLEMENTED_OP_KINDS = frozenset({"contact_upsert", "detail_set", "tag_add", "event_ingest"})


@lru_cache(maxsize=1)
def _load_capabilities() -> dict[str, Any]:
    with _CAPABILITIES_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    caps = data.get("capabilities") if isinstance(data, dict) else {}
    return caps if isinstance(caps, dict) else {}


def capability_status(capability_id: str | None) -> str | None:
    if not capability_id:
        return None
    row = _load_capabilities().get(capability_id)
    if not isinstance(row, dict):
        return None
    status = row.get("status")
    return str(status) if isinstance(status, str) else None


def capability_batch_max(capability_id: str | None) -> int | None:
    if not capability_id:
        return None
    row = _load_capabilities().get(capability_id)
    if not isinstance(row, dict):
        return None
    value = row.get("batch_max")
    return int(value) if isinstance(value, int) else None


def capability_allows_execute(capability_id: str | None) -> bool:
    status = capability_status(capability_id)
    if status is None:
        return False
    return status in _ALLOWED_EXECUTE


def list_supported_op_kinds() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind in _SUPPORTED_OP_KINDS:
        rows.append(
            {
                "op_kind": kind,
                "adapter_status": "implemented" if kind in _IMPLEMENTED_OP_KINDS else "stub",
            }
        )
    return rows
