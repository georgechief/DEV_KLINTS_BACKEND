"""Isolated supplemental executor registry (DCS-09 Step 3).

Never registers into ``dataruns.dcs.executors.registry`` (headline 42).
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from dataruns.dcs.pilot_gates.contract import (
    ERP_SENSITIVE_CHECK_IDS,
    STATUS_NOT_CONNECTED,
    STATUS_UNKNOWN,
    SUPPLEMENTAL_CHECK_IDS,
    is_erp_sensitive,
)
from dataruns.dcs.pilot_gates.context import SupplementalGateContext
from dataruns.dcs.pilot_gates.master import get_supplemental_check
from dataruns.dcs.types import CheckResult, Confidence, Evidence

SupplementalExecutor = Callable[[SupplementalGateContext], CheckResult]

_REGISTRY: dict[str, SupplementalExecutor] = {}

REASON_MISSING_INPUT = "MISSING_INPUT"
REASON_EXECUTOR_PENDING = "MISSING_INPUT:executor_pending"
REASON_ERP_OUT_OF_SCOPE = "NOT_CONNECTED:erp_out_of_scope"
REASON_NO_SNAPSHOT = "MISSING_INPUT:scoring_snapshot"


def register_supplemental_executor(
    check_id: str,
    executor: SupplementalExecutor,
) -> None:
    cid = str(check_id or "").strip().upper()
    if cid not in SUPPLEMENTAL_CHECK_IDS:
        raise KeyError(f"Not a supplemental check id: {check_id!r}")
    _REGISTRY[cid] = executor


def get_supplemental_executor(check_id: str) -> SupplementalExecutor | None:
    return _REGISTRY.get(str(check_id or "").strip().upper())


def registered_supplemental_check_ids() -> set[str]:
    return set(_REGISTRY)


def clear_supplemental_executor_registry() -> None:
    """Test helper — drop registered supplemental executors."""
    _REGISTRY.clear()
    _register_framework_defaults()


def _utcnow_from_ctx(ctx: SupplementalGateContext) -> str:
    return str(ctx.evaluated_at or "")


def _evidence(
    *,
    source: str,
    locator: str,
    value: Any,
    observed_at: str,
) -> Evidence:
    return Evidence(
        source=source,
        locator=locator,
        value=value,
        observed_at=observed_at,
    )


def make_supplemental_result(
    *,
    check_id: str,
    status: str,
    ctx: SupplementalGateContext,
    reason_code: str | None = None,
    message: str | None = None,
    confidence: Confidence = "HIGH",
    evidence: list[Evidence] | None = None,
) -> CheckResult:
    """Build a CheckResult enriched from supplemental master metadata."""
    master = get_supplemental_check(check_id)
    observed = _utcnow_from_ctx(ctx) or "1970-01-01T00:00:00Z"
    return CheckResult(
        check_id=str(check_id).strip().upper(),
        status=status,  # type: ignore[arg-type]
        confidence=confidence,
        evidence=list(evidence or []),
        reason_code=reason_code,
        message=message,
        severity=master.severity if master is not None else None,
        detection_logic=master.detection_logic if master is not None else None,
        tenant_id=ctx.tenant_id,
        run_id=ctx.run_id,
        evaluated_at=observed,
        scoring_model_version="DCS-SUPP-1.0.0",
    )


def result_unknown_missing_input(
    *,
    check_id: str,
    ctx: SupplementalGateContext,
    reason_code: str = REASON_MISSING_INPUT,
    message: str | None = None,
    detail: Any = None,
) -> CheckResult:
    observed = _utcnow_from_ctx(ctx) or "1970-01-01T00:00:00Z"
    return make_supplemental_result(
        check_id=check_id,
        status=STATUS_UNKNOWN,
        ctx=ctx,
        reason_code=reason_code,
        message=message or f"{check_id} missing required inputs.",
        confidence="LOW",
        evidence=[
            _evidence(
                source="pilot_gates",
                locator="inputs",
                value=detail if detail is not None else reason_code,
                observed_at=observed,
            )
        ],
    )


def result_not_connected_erp(
    *,
    check_id: str,
    ctx: SupplementalGateContext,
) -> CheckResult:
    observed = _utcnow_from_ctx(ctx) or "1970-01-01T00:00:00Z"
    return make_supplemental_result(
        check_id=check_id,
        status=STATUS_NOT_CONNECTED,
        ctx=ctx,
        reason_code=REASON_ERP_OUT_OF_SCOPE,
        message=f"{check_id} requires ERP in scope.",
        confidence="HIGH",
        evidence=[
            _evidence(
                source="pilot_gates",
                locator="erp_in_scope",
                value=False,
                observed_at=observed,
            )
        ],
    )


def _executor_pending(ctx: SupplementalGateContext, check_id: str) -> CheckResult:
    """Placeholder until Slice A/B implements detection (PRD STOP_AND_FLAG)."""
    return result_unknown_missing_input(
        check_id=check_id,
        ctx=ctx,
        reason_code=REASON_EXECUTOR_PENDING,
        message=f"{check_id} executor not implemented yet.",
        detail={"pending": True},
    )


def _make_erp_pending(check_id: str) -> SupplementalExecutor:
    def _run(ctx: SupplementalGateContext) -> CheckResult:
        # Framework also short-circuits ERP-out before calling; this is defense in depth.
        if not ctx.erp_in_scope:
            return result_not_connected_erp(check_id=check_id, ctx=ctx)
        return _executor_pending(ctx, check_id)

    return _run


def _register_framework_defaults() -> None:
    """
    Register ERP-sensitive stubs then overwrite with Slice A + Slice B executors.

    ERP stubs cover BR-09 / PT-06 until Slice B registers real evaluators.
    """
    for check_id in sorted(ERP_SENSITIVE_CHECK_IDS):
        if check_id not in _REGISTRY:
            register_supplemental_executor(check_id, _make_erp_pending(check_id))
    # Late imports: slice modules use helpers from this module.
    from dataruns.dcs.pilot_gates.slice_a import SLICE_A_EXECUTORS
    from dataruns.dcs.pilot_gates.slice_b import SLICE_B_EXECUTORS

    for check_id, executor in SLICE_A_EXECUTORS.items():
        register_supplemental_executor(check_id, executor)
    for check_id, executor in SLICE_B_EXECUTORS.items():
        register_supplemental_executor(check_id, executor)


def run_supplemental_check(
    check_id: str,
    *,
    context: SupplementalGateContext,
) -> CheckResult:
    """
    Run one supplemental check.

    Order:
    1. Unknown id → error
    2. ERP-sensitive + erp_in_scope=false → NOT_CONNECTED
    3. Registered executor
    4. Else UNKNOWN + MISSING_INPUT:executor_pending
    """
    cid = str(check_id or "").strip().upper()
    if cid not in SUPPLEMENTAL_CHECK_IDS:
        raise KeyError(f"Not a supplemental check id: {check_id!r}")

    if is_erp_sensitive(cid) and not context.erp_in_scope:
        return result_not_connected_erp(check_id=cid, ctx=context)

    executor = get_supplemental_executor(cid)
    if executor is None:
        return _executor_pending(context, cid)
    return executor(context)


def run_supplemental_checks(
    check_ids: list[str] | None,
    *,
    context: SupplementalGateContext,
) -> list[CheckResult]:
    """
    Run many supplemental checks (stable sorted unique ids).

    ``check_ids is None`` → all 12 (same omit semantics as
    ``resolve_check_ids_for_evaluate``). Empty list → run nothing.
    Unknown / non-supplemental ids are dropped.
    """
    if check_ids is None:
        ids = sorted(SUPPLEMENTAL_CHECK_IDS)
    else:
        ids = sorted(
            {
                str(c).strip().upper()
                for c in check_ids
                if str(c).strip().upper() in SUPPLEMENTAL_CHECK_IDS
            }
        )
    return [run_supplemental_check(cid, context=context) for cid in ids]


def check_result_to_store_row(result: CheckResult) -> dict[str, Any]:
    """Map executor CheckResult → ``save_pilot_gate_eval`` row shape."""
    evidence: list[Any] = []
    for item in result.evidence or []:
        if hasattr(item, "to_dict"):
            evidence.append(item.to_dict())
        elif isinstance(item, dict):
            evidence.append(deepcopy(item))
    row: dict[str, Any] = {
        "check_id": str(result.check_id).strip().upper(),
        "status": str(result.status).strip().upper(),
        "evidence": evidence,
    }
    if result.severity:
        row["severity"] = result.severity
    if result.reason_code:
        row["reason_code"] = result.reason_code
    if result.message:
        row["message"] = result.message
    if result.evaluated_at:
        row["evaluated_at"] = result.evaluated_at
    return row


# Framework defaults: ERP stubs overwritten by Slice A + Slice B.
_register_framework_defaults()
