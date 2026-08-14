"""Product & Transaction RULE checks PT-01/03/04 (Excel sheet 02 / PRD-DCS-04)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.catalogue import foundation_gate_meta, root_cause_details
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.product_truth import PT04_DELTA_FAIL
from dataruns.dcs.revenue_impact import money_2, seal_revenue_on_result
from dataruns.dcs.types import CheckResult, Confidence, Evidence

PT_SAMPLE = 50
# Sheet 02 PT-01: measure dangling-ID rate — qualitative; any dangling → FAIL.
# PT-03 completeness: any missing/surplus/attribute-empty → FAIL when catalog present.


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _snapshot(ctx: FoundationGateContext) -> dict[str, Any]:
    raw = ctx.extra.get("scoring_snapshot")
    return raw if isinstance(raw, dict) else {}


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


def _catalog(snapshot: dict[str, Any]) -> dict[str, Any]:
    c = snapshot.get("catalog")
    return c if isinstance(c, dict) else {}


def catalog_ids_available(catalog: dict[str, Any]) -> bool:
    if catalog.get("manago_catalog_available"):
        return int(catalog.get("manago_catalog_count") or 0) > 0
    return (
        int(catalog.get("shopify_variants_from_line_items") or 0) > 0
        or int(catalog.get("shopify_active_product_count") or 0) > 0
        or int(catalog.get("shopify_products_from_line_items") or 0) > 0
    )


def evaluate_pt_01(ctx: FoundationGateContext) -> CheckResult:
    """Event product IDs resolve in catalog (Excel PT-01)."""
    snapshot = _snapshot(ctx)
    catalog = _catalog(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()
    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="PT-01",
            status="NOT_CONNECTED",
            reason_code="NO_CONNECTOR:manago_ai",
            confidence="LOW",
            ctx=ctx,
        )
    raw = catalog.get("raw_enrichment") or {}
    unique_ids = int(catalog.get("unique_event_product_ids") or 0)
    dangling = int(catalog.get("dangling_count") or 0)
    rate = float(catalog.get("dangling_rate") or 0)
    resolve_target = str(catalog.get("resolve_target") or "")
    manago_cat = bool(catalog.get("manago_catalog_available"))
    value = {
        "unique_event_product_ids": unique_ids,
        "dangling_count": dangling,
        "dangling_rate": rate,
        "resolve_target": resolve_target,
        "manago_catalog_available": manago_cat,
        "dangling_sample": (catalog.get("dangling_sample") or [])[:20],
        "note": (
            "Excel: event products field vs Product Catalog; "
            "MVP1 resolves against Shopify variants when Manago catalog not ingested"
        ),
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="catalog.event_product_resolve",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": [
            {
                "side": "dangling_product_id",
                "product_id": s.get("product_id"),
                "ref_count": s.get("ref_count"),
            }
            for s in (catalog.get("dangling_sample") or [])[:PT_SAMPLE]
            if isinstance(s, dict)
        ],
    }
    if not raw.get("manago_event_products_present") and unique_ids == 0:
        return _result(
            check_id="PT-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:event_products",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            provenance=provenance,
            detail="No products field on Manago PURCHASE/CART events in snapshot.",
        )
    if not catalog_ids_available(catalog):
        return _result(
            check_id="PT-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:product_catalog",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            provenance=provenance,
            detail=(
                "No Manago catalog and no Shopify line-item catalog proxy to resolve against."
            ),
        )
    confidence: Confidence = "HIGH" if manago_cat else "MEDIUM"
    if dangling > 0:
        return _result(
            check_id="PT-01",
            status="FAIL",
            reason_code="RC-02",
            root_cause_ids=["RC-02", "RC-10", "RC-13"],
            confidence=confidence,
            ctx=ctx,
            detail=(
                f"Dangling event product IDs={dangling}/{unique_ids} "
                f"rate={rate:.2%} resolve_target={resolve_target}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="PT-01",
        status="PASS",
        confidence=confidence,
        ctx=ctx,
        detail=f"All {unique_ids} event product IDs resolve via {resolve_target}.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_pt_03(ctx: FoundationGateContext) -> CheckResult:
    """Catalog completeness vs commerce (Excel PT-03)."""
    snapshot = _snapshot(ctx)
    catalog = _catalog(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()
    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if not shopify_ok or not manago_ok:
        return _result(
            check_id="PT-03",
            status="UNKNOWN" if (shopify_ok or manago_ok) else "NOT_CONNECTED",
            reason_code="MISSING_INPUT:both_platforms",
            confidence="LOW",
            ctx=ctx,
        )
    pt03 = catalog.get("pt03") if isinstance(catalog.get("pt03"), dict) else {}
    value = {
        "manago_catalog_available": bool(catalog.get("manago_catalog_available")),
        "pt03": pt03,
        "shopify_products_from_line_items": catalog.get(
            "shopify_products_from_line_items"
        ),
        "note": "Excel requires Manago v3 catalogList vs active Shopify products.",
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="catalog.completeness_vs_commerce",
            value=value,
            observed_at=observed,
        )
    ]
    if not catalog.get("manago_catalog_available"):
        return _result(
            check_id="PT-03",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:manago_product_catalog",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            detail=(
                "Manago v3 product catalog not ingested; cannot compare completeness "
                f"vs Shopify active set ({pt03.get('shopify_active_count') or 0} from line items)."
            ),
        )
    missing = int(pt03.get("missing_in_manago") or 0)
    surplus = int(pt03.get("surplus_in_manago") or 0)
    empty = int(pt03.get("attribute_empty") or 0)
    provenance = {
        "matches": [],
        "mismatches": [
            {"side": "missing_in_manago", "product_id": pid}
            for pid in (pt03.get("missing_sample") or [])[:PT_SAMPLE]
        ]
        + [
            {"side": "surplus_in_manago", "product_id": pid}
            for pid in (pt03.get("surplus_sample") or [])[:PT_SAMPLE]
        ],
    }
    if missing or surplus or empty:
        return _result(
            check_id="PT-03",
            status="FAIL",
            reason_code="RC-01",
            root_cause_ids=["RC-01", "RC-05", "RC-10"],
            ctx=ctx,
            detail=(
                f"Catalog incompleteness: missing={missing} surplus={surplus} "
                f"attribute_empty={empty}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="PT-03",
        status="PASS",
        ctx=ctx,
        detail="Manago catalog matches Shopify active assortment.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_pt_04(ctx: FoundationGateContext) -> CheckResult:
    """Net vs gross transaction truth per contact (Excel PT-04)."""
    snapshot = _snapshot(ctx)
    truth = snapshot.get("product_truth")
    truth = truth if isinstance(truth, dict) else {}
    observed = ctx.evaluated_at or _utcnow_iso()

    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if not shopify_ok or not manago_ok:
        return _result(
            check_id="PT-04",
            status="UNKNOWN" if (shopify_ok or manago_ok) else "NOT_CONNECTED",
            reason_code=(
                "MISSING_INPUT:both_platforms"
                if (shopify_ok or manago_ok)
                else "NO_CONNECTORS_FOR_PRODUCT_TRUTH"
            ),
            confidence="LOW",
            ctx=ctx,
        )
    raw = truth.get("raw_enrichment") or {}
    if not raw.get("shopify_from_raw") or not raw.get("manago_from_raw"):
        return _result(
            check_id="PT-04",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:product_truth_raw",
            confidence="LOW",
            ctx=ctx,
            detail="PT-04 needs Shopify orders/customers + Manago transactions in raw snapshot.",
        )
    if not truth:
        return _result(
            check_id="PT-04",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:product_truth",
            confidence="LOW",
            ctx=ctx,
        )

    linked = int(truth.get("linked_contacts") or 0)
    over = int(truth.get("contacts_over_delta") or 0)
    refund_blind = int(truth.get("contacts_refund_blind") or 0)
    total_over = float(truth.get("total_overstatement") or 0)
    failing = list(truth.get("failing_sample") or [])
    value = {
        "linked_contacts": linked,
        "contacts_over_delta": over,
        "contacts_refund_blind": refund_blind,
        "total_overstatement": money_2(total_over),
        "fail_delta": truth.get("fail_delta") or PT04_DELTA_FAIL,
        "failing_sample": failing[:20],
        "refund_blind_sample": (truth.get("refund_blind_sample") or [])[:20],
        "note": "Manago lifetime (deduped externalId) vs Shopify net (paid − refunds/cancels)",
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="product_truth.net_vs_gross_per_contact",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": [
            {
                "side": "net_overstatement",
                "person.email": r.get("person.email"),
                "shopify_customer_id": r.get("shopify_customer_id"),
                "manago_contact_id": r.get("manago_contact_id"),
                "shopify_net": r.get("shopify_net"),
                "manago_purchase_value_deduped": r.get("manago_purchase_value_deduped"),
                "delta_vs_net": r.get("delta_vs_net"),
                "refund_blind": r.get("refund_blind"),
                "overstatement": r.get("overstatement"),
            }
            for r in failing[:PT_SAMPLE]
            if isinstance(r, dict)
        ],
    }
    if linked == 0:
        return seal_revenue_on_result(
            _result(
                check_id="PT-04",
                status="UNKNOWN",
                reason_code="MISSING_INPUT:linked_contacts",
                confidence="LOW",
                ctx=ctx,
                evidence=evidence,
                provenance=provenance,
            ),
            amount=0.0,
            currency=None,
            formula_id="PT-04.ltv_overstatement.v1",
            window_days=None,
            as_of=observed,
            source=(
                "snapshot_raw"
                if raw.get("shopify_from_raw") and raw.get("manago_from_raw")
                else "db_fallback"
            ),
            extra={"revenue_scope": "lifetime_linked_contacts"},
        )
    if over > 0 or refund_blind > 0:
        return seal_revenue_on_result(
            _result(
                check_id="PT-04",
                status="FAIL",
                reason_code="RC-01",
                root_cause_ids=["RC-01"],
                ctx=ctx,
                detail=(
                    f"Per-contact net truth failed: over_delta={over}/{linked} "
                    f"refund_blind={refund_blind} total_overstatement={total_over:.2f}"
                ),
                evidence=evidence,
                provenance=provenance,
            ),
            amount=total_over,
            currency=None,
            formula_id="PT-04.ltv_overstatement.v1",
            window_days=None,
            as_of=observed,
            source=(
                "snapshot_raw"
                if raw.get("shopify_from_raw") and raw.get("manago_from_raw")
                else "db_fallback"
            ),
            extra={
                "revenue_scope": "lifetime_linked_contacts",
                "gap_count": over + refund_blind,
            },
        )
    return seal_revenue_on_result(
        _result(
            check_id="PT-04",
            status="PASS",
            ctx=ctx,
            detail=f"Net vs Manago lifetime within {PT04_DELTA_FAIL:.0%} on {linked} contacts.",
            evidence=evidence,
            provenance=provenance,
        ),
        amount=0.0,
        currency=None,
        formula_id="PT-04.ltv_overstatement.v1",
        window_days=None,
        as_of=observed,
        source=(
            "snapshot_raw"
            if raw.get("shopify_from_raw") and raw.get("manago_from_raw")
            else "db_fallback"
        ),
        extra={"revenue_scope": "lifetime_linked_contacts"},
    )


PRODUCT_EXECUTORS = {
    "PT-01": evaluate_pt_01,
    "PT-03": evaluate_pt_03,
    "PT-04": evaluate_pt_04,
}
