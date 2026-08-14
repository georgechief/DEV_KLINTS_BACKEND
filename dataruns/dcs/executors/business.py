"""Business Reality RULE check BR-01 (Excel sheet 02 / PRD-DCS-04 §4c)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.catalogue import foundation_gate_meta, root_cause_details
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.types import CheckResult, Confidence, Evidence

# Sheet 02 qualitative; MVP1: margin share < 0.80 → FAIL when ERP+catalog present.
BR01_MARGIN_PASS_SHARE = 0.80


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _snapshot(ctx: FoundationGateContext) -> dict[str, Any]:
    raw = ctx.extra.get("scoring_snapshot")
    return raw if isinstance(raw, dict) else {}


def _connector_status(snapshot: dict[str, Any], platform: str) -> str:
    connectors = snapshot.get("connectors")
    if not isinstance(connectors, dict):
        return "not_connected"
    row = connectors.get(platform)
    if not isinstance(row, dict):
        return "not_connected"
    return str(row.get("status") or "not_connected")


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


def evaluate_br_01(ctx: FoundationGateContext) -> CheckResult:
    """Margin data coverage per product (Excel BR-01).

    PRD acceptance: ``erp_in_scope=false`` → NOT_CONNECTED.
    When ERP in scope + Manago catalog margin fields present → evaluate share.
    """
    snapshot = _snapshot(ctx)
    observed = ctx.evaluated_at or _utcnow_iso()
    erp_status = _connector_status(snapshot, "erp")
    erp_connected = erp_status in {"connected", "degraded"}
    catalog = snapshot.get("catalog") if isinstance(snapshot.get("catalog"), dict) else {}
    margin = catalog.get("margin") if isinstance(catalog.get("margin"), dict) else {}
    value = {
        "erp_in_scope": bool(ctx.erp_in_scope),
        "erp_connector_status": erp_status,
        "margin": margin,
        "thresholds": {
            "pass_share": BR01_MARGIN_PASS_SHARE,
            "note": "Provisional MVP1 — flag George (sheet 02 qualitative)",
        },
        "note": "Excel: share of active products with margin from ERP cost → Manago catalog.",
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="business.margin_coverage",
            value=value,
            observed_at=observed,
        )
    ]
    if not ctx.erp_in_scope or not erp_connected:
        return _result(
            check_id="BR-01",
            status="NOT_CONNECTED",
            reason_code="ERP_OUT_OF_SCOPE",
            confidence="HIGH",
            ctx=ctx,
            evidence=evidence,
            detail="ERP not in scope / not connected — margin coverage N/A.",
        )
    if not catalog.get("manago_catalog_available"):
        return _result(
            check_id="BR-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:manago_product_catalog",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            detail="ERP in scope but Manago catalog products (margin field) not in snapshot.",
        )
    products = int(margin.get("manago_products") or 0)
    share = float(margin.get("margin_share") or 0)
    unknown = int(margin.get("margin_unknown") or 0)
    if products == 0:
        return _result(
            check_id="BR-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:catalog_products",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
        )
    if share < BR01_MARGIN_PASS_SHARE:
        return _result(
            check_id="BR-01",
            status="FAIL",
            reason_code="RC-01",
            root_cause_ids=["RC-01", "RC-02"],
            ctx=ctx,
            evidence=evidence,
            detail=(
                f"Margin coverage share={share:.2%} unknown={unknown}/{products} "
                f"(pass≥{BR01_MARGIN_PASS_SHARE:.0%})."
            ),
        )
    return _result(
        check_id="BR-01",
        status="PASS",
        ctx=ctx,
        evidence=evidence,
        detail=f"Margin populated on {share:.2%} of {products} catalog products.",
    )


BUSINESS_EXECUTORS = {
    "BR-01": evaluate_br_01,
}
