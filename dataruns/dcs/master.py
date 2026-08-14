"""Load and validate the MVP1 check master (PRD-DCS-00).

Runtime source of truth is DB ``CheckMaster`` / ``DimensionMaster``.
JSON remains available only for unit fixtures via ``load_check_master_from_json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.db.models import Max

from dataruns.dcs.constants import DCS_SCORING_MODEL_VERSION

_PACKAGE_DIR = Path(__file__).resolve().parent
_MASTER_PATH = _PACKAGE_DIR / "check_master_mvp1.json"

# Match check_master_mvp1.json / assemble expectations.
_SCOPE_MODEL_VERSION = "MVP1-42-v1.4.1"
_MASTER_VERSION = "1.0.0"
_FOUNDATION_DIMENSION_ID = "00"
_BUSINESS_REALITY_DIMENSION_ID = "07"
_EXPECTED_CHECK_COUNT = 42


@dataclass(frozen=True)
class CheckDefinition:
    check_id: str
    dimension: str
    numeric_weight: int
    role: str
    is_optional: bool = False


@dataclass(frozen=True)
class CheckMaster:
    version: str
    scope_model_version: str
    scoring_model_version: str
    dimension_weights: dict[str, int]
    required_dimensions: tuple[str, ...]
    checks: tuple[CheckDefinition, ...]

    def by_id(self) -> dict[str, CheckDefinition]:
        return {check.check_id: check for check in self.checks}

    def check_ids(self) -> set[str]:
        return {check.check_id for check in self.checks}


class CheckMasterNotSeededError(RuntimeError):
    """Raised when DCS master tables are empty or incomplete."""


def _dimension_label(dimension) -> str:
    key = (getattr(dimension, "key", None) or "").strip()
    if key:
        return key
    dimension_id = getattr(dimension, "dimension_id", "") or ""
    name = (getattr(dimension, "name", None) or "").strip()
    if dimension_id and name:
        return f"{dimension_id} {name}"
    return name or dimension_id or "unknown"


def _build_master_from_rows(*, check_rows, dimension_rows) -> CheckMaster:
    checks = tuple(
        CheckDefinition(
            check_id=row.check_id,
            dimension=_dimension_label(row.dimension),
            numeric_weight=int(row.numeric_weight),
            role=row.role,
            is_optional=bool(row.is_optional),
        )
        for row in check_rows
    )
    if len(checks) != _EXPECTED_CHECK_COUNT:
        raise CheckMasterNotSeededError(
            f"Check master must contain {_EXPECTED_CHECK_COUNT} active checks, "
            f"found {len(checks)}. Run: python manage.py seed_dcs_master"
        )

    dimension_weights: dict[str, int] = {}
    required: list[str] = []
    for dim in dimension_rows:
        if dim.dimension_id == _FOUNDATION_DIMENSION_ID:
            continue
        label = _dimension_label(dim)
        dimension_weights[label] = int(dim.weight_percent or 0)
        if dim.dimension_id != _BUSINESS_REALITY_DIMENSION_ID:
            required.append(label)

    if not dimension_weights:
        raise CheckMasterNotSeededError(
            "No scored dimensions in dimension_masters. "
            "Run: python manage.py seed_dcs_master"
        )

    return CheckMaster(
        version=_MASTER_VERSION,
        scope_model_version=_SCOPE_MODEL_VERSION,
        scoring_model_version=DCS_SCORING_MODEL_VERSION,
        dimension_weights=dimension_weights,
        required_dimensions=tuple(required),
        checks=checks,
    )


def _db_cache_token() -> str:
    """Invalidate lru_cache when master rows are re-seeded."""
    from dataruns.models import CheckMaster as CheckMasterRow
    from dataruns.models import DimensionMaster

    check_updated = (
        CheckMasterRow.objects.aggregate(m=Max("updated_at")).get("m")
    )
    dim_updated = (
        DimensionMaster.objects.aggregate(m=Max("updated_at")).get("m")
    )
    check_count = CheckMasterRow.objects.filter(is_active=True).count()
    return f"{check_count}:{check_updated}:{dim_updated}"


@lru_cache(maxsize=8)
def _load_check_master_from_db_cached(cache_token: str) -> CheckMaster:
    del cache_token  # used only as cache key
    from dataruns.models import CheckMaster as CheckMasterRow
    from dataruns.models import DimensionMaster

    check_rows = list(
        CheckMasterRow.objects.filter(is_active=True)
        .select_related("dimension")
        .order_by("sequence")
    )
    if not check_rows:
        raise CheckMasterNotSeededError(
            "check_masters is empty. Run: python manage.py seed_dcs_master"
        )

    dimension_rows = list(
        DimensionMaster.objects.filter(is_active=True).order_by("dimension_id")
    )
    return _build_master_from_rows(
        check_rows=check_rows,
        dimension_rows=dimension_rows,
    )


def load_check_master_from_json(path: str | Path | None = None) -> CheckMaster:
    """Load master from JSON fixture (unit tests / parity only)."""
    master_path = Path(path) if path else _MASTER_PATH
    raw: dict[str, Any] = json.loads(master_path.read_text(encoding="utf-8"))
    checks = tuple(
        CheckDefinition(
            check_id=row["check_id"],
            dimension=row["dimension"],
            numeric_weight=int(row["numeric_weight"]),
            role=row["role"],
            is_optional=bool(
                row.get("is_optional", row.get("isOptional", False))
            ),
        )
        for row in raw["checks"]
    )
    if len(checks) != _EXPECTED_CHECK_COUNT:
        raise ValueError(
            f"Check master must contain {_EXPECTED_CHECK_COUNT} checks, "
            f"found {len(checks)}"
        )
    return CheckMaster(
        version=str(raw.get("version", "1.0.0")),
        scope_model_version=str(raw["scope_model_version"]),
        scoring_model_version=str(raw["scoring_model_version"]),
        dimension_weights={
            key: int(value) for key, value in raw["dimension_weights"].items()
        },
        required_dimensions=tuple(raw["required_dimensions"]),
        checks=checks,
    )


def load_check_master(path: str | None = None) -> CheckMaster:
    """
    Load MVP1 check master.

    - ``path`` set → JSON fixture (tests)
    - default → DB CheckMaster / DimensionMaster
    """
    if path is not None:
        return load_check_master_from_json(path)
    return _load_check_master_from_db_cached(_db_cache_token())


def clear_check_master_cache() -> None:
    _load_check_master_from_db_cached.cache_clear()
