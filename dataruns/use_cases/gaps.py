"""
WF-12 gap → pilot matching (PRD-UC-01 Phase C / §6).

``gap_suggested`` is a boolean FLAG on a pilot row — never a status enum value.
"""

from __future__ import annotations

from dataruns.architecture.lifecycle_model import normalize_lifecycle_stage
from dataruns.use_cases.constants import MVP1_PILOT_IDS, PILOT_PRIMARY_STAGES


def normalize_gap_stage_id(value: str | None) -> str | None:
    """Normalize AF / WF-12 stage tokens to ``stage_XX``."""
    return normalize_lifecycle_stage(value)


def collect_gap_stage_ids(raw_gaps: object) -> list[str]:
    """
    Extract normalized stage_ids from AF ``lifecycle_gaps`` payloads.

    Accepts:
    - list of dicts with ``stage_id`` / ``stage``
    - list of stage id strings
    - mixed / messy tokens (``stage_2``, ``2``, ``Stage 02``)
    """
    if not isinstance(raw_gaps, list):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for item in raw_gaps:
        candidates: list[str] = []
        if isinstance(item, dict):
            sid = item.get("stage_id")
            if isinstance(sid, str) and sid.strip():
                candidates.append(sid)
            stage_num = item.get("stage")
            if stage_num is not None:
                candidates.append(str(stage_num))
        elif isinstance(item, str) and item.strip():
            candidates.append(item)
        elif isinstance(item, int):
            candidates.append(str(item))

        for raw in candidates:
            normalized = normalize_gap_stage_id(raw)
            if normalized and normalized not in seen:
                seen.add(normalized)
                out.append(normalized)
                break
    return out


def collect_gap_stage_ids_from_probe_coverage(
    probe_coverage: dict | None,
) -> list[str]:
    """Read gap stage ids from an ArchitectureAssessment.probe_coverage blob."""
    if not isinstance(probe_coverage, dict):
        return []

    stage_ids = collect_gap_stage_ids(probe_coverage.get("lifecycle_gaps"))

    for key in ("lifecycle_gap_stage_ids", "gap_stage_ids"):
        extra = probe_coverage.get(key)
        if not isinstance(extra, list):
            continue
        for sid in collect_gap_stage_ids(extra):
            if sid not in stage_ids:
                stage_ids.append(sid)
    return stage_ids


def primary_stages_for_pilot(use_case_id: str) -> tuple[str, ...]:
    """Locked PRD §6 primary stages for a pilot (empty if unknown)."""
    return PILOT_PRIMARY_STAGES.get(use_case_id, ())


def matched_gap_stages(
    *,
    primary_stages: list[str] | tuple[str, ...],
    af_gap_stage_ids: list[str] | tuple[str, ...] | set[str],
) -> list[str]:
    """Intersection of pilot primary stages and AF coverage gaps (normalized)."""
    gap_set = {
        sid
        for sid in (normalize_gap_stage_id(s) for s in af_gap_stage_ids)
        if sid
    }
    matched: list[str] = []
    for stage in primary_stages:
        normalized = normalize_gap_stage_id(stage) or stage
        if normalized in gap_set and normalized not in matched:
            matched.append(normalized)
    return matched


def is_gap_suggested(
    *,
    primary_stages: list[str] | tuple[str, ...],
    af_gap_stage_ids: list[str] | tuple[str, ...] | set[str],
) -> bool:
    """True when any primary stage is uncovered in WF-12 gaps."""
    return bool(
        matched_gap_stages(
            primary_stages=primary_stages,
            af_gap_stage_ids=af_gap_stage_ids,
        )
    )


def pilots_suggested_for_gap(stage_id: str) -> list[str]:
    """Which MVP1 pilots fill a given uncovered stage (for debugging / tests)."""
    normalized = normalize_gap_stage_id(stage_id)
    if not normalized:
        return []
    return sorted(
        [
            uc_id
            for uc_id, stages in PILOT_PRIMARY_STAGES.items()
            if normalized in stages and uc_id in MVP1_PILOT_IDS
        ]
    )


def assert_stage_map_complete() -> None:
    """Raise if any MVP1 pilot is missing a primary stage mapping."""
    missing = sorted(MVP1_PILOT_IDS - set(PILOT_PRIMARY_STAGES.keys()))
    if missing:
        raise ValueError(f"PILOT_PRIMARY_STAGES missing pilots: {missing}")
    empty = sorted(
        uc for uc, stages in PILOT_PRIMARY_STAGES.items() if uc in MVP1_PILOT_IDS and not stages
    )
    if empty:
        raise ValueError(f"PILOT_PRIMARY_STAGES empty for: {empty}")
