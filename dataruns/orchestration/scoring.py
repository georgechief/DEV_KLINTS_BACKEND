"""Four-factor priority scoring (PRD-ORCH-01 / BL-011).

No LLM. Formula locked to pack sheet 02 / 09:
  priority_score = 0.40*blocker + 0.30*severity + 0.20*readiness + 0.10*effort
"""

from __future__ import annotations

import logging
import math
from typing import Any, Mapping, TypedDict

from dataruns.orchestration.constants import (
    FACTOR_KEYS,
    FACTOR_MAX,
    FACTOR_MIN,
    FACTOR_WEIGHTS,
    PRIORITY_CLASS_ORDER,
    PRIORITY_CLASS_P0_MIN,
    PRIORITY_CLASS_P1_MIN,
    SCORE_DECIMALS,
    SCORE_MAX,
    SCORE_MIN,
    WEIGHT_BLOCKER_STATUS,
    WEIGHT_DEPENDENCY_READINESS,
    WEIGHT_EFFORT_IMPACT,
    WEIGHT_SEVERITY_RISK,
)

logger = logging.getLogger(__name__)


class PriorityInputs(TypedDict):
    blocker_status: int
    severity_risk: int
    dependency_readiness: int
    effort_impact: int


class PriorityExplainRow(TypedDict):
    factor: str
    value: int
    weight: float
    contribution: float
    reason: str


def clamp_factor(value: Any, *, factor: str = "factor") -> int:
    """Coerce to int and clamp to [0, 3]. Logs when clamping."""
    try:
        if value is None:
            n = FACTOR_MIN
        else:
            n = int(value)
    except (TypeError, ValueError):
        logger.warning("orch priority: invalid %s=%r; using 0", factor, value)
        return FACTOR_MIN

    if n < FACTOR_MIN or n > FACTOR_MAX:
        logger.warning(
            "orch priority: clamping %s=%s to [%s, %s]",
            factor,
            n,
            FACTOR_MIN,
            FACTOR_MAX,
        )
        n = max(FACTOR_MIN, min(FACTOR_MAX, n))
    return n


def normalize_priority_inputs(raw: Mapping[str, Any]) -> PriorityInputs:
    """Build clamped PriorityInputs from a partial mapping."""
    return PriorityInputs(
        blocker_status=clamp_factor(
            raw.get("blocker_status", FACTOR_MIN), factor="blocker_status"
        ),
        severity_risk=clamp_factor(
            raw.get("severity_risk", FACTOR_MIN), factor="severity_risk"
        ),
        dependency_readiness=clamp_factor(
            raw.get("dependency_readiness", FACTOR_MIN),
            factor="dependency_readiness",
        ),
        effort_impact=clamp_factor(
            raw.get("effort_impact", FACTOR_MIN), factor="effort_impact"
        ),
    )


def compute_priority_score(inputs: Mapping[str, Any]) -> float:
    """Return priority_score in [0, 3], rounded to SCORE_DECIMALS."""
    normalized = normalize_priority_inputs(inputs)
    raw = (
        WEIGHT_BLOCKER_STATUS * normalized["blocker_status"]
        + WEIGHT_SEVERITY_RISK * normalized["severity_risk"]
        + WEIGHT_DEPENDENCY_READINESS * normalized["dependency_readiness"]
        + WEIGHT_EFFORT_IMPACT * normalized["effort_impact"]
    )
    score = round(float(raw), SCORE_DECIMALS)
    if score < SCORE_MIN:
        return SCORE_MIN
    if score > SCORE_MAX:
        return SCORE_MAX
    return score


def priority_class_from_score(score: float) -> str:
    """Map score → P0 / P1 / P2 (PRD §2)."""
    if score >= PRIORITY_CLASS_P0_MIN:
        return "P0"
    if score >= PRIORITY_CLASS_P1_MIN:
        return "P1"
    return "P2"


def build_priority_explain(
    inputs: Mapping[str, Any],
    *,
    reasons: Mapping[str, str] | None = None,
) -> list[PriorityExplainRow]:
    """Factor breakdown for API `priority_explain` (sorted by contribution DESC)."""
    normalized = normalize_priority_inputs(inputs)
    reason_map = reasons or {}
    rows: list[PriorityExplainRow] = []
    for key in FACTOR_KEYS:
        value = normalized[key]  # type: ignore[literal-required]
        weight = FACTOR_WEIGHTS[key]
        contribution = round(weight * value, SCORE_DECIMALS)
        rows.append(
            PriorityExplainRow(
                factor=key,
                value=value,
                weight=weight,
                contribution=contribution,
                reason=str(reason_map.get(key) or ""),
            )
        )
    rows.sort(key=lambda r: (-r["contribution"], r["factor"]))
    return rows


def task_sort_key(task: Mapping[str, Any]) -> tuple:
    """Tie-break: score DESC → class P0..P2 → task_id ASC."""
    raw_score = task.get("priority_score")
    try:
        score = float(raw_score) if raw_score is not None else 0.0
    except (TypeError, ValueError):
        score = 0.0
    if not math.isfinite(score):
        score = 0.0
    klass = str(task.get("priority_class") or priority_class_from_score(score))
    class_rank = PRIORITY_CLASS_ORDER.get(klass, 99)
    task_id = str(task.get("task_id") or "")
    return (-score, class_rank, task_id)


def sort_tasks_by_priority(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable priority ordering for plan payloads."""
    return sorted(tasks, key=task_sort_key)
