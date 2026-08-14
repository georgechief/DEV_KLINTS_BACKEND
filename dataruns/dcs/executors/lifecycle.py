"""Lifecycle RULE checks LE-01/02/03/04/05/09 (Excel sheet 02 / PRD-DCS-04).

Read frozen scoring snapshot only — never live HTTP.

Excel sheet 02 detection (authoritative):
- LE-01: per calendar month, Shopify paid non-test orders vs Manago PURCHASE;
  flag months with relative count delta > 2%.
- LE-02: PURCHASE value vs Shopify order totals (monthly); decompose vs LE-01.
- LE-03: share of PURCHASE events carrying externalId (order.id join key).
- LE-04: duplicate PURCHASE per externalId.
- LE-05: exact order-level gap list (Shopify↔Manago).
- LE-09: Shopify refunds/cancels vs Manago RETURN/CANCELLATION on externalId.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.catalogue import foundation_gate_meta, root_cause_details
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.revenue_impact import (
    duplicate_purchase_gmv,
    money_2,
    seal_revenue_on_result,
    snapshot_revenue_context,
)
from dataruns.dcs.types import CheckResult, Confidence, Evidence

# Sheet 02 LE-01: flag months deviating > 2%.
LE01_MONTH_DELTA_FAIL = 0.02
# LE-02 sheet 02 is qualitative (decompose); MVP1 uses same 2% band — flag George.
LE02_VALUE_DELTA_FAIL = 0.02
LE02_VALUE_DELTA_WARN = 0.02
# LE-03 sheet 02 qualitative share; provisional cutovers — flag George.
LE03_PASS_WITH_EXT_SHARE = 0.95
LE03_WARN_WITH_EXT_SHARE = 0.80
# LE-04 provisional (sheet qualitative duplicate rate).
LE04_FAIL_DUP_RATE = 0.02
LE_MISMATCH_SAMPLE = 50


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _snapshot(ctx: FoundationGateContext) -> dict[str, Any]:
    raw = ctx.extra.get("scoring_snapshot")
    return raw if isinstance(raw, dict) else {}


def _lifecycle(snapshot: dict[str, Any]) -> dict[str, Any]:
    life = snapshot.get("lifecycle")
    return life if isinstance(life, dict) else {}


def _connector_connected(snapshot: dict[str, Any], platform: str) -> bool:
    connectors = snapshot.get("connectors")
    if not isinstance(connectors, dict):
        return False
    row = connectors.get(platform)
    if not isinstance(row, dict):
        return False
    return str(row.get("status") or "") in {"connected", "degraded"}


def _with_revenue(
    result: CheckResult,
    *,
    snapshot: dict[str, Any],
    life: dict[str, Any],
    amount: float | None,
    formula_id: str,
    extra: dict[str, Any] | None = None,
) -> CheckResult:
    """Attach PRD-DCS-08 provenance money fields."""
    meta = snapshot_revenue_context(snapshot, life=life)
    return seal_revenue_on_result(
        result,
        amount=amount if amount is not None else 0.0,
        currency=meta.get("currency"),
        formula_id=formula_id,
        window_days=meta.get("window_days"),
        as_of=meta.get("as_of") or result.evaluated_at,
        source=str(meta.get("source") or "db_fallback"),
        extra=extra,
    )


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
            check_id=check_id,
            root_cause_ids=codes,
            detail=detail,
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


def _gap_mismatch_rows(
    *,
    shopify_only: list[Any],
    manago_only: list[Any],
    limit: int = LE_MISMATCH_SAMPLE,
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    truncated = False
    for oid in shopify_only:
        rows.append({"side": "shopify_only", "order.id": str(oid)})
        if len(rows) > limit:
            return rows[:limit], True
    for oid in manago_only:
        rows.append({"side": "manago_only", "order.id": str(oid)})
        if len(rows) > limit:
            return rows[:limit], True
    return rows, truncated


def evaluate_le_01(ctx: FoundationGateContext) -> CheckResult:
    """Purchase event count parity — Excel: monthly delta > 2%."""
    snapshot = _snapshot(ctx)
    life = _lifecycle(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if not shopify_ok and not manago_ok:
        return _result(
            check_id="LE-01",
            status="NOT_CONNECTED",
            reason_code="NO_CONNECTORS_FOR_LIFECYCLE",
            ctx=ctx,
            detail="Neither Shopify nor Manago connected for purchase parity.",
        )
    if not shopify_ok or not manago_ok:
        return _result(
            check_id="LE-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:both_platforms",
            confidence="LOW",
            ctx=ctx,
            detail="LE-01 needs both Shopify orders and Manago PURCHASE events.",
        )
    if not life:
        return _result(
            check_id="LE-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:lifecycle",
            confidence="LOW",
            ctx=ctx,
        )

    shopify_n = int(life.get("shopify_paid_orders") or 0)
    manago_n = int(life.get("manago_purchase_events") or 0)
    monthly = list(life.get("monthly") or [])
    failing_months = [
        m
        for m in monthly
        if isinstance(m, dict)
        and float(m.get("count_delta") or 0) > LE01_MONTH_DELTA_FAIL
        and (int(m.get("shopify_orders") or 0) + int(m.get("manago_purchases") or 0)) > 0
    ]
    denom = max(shopify_n, manago_n, 1)
    overall_delta = abs(shopify_n - manago_n) / denom
    value = {
        "shopify_paid_orders": shopify_n,
        "manago_purchase_events": manago_n,
        "overall_count_delta": round(overall_delta, 6),
        "month_fail_threshold": LE01_MONTH_DELTA_FAIL,
        "failing_months": failing_months,
        "monthly": monthly,
        "excluded_test_orders": life.get("shopify_excluded_test_orders"),
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="lifecycle.purchase_count_parity",
            value=value,
            observed_at=observed,
        )
    ]
    mismatches, _trunc = _gap_mismatch_rows(
        shopify_only=list(life.get("shopify_only") or []),
        manago_only=list(life.get("manago_only") or []),
    )
    provenance = {"matches": [], "mismatches": mismatches}

    if shopify_n == 0 and manago_n == 0:
        return _result(
            check_id="LE-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:orders",
            confidence="LOW",
            ctx=ctx,
            detail="No paid Shopify orders or Manago PURCHASE events in snapshot.",
            evidence=evidence,
            provenance=provenance,
        )

    if failing_months or overall_delta > LE01_MONTH_DELTA_FAIL:
        return _result(
            check_id="LE-01",
            status="FAIL",
            reason_code="RC-01",
            root_cause_ids=["RC-01", "RC-05", "RC-15"],
            ctx=ctx,
            detail=(
                f"Purchase count parity failed: Shopify={shopify_n} Manago={manago_n} "
                f"overall_delta={overall_delta:.2%} failing_months={len(failing_months)}"
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="LE-01",
        status="PASS",
        ctx=ctx,
        detail=(
            f"Purchase counts within {LE01_MONTH_DELTA_FAIL:.0%}: "
            f"Shopify={shopify_n} Manago={manago_n}"
        ),
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_le_02(ctx: FoundationGateContext) -> CheckResult:
    """Purchase value parity — Excel LE-02 decompose missing / field / gross-net."""
    snapshot = _snapshot(ctx)
    life = _lifecycle(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if not shopify_ok or not manago_ok:
        return _result(
            check_id="LE-02",
            status="UNKNOWN" if (shopify_ok or manago_ok) else "NOT_CONNECTED",
            reason_code=(
                "MISSING_INPUT:both_platforms"
                if (shopify_ok or manago_ok)
                else "NO_CONNECTORS_FOR_LIFECYCLE"
            ),
            confidence="LOW",
            ctx=ctx,
        )
    if not life:
        return _result(
            check_id="LE-02",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:lifecycle",
            confidence="LOW",
            ctx=ctx,
        )

    shopify_v = float(
        life.get("shopify_order_value_gross") or life.get("shopify_order_value") or 0
    )
    shopify_net = float(life.get("shopify_order_value_net") or shopify_v)
    manago_v = float(life.get("manago_purchase_value") or 0)
    shopify_n = int(life.get("shopify_paid_orders") or 0)
    manago_n = int(life.get("manago_purchase_events") or 0)
    decomp = life.get("value_decomposition") if isinstance(life.get("value_decomposition"), dict) else {}
    composition = life.get("value_composition") if isinstance(life.get("value_composition"), dict) else {}
    monthly = list(life.get("monthly") or [])
    failing_months = [
        m
        for m in monthly
        if isinstance(m, dict)
        and float(m.get("value_delta") or 0) > LE02_VALUE_DELTA_FAIL
        and (float(m.get("shopify_value") or 0) + float(m.get("manago_value") or 0)) > 0
    ]
    denom = max(shopify_v, manago_v, 1.0)
    overall_delta = abs(shopify_v - manago_v) / denom
    net_delta = abs(shopify_net - manago_v) / max(shopify_net, manago_v, 1.0)
    count_delta = abs(shopify_n - manago_n) / max(shopify_n, manago_n, 1)
    missing_val = float(decomp.get("missing_events_value") or 0)
    extra_val = float(decomp.get("extra_events_value") or 0)
    matched_gross_delta = float(decomp.get("matched_gross_delta") or 0)
    matched_net_delta = float(decomp.get("matched_net_delta") or 0)
    # Residual after removing gap-attributable value (Excel decompose).
    residual = abs(shopify_v - manago_v) - missing_val - extra_val
    if residual < 0:
        residual = 0.0
    drivers: list[str] = []
    if missing_val > 0 or extra_val > 0 or count_delta > LE01_MONTH_DELTA_FAIL:
        drivers.append("missing_or_extra_events(LE-01/LE-05)")
    if matched_gross_delta > matched_net_delta and matched_net_delta <= matched_gross_delta * 0.5:
        drivers.append("gross_vs_net_definition")
    elif matched_gross_delta > 0.01 or matched_net_delta > 0.01:
        drivers.append("value_field_mapping")
    value = {
        "shopify_order_value_gross": round(shopify_v, 4),
        "shopify_order_value_net": round(shopify_net, 4),
        "manago_purchase_value": round(manago_v, 4),
        "overall_value_delta_gross": round(overall_delta, 6),
        "overall_value_delta_net": round(net_delta, 6),
        "overall_count_delta": round(count_delta, 6),
        "value_composition": composition,
        "value_decomposition": decomp,
        "residual_after_gap_value": round(residual, 4),
        "drivers": drivers,
        "failing_months": failing_months,
        "monthly": monthly,
        "thresholds": {
            "fail_delta": LE02_VALUE_DELTA_FAIL,
            "note": "Sheet 02 LE-02 qualitative; MVP1 uses 2% on gross + decomposition — flag George",
        },
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="lifecycle.purchase_value_parity",
            value=value,
            observed_at=observed,
        )
    ]
    mismatches = [
        {"side": "driver", "driver": d} for d in drivers
    ]

    if shopify_n == 0 and manago_n == 0:
        return _with_revenue(
            _result(
                check_id="LE-02",
                status="UNKNOWN",
                reason_code="MISSING_INPUT:orders",
                confidence="LOW",
                ctx=ctx,
                evidence=evidence,
                provenance={"matches": [], "mismatches": mismatches},
            ),
            snapshot=snapshot,
            life=life,
            amount=0.0,
            formula_id="LE-02.missing_events_value.v1",
        )

    if failing_months or overall_delta > LE02_VALUE_DELTA_FAIL:
        detail = (
            f"Value parity failed: gross Shopify={shopify_v:.2f} Manago={manago_v:.2f} "
            f"delta={overall_delta:.2%} net_delta={net_delta:.2%} drivers={drivers}"
        )
        return _with_revenue(
            _result(
                check_id="LE-02",
                status="FAIL",
                reason_code="RC-02",
                root_cause_ids=["RC-02", "RC-13", "RC-14"],
                ctx=ctx,
                detail=detail,
                evidence=evidence,
                provenance={"matches": [], "mismatches": mismatches},
            ),
            snapshot=snapshot,
            life=life,
            amount=missing_val,
            formula_id="LE-02.missing_events_value.v1",
            extra={
                "parity_abs_delta_gross": money_2(abs(shopify_v - manago_v)),
                "residual_after_gaps": money_2(residual),
                "gap_count": int(life.get("shopify_only_count") or 0),
            },
        )
    return _with_revenue(
        _result(
            check_id="LE-02",
            status="PASS",
            ctx=ctx,
            detail=f"Value parity within {LE02_VALUE_DELTA_FAIL:.0%} (gross).",
            evidence=evidence,
            provenance={"matches": [], "mismatches": []},
        ),
        snapshot=snapshot,
        life=life,
        amount=0.0,
        formula_id="LE-02.missing_events_value.v1",
    )


def evaluate_le_03(ctx: FoundationGateContext) -> CheckResult:
    """Order ID (externalId) presence on Manago PURCHASE events."""
    snapshot = _snapshot(ctx)
    life = _lifecycle(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="LE-03",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            ctx=ctx,
        )
    if not life:
        return _result(
            check_id="LE-03",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:lifecycle",
            confidence="LOW",
            ctx=ctx,
        )

    total = int(life.get("manago_purchase_events") or 0)
    # Excel LE-03 requires knowing whether payload carried externalId.
    if not life.get("external_id_known"):
        return _result(
            check_id="LE-03",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:manago_raw_external_id",
            confidence="LOW",
            ctx=ctx,
            detail=(
                "Cannot evaluate externalId presence without Manago raw "
                "ConnectorSnapshot transactions (DB Order.external_id alone is "
                "ambiguous with transactionId)."
            ),
            evidence=[
                _evidence(
                    source="manago_ai",
                    locator="lifecycle.purchase_external_id_presence",
                    value={
                        "manago_purchase_events": total,
                        "external_id_known": False,
                        "raw_enrichment": life.get("raw_enrichment"),
                    },
                    observed_at=observed,
                )
            ],
        )

    with_ext = int(life.get("purchase_with_external_id") or 0)
    without = int(life.get("purchase_without_external_id") or 0)
    share = with_ext / max(total, 1)
    missing_events = [
        {
            "side": "missing_external_id",
            "order.id": str(e.get("order.id") or ""),
            "email": str(e.get("person.email") or ""),
            "join_key_source": e.get("join_key_source"),
        }
        for e in (snapshot.get("events") or [])
        if isinstance(e, dict)
        and str(e.get("type") or "").upper() == "PURCHASE"
        and e.get("has_external_id") is False
    ][:LE_MISMATCH_SAMPLE]
    value = {
        "manago_purchase_events": total,
        "with_external_id": with_ext,
        "without_external_id": without,
        "external_id_share": round(share, 4),
        "external_id_known": True,
        "thresholds": {
            "pass_share": LE03_PASS_WITH_EXT_SHARE,
            "warn_share": LE03_WARN_WITH_EXT_SHARE,
            "note": "Provisional MVP1 shares — sheet 02 qualitative; flag George",
        },
        "raw_enrichment": (life.get("raw_enrichment") or {}).get("external_id_from_raw"),
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="lifecycle.purchase_external_id_presence",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {"matches": [], "mismatches": missing_events}

    if total == 0:
        return _result(
            check_id="LE-03",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:purchase_events",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            provenance=provenance,
        )
    if share >= LE03_PASS_WITH_EXT_SHARE:
        return _result(
            check_id="LE-03",
            status="PASS",
            ctx=ctx,
            detail=f"externalId share={share:.2%} ({with_ext}/{total}).",
            evidence=evidence,
            provenance=provenance,
        )
    if share >= LE03_WARN_WITH_EXT_SHARE:
        return _result(
            check_id="LE-03",
            status="WARN",
            reason_code="RC-02",
            root_cause_ids=["RC-02", "RC-13"],
            ctx=ctx,
            detail=f"Partial externalId share={share:.2%} ({with_ext}/{total}).",
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="LE-03",
        status="FAIL",
        reason_code="RC-02",
        root_cause_ids=["RC-02", "RC-13"],
        ctx=ctx,
        detail=f"Low externalId share={share:.2%} ({with_ext}/{total}).",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_le_04(ctx: FoundationGateContext) -> CheckResult:
    """Duplicate purchase events per order (externalId)."""
    snapshot = _snapshot(ctx)
    life = _lifecycle(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="LE-04",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            ctx=ctx,
        )
    if not life:
        return _result(
            check_id="LE-04",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:lifecycle",
            confidence="LOW",
            ctx=ctx,
        )

    total = int(life.get("manago_purchase_events") or 0)
    clusters = list(life.get("duplicate_purchase_clusters") or [])
    extra = int(life.get("duplicate_extra_events") or 0)
    rate = extra / max(total, 1)
    gmv = float(life.get("duplicate_purchase_gmv") or 0)
    if not gmv and clusters:
        gmv = duplicate_purchase_gmv(
            [c for c in clusters if isinstance(c, dict)]
        )
    mismatches = [
        {
            "side": "duplicate_purchase",
            "order.id": str(c.get("order.id") or ""),
            "count": c.get("count"),
            "values": c.get("values"),
            "representative_value": c.get("representative_value"),
            "cluster_impact": c.get("cluster_impact"),
        }
        for c in clusters
        if isinstance(c, dict)
    ][:LE_MISMATCH_SAMPLE]
    value = {
        "manago_purchase_events": total,
        "duplicate_clusters": len(clusters),
        "duplicate_extra_events": extra,
        "duplicate_rate": round(rate, 4),
        "duplicate_purchase_gmv": money_2(gmv),
        "clusters_sample": clusters[:20],
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="lifecycle.duplicate_purchase_events",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {"matches": [], "mismatches": mismatches}

    if total == 0:
        return _with_revenue(
            _result(
                check_id="LE-04",
                status="UNKNOWN",
                reason_code="MISSING_INPUT:purchase_events",
                confidence="LOW",
                ctx=ctx,
                evidence=evidence,
                provenance=provenance,
            ),
            snapshot=snapshot,
            life=life,
            amount=0.0,
            formula_id="LE-04.duplicate_purchase_gmv.v1",
        )
    if rate > LE04_FAIL_DUP_RATE or len(clusters) > 10:
        return _with_revenue(
            _result(
                check_id="LE-04",
                status="FAIL",
                reason_code="RC-04",
                root_cause_ids=["RC-04", "RC-05", "RC-13"],
                ctx=ctx,
                detail=f"Duplicate PURCHASE rate={rate:.2%} clusters={len(clusters)}.",
                evidence=evidence,
                provenance=provenance,
            ),
            snapshot=snapshot,
            life=life,
            amount=gmv,
            formula_id="LE-04.duplicate_purchase_gmv.v1",
            extra={"gap_count": len(clusters)},
        )
    if clusters:
        return _with_revenue(
            _result(
                check_id="LE-04",
                status="WARN",
                reason_code="RC-04",
                root_cause_ids=["RC-04", "RC-05", "RC-13"],
                ctx=ctx,
                detail=f"Duplicate PURCHASE clusters={len(clusters)}.",
                evidence=evidence,
                provenance=provenance,
            ),
            snapshot=snapshot,
            life=life,
            amount=gmv,
            formula_id="LE-04.duplicate_purchase_gmv.v1",
            extra={"gap_count": len(clusters)},
        )
    return _with_revenue(
        _result(
            check_id="LE-04",
            status="PASS",
            ctx=ctx,
            evidence=evidence,
            provenance=provenance,
        ),
        snapshot=snapshot,
        life=life,
        amount=0.0,
        formula_id="LE-04.duplicate_purchase_gmv.v1",
    )


def evaluate_le_05(ctx: FoundationGateContext) -> CheckResult:
    """Order-level event gap list — Excel LE-05 actionable diff."""
    snapshot = _snapshot(ctx)
    life = _lifecycle(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if not shopify_ok or not manago_ok:
        return _result(
            check_id="LE-05",
            status="UNKNOWN" if (shopify_ok or manago_ok) else "NOT_CONNECTED",
            reason_code=(
                "MISSING_INPUT:both_platforms"
                if (shopify_ok or manago_ok)
                else "NO_CONNECTORS_FOR_LIFECYCLE"
            ),
            confidence="LOW",
            ctx=ctx,
        )
    if not life:
        return _result(
            check_id="LE-05",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:lifecycle",
            confidence="LOW",
            ctx=ctx,
        )

    shopify_n = int(life.get("shopify_paid_orders") or 0)
    manago_n = int(life.get("manago_purchase_events") or 0)
    shopify_only_count = int(life.get("shopify_only_count") or 0)
    manago_only_count = int(life.get("manago_only_count") or 0)
    decomp = (
        life.get("value_decomposition")
        if isinstance(life.get("value_decomposition"), dict)
        else {}
    )
    missing_gmv = float(decomp.get("missing_events_value") or 0)
    mismatches, truncated = _gap_mismatch_rows(
        shopify_only=list(life.get("shopify_only") or []),
        manago_only=list(life.get("manago_only") or []),
    )
    orders_by_id = {
        str(o.get("order.id")): o
        for o in (snapshot.get("orders") or [])
        if isinstance(o, dict) and o.get("order.id") is not None
    }
    for row in mismatches:
        if row.get("side") != "shopify_only":
            continue
        order = orders_by_id.get(str(row.get("order.id") or ""))
        if order:
            row["amount_gross"] = order.get("amount_gross")
            row["currency"] = order.get("currency")
    value = {
        "shopify_paid_orders": shopify_n,
        "manago_purchase_events": manago_n,
        "in_both": life.get("in_both"),
        "shopify_only_count": shopify_only_count,
        "manago_only_count": manago_only_count,
        "missing_events_value": money_2(missing_gmv),
        "manago_events_without_order_id": life.get("manago_events_without_order_id"),
        "heuristic_match_count": life.get("heuristic_match_count"),
        "heuristic_matches": life.get("heuristic_matches") or [],
        "gaps_truncated": truncated or bool(life.get("gaps_truncated")),
        "gap_sample": mismatches,
        "join_spine": "event.externalId ↔ orders.id (fallback email+date+value)",
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="lifecycle.order_level_gaps",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {"matches": [], "mismatches": mismatches}

    if shopify_n == 0 and manago_n == 0:
        return _with_revenue(
            _result(
                check_id="LE-05",
                status="UNKNOWN",
                reason_code="MISSING_INPUT:orders",
                confidence="LOW",
                ctx=ctx,
                evidence=evidence,
                provenance=provenance,
            ),
            snapshot=snapshot,
            life=life,
            amount=0.0,
            formula_id="LE-05.missing_purchase_gmv.v1",
        )
    if shopify_only_count or manago_only_count:
        return _with_revenue(
            _result(
                check_id="LE-05",
                status="FAIL",
                reason_code="RC-01",
                root_cause_ids=["RC-01", "RC-05", "RC-15"],
                ctx=ctx,
                detail=(
                    f"Order-level gaps: shopify_only={shopify_only_count} "
                    f"manago_only={manago_only_count}"
                ),
                evidence=evidence,
                provenance=provenance,
            ),
            snapshot=snapshot,
            life=life,
            amount=missing_gmv,
            formula_id="LE-05.missing_purchase_gmv.v1",
            extra={"gap_count": shopify_only_count},
        )
    return _with_revenue(
        _result(
            check_id="LE-05",
            status="PASS",
            ctx=ctx,
            detail="No order-level PURCHASE gaps by externalId.",
            evidence=evidence,
            provenance=provenance,
        ),
        snapshot=snapshot,
        life=life,
        amount=0.0,
        formula_id="LE-05.missing_purchase_gmv.v1",
    )


def evaluate_le_09(ctx: FoundationGateContext) -> CheckResult:
    """Returns and cancellations reflected — Excel LE-09."""
    snapshot = _snapshot(ctx)
    life = _lifecycle(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if not shopify_ok or not manago_ok:
        return _result(
            check_id="LE-09",
            status="UNKNOWN" if (shopify_ok or manago_ok) else "NOT_CONNECTED",
            reason_code=(
                "MISSING_INPUT:both_platforms"
                if (shopify_ok or manago_ok)
                else "NO_CONNECTORS_FOR_LIFECYCLE"
            ),
            confidence="LOW",
            ctx=ctx,
        )
    if not life:
        return _result(
            check_id="LE-09",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:lifecycle",
            confidence="LOW",
            ctx=ctx,
        )

    coverage = (
        life.get("return_coverage")
        if isinstance(life.get("return_coverage"), dict)
        else {}
    )
    shopify_rc = int(life.get("shopify_refund_cancel_orders") or 0)
    manago_rc = int(life.get("manago_return_cancel_events") or 0)
    shopify_only_n = int(coverage.get("shopify_only_returns_count") or 0)
    manago_only_n = int(coverage.get("manago_only_returns_count") or 0)
    return_value_delta = float(coverage.get("return_value_delta") or 0)
    shopify_return_value = float(coverage.get("shopify_return_value") or 0)
    shopify_only_returns_value = float(
        coverage.get("shopify_only_returns_value") or 0
    )
    raw_ok = bool(
        (life.get("raw_enrichment") or {}).get("return_events_from_raw")
        or (life.get("raw_enrichment") or {}).get("shopify_orders_from_raw")
    )
    mismatches: list[dict[str, Any]] = []
    for oid in coverage.get("shopify_only_returns") or []:
        mismatches.append({"side": "shopify_only_return", "order.id": str(oid)})
    for oid in coverage.get("manago_only_returns") or []:
        mismatches.append({"side": "manago_only_return", "order.id": str(oid)})
    mismatches = mismatches[:LE_MISMATCH_SAMPLE]
    value = {
        "shopify_refund_cancel_orders": shopify_rc,
        "manago_return_cancel_events": manago_rc,
        "shopify_only_returns_count": shopify_only_n,
        "manago_only_returns_count": manago_only_n,
        "shopify_return_value": coverage.get("shopify_return_value"),
        "shopify_only_returns_value": money_2(shopify_only_returns_value),
        "manago_return_value": coverage.get("manago_return_value"),
        "return_value_delta": return_value_delta,
        "return_coverage": coverage,
        "raw_enrichment": life.get("raw_enrichment"),
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="lifecycle.returns_cancellations",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {"matches": [], "mismatches": mismatches}
    formula = "LE-09.missing_return_gmv.v1"

    if shopify_rc == 0 and manago_rc == 0:
        return _with_revenue(
            _result(
                check_id="LE-09",
                status="PASS",
                ctx=ctx,
                detail="No refunds/cancellations on either side in snapshot window.",
                evidence=evidence,
                provenance=provenance,
            ),
            snapshot=snapshot,
            life=life,
            amount=0.0,
            formula_id=formula,
        )

    # Shopify has returns/cancels but Manago RETURN/CANCELLATION stream is empty.
    if shopify_rc > 0 and manago_rc == 0:
        return _with_revenue(
            _result(
                check_id="LE-09",
                status="FAIL",
                reason_code="RC-01",
                root_cause_ids=["RC-01"],
                confidence="HIGH" if raw_ok else "MEDIUM",
                ctx=ctx,
                detail=(
                    f"Shopify refunds/cancels={shopify_rc} but Manago RETURN/"
                    f"CANCELLATION events=0."
                ),
                evidence=evidence,
                provenance=provenance,
            ),
            snapshot=snapshot,
            life=life,
            amount=shopify_return_value,
            formula_id=formula,
            extra={"gap_count": shopify_rc},
        )

    if shopify_only_n or manago_only_n:
        return _with_revenue(
            _result(
                check_id="LE-09",
                status="FAIL",
                reason_code="RC-01",
                root_cause_ids=["RC-01"],
                ctx=ctx,
                detail=(
                    f"Return stream gaps: shopify_only={shopify_only_n} "
                    f"manago_only={manago_only_n} value_delta={return_value_delta:.2%}"
                ),
                evidence=evidence,
                provenance=provenance,
            ),
            snapshot=snapshot,
            life=life,
            amount=shopify_only_returns_value,
            formula_id=formula,
            extra={"gap_count": shopify_only_n},
        )
    if return_value_delta > LE01_MONTH_DELTA_FAIL:
        return _with_revenue(
            _result(
                check_id="LE-09",
                status="WARN",
                reason_code="RC-01",
                root_cause_ids=["RC-01"],
                ctx=ctx,
                detail=(
                    f"Return ids matched but value parity delta={return_value_delta:.2%}."
                ),
                evidence=evidence,
                provenance=provenance,
            ),
            snapshot=snapshot,
            life=life,
            amount=0.0,
            formula_id=formula,
        )
    return _with_revenue(
        _result(
            check_id="LE-09",
            status="PASS",
            ctx=ctx,
            detail="Returns/cancellations matched on externalId with value parity.",
            evidence=evidence,
            provenance=provenance,
        ),
        snapshot=snapshot,
        life=life,
        amount=0.0,
        formula_id=formula,
    )


LIFECYCLE_EXECUTORS = {
    "LE-01": evaluate_le_01,
    "LE-02": evaluate_le_02,
    "LE-03": evaluate_le_03,
    "LE-04": evaluate_le_04,
    "LE-05": evaluate_le_05,
    "LE-09": evaluate_le_09,
}
