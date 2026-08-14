"""CheckMaster optional flags and gate helpers (PRD-FE-03 §0)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from django.db.models import Max

OPTIONAL_CHECK_IDS_DEFAULT = frozenset({"FD-03"})


def _optional_cache_token() -> str:
    from dataruns.models import CheckMaster as CheckMasterRow

    updated = CheckMasterRow.objects.aggregate(m=Max("updated_at")).get("m")
    count = CheckMasterRow.objects.filter(is_optional=True, is_active=True).count()
    return f"{count}:{updated}"


@lru_cache(maxsize=8)
def _load_optional_check_ids_cached(cache_token: str) -> frozenset[str]:
    del cache_token
    from dataruns.models import CheckMaster as CheckMasterRow

    ids = list(
        CheckMasterRow.objects.filter(is_optional=True, is_active=True).values_list(
            "check_id", flat=True
        )
    )
    if not ids:
        # Empty table or none flagged — keep FD-03 default for safe boot.
        return OPTIONAL_CHECK_IDS_DEFAULT
    return frozenset(ids)


def load_optional_check_ids() -> frozenset[str]:
    """Load optional check ids from DB CheckMaster.is_optional."""
    try:
        return _load_optional_check_ids_cached(_optional_cache_token())
    except Exception:  # noqa: BLE001 — allow import before apps ready / empty migrate
        return OPTIONAL_CHECK_IDS_DEFAULT


def clear_optional_check_ids_cache() -> None:
    _load_optional_check_ids_cached.cache_clear()


def is_optional_check_id(check_id: str | None, *, optional_check_ids: frozenset[str]) -> bool:
    if not check_id:
        return False
    return check_id in optional_check_ids


def partition_gate_failures(
    check_results: list[dict[str, Any]],
    *,
    optional_check_ids: frozenset[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split FAIL foundation-gate results into required vs optional (PRD-FE-03 §0.4)."""
    required: list[dict[str, Any]] = []
    optional: list[dict[str, Any]] = []
    for result in check_results:
        if result.get("status") != "FAIL":
            continue
        check_id = result.get("check_id")
        # App lock cares about foundation gates (FD-*), not scored-check FAILs.
        if not (isinstance(check_id, str) and check_id.startswith("FD-")):
            continue
        if is_optional_check_id(check_id, optional_check_ids=optional_check_ids):
            optional.append(result)
        else:
            required.append(result)
    return required, optional


def count_required_blocking_gate_failures(
    check_results: list[dict[str, Any]],
    *,
    optional_check_ids: frozenset[str],
) -> int:
    """App-facing blocking gate count excluding optional checks (PRD-FE-03 §0.3)."""
    required, _optional = partition_gate_failures(
        check_results,
        optional_check_ids=optional_check_ids,
    )
    return len(required)


def is_effectively_blocked(
    *,
    run_state: str | None,
    headline_score,
    check_results: list[dict[str, Any]],
    optional_check_ids: frozenset[str],
) -> bool:
    """Return True when required gate FAILs should hard-lock the app shell."""
    required_fails, _optional_fails = partition_gate_failures(
        check_results,
        optional_check_ids=optional_check_ids,
    )
    if not required_fails:
        return False
    if run_state == "BLOCKED":
        return True
    return headline_score is None
