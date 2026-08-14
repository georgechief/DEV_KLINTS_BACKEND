"""Shared connector field mapping — api_key ↔ db_key (PRD-WB-01 §2.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CONNECTORS_DIR = Path(__file__).resolve().parent
_SUPPORTED_PLATFORMS = frozenset({"shopify", "manago_ai"})


class UnmappedFieldError(ValueError):
    """Raised when a required db_key has no reverse mapping to api_key."""

    def __init__(self, db_key: str) -> None:
        self.db_key = db_key
        super().__init__(f"unmapped_field:{db_key}")


def load_connector_map(platform: str) -> dict[str, Any]:
    """Load ``connectors/{platform}/map.json``."""
    if platform not in _SUPPORTED_PLATFORMS:
        raise ValueError(f"Unknown platform: {platform}")
    map_path = _CONNECTORS_DIR / platform / "map.json"
    with map_path.open(encoding="utf-8") as map_file:
        data = json.load(map_file)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid map.json for platform {platform}.")
    return data


def mappings_for_entity(connector_map: dict[str, Any], entity: str) -> list[dict[str, str]]:
    key_mapping = connector_map.get("key_mapping")
    if not isinstance(key_mapping, list):
        return []
    return [
        row
        for row in key_mapping
        if isinstance(row, dict)
        and row.get("entity") == entity
        and isinstance(row.get("api_key"), str)
        and isinstance(row.get("db_key"), str)
    ]


def get_path(item: dict[str, Any], path: str) -> Any:
    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def set_path(item: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current: dict[str, Any] = item
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    current[parts[-1]] = value


def apply_status_map(value: Any, status_map: dict[str, Any] | None) -> Any:
    """Map inbound API status values to normalized db status (import)."""
    if not status_map:
        return value
    lookup = str(value)
    if lookup in status_map:
        return status_map[lookup]
    upper = lookup.upper()
    if upper in status_map:
        return status_map[upper]
    lower = lookup.lower()
    if lower in status_map:
        return status_map[lower]
    return value


def _invert_status_map(status_map: dict[str, Any] | None) -> dict[str, Any]:
    if not status_map:
        return {}
    inverted: dict[str, Any] = {}
    for api_value, db_value in status_map.items():
        key = str(db_value)
        if key not in inverted:
            inverted[key] = api_value
    return inverted


def apply_status_map_write(
    value: Any,
    *,
    status_map: dict[str, Any] | None,
    status_map_write: dict[str, Any] | None,
) -> Any:
    """Map db status back to API status (export / writeback)."""
    if status_map_write:
        lookup = str(value)
        if lookup in status_map_write:
            return status_map_write[lookup]
        lower = lookup.lower()
        if lower in status_map_write:
            return status_map_write[lower]
    inverted = _invert_status_map(status_map)
    lookup = str(value)
    if lookup in inverted:
        return inverted[lookup]
    return value


def map_api_to_db(
    item: dict[str, Any],
    mappings: list[dict[str, str]],
    status_map: dict[str, Any] | None,
) -> dict[str, Any]:
    """Inbound: connector API payload → canonical db_key record."""
    record: dict[str, Any] = {}
    for mapping in mappings:
        api_key = mapping["api_key"]
        db_key = mapping["db_key"]
        value = get_path(item, api_key)
        if value is None or value == "":
            continue
        if db_key == "status":
            value = apply_status_map(value, status_map)
            if value is None or value == "":
                continue
        record[db_key] = value
    return record


def map_db_to_api(
    record: dict[str, Any],
    mappings: list[dict[str, str]],
    *,
    status_map: dict[str, Any] | None = None,
    status_map_write: dict[str, Any] | None = None,
    required_db_keys: set[str] | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Outbound: canonical db_key record → connector API payload.

    ``extras`` are merged after reverse-map (api_key → value) and win on conflict.
  Unmapped required db_keys raise ``UnmappedFieldError``.
    """
    payload: dict[str, Any] = {}
    mapping_by_db = {row["db_key"]: row["api_key"] for row in mappings}

    keys_to_map = set(record.keys())
    if required_db_keys:
        keys_to_map |= required_db_keys

    for db_key in keys_to_map:
        if db_key not in record:
            if required_db_keys and db_key in required_db_keys:
                if db_key not in mapping_by_db:
                    raise UnmappedFieldError(db_key)
            continue
        value = record[db_key]
        if value is None or value == "":
            continue
        api_key = mapping_by_db.get(db_key)
        if api_key is None:
            if required_db_keys and db_key in required_db_keys:
                raise UnmappedFieldError(db_key)
            continue
        if db_key == "status":
            value = apply_status_map_write(
                value,
                status_map=status_map,
                status_map_write=status_map_write,
            )
            if value is None or value == "":
                continue
        set_path(payload, api_key, value)

    if extras:
        for api_key, value in extras.items():
            if value is None:
                continue
            set_path(payload, api_key, value)

    return payload


def reverse_map_record(
    record: dict[str, Any],
    *,
    platform: str,
    entity: str,
    required_db_keys: set[str] | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience: load map.json and reverse-map one entity record."""
    connector_map = load_connector_map(platform)
    mappings = mappings_for_entity(connector_map, entity)
    status_map = connector_map.get("status_map")
    if status_map is not None and not isinstance(status_map, dict):
        status_map = None
    status_map_write = connector_map.get("status_map_write")
    if status_map_write is not None and not isinstance(status_map_write, dict):
        status_map_write = None
    return map_db_to_api(
        record,
        mappings,
        status_map=status_map,
        status_map_write=status_map_write,
        required_db_keys=required_db_keys,
        extras=extras,
    )
