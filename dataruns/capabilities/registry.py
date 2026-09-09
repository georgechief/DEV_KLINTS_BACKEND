"""Capability Matrix registry loader (PRD-CAP-01 Step 3).

File-only v1 — reads committed matrix_seed.json. No DB overlay.
Writebacks stay on dataruns/writebacks/capabilities.py (option B).
"""

from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from dataruns.capabilities.contract import (
    CAPABILITY_RECORD_SCHEMA_VERSION,
    CAP_MODE_ENUM,
    CAP_STATUS_ENUM,
    MATRIX_PACK_SOURCE,
    MATRIX_SEED_REL,
    SEED_ROW_REQUIRED_FIELDS,
)

_SEED_FILENAME = "matrix_seed.json"
_SEED_PATH = Path(__file__).resolve().parent / _SEED_FILENAME


class MatrixSeedError(ValueError):
    """Committed seed is missing or malformed."""


def matrix_seed_path() -> Path:
    """Runtime path to committed seed (Docker-safe; next to this package)."""
    return _SEED_PATH


@lru_cache(maxsize=1)
def _load_seed_envelope() -> dict[str, Any]:
    path = matrix_seed_path()
    if not path.is_file():
        raise MatrixSeedError(f"Matrix seed not found: {MATRIX_SEED_REL}")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise MatrixSeedError("Matrix seed root must be an object")
    caps = data.get("capabilities")
    if not isinstance(caps, list):
        raise MatrixSeedError("Matrix seed capabilities must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(caps):
        if not isinstance(row, dict):
            raise MatrixSeedError(f"capabilities[{idx}] must be an object")
        missing = SEED_ROW_REQUIRED_FIELDS - set(row.keys())
        if missing:
            raise MatrixSeedError(
                f"capabilities[{idx}] missing fields: {sorted(missing)}"
            )
        cap_id = str(row.get("capability_id") or "").strip()
        if not cap_id:
            raise MatrixSeedError(f"capabilities[{idx}] missing capability_id")
        if cap_id in by_id:
            raise MatrixSeedError(f"Duplicate capability_id in seed: {cap_id}")
        status = str(row.get("status") or "").strip().upper()
        if status not in CAP_STATUS_ENUM:
            raise MatrixSeedError(
                f"capabilities[{idx}] ({cap_id}) invalid status: {row.get('status')!r}"
            )
        mode = str(row.get("mode") or "").strip().upper()
        if mode not in CAP_MODE_ENUM:
            raise MatrixSeedError(
                f"capabilities[{idx}] ({cap_id}) invalid mode: {row.get('mode')!r}"
            )
        evidence = row.get("evidence")
        if not isinstance(evidence, list):
            raise MatrixSeedError(
                f"capabilities[{idx}] ({cap_id}) evidence must be a list"
            )
        # Normalize enum casing in-memory so lookups stay consistent.
        row = {**row, "capability_id": cap_id, "status": status, "mode": mode}
        by_id[cap_id] = row
    declared_count = data.get("count")
    if declared_count is not None and int(declared_count) != len(by_id):
        raise MatrixSeedError(
            f"Matrix seed count {declared_count!r} != capabilities length {len(by_id)}"
        )
    return {
        "schema_version": str(
            data.get("schema_version") or CAPABILITY_RECORD_SCHEMA_VERSION
        ),
        "source": str(data.get("source") or MATRIX_PACK_SOURCE),
        "generated_from": data.get("generated_from"),
        "count": len(by_id),
        "capabilities": list(by_id.values()),
        "_by_id": by_id,
    }


def clear_matrix_registry_cache() -> None:
    """Drop cached seed (tests / in-process regen)."""
    _load_seed_envelope.cache_clear()


def get_matrix_source() -> str:
    return str(_load_seed_envelope().get("source") or MATRIX_PACK_SOURCE)


def get_matrix_schema_version() -> str:
    return str(
        _load_seed_envelope().get("schema_version") or CAPABILITY_RECORD_SCHEMA_VERSION
    )


def get_capability(capability_id: str | None) -> dict[str, Any] | None:
    """
    PRD §4.1 — lookup one Matrix record by id.

    Returns a deep copy (callers must not mutate the cache).
    Unknown / empty id → None (fail closed for MCP route).
    Lookup is case-insensitive (seed ids are uppercase).
    """
    cap_id = str(capability_id or "").strip()
    if not cap_id:
        return None
    by_id = _load_seed_envelope()["_by_id"]
    row = by_id.get(cap_id)
    if row is None:
        row = by_id.get(cap_id.upper())
    if row is None:
        return None
    return deepcopy(row)


def list_capabilities(
    *,
    channel: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """
    List Matrix records (PRD §6 envelope shape).

    Optional filters: channel (exact), status (exact), q (substring on capability_id).
    """
    envelope = _load_seed_envelope()
    rows: list[dict[str, Any]] = [deepcopy(r) for r in envelope["capabilities"]]

    channel_f = str(channel or "").strip().upper()
    if channel_f:
        rows = [
            r
            for r in rows
            if str(r.get("channel") or "").strip().upper() == channel_f
        ]

    status_f = str(status or "").strip().upper()
    if status_f:
        rows = [
            r for r in rows if str(r.get("status") or "").strip().upper() == status_f
        ]

    q_f = str(q or "").strip().upper()
    if q_f:
        rows = [
            r
            for r in rows
            if q_f in str(r.get("capability_id") or "").strip().upper()
        ]

    return {
        "schema_version": envelope["schema_version"],
        "source": envelope["source"],
        "count": len(rows),
        "results": rows,
    }
