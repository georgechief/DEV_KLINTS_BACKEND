"""ORCH-01 priority weights and class thresholds (pack sheet 02 / 09)."""

from __future__ import annotations

# priority_score = 0.40*B + 0.30*S + 0.20*R + 0.10*E
WEIGHT_BLOCKER_STATUS = 0.40
WEIGHT_SEVERITY_RISK = 0.30
WEIGHT_DEPENDENCY_READINESS = 0.20
WEIGHT_EFFORT_IMPACT = 0.10

FACTOR_MIN = 0
FACTOR_MAX = 3
SCORE_MIN = 0.0
SCORE_MAX = 3.0
SCORE_DECIMALS = 2

# priority_class from score (PRD §2)
PRIORITY_CLASS_P0_MIN = 2.0
PRIORITY_CLASS_P1_MIN = 1.0

PRIORITY_CLASS_ORDER = {"P0": 0, "P1": 1, "P2": 2}

FACTOR_KEYS = (
    "blocker_status",
    "severity_risk",
    "dependency_readiness",
    "effort_impact",
)

FACTOR_WEIGHTS: dict[str, float] = {
    "blocker_status": WEIGHT_BLOCKER_STATUS,
    "severity_risk": WEIGHT_SEVERITY_RISK,
    "dependency_readiness": WEIGHT_DEPENDENCY_READINESS,
    "effort_impact": WEIGHT_EFFORT_IMPACT,
}
