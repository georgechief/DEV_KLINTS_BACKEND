"""Generate disabled writeback mapping stubs from CheckMaster (PRD-WB-01 §3)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_MAPPINGS_DIR = Path(__file__).resolve().parent / "mappings"
_REGISTRY_PATH = _MAPPINGS_DIR / "registry.json"

_TEMPLATE_META: dict[str, dict[str, str]] = {
    "T1": {"op_kind": "contact_upsert", "approval_tier": "batch"},
    "T2": {"op_kind": "contact_upsert", "approval_tier": "individual"},
    "T3": {"op_kind": "contact_merge", "approval_tier": "individual"},
    "T4": {"op_kind": "contact_upsert", "approval_tier": "batch"},
    "T5": {"op_kind": "event_ingest", "approval_tier": "batch"},
    "T6": {"op_kind": "event_correct", "approval_tier": "individual"},
    "T7": {"op_kind": "product_upsert", "approval_tier": "batch"},
    "T8": {"op_kind": "detail_set", "approval_tier": "individual"},
    "T9": {"op_kind": "tag_add", "approval_tier": "batch"},
    "T10": {"op_kind": "erp_attribute_feed", "approval_tier": "batch"},
    "T11": {"op_kind": "tag_add", "approval_tier": "batch"},
}

_DEFAULT_TEMPLATE = {"op_kind": "contact_upsert", "approval_tier": "batch"}


def slugify_check_id(check_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", check_id.strip().upper()).strip("_").lower()


def build_stub_spec(
    *,
    check_id: str,
    check_name: str,
    template_id: str | None,
) -> dict[str, Any]:
    template_key = (template_id or "").strip().upper()
    meta = _TEMPLATE_META.get(template_key, _DEFAULT_TEMPLATE)
    op_kind = meta["op_kind"]
    approval_tier = meta["approval_tier"]
    irreversible = op_kind in ("contact_merge", "event_ingest", "event_correct", "product_upsert")
    return {
        "schema_version": "1.0.0",
        "check_id": check_id.upper(),
        "template_id": template_key or None,
        "title": check_name or f"{check_id} writeback stub",
        "enabled": False,
        "approval_tier": approval_tier,
        "requires_consent_namespace_clean": check_id.upper().startswith("CC-"),
        "irreversible": irreversible,
        "operator_disclosure": (
            "Bulk automated writeback for this check is not enabled yet."
            if irreversible
            else None
        ),
        "rollback": {
            "strategy": "tagged_backfill_delete"
            if op_kind in ("contact_upsert", "event_ingest")
            else "revert_detail"
            if op_kind == "detail_set"
            else "remove_tag"
            if op_kind in ("tag_add", "tag_remove")
            else "restore_prior_field"
        },
        "operations": [],
    }


def stub_filename(check_id: str) -> str:
    return f"{check_id.upper()}.{slugify_check_id(check_id)}.stub.v1.json"


def load_registry() -> dict[str, Any]:
    with _REGISTRY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_registry(registry: dict[str, Any]) -> None:
    with _REGISTRY_PATH.open("w", encoding="utf-8") as handle:
        json.dump(registry, handle, indent=2)
        handle.write("\n")
