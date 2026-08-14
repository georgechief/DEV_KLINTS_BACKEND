"""Map DCS enriched worklist issues → four-factor priority_inputs (PRD-ORCH-01 §5.1)."""

from __future__ import annotations

import math
from typing import Any, Mapping

from dataruns.models import CheckMaster
from dataruns.orchestration.scoring import PriorityInputs, normalize_priority_inputs


def _severity_token(issue: Mapping[str, Any]) -> str:
    raw = issue.get("severity")
    if raw is None:
        return ""
    return str(raw).strip().lower()


def _status_token(issue: Mapping[str, Any]) -> str:
    return str(issue.get("status") or "").strip().upper()


def _check_id(issue: Mapping[str, Any]) -> str:
    raw = issue.get("check_id")
    if raw is None:
        return ""
    return str(raw).strip()


def _revenue(issue: Mapping[str, Any]) -> float:
    try:
        value = float(issue.get("revenue_impact") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return value


def _master_for(
    issue: Mapping[str, Any],
    *,
    master_by_id: Mapping[str, CheckMaster] | None,
) -> CheckMaster | None:
    if not master_by_id:
        return None
    check_id = _check_id(issue)
    if not check_id:
        return None
    return master_by_id.get(check_id)


def is_foundation_gate(
    issue: Mapping[str, Any],
    *,
    master_by_id: Mapping[str, CheckMaster] | None = None,
) -> bool:
    """Foundation / gate-like check (PRD §5.1 blocker + readiness)."""
    check_id = _check_id(issue)
    if check_id.upper().startswith("FD-"):
        return True

    master = _master_for(issue, master_by_id=master_by_id)
    if master is not None:
        role = str(getattr(master, "role", "") or "").upper()
        if role == CheckMaster.Role.GATE:
            return True

    dimension = str(issue.get("dimension") or "").strip().lower()
    if "foundation" in dimension:
        return True

    # Explicit flag if callers attach it (tests / future enrichment).
    if issue.get("is_foundation_gate") is True:
        return True
    if str(issue.get("role") or "").strip().upper() == "GATE":
        return True

    return False


def severity_risk(issue: Mapping[str, Any]) -> tuple[int, str]:
    token = _severity_token(issue)
    if token == "critical":
        return 3, "Critical severity"
    if token == "high":
        return 2, "High severity"
    if token == "medium":
        return 1, "Medium severity"
    if token in {"low", "informational", "info"}:
        return 0, "Low / informational severity"
    if not token:
        return 0, "Missing severity"
    return 0, f"Unrecognized severity ({token})"


def blocker_status(
    issue: Mapping[str, Any],
    *,
    gating_check_ids: frozenset[str] | None = None,
    master_by_id: Mapping[str, CheckMaster] | None = None,
) -> tuple[int, str]:
    """First-match wins (PRD §5.1)."""
    if is_foundation_gate(issue, master_by_id=master_by_id):
        return 3, "Foundation / gate check"

    check_id = _check_id(issue)
    gates = gating_check_ids or frozenset()
    # Case-insensitive: blueprint ids and worklist ids may differ in casing.
    if check_id and (
        check_id in gates or check_id.upper() in gates or check_id.lower() in gates
    ):
        return 2, "Gates MVP1 pilots"

    status = _status_token(issue)
    optional = bool(issue.get("is_optional"))
    revenue = _revenue(issue)
    if status == "FAIL" and not optional and revenue > 0:
        return 1, "Non-optional FAIL with revenue impact"

    if optional:
        return 0, "Optional check"
    if status == "WARN":
        return 0, "WARN with no unlock signal"
    return 0, "No unlock signal"


def dependency_readiness(
    issue: Mapping[str, Any],
    *,
    has_open_foundation_fail: bool,
    master_by_id: Mapping[str, CheckMaster] | None = None,
) -> tuple[int, str]:
    """v1: only 3 or 1 (PRD §5.1)."""
    if is_foundation_gate(issue, master_by_id=master_by_id):
        return 3, "This check is foundation / gate"
    if has_open_foundation_fail:
        return 1, "Blocked on open foundation / gate FAIL"
    return 3, "No open foundation / gate FAIL"


def top_quartile_revenue_threshold(revenues: list[float]) -> float | None:
    """
    Threshold for effort_impact top-quartile credit.

    - 0 values → None (skip quartile)
    - 1–3 → max
    - ≥4 → 75th percentile (inclusive: value >= threshold)
    """
    values = [float(v) for v in revenues if isinstance(v, (int, float)) and math.isfinite(v)]
    if not values:
        return None
    if len(values) <= 3:
        return max(values)
    ordered = sorted(values)
    # Nearest-rank 75th percentile (1-indexed): ceil(0.75 * n) - 1
    index = max(0, math.ceil(0.75 * len(ordered)) - 1)
    return ordered[index]


def effort_impact(
    issue: Mapping[str, Any],
    *,
    top_quartile_threshold: float | None,
) -> tuple[int, str]:
    token = _severity_token(issue)
    revenue = _revenue(issue)
    optional = bool(issue.get("is_optional"))
    status = _status_token(issue)

    in_top_quartile = (
        top_quartile_threshold is not None
        and revenue >= top_quartile_threshold
        and revenue > 0
    )

    if token == "critical" or in_top_quartile:
        if token == "critical" and in_top_quartile:
            return 3, "Critical severity and top-quartile revenue"
        if token == "critical":
            return 3, "Critical severity"
        return 3, "Top-quartile revenue impact"

    if revenue > 0 or token == "high":
        if revenue > 0 and token == "high":
            return 2, "High severity with revenue impact"
        if revenue > 0:
            return 2, "Positive revenue impact"
        return 2, "High severity"

    if status == "WARN" or token == "medium":
        return 1, "WARN / medium severity"

    if optional or revenue <= 0:
        return 0, "Optional or low / empty revenue"

    return 0, "Low effort/impact"


def worklist_has_open_foundation_fail(
    issues: list[Mapping[str, Any]],
    *,
    master_by_id: Mapping[str, CheckMaster] | None = None,
) -> bool:
    for issue in issues:
        if _status_token(issue) != "FAIL":
            continue
        if is_foundation_gate(issue, master_by_id=master_by_id):
            return True
    return False


def map_dcs_issue_to_priority_inputs(
    issue: Mapping[str, Any],
    *,
    has_open_foundation_fail: bool,
    gating_check_ids: frozenset[str] | None = None,
    master_by_id: Mapping[str, CheckMaster] | None = None,
    top_quartile_threshold: float | None = None,
) -> tuple[PriorityInputs, dict[str, str]]:
    """Return clamped PriorityInputs + human reasons per factor."""
    b, b_reason = blocker_status(
        issue,
        gating_check_ids=gating_check_ids,
        master_by_id=master_by_id,
    )
    s, s_reason = severity_risk(issue)
    r, r_reason = dependency_readiness(
        issue,
        has_open_foundation_fail=has_open_foundation_fail,
        master_by_id=master_by_id,
    )
    e, e_reason = effort_impact(
        issue,
        top_quartile_threshold=top_quartile_threshold,
    )
    inputs = normalize_priority_inputs(
        {
            "blocker_status": b,
            "severity_risk": s,
            "dependency_readiness": r,
            "effort_impact": e,
        }
    )
    reasons = {
        "blocker_status": b_reason,
        "severity_risk": s_reason,
        "dependency_readiness": r_reason,
        "effort_impact": e_reason,
    }
    return inputs, reasons
