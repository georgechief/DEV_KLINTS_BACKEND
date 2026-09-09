"""Load supplemental check master + UC↔gate map (DCS-09 Step 1).

File-only. Isolated from headline CheckMaster (42).
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dataruns.dcs.pilot_gates.contract import (
    ERP_SENSITIVE_CHECK_IDS,
    EXPECTED_SUPPLEMENTAL_CHECK_COUNT,
    GATE_CATALOG_VERSION,
    SEVERITY_ENUM,
    SUPPLEMENTAL_CHECK_IDS,
    SUPPLEMENTAL_CHECK_REQUIRED_FIELDS,
    SUPPLEMENTAL_GATE_MAP_REL,
    SUPPLEMENTAL_MASTER_REL,
    SUPPLEMENTAL_MASTER_SCHEMA_VERSION,
    SUPPLEMENTAL_PACK_SOURCE,
)
from dataruns.use_cases.constants import SUPPLEMENTAL_PREFLIGHT_CHECKS

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_MASTER_PATH = _PACKAGE_DIR / "check_master_supplemental_mvp1.json"
_GATE_MAP_PATH = _PACKAGE_DIR / "pilot_supplemental_gate_map.json"


class SupplementalMasterError(ValueError):
    """Committed supplemental master / gate map is missing or malformed."""


@dataclass(frozen=True)
class SupplementalCheckDefinition:
    check_id: str
    dimension: str
    title: str
    detection_logic: str
    systems: str
    severity: str
    required_by: tuple[str, ...]
    failure_behavior: str
    erp_sensitive: bool
    role: str = "PILOT_SUPPLEMENTAL"
    in_headline_score: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "dimension": self.dimension,
            "title": self.title,
            "detection_logic": self.detection_logic,
            "systems": self.systems,
            "severity": self.severity,
            "required_by": list(self.required_by),
            "failure_behavior": self.failure_behavior,
            "erp_sensitive": self.erp_sensitive,
            "role": self.role,
            "in_headline_score": self.in_headline_score,
        }


@dataclass(frozen=True)
class SupplementalCheckMaster:
    schema_version: str
    gate_catalog_version: str
    source: str
    count: int
    checks: tuple[SupplementalCheckDefinition, ...]

    def by_id(self) -> dict[str, SupplementalCheckDefinition]:
        return {c.check_id: c for c in self.checks}

    def check_ids(self) -> set[str]:
        return {c.check_id for c in self.checks}


def supplemental_master_path() -> Path:
    return _MASTER_PATH


def supplemental_gate_map_path() -> Path:
    return _GATE_MAP_PATH


def _parse_check_row(row: dict[str, Any], *, idx: int) -> SupplementalCheckDefinition:
    missing = SUPPLEMENTAL_CHECK_REQUIRED_FIELDS - set(row.keys())
    if missing:
        raise SupplementalMasterError(
            f"checks[{idx}] missing fields: {sorted(missing)}"
        )
    check_id = str(row.get("check_id") or "").strip().upper()
    if not check_id:
        raise SupplementalMasterError(f"checks[{idx}] missing check_id")
    if check_id not in SUPPLEMENTAL_CHECK_IDS:
        raise SupplementalMasterError(
            f"checks[{idx}] unknown supplemental id: {check_id!r}"
        )
    required_by = row.get("required_by")
    if not isinstance(required_by, list) or not required_by:
        raise SupplementalMasterError(
            f"checks[{idx}] ({check_id}) required_by must be a non-empty list"
        )
    severity = str(row.get("severity") or "").strip()
    if severity not in SEVERITY_ENUM:
        raise SupplementalMasterError(
            f"checks[{idx}] ({check_id}) invalid severity: {severity!r}"
        )
    if bool(row.get("in_headline_score")):
        raise SupplementalMasterError(
            f"checks[{idx}] ({check_id}) must have in_headline_score=false"
        )
    erp_sensitive = bool(row.get("erp_sensitive"))
    expected_erp = check_id in ERP_SENSITIVE_CHECK_IDS
    if erp_sensitive != expected_erp:
        raise SupplementalMasterError(
            f"checks[{idx}] ({check_id}) erp_sensitive={erp_sensitive} "
            f"but contract expects {expected_erp}"
        )
    required_tuple = tuple(
        str(u).strip().upper() for u in required_by if str(u).strip()
    )
    if not required_tuple:
        raise SupplementalMasterError(
            f"checks[{idx}] ({check_id}) required_by empty after normalize"
        )
    return SupplementalCheckDefinition(
        check_id=check_id,
        dimension=str(row.get("dimension") or "").strip(),
        title=str(row.get("title") or "").strip(),
        detection_logic=str(row.get("detection_logic") or "").strip(),
        systems=str(row.get("systems") or "").strip(),
        severity=severity,
        required_by=required_tuple,
        failure_behavior=str(row.get("failure_behavior") or "").strip(),
        erp_sensitive=erp_sensitive,
        role=str(row.get("role") or "PILOT_SUPPLEMENTAL").strip(),
        in_headline_score=False,
    )


@lru_cache(maxsize=1)
def _load_master() -> SupplementalCheckMaster:
    path = supplemental_master_path()
    if not path.is_file():
        raise SupplementalMasterError(f"Supplemental master not found: {SUPPLEMENTAL_MASTER_REL}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SupplementalMasterError("Supplemental master root must be an object")
    checks_raw = data.get("checks")
    if not isinstance(checks_raw, list):
        raise SupplementalMasterError("Supplemental master checks must be a list")
    parsed: list[SupplementalCheckDefinition] = []
    seen: set[str] = set()
    for idx, row in enumerate(checks_raw):
        if not isinstance(row, dict):
            raise SupplementalMasterError(f"checks[{idx}] must be an object")
        item = _parse_check_row(row, idx=idx)
        if item.check_id in seen:
            raise SupplementalMasterError(f"Duplicate check_id: {item.check_id}")
        seen.add(item.check_id)
        parsed.append(item)
    if len(parsed) != EXPECTED_SUPPLEMENTAL_CHECK_COUNT:
        raise SupplementalMasterError(
            f"Expected {EXPECTED_SUPPLEMENTAL_CHECK_COUNT} supplemental checks, "
            f"found {len(parsed)}"
        )
    if seen != set(SUPPLEMENTAL_PREFLIGHT_CHECKS):
        raise SupplementalMasterError(
            "Supplemental master IDs must match SUPPLEMENTAL_PREFLIGHT_CHECKS "
            f"(missing={sorted(set(SUPPLEMENTAL_PREFLIGHT_CHECKS) - seen)} "
            f"extra={sorted(seen - set(SUPPLEMENTAL_PREFLIGHT_CHECKS))})"
        )
    declared = data.get("count")
    if declared is not None and int(declared) != len(parsed):
        raise SupplementalMasterError(
            f"count {declared!r} != checks length {len(parsed)}"
        )
    catalog = str(data.get("gate_catalog_version") or "").strip()
    if catalog != GATE_CATALOG_VERSION:
        raise SupplementalMasterError(
            f"gate_catalog_version must be {GATE_CATALOG_VERSION!r}, got {catalog!r}"
        )
    return SupplementalCheckMaster(
        schema_version=str(
            data.get("schema_version") or SUPPLEMENTAL_MASTER_SCHEMA_VERSION
        ),
        gate_catalog_version=catalog,
        source=str(data.get("source") or SUPPLEMENTAL_PACK_SOURCE),
        count=len(parsed),
        checks=tuple(parsed),
    )


@lru_cache(maxsize=1)
def _load_gate_map() -> dict[str, tuple[str, ...]]:
    path = supplemental_gate_map_path()
    if not path.is_file():
        raise SupplementalMasterError(f"Gate map not found: {SUPPLEMENTAL_GATE_MAP_REL}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SupplementalMasterError("Gate map root must be an object")
    use_cases = data.get("use_cases")
    if not isinstance(use_cases, dict):
        raise SupplementalMasterError("Gate map use_cases must be an object")
    catalog = str(data.get("gate_catalog_version") or "").strip()
    if catalog != GATE_CATALOG_VERSION:
        raise SupplementalMasterError(
            f"gate map catalog must be {GATE_CATALOG_VERSION!r}, got {catalog!r}"
        )
    out: dict[str, tuple[str, ...]] = {}
    for uc, body in use_cases.items():
        uc_id = str(uc).strip().upper()
        if not isinstance(body, dict):
            raise SupplementalMasterError(f"use_cases[{uc_id}] must be an object")
        ids = body.get("supplemental_check_ids")
        if not isinstance(ids, list) or not ids:
            raise SupplementalMasterError(
                f"use_cases[{uc_id}].supplemental_check_ids must be a non-empty list"
            )
        cleaned = tuple(sorted({str(i).strip() for i in ids if str(i).strip()}))
        unknown = set(cleaned) - set(SUPPLEMENTAL_PREFLIGHT_CHECKS)
        if unknown:
            raise SupplementalMasterError(
                f"use_cases[{uc_id}] unknown check ids: {sorted(unknown)}"
            )
        out[uc_id] = cleaned
    # Cross-check against master required_by
    master = _load_master()
    expected: dict[str, set[str]] = {}
    for check in master.checks:
        for uc in check.required_by:
            expected.setdefault(str(uc).strip().upper(), set()).add(check.check_id)
    for uc, ids in expected.items():
        mapped = set(out.get(uc, ()))
        if mapped != ids:
            raise SupplementalMasterError(
                f"Gate map for {uc} {sorted(mapped)} != master required_by {sorted(ids)}"
            )
    if set(out) != set(expected):
        raise SupplementalMasterError(
            f"Gate map UCs {sorted(out)} != master inverted UCs {sorted(expected)}"
        )
    return out


def clear_supplemental_master_cache() -> None:
    _load_master.cache_clear()
    _load_gate_map.cache_clear()


def load_supplemental_check_master() -> SupplementalCheckMaster:
    return _load_master()


def get_supplemental_check(check_id: str | None) -> SupplementalCheckDefinition | None:
    cap = str(check_id or "").strip()
    if not cap:
        return None
    by_id = _load_master().by_id()
    row = by_id.get(cap) or by_id.get(cap.upper())
    return row


def list_supplemental_checks() -> dict[str, Any]:
    """Envelope for GET master API (Step 7)."""
    master = _load_master()
    return {
        "schema_version": master.schema_version,
        "gate_catalog_version": master.gate_catalog_version,
        "source": master.source,
        "count": master.count,
        "checks": [c.to_dict() for c in master.checks],
        "use_case_map": {
            uc: list(ids) for uc, ids in sorted(_load_gate_map().items())
        },
    }


def get_supplemental_checks_for_use_case(use_case_id: str | None) -> tuple[str, ...]:
    """Supplemental check_ids required by a pilot (empty if none / unknown UC)."""
    uc = str(use_case_id or "").strip().upper()
    if not uc:
        return ()
    return _load_gate_map().get(uc, ())


def resolve_check_ids_for_evaluate(
    *,
    use_case_ids: list[str] | None = None,
    check_ids: list[str] | None = None,
) -> list[str]:
    """
    PRD §7 evaluate resolution:

    - ``check_ids is not None`` → exact subset of the 12 (empty list → [])
    - else ``use_case_ids is not None`` → union of gates for those UCs (empty → [])
    - both ``None`` → all 12

    Empty list is **not** treated as “all 12” (only ``None`` means omitted).
    """
    if check_ids is not None:
        return sorted(
            {
                str(c).strip().upper()
                for c in check_ids
                if str(c).strip().upper() in SUPPLEMENTAL_PREFLIGHT_CHECKS
            }
        )
    if use_case_ids is not None:
        union: set[str] = set()
        for uc in use_case_ids:
            union.update(get_supplemental_checks_for_use_case(uc))
        return sorted(union)
    return sorted(SUPPLEMENTAL_PREFLIGHT_CHECKS)


def master_as_api_payload() -> dict[str, Any]:
    """Deep-copy list envelope (callers must not mutate cache)."""
    return deepcopy(list_supplemental_checks())
