"""Load check → writeback mapping JSON (PRD-WB-01 §3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_MAPPINGS_DIR = Path(__file__).resolve().parent / "mappings"


class MappingNotFound(Exception):
    def __init__(self, check_id: str) -> None:
        self.check_id = check_id
        super().__init__(f"No writeback mapping for check {check_id}")


class MappingDisabled(Exception):
    def __init__(self, check_id: str) -> None:
        self.check_id = check_id
        super().__init__(f"Writeback mapping disabled for check {check_id}")


@dataclass(frozen=True)
class MappingListItem:
    check_id: str
    enabled: bool
    schema_version: str
    title: str
    template_id: str | None
    op_kinds: list[str]
    approval_tier: str | None


@lru_cache(maxsize=1)
def _load_registry() -> dict[str, Any]:
    path = _MAPPINGS_DIR / "registry.json"
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Invalid writeback registry.json")
    return data


def list_mapping_entries() -> list[dict[str, Any]]:
    registry = _load_registry()
    mappings = registry.get("mappings")
    if not isinstance(mappings, dict):
        return []

    entries = [
        {"check_id": check_id, **(meta if isinstance(meta, dict) else {})}
        for check_id, meta in mappings.items()
    ]
    known = {str(entry.get("check_id") or "").strip().upper() for entry in entries}
    for check_id, template_id in _automated_writeback_check_ids():
        if check_id and check_id not in known:
            stub: dict[str, Any] = {"check_id": check_id, "enabled": False}
            if template_id:
                stub["template_id"] = template_id
            entries.append(stub)
    return entries


def _automated_writeback_check_ids() -> list[tuple[str, str | None]]:
    try:
        from dataruns.models import CheckMaster

        rows = CheckMaster.objects.filter(
            fix_type__icontains="Automated writeback",
        ).values_list("check_id", "template_id")
        seen: dict[str, str | None] = {}
        for check_id, template_id in rows:
            if not check_id:
                continue
            normalized = str(check_id).strip().upper()
            template = str(template_id).strip() if template_id else None
            seen[normalized] = template
        return sorted(seen.items())
    except Exception:
        return []


def get_check_mapping(check_id: str) -> dict[str, Any]:
    normalized = (check_id or "").strip().upper()
    if not normalized:
        raise MappingNotFound(check_id)

    registry = _load_registry()
    mappings = registry.get("mappings")
    if not isinstance(mappings, dict):
        raise MappingNotFound(check_id)

    entry = mappings.get(normalized)
    if not isinstance(entry, dict):
        raise MappingNotFound(check_id)

    filename = entry.get("file")
    if not isinstance(filename, str) or not filename.strip():
        raise MappingNotFound(check_id)

    path = _MAPPINGS_DIR / filename
    with path.open(encoding="utf-8") as handle:
        spec = json.load(handle)
    if not isinstance(spec, dict):
        raise ValueError(f"Invalid mapping file {filename}")

    enabled = bool(entry.get("enabled", spec.get("enabled", False)))
    if not enabled:
        raise MappingDisabled(normalized)

    spec = dict(spec)
    spec["check_id"] = normalized
    if entry.get("template_id") and not spec.get("template_id"):
        spec["template_id"] = entry.get("template_id")
    return spec


def list_mappings() -> list[MappingListItem]:
    items: list[MappingListItem] = []
    for entry in list_mapping_entries():
        check_id = str(entry.get("check_id") or "").strip().upper()
        if not check_id:
            continue
        filename = entry.get("file")
        op_kinds: list[str] = []
        title = ""
        schema_version = "1.0.0"
        approval_tier = None
        if isinstance(filename, str) and filename:
            path = _MAPPINGS_DIR / filename
            if path.exists():
                with path.open(encoding="utf-8") as handle:
                    spec = json.load(handle)
                if isinstance(spec, dict):
                    title = str(spec.get("title") or "")
                    schema_version = str(spec.get("schema_version") or schema_version)
                    approval_tier = spec.get("approval_tier")
                    for op in spec.get("operations") or []:
                        if isinstance(op, dict) and isinstance(op.get("op_kind"), str):
                            op_kinds.append(op["op_kind"])
        items.append(
            MappingListItem(
                check_id=check_id,
                enabled=bool(entry.get("enabled")),
                schema_version=schema_version,
                title=title,
                template_id=entry.get("template_id"),
                op_kinds=op_kinds,
                approval_tier=approval_tier,
            )
        )
    return items
