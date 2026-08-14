"""Measurement RULE check ME-02 (Excel sheet 02 / PRD-DCS-04 §4c)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.catalogue import foundation_gate_meta, root_cause_details
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.types import CheckResult, Confidence, Evidence


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _snapshot(ctx: FoundationGateContext) -> dict[str, Any]:
    raw = ctx.extra.get("scoring_snapshot")
    return raw if isinstance(raw, dict) else {}


def _measurement(snapshot: dict[str, Any]) -> dict[str, Any]:
    m = snapshot.get("measurement")
    return m if isinstance(m, dict) else {}


def _connector_connected(snapshot: dict[str, Any], platform: str) -> bool:
    connectors = snapshot.get("connectors")
    if not isinstance(connectors, dict):
        return False
    row = connectors.get(platform)
    if not isinstance(row, dict):
        return False
    return str(row.get("status") or "") in {"connected", "degraded"}


def _evidence(*, source: str, locator: str, value: Any, observed_at: str) -> Evidence:
    return Evidence(
        source=source, locator=locator, value=value, observed_at=observed_at
    )


def _result(
    *,
    check_id: str,
    status: str,
    ctx: FoundationGateContext,
    confidence: Confidence = "HIGH",
    reason_code: str | None = None,
    root_cause_ids: list[str] | None = None,
    detail: str | None = None,
    evidence: list[Evidence] | None = None,
    provenance: dict[str, Any] | None = None,
) -> CheckResult:
    meta = foundation_gate_meta(check_id)
    if not meta.get("check_name"):
        meta = {
            "check_name": check_id,
            "severity": None,
            "root_cause_ids": root_cause_ids or [],
            "suggested_fix": None,
            "detection_logic": None,
        }
    codes = list(root_cause_ids or [])
    if not codes and reason_code and str(reason_code).startswith("RC-"):
        codes = [str(reason_code)]
    if status == "FAIL" and not codes:
        codes = list(meta.get("root_cause_ids") or [])
    message = None
    suggested_fix = meta.get("suggested_fix")
    if status == "FAIL" and codes:
        from dataruns.dcs.catalogue import build_failure_message

        message = build_failure_message(
            check_id=check_id, root_cause_ids=codes, detail=detail
        )
    elif detail:
        message = detail
    return CheckResult(
        check_id=check_id,
        status=status,  # type: ignore[arg-type]
        confidence=confidence,
        evidence=evidence or [],
        reason_code=reason_code,
        tenant_id=ctx.tenant_id,
        run_id=ctx.run_id,
        evaluated_at=ctx.evaluated_at or _utcnow_iso(),
        severity=meta.get("severity"),
        root_cause_ids=codes,
        root_causes=root_cause_details(codes) if codes else [],
        message=message,
        suggested_fix=suggested_fix,
        detection_logic=meta.get("detection_logic"),
        provenance=provenance,
    )


def evaluate_me_02(ctx: FoundationGateContext) -> CheckResult:
    """Workflow revenue attribution wiring (Excel ME-02)."""
    snapshot = _snapshot(ctx)
    measurement = _measurement(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()
    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="ME-02",
            status="NOT_CONNECTED",
            reason_code="NO_CONNECTOR:manago_ai",
            confidence="LOW",
            ctx=ctx,
        )
    value = {
        "workflows_available": measurement.get("workflows_available"),
        "live_workflow_count": measurement.get("live_workflow_count"),
        "with_purchase_linkage": measurement.get("with_purchase_linkage"),
        "zero_outcome_path": measurement.get("zero_outcome_path"),
        "funnel_membership_ids_seen": measurement.get("funnel_membership_ids_seen"),
        "note": "Requires Manago workflow definitions + analytics ingest.",
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="measurement.workflow_revenue_attribution",
            value=value,
            observed_at=observed,
        )
    ]
    if not measurement.get("workflows_available"):
        return _result(
            check_id="ME-02",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:workflows",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            detail=(
                "Workflow definitions/analytics not in scoring snapshot; "
                "cannot verify PURCHASE linkage on live automations."
            ),
        )
    live = int(measurement.get("live_workflow_count") or 0)
    zero = int(measurement.get("zero_outcome_path") or 0)
    linked = int(measurement.get("with_purchase_linkage") or 0)
    if live == 0:
        return _result(
            check_id="ME-02",
            status="PASS",
            ctx=ctx,
            detail="No live workflows — revenue attribution N/A.",
            evidence=evidence,
        )
    if zero > 0:
        return _result(
            check_id="ME-02",
            status="FAIL",
            reason_code="RC-12",
            root_cause_ids=["RC-12"],
            ctx=ctx,
            detail=(
                f"Live workflows with zero measurable outcome path={zero}/{live} "
                f"(linked={linked})."
            ),
            evidence=evidence,
            provenance={
                "matches": [],
                "mismatches": list(measurement.get("zero_outcome_sample") or [])[:50],
            },
        )
    return _result(
        check_id="ME-02",
        status="PASS",
        ctx=ctx,
        detail=f"All {live} live workflows have measurement/analytics wired.",
        evidence=evidence,
    )


MEASUREMENT_EXECUTORS = {
    "ME-02": evaluate_me_02,
}
