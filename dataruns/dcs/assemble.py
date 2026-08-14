"""DCS score assembly engine (PRD-DCS-00 sheet 08)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

from dataruns.dcs.master import CheckMaster, load_check_master
from dataruns.dcs.types import (
    ELIGIBLE_STATUSES,
    EXCLUDED_STATUSES,
    CheckResult,
    DcsRun,
    DimensionScore,
    RunState,
)

BLOCKING_GATE_IDS = frozenset(
    {"FD-01", "FD-02", "FD-04", "FD-05", "FD-06", "FD-07"}
)
ERP_GATE_ID = "FD-03"
BR_DIMENSION = "07 Business Reality"
COVERAGE_THRESHOLD = 0.80
BR_CONFIDENCE_CAP = 0.85


class AssembleValidationError(ValueError):
    """Raised when check results cannot be assembled."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _round4(value: float) -> float:
    return round(value + 1e-12, 4)


def _round3(value: float) -> float:
    return round(value + 1e-12, 3)


def _normalize_results(
    check_results: Sequence[CheckResult],
    master: CheckMaster,
    *,
    erp_in_scope: bool,
) -> list[CheckResult]:
    by_id = master.by_id()
    seen: set[str] = set()
    normalized: list[CheckResult] = []

    for result in check_results:
        if result.check_id in seen:
            raise AssembleValidationError(
                f"Duplicate check_id in results: {result.check_id}"
            )
        seen.add(result.check_id)

        definition = by_id.get(result.check_id)
        if definition is None:
            raise AssembleValidationError(
                f"Unknown check_id not in master: {result.check_id}"
            )

        status = result.status
        reason_code = result.reason_code

        if result.check_id == ERP_GATE_ID and not erp_in_scope:
            status = "NOT_CONNECTED"
            reason_code = reason_code or "ERP_OUT_OF_SCOPE"

        if status in EXCLUDED_STATUSES and not reason_code:
            raise AssembleValidationError(
                f"{result.check_id} status {status} requires reason_code"
            )

        weight = (
            float(result.numeric_weight)
            if result.numeric_weight is not None
            else float(definition.numeric_weight)
        )

        normalized.append(
            CheckResult(
                check_id=result.check_id,
                status=status,  # type: ignore[arg-type]
                confidence=result.confidence,
                evidence=list(result.evidence),
                reason_code=reason_code,
                score_factor=result.normalized_score_factor(),
                numeric_weight=weight,
                confidence_factor=result.normalized_confidence_factor(),
                schema_version=result.schema_version,
                tenant_id=result.tenant_id,
                run_id=result.run_id,
                scoring_model_version=result.scoring_model_version,
                evaluated_at=result.evaluated_at,
                provenance=result.provenance,
                severity=result.severity,
                root_cause_ids=list(result.root_cause_ids),
                root_causes=list(result.root_causes),
                message=result.message,
                suggested_fix=result.suggested_fix,
                detection_logic=result.detection_logic,
            )
        )

    missing = master.check_ids() - seen
    if missing:
        raise AssembleValidationError(
            f"Missing check results for: {', '.join(sorted(missing))}"
        )
    return normalized


def _blocking_gate_failures(
    results: Iterable[CheckResult],
    master: CheckMaster,
    *,
    erp_in_scope: bool,
) -> list[str]:
    """Required gate FAILs only; ``is_optional`` checks never block (FE-03)."""
    by_id = master.by_id()
    failed: list[str] = []
    for result in results:
        if result.status != "FAIL":
            continue
        definition = by_id.get(result.check_id)
        if definition is not None and definition.is_optional:
            continue
        if result.check_id in BLOCKING_GATE_IDS:
            failed.append(result.check_id)
        elif result.check_id == ERP_GATE_ID and erp_in_scope:
            # Legacy path; FD-03 is optional in master so normally skipped above.
            failed.append(result.check_id)
    return failed


def _score_dimensions(
    results: Sequence[CheckResult],
    master: CheckMaster,
    *,
    erp_in_scope: bool,
) -> dict[str, DimensionScore]:
    by_id = master.by_id()
    scored_dims = [
        dim
        for dim in master.dimension_weights
        if erp_in_scope or dim != BR_DIMENSION
    ]

    # Group results by scored dimension
    by_dim: dict[str, list[CheckResult]] = {dim: [] for dim in scored_dims}
    for result in results:
        definition = by_id[result.check_id]
        if definition.dimension not in by_dim:
            continue
        if definition.numeric_weight <= 0:
            continue
        by_dim[definition.dimension].append(result)

    dimensions: dict[str, DimensionScore] = {}
    for dim in scored_dims:
        rows = by_dim[dim]
        weight_percent = master.dimension_weights[dim]

        scoped_applicable = 0.0
        for result in rows:
            if result.status == "NOT_APPLICABLE":
                continue
            scoped_applicable += float(result.numeric_weight or 0)

        eligible = [
            result
            for result in rows
            if result.status in ELIGIBLE_STATUSES
            and float(result.numeric_weight or 0) > 0
        ]
        eligible_weight = sum(float(r.numeric_weight or 0) for r in eligible)

        if eligible_weight <= 0:
            dimensions[dim] = DimensionScore(
                score=None,
                coverage=0.0 if scoped_applicable > 0 else 1.0,
                confidence=0.0,
                weight_percent=weight_percent,
            )
            continue

        earned = sum(
            float(r.numeric_weight or 0) * float(r.normalized_score_factor() or 0)
            for r in eligible
        )
        score = _round4(100.0 * earned / eligible_weight)
        coverage = (
            _round4(eligible_weight / scoped_applicable)
            if scoped_applicable > 0
            else 1.0
        )
        confidence = _round4(
            sum(
                float(r.numeric_weight or 0) * r.normalized_confidence_factor()
                for r in eligible
            )
            / eligible_weight
        )
        dimensions[dim] = DimensionScore(
            score=score,
            coverage=coverage,
            confidence=confidence,
            weight_percent=weight_percent,
        )
    return dimensions


def _headline_and_overall(
    dimensions: dict[str, DimensionScore],
    *,
    erp_in_scope: bool,
) -> tuple[float | None, float, float]:
    included = [
        (dim, ds)
        for dim, ds in dimensions.items()
        if ds.score is not None and (erp_in_scope or dim != BR_DIMENSION)
    ]
    if not included:
        return None, 0.0, 0.0

    weight_sum = sum(ds.weight_percent for _, ds in included)
    if weight_sum <= 0:
        return None, 0.0, 0.0

    headline = sum(float(ds.score) * ds.weight_percent for _, ds in included) / weight_sum
    # Match Lumera fixture display precision (3 decimals on headline).
    headline = _round3(headline)

    overall_coverage = sum(ds.coverage * ds.weight_percent for _, ds in included) / weight_sum
    overall_confidence = (
        sum(ds.confidence * ds.weight_percent for _, ds in included) / weight_sum
    )
    overall_coverage = _round4(overall_coverage)
    overall_confidence = _round4(overall_confidence)

    if not erp_in_scope:
        overall_confidence = min(overall_confidence, BR_CONFIDENCE_CAP)

    return headline, overall_coverage, overall_confidence


def _run_state_from_score(
    headline: float | None,
    *,
    erp_in_scope: bool,
    incomplete: bool,
) -> RunState:
    if incomplete:
        return "INCOMPLETE"
    if headline is None:
        return "BLOCKED"
    if headline >= 90:
        state: RunState = "READY"
    elif headline >= 70:
        state = "CONDITIONALLY_READY"
    elif headline >= 50:
        state = "REMEDIATE"
    else:
        state = "BLOCKED"

    if not erp_in_scope and state == "READY":
        return "CONDITIONALLY_READY"
    return state


def _required_coverage_incomplete(
    dimensions: dict[str, DimensionScore],
    master: CheckMaster,
    *,
    erp_in_scope: bool,
) -> bool:
    for dim in master.required_dimensions:
        if dim == BR_DIMENSION and not erp_in_scope:
            continue
        ds = dimensions.get(dim)
        if ds is None or ds.coverage < COVERAGE_THRESHOLD:
            return True
    return False


def assemble_dcs_score(
    check_results: Sequence[CheckResult] | Sequence[dict],
    *,
    scoring_model_version: str = "DCS-1.0.0",
    erp_in_scope: bool = False,
    sweep_complete: bool = True,
    tenant_id: str | None = None,
    run_id: str | None = None,
    master: CheckMaster | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> DcsRun:
    """
    Assemble a DCS run payload from 42 check results (sheet 08).

    Pure function: no DB / connector I/O.
    """
    master = master or load_check_master()
    results_in: list[CheckResult] = [
        item if isinstance(item, CheckResult) else CheckResult.from_dict(item)
        for item in check_results
    ]
    results = _normalize_results(results_in, master, erp_in_scope=erp_in_scope)

    now = _utcnow_iso()
    started = started_at or now
    completed = completed_at if completed_at is not None else now
    tenant = tenant_id or (results[0].tenant_id if results else "")
    run = run_id or (results[0].run_id if results else "")

    gate_failures = _blocking_gate_failures(
        results, master, erp_in_scope=erp_in_scope
    )
    if gate_failures:
        return DcsRun(
            schema_version="1.0.0",
            tenant_id=tenant,
            run_id=run,
            run_state="BLOCKED",
            scope_model_version=master.scope_model_version,
            scoring_model_version=scoring_model_version or master.scoring_model_version,
            headline_score=None,
            dimension_scores={},
            dimensions={},
            coverage=0.0,
            confidence=0.0,
            check_result_refs=[r.check_id for r in results],
            blocking_gates_failed=len(gate_failures),
            missing_required_inputs=[],
            started_at=started,
            completed_at=completed,
            provenance={
                "source_versions": {
                    "check_master": master.version,
                    "scoring_model": scoring_model_version,
                },
                "created_at": now,
                "created_by": "dcs.assemble",
            },
        )

    dimensions = _score_dimensions(results, master, erp_in_scope=erp_in_scope)
    incomplete = (not sweep_complete) or _required_coverage_incomplete(
        dimensions, master, erp_in_scope=erp_in_scope
    )
    headline, coverage, confidence = _headline_and_overall(
        dimensions, erp_in_scope=erp_in_scope
    )

    if incomplete:
        run_state: RunState = "INCOMPLETE"
        # Keep headline when publishable; gate_fail / incomplete fixtures differ.
        # partial_sweep expects INCOMPLETE; may still have a numeric headline.
    else:
        run_state = _run_state_from_score(
            headline, erp_in_scope=erp_in_scope, incomplete=False
        )

    missing_inputs = [
        r.check_id
        for r in results
        if r.status == "UNKNOWN"
        and isinstance(r.reason_code, str)
        and r.reason_code.startswith("MISSING_INPUT")
    ]

    return DcsRun(
        schema_version="1.0.0",
        tenant_id=tenant,
        run_id=run,
        run_state=run_state,
        scope_model_version=master.scope_model_version,
        scoring_model_version=scoring_model_version or master.scoring_model_version,
        headline_score=None if (incomplete and headline is None) else headline,
        dimension_scores={
            dim: ds.score for dim, ds in dimensions.items()
        },
        dimensions=dimensions,
        coverage=coverage,
        confidence=confidence,
        check_result_refs=[r.check_id for r in results],
        blocking_gates_failed=0,
        missing_required_inputs=missing_inputs,
        started_at=started,
        completed_at=completed,
        provenance={
            "source_versions": {
                "check_master": master.version,
                "scoring_model": scoring_model_version,
            },
            "created_at": now,
            "created_by": "dcs.assemble",
        },
    )
