"""Company-scoped pilot recommendations (PRD-UC-01 Phase B §5–§7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.utils import timezone

from dataruns.architecture.enqueue import find_latest_architecture_assessment
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.worklist import (
    coerce_headline_score,
    extract_dcs_payload,
    get_latest_terminal_dcs_run,
    get_previous_scored_dcs_run,
)
from dataruns.models import DataRun
from dataruns.use_cases.gaps import (
    collect_gap_stage_ids_from_probe_coverage,
    is_gap_suggested,
)
from dataruns.use_cases.models import UseCasePilot
from tenants.models import Company

STATUS_READY = "ready"
STATUS_BLOCKED_DCS = "blocked_dcs_score"
STATUS_BLOCKED_CHECKS = "blocked_checks"
STATUS_BLOCKED_MODE = "blocked_mode"
STATUS_UNAVAILABLE = "unavailable"

# Sort priority (lower = first). ready+gap handled separately.
_STATUS_SORT_RANK = {
    STATUS_READY: 1,
    STATUS_BLOCKED_CHECKS: 2,
    STATUS_BLOCKED_DCS: 3,
    STATUS_BLOCKED_MODE: 4,
    STATUS_UNAVAILABLE: 5,
}


@dataclass
class RecommendationContext:
    """Latest DCS + AF inputs for evaluating all pilots."""

    headline_score: float | None
    score_ready: bool
    dcs_data_run_id: int | None
    check_results: dict[str, str]  # check_id → PASS|FAIL|WARN|…
    af_mode: str | None
    af_assessment_id: str | None
    gap_stage_ids: list[str]
    as_of: datetime = field(default_factory=timezone.now)


def _check_results_map(check_results: list[Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in check_results:
        if not isinstance(row, dict):
            continue
        check_id = row.get("check_id")
        if not isinstance(check_id, str) or not check_id.strip():
            continue
        status = str(row.get("status") or "").strip().upper()
        if not status:
            continue
        out[check_id.strip()] = status
    return out


def _gap_stage_ids_from_assessment(
    assessment: ArchitectureAssessment | None,
) -> list[str]:
    if assessment is None:
        return []
    probe = assessment.probe_coverage if isinstance(assessment.probe_coverage, dict) else {}
    return collect_gap_stage_ids_from_probe_coverage(probe)

def resolve_recommendation_context(*, company: Company) -> RecommendationContext:
    """
    Join latest scored DCS run + latest succeeded AF assessment.
    """
    # Prefer a succeeded run that actually has a headline score.
    scored = get_previous_scored_dcs_run(company=company, before_data_run_id=None)
    dcs_run: DataRun | None = scored
    if dcs_run is None:
        dcs_run = get_latest_terminal_dcs_run(company=company)

    headline: float | None = None
    checks: dict[str, str] = {}
    dcs_id: int | None = None
    if dcs_run is not None:
        dcs_id = dcs_run.id
        payload = extract_dcs_payload(
            dcs_run.metadata if isinstance(dcs_run.metadata, dict) else {}
        )
        headline = coerce_headline_score(payload.get("headline_score"))
        checks = _check_results_map(payload.get("check_results") or [])

    # Prefer succeeded AF for mode/gaps; fall back to latest (may be incomplete).
    af = (
        ArchitectureAssessment.objects.filter(
            company=company,
            status=ArchitectureAssessment.Status.SUCCEEDED,
        )
        .order_by("-created_at")
        .first()
    )
    if af is None:
        af = find_latest_architecture_assessment(company=company)

    mode = af.mode if af is not None else None
    assessment_id = str(af.id) if af is not None else None
    gap_ids = _gap_stage_ids_from_assessment(af)

    return RecommendationContext(
        headline_score=headline,
        score_ready=headline is not None,
        dcs_data_run_id=dcs_id,
        check_results=checks,
        af_mode=mode,
        af_assessment_id=assessment_id,
        gap_stage_ids=gap_ids,
        as_of=timezone.now(),
    )


def _gates_from_blueprint(body: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {
            "min_dcs": 70,
            "gating_check_ids": [],
            "architecture_modes": ["AUGMENT", "SELECTIVE_REBUILD", "REBUILD"],
        }
    gates = body.get("gates") if isinstance(body.get("gates"), dict) else {}
    min_dcs = gates.get("min_dcs")
    try:
        min_dcs_f = float(min_dcs) if min_dcs is not None else 70.0
    except (TypeError, ValueError):
        min_dcs_f = 70.0
    modes = gates.get("architecture_modes")
    if not isinstance(modes, list) or not modes:
        modes = ["AUGMENT", "SELECTIVE_REBUILD", "REBUILD"]
    check_ids = gates.get("gating_check_ids")
    if not isinstance(check_ids, list):
        check_ids = []
    return {
        "min_dcs": min_dcs_f,
        "gating_check_ids": [str(c).strip() for c in check_ids if str(c).strip()],
        "architecture_modes": [str(m).strip() for m in modes if str(m).strip()],
    }


def evaluate_pilot(
    pilot: UseCasePilot,
    ctx: RecommendationContext,
) -> dict[str, Any]:
    """
    Evaluate one pilot against DCS + AF (PRD §7.1).

    Order: DCS score → architecture mode → gating checks.
    Missing gate checks ⇒ blocked_checks (honest, never silent ready).
    """
    blueprint = getattr(pilot, "blueprint", None)
    body = blueprint.body if blueprint is not None and isinstance(blueprint.body, dict) else None
    if blueprint is None or body is None:
        return _pilot_payload(
            pilot=pilot,
            status=STATUS_UNAVAILABLE,
            gates=_gates_from_blueprint(None),
            gap_suggested=False,
            gap_stages=[],
            blockers=[
                {
                    "code": "blueprint_missing",
                    "detail": "Blueprint not seeded for this pilot.",
                    "href": None,
                }
            ],
            check_results=[],
        )

    gates = _gates_from_blueprint(body)
    primary_stages = [
        m.stage_id for m in pilot.stage_maps.all() if getattr(m, "is_primary", True)
    ]
    gap_suggested = is_gap_suggested(
        primary_stages=primary_stages,
        af_gap_stage_ids=ctx.gap_stage_ids,
    )

    blockers: list[dict[str, Any]] = []

    # 1) DCS score gate
    if ctx.headline_score is None:
        return _pilot_payload(
            pilot=pilot,
            status=STATUS_BLOCKED_DCS,
            gates=gates,
            gap_suggested=gap_suggested,
            gap_stages=primary_stages,
            blockers=[
                {
                    "code": "min_dcs",
                    "detail": "No Data Consistency Score yet.",
                    "href": "/data-consistency",
                }
            ],
            check_results=_check_rows_for_gates(gates["gating_check_ids"], ctx),
        )

    if ctx.headline_score < float(gates["min_dcs"]):
        return _pilot_payload(
            pilot=pilot,
            status=STATUS_BLOCKED_DCS,
            gates=gates,
            gap_suggested=gap_suggested,
            gap_stages=primary_stages,
            blockers=[
                {
                    "code": "min_dcs",
                    "detail": (
                        f"Score {ctx.headline_score:g} < {gates['min_dcs']:g}"
                    ),
                    "href": "/data-consistency",
                }
            ],
            check_results=_check_rows_for_gates(gates["gating_check_ids"], ctx),
        )

    # 2) Architecture mode gate
    mode = ctx.af_mode
    allowed_modes = set(gates["architecture_modes"])
    if mode is None or mode == ArchitectureAssessment.Mode.INCOMPLETE or mode not in allowed_modes:
        detail = "Architecture map incomplete or mode not allowed for this pilot."
        if mode is None:
            detail = "Architecture Assessment has not finished yet."
        elif mode == ArchitectureAssessment.Mode.INCOMPLETE:
            detail = "Architecture mode is INCOMPLETE — Retire/Consolidate gated."
        else:
            detail = f"Architecture mode {mode} is not in allowed modes."
        return _pilot_payload(
            pilot=pilot,
            status=STATUS_BLOCKED_MODE,
            gates=gates,
            gap_suggested=gap_suggested,
            gap_stages=primary_stages,
            blockers=[
                {
                    "code": "architecture_mode",
                    "detail": detail,
                    "href": "/lifecycle",
                }
            ],
            check_results=_check_rows_for_gates(gates["gating_check_ids"], ctx),
        )

    # 3) Gating checks — WARN/missing/FAIL all block (PRD locked default)
    check_rows = _check_rows_for_gates(gates["gating_check_ids"], ctx)
    failing: list[str] = []
    for check_id in gates["gating_check_ids"]:
        result = ctx.check_results.get(check_id)
        if result != "PASS":
            failing.append(check_id)
            if result is None:
                blockers.append(
                    {
                        "code": "gate_not_in_latest_score",
                        "detail": f"{check_id} was not evaluated in the latest score.",
                        "href": f"/data-consistency?issue={check_id}",
                        "check_id": check_id,
                    }
                )
            else:
                blockers.append(
                    {
                        "code": "gating_check",
                        "detail": f"{check_id} is {result}.",
                        "href": f"/data-consistency?issue={check_id}",
                        "check_id": check_id,
                    }
                )

    if failing:
        return _pilot_payload(
            pilot=pilot,
            status=STATUS_BLOCKED_CHECKS,
            gates=gates,
            gap_suggested=gap_suggested,
            gap_stages=primary_stages,
            blockers=blockers,
            check_results=check_rows,
        )

    return _pilot_payload(
        pilot=pilot,
        status=STATUS_READY,
        gates=gates,
        gap_suggested=gap_suggested,
        gap_stages=primary_stages,
        blockers=[],
        check_results=check_rows,
    )


def _check_rows_for_gates(
    gating_check_ids: list[str],
    ctx: RecommendationContext,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for check_id in gating_check_ids:
        result = ctx.check_results.get(check_id)
        row: dict[str, Any] = {
            "check_id": check_id,
            "result": result if result is not None else "unknown",
        }
        if result != "PASS":
            row["href"] = f"/data-consistency?issue={check_id}"
        rows.append(row)
    return rows


def _pilot_payload(
    *,
    pilot: UseCasePilot,
    status: str,
    gates: dict[str, Any],
    gap_suggested: bool,
    gap_stages: list[str],
    blockers: list[dict[str, Any]],
    check_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "use_case_id": pilot.use_case_id,
        "pilot_rank": pilot.pilot_rank,
        "title": pilot.title,
        "status": status,
        "gap_suggested": gap_suggested,
        "gap_stages": gap_stages,
        "gates": {
            "min_dcs": gates["min_dcs"],
            "gating_check_ids": list(gates["gating_check_ids"]),
            "architecture_modes": list(gates["architecture_modes"]),
        },
        "blockers": blockers,
        "check_results": check_results,
        "execution": {
            "mcp_dependency": pilot.mcp_dependency,
            "fallback": pilot.fallback or "HUMAN.WORKFLOW.BUILD",
            "build_available": False,
            "note": "Human build guide only until MCP discovery.",
        },
        "cta": {
            "label": "View blueprint",
            "href": f"/opportunities?uc={pilot.use_case_id}",
        },
    }


def _sort_pilots(pilots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    PRD §5.1: ready + gap_suggested first → other ready → blocked_checks
    → blocked_dcs_score → blocked_mode → unavailable (by pilot_rank within bucket).
    """

    def key(row: dict[str, Any]) -> tuple:
        status = row.get("status") or STATUS_UNAVAILABLE
        gap = bool(row.get("gap_suggested"))
        rank = int(row.get("pilot_rank") or 999)
        if status == STATUS_READY and gap:
            bucket = 0
        else:
            bucket = _STATUS_SORT_RANK.get(status, 9)
        return (bucket, rank)

    return sorted(pilots, key=key)


def build_recommendations_payload(*, company: Company) -> dict[str, Any]:
    """Full GET /use-cases/recommendations/ response."""
    ctx = resolve_recommendation_context(company=company)
    pilots_qs = (
        UseCasePilot.objects.select_related("blueprint")
        .prefetch_related("stage_maps")
        .order_by("pilot_rank")
    )
    evaluated = [evaluate_pilot(p, ctx) for p in pilots_qs]
    ordered = _sort_pilots(evaluated)

    ready_n = sum(1 for p in ordered if p["status"] == STATUS_READY)
    blocked_n = sum(
        1
        for p in ordered
        if p["status"]
        in {STATUS_BLOCKED_DCS, STATUS_BLOCKED_CHECKS, STATUS_BLOCKED_MODE}
    )
    gap_n = sum(1 for p in ordered if p["gap_suggested"])

    as_of = ctx.as_of
    if timezone.is_naive(as_of):
        as_of_iso = timezone.make_aware(as_of, dt_timezone.utc).isoformat()
    else:
        as_of_iso = as_of.isoformat()

    return {
        "as_of": as_of_iso,
        "dcs": {
            "headline_score": ctx.headline_score,
            "min_dcs_required": 70,
            "data_run_id": ctx.dcs_data_run_id,
            "score_ready": ctx.score_ready,
        },
        "architecture": {
            "mode": ctx.af_mode,
            "assessment_id": ctx.af_assessment_id,
            "gap_count": len(ctx.gap_stage_ids),
            "gap_stage_ids": list(ctx.gap_stage_ids),
        },
        "summary": {
            "ready": ready_n,
            "blocked": blocked_n,
            "gap_suggested": gap_n,
            "unavailable": sum(
                1 for p in ordered if p["status"] == STATUS_UNAVAILABLE
            ),
        },
        "pilots": ordered,
    }


def build_single_recommendation_payload(
    *,
    company: Company,
    use_case_id: str,
) -> dict[str, Any] | None:
    """GET /use-cases/recommendations/{use_case_id}/ — None if pilot missing."""
    pilot = (
        UseCasePilot.objects.select_related("blueprint")
        .prefetch_related("stage_maps")
        .filter(use_case_id=use_case_id.upper())
        .first()
    )
    if pilot is None:
        return None
    ctx = resolve_recommendation_context(company=company)
    row = evaluate_pilot(pilot, ctx)
    as_of = ctx.as_of
    if timezone.is_naive(as_of):
        as_of_iso = timezone.make_aware(as_of, dt_timezone.utc).isoformat()
    else:
        as_of_iso = as_of.isoformat()
    return {
        "as_of": as_of_iso,
        "dcs": {
            "headline_score": ctx.headline_score,
            "min_dcs_required": 70,
            "data_run_id": ctx.dcs_data_run_id,
            "score_ready": ctx.score_ready,
        },
        "architecture": {
            "mode": ctx.af_mode,
            "assessment_id": ctx.af_assessment_id,
            "gap_count": len(ctx.gap_stage_ids),
            "gap_stage_ids": list(ctx.gap_stage_ids),
        },
        "pilot": row,
    }
