"""DRIFT checks — all 14 (Excel sheet 02 / PRD-DCS-05).

Read frozen scoring snapshot only. confidence=MEDIUM for distribution
heuristics (PRD-DCS-05). Thresholds provisional when sheet 02 is qualitative.
BR-02/BR-12 → NOT_CONNECTED when erp_in_scope=false.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.catalogue import foundation_gate_meta, root_cause_details
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.types import CheckResult, Confidence, Evidence

# Provisional MVP1 cutovers — Excel sheet 02 is qualitative; BI text used where present.
CI13_FAIL_DEAD_SHARE = 0.40  # Excel BI: ~40% blocked
CI13_WARN_DEAD_SHARE = 0.25
CI14_FAIL_MATCH_RATE = 0.15
CI14_WARN_MATCH_RATE = 0.30
CI15_FAIL_STALE_SHARE = 0.50
CI15_WARN_STALE_SHARE = 0.30
CI15_FAIL_PAIR_STALE_SHARE = 0.50
CI15_WARN_PAIR_STALE_SHARE = 0.30
LE08_FAIL_STALE_SHARE = 0.20
LE08_WARN_STALE_SHARE = 0.05
LE11_FAIL_LOSS_SHARE = 0.20
LE11_WARN_LOSS_SHARE = 0.05
LE11_FAIL_DROP_RISK = 5
# Excel LE-13 BI: "drift caught at 3%" / "at 30%"
LE13_WARN_DELTA = 0.03
LE13_FAIL_DELTA = 0.30
PT14_FAIL_HUGE_SHARE = 0.10
SP12_FAIL_STALE_SHARE = 0.50
SP12_WARN_STALE_SHARE = 0.25
CC12_FAIL_STALE_SHARE = 0.40
CC12_WARN_STALE_SHARE = 0.25
CC12_WARN_MULTI_POLICY = 2  # superseded policy versions present
ME09_FAIL_INVALID_SHARE = 0.10
ME09_WARN_INVALID_SHARE = 0.05
BR02_FAIL_STALE_SHARE = 0.30
BR02_WARN_STALE_SHARE = 0.10
BR12_STALE_HOURS = 48


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _snapshot(ctx: FoundationGateContext) -> dict[str, Any]:
    raw = ctx.extra.get("scoring_snapshot")
    return raw if isinstance(raw, dict) else {}


def _drift(snapshot: dict[str, Any]) -> dict[str, Any]:
    d = snapshot.get("drift")
    return d if isinstance(d, dict) else {}


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
    confidence: Confidence = "MEDIUM",
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


def evaluate_ci_13(ctx: FoundationGateContext) -> CheckResult:
    """Contact state distribution sanity — Excel CI-13."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="CI-13",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            ctx=ctx,
        )
    if not drift or int(drift.get("contacts_scanned") or 0) == 0:
        return _result(
            check_id="CI-13",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:contacts",
            confidence="LOW",
            ctx=ctx,
        )

    dead = float(drift.get("ci13_dead_share") or 0)
    cluster = bool(drift.get("ci13_dead_date_cluster"))
    dist = drift.get("ci13_state_distribution") or {}
    value = {
        "contacts_scanned": drift.get("contacts_scanned"),
        "state_distribution": dist,
        "dead_share": dead,
        "opt_out_share": drift.get("ci13_opt_out_share"),
        "dead_date_cluster": cluster,
        "spike_day": drift.get("ci13_spike_day"),
        "spike_count": drift.get("ci13_spike_count"),
        "spike_share_of_dead": drift.get("ci13_spike_share_of_dead"),
        "thresholds": {
            "fail_dead_share": CI13_FAIL_DEAD_SHARE,
            "warn_dead_share": CI13_WARN_DEAD_SHARE,
            "note": "Excel CI-13: state mix + date clustering of blocked/resigned spikes",
        },
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="drift.contact_state_distribution",
            value=value,
            observed_at=observed,
        )
    ]
    mismatches = [
        {"side": "dead_state", "bucket": k, "count": v}
        for k, v in (dist.items() if isinstance(dist, dict) else [])
        if k in {"blocked", "resigned"} and int(v or 0) > 0
    ]
    if cluster:
        mismatches.append(
            {
                "side": "dead_date_cluster",
                "day": drift.get("ci13_spike_day"),
                "count": drift.get("ci13_spike_count"),
            }
        )
    provenance = {"matches": [], "mismatches": mismatches}

    if dead >= CI13_FAIL_DEAD_SHARE or (cluster and dead >= CI13_WARN_DEAD_SHARE):
        return _result(
            check_id="CI-13",
            status="FAIL",
            reason_code="RC-08",
            root_cause_ids=["RC-08", "RC-15"],
            ctx=ctx,
            detail=(
                f"Dead-state share={dead:.1%} cluster={cluster} "
                f"spike_day={drift.get('ci13_spike_day')}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    if dead >= CI13_WARN_DEAD_SHARE or cluster:
        return _result(
            check_id="CI-13",
            status="WARN",
            reason_code="RC-08",
            root_cause_ids=["RC-08", "RC-15"],
            ctx=ctx,
            detail=f"Elevated dead-state share={dead:.1%} cluster={cluster}.",
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="CI-13",
        status="PASS",
        ctx=ctx,
        detail=f"State distribution OK; dead_share={dead:.1%}.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_ci_15(ctx: FoundationGateContext) -> CheckResult:
    """Contact record freshness — Excel CI-15."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="CI-15",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            ctx=ctx,
        )
    with_ts = int(drift.get("ci15_modified_with_ts") or 0)
    if with_ts == 0:
        return _result(
            check_id="CI-15",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:modifiedOn",
            confidence="LOW",
            ctx=ctx,
        )

    share = float(drift.get("ci15_stale_modified_share") or 0)
    pair_n = int(drift.get("ci15_linked_pairs") or 0)
    pair_share = float(drift.get("ci15_pair_stale_share") or 0)
    value = {
        "modified_with_ts": with_ts,
        "stale_modified_count": drift.get("ci15_stale_modified_count"),
        "stale_modified_share": share,
        "stale_months": drift.get("ci15_stale_months"),
        "linked_pairs": pair_n,
        "pair_stale_count": drift.get("ci15_pair_stale_count"),
        "pair_stale_share": pair_share,
        "pair_lag_days_median": drift.get("ci15_pair_lag_days_median"),
        "pair_lag_sla_days": drift.get("ci15_pair_lag_sla_days"),
        "thresholds": {
            "fail_share": CI15_FAIL_STALE_SHARE,
            "warn_share": CI15_WARN_STALE_SHARE,
            "fail_pair_share": CI15_FAIL_PAIR_STALE_SHARE,
            "warn_pair_share": CI15_WARN_PAIR_STALE_SHARE,
            "note": "Excel CI-15: modifiedOn >24mo + linked pairs vs Shopify updated_at",
        },
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="drift.contact_freshness",
            value=value,
            observed_at=observed,
        )
    ]
    mismatches: list[dict[str, Any]] = []
    if share > 0:
        mismatches.append({"side": "stale_modified", "share": share})
    if pair_n and pair_share > 0:
        mismatches.append({"side": "stale_linked_pair", "share": pair_share})
    provenance = {"matches": [], "mismatches": mismatches}

    fail = share >= CI15_FAIL_STALE_SHARE or (
        pair_n > 0 and pair_share >= CI15_FAIL_PAIR_STALE_SHARE
    )
    warn = share >= CI15_WARN_STALE_SHARE or (
        pair_n > 0 and pair_share >= CI15_WARN_PAIR_STALE_SHARE
    )
    if fail:
        return _result(
            check_id="CI-15",
            status="FAIL",
            reason_code="RC-09",
            root_cause_ids=["RC-09", "RC-01"],
            ctx=ctx,
            detail=(
                f"Stale contacts share={share:.1%}; "
                f"linked-pair lag share={pair_share:.1%} (n={pair_n})."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    if warn:
        return _result(
            check_id="CI-15",
            status="WARN",
            reason_code="RC-09",
            root_cause_ids=["RC-09", "RC-01"],
            ctx=ctx,
            detail=(
                f"Elevated stale share={share:.1%}; "
                f"linked-pair lag share={pair_share:.1%}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="CI-15",
        status="PASS",
        ctx=ctx,
        detail=f"Contact freshness OK; stale_share={share:.1%} pair_lag={pair_share:.1%}.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_le_08(ctx: FoundationGateContext) -> CheckResult:
    """Stale open carts — Excel LE-08."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="LE-08",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            ctx=ctx,
        )
    cart_n = int(drift.get("le08_cart_events") or 0)
    if cart_n == 0:
        return _result(
            check_id="LE-08",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:cart_events",
            confidence="LOW",
            ctx=ctx,
            detail="No CART events in snapshot window — cannot score stale open carts.",
        )

    share = float(drift.get("le08_stale_cart_share") or 0)
    stale_n = int(drift.get("le08_open_stale_carts") or 0)
    value = {
        "cart_events": cart_n,
        "converted_carts": drift.get("le08_converted_carts"),
        "open_stale_carts": stale_n,
        "stale_cart_share": share,
        "stale_days": drift.get("le08_stale_days"),
        "checkouts_present": drift.get("le08_checkouts_present"),
        "thresholds": {
            "fail_share": LE08_FAIL_STALE_SHARE,
            "warn_share": LE08_WARN_STALE_SHARE,
            "note": (
                "Excel LE-08: open carts older than N days; conversion via "
                "PURCHASE externalId / Shopify orders (checkouts when ingested)"
            ),
        },
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="drift.stale_open_carts",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": (
            [{"side": "stale_open_cart", "count": stale_n}] if stale_n else []
        ),
    }

    if share >= LE08_FAIL_STALE_SHARE:
        return _result(
            check_id="LE-08",
            status="FAIL",
            reason_code="RC-05",
            root_cause_ids=["RC-05", "RC-13"],
            ctx=ctx,
            detail=f"Stale open carts={stale_n}/{cart_n} share={share:.1%}.",
            evidence=evidence,
            provenance=provenance,
        )
    if share >= LE08_WARN_STALE_SHARE:
        return _result(
            check_id="LE-08",
            status="WARN",
            reason_code="RC-05",
            root_cause_ids=["RC-05", "RC-13"],
            ctx=ctx,
            detail=f"Some stale open carts share={share:.1%}.",
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="LE-08",
        status="PASS",
        ctx=ctx,
        detail=f"Open cart freshness OK; stale_share={share:.1%}.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_le_13(ctx: FoundationGateContext) -> CheckResult:
    """Event volume drift monitor — Excel LE-13 (7/28 vs Shopify)."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if not shopify_ok or not manago_ok:
        return _result(
            check_id="LE-13",
            status="UNKNOWN" if (shopify_ok or manago_ok) else "NOT_CONNECTED",
            reason_code=(
                "MISSING_INPUT:both_platforms"
                if (shopify_ok or manago_ok)
                else "NO_CONNECTORS_FOR_DRIFT"
            ),
            confidence="LOW",
            ctx=ctx,
        )
    if not drift:
        return _result(
            check_id="LE-13",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:drift",
            confidence="LOW",
            ctx=ctx,
        )

    self_delta = float(drift.get("le13_manago_self_delta") or 0)
    cross_delta = float(drift.get("le13_cross_7d_delta") or 0)
    prior_cross_delta = drift.get("le13_prior_cross_delta")
    manago_prior = int(drift.get("le13_manago_prior_21d") or 0)
    primary = self_delta if manago_prior > 0 else cross_delta
    if prior_cross_delta is not None:
        try:
            primary = max(primary, float(prior_cross_delta))
        except (TypeError, ValueError):
            pass
    value = {
        "manago_7d": drift.get("le13_manago_7d"),
        "manago_prior_21d": manago_prior,
        "shopify_7d": drift.get("le13_shopify_7d"),
        "shopify_orders_7d": drift.get("le13_shopify_orders_7d"),
        "shopify_checkouts_7d": drift.get("le13_shopify_checkouts_7d"),
        "shopify_prior_21d": drift.get("le13_shopify_prior_21d"),
        "manago_self_delta": self_delta,
        "cross_7d_delta": cross_delta,
        "prior_cross_delta": prior_cross_delta,
        "primary_delta": round(primary, 4),
        "thresholds": {
            "fail_delta": LE13_FAIL_DELTA,
            "warn_delta": LE13_WARN_DELTA,
            "note": (
                "Excel LE-13 BI: catch at ~3%; severe at ~30% "
                "(7/28 vs orders+abandoned checkouts)"
            ),
        },
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="drift.event_volume",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {"matches": [], "mismatches": []}

    total = int(drift.get("le13_manago_7d") or 0) + int(
        drift.get("le13_shopify_7d") or 0
    ) + manago_prior
    if total == 0:
        return _result(
            check_id="LE-13",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:event_volume",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            provenance=provenance,
        )

    if primary >= LE13_FAIL_DELTA:
        return _result(
            check_id="LE-13",
            status="FAIL",
            reason_code="RC-05",
            root_cause_ids=["RC-05", "RC-15"],
            ctx=ctx,
            detail=f"Event volume drift delta={primary:.1%}.",
            evidence=evidence,
            provenance=provenance,
        )
    if primary >= LE13_WARN_DELTA:
        return _result(
            check_id="LE-13",
            status="WARN",
            reason_code="RC-05",
            root_cause_ids=["RC-05", "RC-15"],
            ctx=ctx,
            detail=f"Elevated event volume drift delta={primary:.1%}.",
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="LE-13",
        status="PASS",
        ctx=ctx,
        detail=f"Event volume stable; delta={primary:.1%}.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_pt_14(ctx: FoundationGateContext) -> CheckResult:
    """Order value distribution anomaly — Excel PT-14."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="PT-14",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            ctx=ctx,
        )
    n_m = int(drift.get("pt14_manago_values_n") or 0)
    n_s = int(drift.get("pt14_shopify_values_n") or 0)
    if n_m == 0:
        return _result(
            check_id="PT-14",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:purchase_values",
            confidence="LOW",
            ctx=ctx,
        )

    unit = bool(drift.get("pt14_unit_artifact"))
    trunc = bool(drift.get("pt14_truncation_suspect"))
    huge = float(drift.get("pt14_huge_value_share") or 0)
    value = {
        "manago_values_n": n_m,
        "shopify_values_n": n_s,
        "median_manago": drift.get("pt14_median_manago"),
        "median_shopify": drift.get("pt14_median_shopify"),
        "median_ratio": drift.get("pt14_median_ratio"),
        "unit_artifact": unit,
        "truncation_suspect": trunc,
        "huge_value_share": huge,
        "thresholds": {
            "fail_huge_share": PT14_FAIL_HUGE_SHARE,
            "unit_ratio_band": ">=50 or <=0.02 vs Shopify median",
            "note": "Excel PT-14: truncation / ×100 minor-units / test orders excluded",
        },
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="drift.order_value_distribution",
            value=value,
            observed_at=observed,
        )
    ]
    mismatches = []
    if unit:
        mismatches.append(
            {
                "side": "unit_artifact",
                "median_ratio": drift.get("pt14_median_ratio"),
            }
        )
    if trunc:
        mismatches.append({"side": "truncation_suspect"})
    if huge >= PT14_FAIL_HUGE_SHARE:
        mismatches.append({"side": "huge_values", "share": huge})
    provenance = {"matches": [], "mismatches": mismatches}

    if unit or trunc or huge >= PT14_FAIL_HUGE_SHARE:
        return _result(
            check_id="PT-14",
            status="FAIL",
            reason_code="RC-13",
            root_cause_ids=["RC-13", "RC-14", "RC-08"],
            ctx=ctx,
            detail=(
                f"Value shape anomaly unit_artifact={unit} truncation={trunc} "
                f"huge_share={huge:.1%} ratio={drift.get('pt14_median_ratio')}"
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="PT-14",
        status="PASS",
        ctx=ctx,
        detail="Purchase value distribution shape looks consistent.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_sp_08(ctx: FoundationGateContext) -> CheckResult:
    """Segment population sanity — Excel SP-08 (Manago /api/contact/tags)."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="SP-08",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            ctx=ctx,
        )
    tag_n = int(drift.get("sp08_tag_count") or 0)
    if tag_n == 0 and int(drift.get("sp08_zero_population") or 0) == 0:
        return _result(
            check_id="SP-08",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:segments",
            confidence="LOW",
            ctx=ctx,
            detail=(
                "No Manago tags/funnels with population in snapshot "
                "(contact/tags ingest empty and no contact-level tags)."
            ),
        )

    all_tags = list(drift.get("sp08_all_contacts_tags") or [])
    zero_n = int(drift.get("sp08_zero_population") or 0)
    shifted_n = int(drift.get("sp08_shifted_count") or 0)
    from_api = bool(drift.get("sp08_from_api_tags"))
    value = {
        "segment_count": tag_n,
        "from_api_tags": from_api,
        "api_zero_tag_count": drift.get("sp08_api_zero_tag_count"),
        "zero_population": zero_n,
        "zero_population_sample": drift.get("sp08_zero_population_sample"),
        "all_contacts_segment_count": len(all_tags),
        "all_contacts_segments": all_tags[:20],
        "tag_populations_sample": drift.get("sp08_tag_populations_sample"),
        "shifted_count": shifted_n,
        "shifted_sample": drift.get("sp08_shifted_sample"),
        "shift_unavailable": drift.get("sp08_shift_unavailable"),
        "shift_threshold": drift.get("sp08_shift_threshold"),
        "note": (
            "Excel SP-08: 0-pop (prior drop) / all-contacts (contact-proxy only) "
            "/ >50% shift; populations from /api/contact/tags numberOfTagged "
            "when ingested (segmentation-center has no public list API)"
        ),
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="drift.segment_population",
            value=value,
            observed_at=observed,
        )
    ]
    mismatches = [
        {"side": "all_contacts_segment", "tag": t} for t in all_tags[:50]
    ]
    for row in drift.get("sp08_zero_population_sample") or []:
        mismatches.append({"side": "zero_population", "segment": row})
    for row in drift.get("sp08_shifted_sample") or []:
        if isinstance(row, dict):
            mismatches.append({"side": "population_shift", **row})
    provenance = {"matches": [], "mismatches": mismatches[:50]}

    if all_tags or zero_n or shifted_n:
        return _result(
            check_id="SP-08",
            status="FAIL",
            reason_code="RC-06",
            root_cause_ids=["RC-06", "RC-08", "RC-10"],
            ctx=ctx,
            detail=(
                f"Segment sanity failed: all_contacts={len(all_tags)} "
                f"zero_pop={zero_n} shifted={shifted_n}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="SP-08",
        status="PASS",
        confidence="MEDIUM",
        ctx=ctx,
        detail=f"Segment/tag populations look bounded ({tag_n}); shift OK or N/A.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_cc_12(ctx: FoundationGateContext) -> CheckResult:
    """Consent age and re-permission surface — Excel CC-12."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="CC-12",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            ctx=ctx,
        )
    with_ts = int(drift.get("cc12_consent_with_ts") or 0)
    if with_ts == 0:
        return _result(
            check_id="CC-12",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:consent_timestamps",
            confidence="LOW",
            ctx=ctx,
        )

    share = float(drift.get("cc12_stale_consent_share") or 0)
    policy_n = int(drift.get("cc12_policy_version_count") or 0)
    value = {
        "opted_in": drift.get("cc12_opted_in"),
        "consent_with_ts": with_ts,
        "stale_consent_count": drift.get("cc12_stale_consent_count"),
        "stale_consent_share": share,
        "stale_months": drift.get("cc12_stale_months"),
        "policy_versions": drift.get("cc12_policy_versions"),
        "policy_version_count": policy_n,
        "thresholds": {
            "fail_share": CC12_FAIL_STALE_SHARE,
            "warn_share": CC12_WARN_STALE_SHARE,
            "warn_multi_policy": CC12_WARN_MULTI_POLICY,
            "note": "Excel CC-12: consent age + superseded policy versions when tracked",
        },
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="drift.consent_age",
            value=value,
            observed_at=observed,
        )
    ]
    mismatches: list[dict[str, Any]] = []
    if share > 0:
        mismatches.append({"side": "stale_consent", "share": share})
    if policy_n >= CC12_WARN_MULTI_POLICY:
        mismatches.append(
            {
                "side": "multi_policy_version",
                "versions": drift.get("cc12_policy_versions"),
            }
        )
    provenance = {"matches": [], "mismatches": mismatches}

    if share >= CC12_FAIL_STALE_SHARE:
        return _result(
            check_id="CC-12",
            status="FAIL",
            reason_code="RC-09",
            root_cause_ids=["RC-09"],
            ctx=ctx,
            detail=f"Stale consent share={share:.1%}.",
            evidence=evidence,
            provenance=provenance,
        )
    if share >= CC12_WARN_STALE_SHARE or policy_n >= CC12_WARN_MULTI_POLICY:
        return _result(
            check_id="CC-12",
            status="WARN",
            reason_code="RC-09",
            root_cause_ids=["RC-09"],
            ctx=ctx,
            detail=(
                f"Consent freshness concern stale_share={share:.1%} "
                f"policy_versions={policy_n}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="CC-12",
        status="PASS",
        ctx=ctx,
        detail=f"Consent age OK; stale_share={share:.1%}.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_ci_14(ctx: FoundationGateContext) -> CheckResult:
    """Web identity match rate — Excel CI-14 (VISIT / smclient)."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="CI-14",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            ctx=ctx,
        )
    rate = drift.get("ci14_identity_match_rate")
    source = drift.get("ci14_source") or "missing"
    if rate is None or source == "missing":
        return _result(
            check_id="CI-14",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:visit_identity",
            confidence="LOW",
            ctx=ctx,
            detail="No VISIT events or monitored-contact proxy for identity match rate.",
        )

    rate_f = float(rate)
    value = {
        "identity_match_rate": rate_f,
        "visit_total": drift.get("ci14_visit_total"),
        "visit_identified": drift.get("ci14_visit_identified"),
        "monitored_contacts": drift.get("ci14_monitored_contacts"),
        "source": source,
        "thresholds": {
            "fail_below": CI14_FAIL_MATCH_RATE,
            "warn_below": CI14_WARN_MATCH_RATE,
            "note": "Excel CI-14: identified vs anonymous visits / smclient linkage",
        },
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="drift.web_identity_match_rate",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": (
            [{"side": "low_identity_match", "rate": rate_f}]
            if rate_f < CI14_WARN_MATCH_RATE
            else []
        ),
    }
    if rate_f < CI14_FAIL_MATCH_RATE:
        return _result(
            check_id="CI-14",
            status="FAIL",
            reason_code="RC-12",
            root_cause_ids=["RC-12", "RC-03"],
            ctx=ctx,
            detail=f"Web identity match rate={rate_f:.1%} below fail band.",
            evidence=evidence,
            provenance=provenance,
        )
    if rate_f < CI14_WARN_MATCH_RATE:
        return _result(
            check_id="CI-14",
            status="WARN",
            reason_code="RC-12",
            root_cause_ids=["RC-12", "RC-03"],
            ctx=ctx,
            detail=f"Web identity match rate={rate_f:.1%} elevated anonymous share.",
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="CI-14",
        status="PASS",
        ctx=ctx,
        detail=f"Web identity match rate OK ({rate_f:.1%}); source={source}.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_le_11(ctx: FoundationGateContext) -> CheckResult:
    """Event ingestion lag and loss — Excel LE-11 (1h contact-not-exists window)."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="LE-11",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            ctx=ctx,
        )
    events_n = int(drift.get("le11_lifecycle_events") or 0)
    loss_n = int(drift.get("le11_race_loss_orders") or 0)
    drop_risk = int(drift.get("le11_race_drop_risk_events") or 0)
    if events_n == 0 and loss_n == 0 and not _connector_connected(snapshot, "shopify"):
        return _result(
            check_id="LE-11",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:events",
            confidence="LOW",
            ctx=ctx,
        )

    loss_share = float(drift.get("le11_race_loss_share") or 0)
    value = {
        "lifecycle_events": events_n,
        "race_survivor_events": drift.get("le11_race_survivor_events"),
        "race_drop_risk_events": drop_risk,
        "lag_hours_median": drift.get("le11_lag_hours_median"),
        "race_loss_orders": loss_n,
        "race_loss_share": loss_share,
        "race_loss_sample": drift.get("le11_race_loss_sample"),
        "race_hours": drift.get("le11_race_hours"),
        "thresholds": {
            "fail_loss_share": LE11_FAIL_LOSS_SHARE,
            "warn_loss_share": LE11_WARN_LOSS_SHARE,
            "fail_drop_risk_events": LE11_FAIL_DROP_RISK,
            "note": (
                "Excel LE-11: contact-not-exists retry 5m / 1h expiry; "
                "Shopify new-customer orders without Manago PURCHASE = loss proxy"
            ),
        },
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="drift.event_ingestion_lag",
            value=value,
            observed_at=observed,
        )
    ]
    mismatches = []
    if loss_n:
        mismatches.append({"side": "race_loss_orders", "count": loss_n})
    if drop_risk:
        mismatches.append({"side": "race_drop_risk_events", "count": drop_risk})
    provenance = {"matches": [], "mismatches": mismatches}

    if loss_share >= LE11_FAIL_LOSS_SHARE or drop_risk >= LE11_FAIL_DROP_RISK:
        return _result(
            check_id="LE-11",
            status="FAIL",
            reason_code="RC-05",
            root_cause_ids=["RC-05", "RC-15"],
            ctx=ctx,
            detail=(
                f"Event ingestion loss share={loss_share:.1%} "
                f"drop_risk_events={drop_risk}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    if loss_share >= LE11_WARN_LOSS_SHARE or drop_risk > 0:
        return _result(
            check_id="LE-11",
            status="WARN",
            reason_code="RC-05",
            root_cause_ids=["RC-05", "RC-15"],
            ctx=ctx,
            detail=(
                f"Elevated ingestion race risk loss_share={loss_share:.1%} "
                f"drop_risk_events={drop_risk}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="LE-11",
        status="PASS",
        ctx=ctx,
        detail="Event ingestion lag/loss within band.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_sp_12(ctx: FoundationGateContext) -> CheckResult:
    """Property freshness on decision fields — Excel SP-12."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="SP-12",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            ctx=ctx,
        )
    field_n = int(drift.get("sp12_decision_field_count") or 0)
    if field_n == 0:
        return _result(
            check_id="SP-12",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:decision_fields",
            confidence="LOW",
            ctx=ctx,
            detail="No tags/properties on contacts to score decision-field freshness.",
        )

    share = float(drift.get("sp12_stale_field_share") or 0)
    arch = int(drift.get("sp12_archaeology_field_count") or 0)
    value = {
        "decision_field_count": field_n,
        "stale_field_count": drift.get("sp12_stale_field_count"),
        "stale_field_share": share,
        "archaeology_field_count": arch,
        "stale_sample": drift.get("sp12_stale_sample"),
        "sla_days": drift.get("sp12_sla_days"),
        "archaeology_days": drift.get("sp12_archaeology_days"),
        "thresholds": {
            "fail_share": SP12_FAIL_STALE_SHARE,
            "warn_share": SP12_WARN_STALE_SHARE,
            "note": (
                "Excel SP-12: last-write recency for tags/details; "
                "dict DATE props when present; else contact.modifiedOn; "
                "workflow condition keys coverage-only"
            ),
        },
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="drift.property_freshness",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": (
            [{"side": "stale_decision_field", "share": share, "archaeology": arch}]
            if share > 0 or arch
            else []
        ),
    }
    if share >= SP12_FAIL_STALE_SHARE or (
        arch > 0 and share >= SP12_WARN_STALE_SHARE
    ):
        return _result(
            check_id="SP-12",
            status="FAIL",
            reason_code="RC-05",
            root_cause_ids=["RC-05", "RC-10"],
            ctx=ctx,
            detail=f"Stale decision fields share={share:.1%} archaeology={arch}.",
            evidence=evidence,
            provenance=provenance,
        )
    if share >= SP12_WARN_STALE_SHARE or arch > 0:
        return _result(
            check_id="SP-12",
            status="WARN",
            reason_code="RC-05",
            root_cause_ids=["RC-05", "RC-10"],
            ctx=ctx,
            detail=f"Elevated stale decision fields share={share:.1%}.",
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="SP-12",
        status="PASS",
        ctx=ctx,
        detail=f"Decision-field freshness OK; stale_share={share:.1%}.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_me_08(ctx: FoundationGateContext) -> CheckResult:
    """Baseline computability for impact claims — Excel ME-08."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if not shopify_ok and not manago_ok:
        return _result(
            check_id="ME-08",
            status="NOT_CONNECTED",
            reason_code="NO_CONNECTORS_FOR_BASELINE",
            confidence="HIGH",
            ctx=ctx,
        )
    if not drift:
        return _result(
            check_id="ME-08",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:drift",
            confidence="LOW",
            ctx=ctx,
        )

    history = snapshot.get("history_depth") if isinstance(snapshot, dict) else {}
    common_days = None
    if isinstance(history, dict):
        common_days = history.get("common_window_days")

    computable = bool(drift.get("me08_baseline_computable"))
    history_ok = bool(drift.get("me08_history_ok"))
    if common_days is not None:
        try:
            history_ok = history_ok or int(common_days) >= int(
                drift.get("me08_min_history_days") or 30
            )
        except (TypeError, ValueError):
            pass
    volume_ok = bool(drift.get("me08_volume_ok"))
    aov_ok = bool(drift.get("me08_aov_ok"))
    repeat_ok = bool(drift.get("me08_repeat_ok"))
    if common_days is not None and not drift.get("me08_baseline_computable"):
        computable = history_ok and volume_ok and aov_ok

    segment_n = int(drift.get("me08_segment_baseline_n") or 0)
    value = {
        "history_span_days": drift.get("me08_history_span_days"),
        "common_window_days": common_days,
        "paid_order_n": drift.get("me08_paid_order_n"),
        "manago_purchase_n": drift.get("me08_manago_purchase_n"),
        "aov_values_n": drift.get("me08_aov_values_n"),
        "repeat_buyers": drift.get("me08_repeat_buyers"),
        "segment_baseline_n": segment_n,
        "segment_baselines_sample": drift.get("me08_segment_baselines_sample"),
        "history_ok": history_ok,
        "volume_ok": volume_ok,
        "aov_ok": aov_ok,
        "repeat_ok": repeat_ok,
        "baseline_computable": computable,
        "note": (
            "Excel ME-08: sufficient clean history for revenue/AOV/repeat "
            "baselines; AOV-by-tag segment samples when tags present "
            "(ERP margin feed not ingested)"
        ),
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="drift.baseline_computability",
            value=value,
            observed_at=observed,
        )
    ]
    gaps = [
        name
        for name, ok in (
            ("history", history_ok),
            ("volume", volume_ok),
            ("aov", aov_ok),
        )
        if not ok
    ]
    provenance = {"matches": [], "mismatches": [{"side": g} for g in gaps]}

    if not (drift.get("me08_paid_order_n") or drift.get("me08_manago_purchase_n")):
        return _result(
            check_id="ME-08",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:order_history",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            provenance=provenance,
        )
    if not computable:
        return _result(
            check_id="ME-08",
            status="FAIL",
            reason_code="RC-09",
            root_cause_ids=["RC-09"],
            ctx=ctx,
            detail=f"Baseline not computable; gaps={gaps}.",
            evidence=evidence,
            provenance=provenance,
        )
    if not repeat_ok:
        return _result(
            check_id="ME-08",
            status="WARN",
            reason_code="RC-09",
            root_cause_ids=["RC-09"],
            ctx=ctx,
            detail="Baselines computable but repeat-rate cohort is thin.",
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="ME-08",
        status="PASS",
        ctx=ctx,
        detail=(
            "Baseline computability OK for revenue/AOV "
            f"(repeat available; segment_samples={segment_n})."
        ),
        evidence=evidence,
        provenance=provenance,
    )



def evaluate_me_09(ctx: FoundationGateContext) -> CheckResult:
    """Email deliverability posture snapshot — Excel ME-09."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="ME-09",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            ctx=ctx,
        )
    stats_ok = bool(drift.get("me09_stats_available"))
    invalid_seen = bool(drift.get("me09_invalid_field_seen"))
    if int(drift.get("contacts_scanned") or 0) == 0 and not stats_ok:
        return _result(
            check_id="ME-09",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:contacts",
            confidence="LOW",
            ctx=ctx,
        )
    if not stats_ok and not invalid_seen:
        return _result(
            check_id="ME-09",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:bounce_stats",
            confidence="LOW",
            ctx=ctx,
            detail=(
                "Manago email globalConversationStatistics not available and "
                "contact.invalid field absent."
            ),
        )

    invalid_share = float(drift.get("me09_invalid_share") or 0)
    bounce_rate = drift.get("me09_bounce_rate")
    hard_bounce = drift.get("me09_hard_bounce_rate")
    try:
        bounce_f = float(bounce_rate) if bounce_rate is not None else None
    except (TypeError, ValueError):
        bounce_f = None
    try:
        hard_f = float(hard_bounce) if hard_bounce is not None else None
    except (TypeError, ValueError):
        hard_f = None
    # Prefer API bounce rate; fall back to contact.invalid share.
    primary = bounce_f if bounce_f is not None else invalid_share
    dead = float(drift.get("me09_dead_share") or 0)
    value = {
        "bounce_rate": bounce_f,
        "hard_bounce_rate": hard_f,
        "email_sent": drift.get("me09_email_sent"),
        "stats_available": stats_ok,
        "invalid_share": invalid_share,
        "invalid_count": drift.get("me09_invalid_count"),
        "opt_out_share": drift.get("me09_opt_out_share"),
        "dead_share_ci13": dead,
        "primary_rate": primary,
        "thresholds": {
            "fail_rate": ME09_FAIL_INVALID_SHARE,
            "warn_rate": ME09_WARN_INVALID_SHARE,
            "note": (
                "Excel ME-09: prefer api/email/globalConversationStatistics "
                "bounce rates; else contact.invalid proxy; correlate CI-13"
            ),
        },
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="drift.deliverability_posture",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": (
            [{"side": "bounce_or_invalid", "rate": primary}] if primary > 0 else []
        ),
    }
    fail = primary >= ME09_FAIL_INVALID_SHARE or (
        primary >= ME09_WARN_INVALID_SHARE and dead >= CI13_WARN_DEAD_SHARE
    )
    warn = primary >= ME09_WARN_INVALID_SHARE or dead >= CI13_WARN_DEAD_SHARE
    if fail:
        return _result(
            check_id="ME-09",
            status="FAIL",
            reason_code="RC-08",
            root_cause_ids=["RC-08", "RC-15"],
            ctx=ctx,
            detail=(
                f"Deliverability posture damaged rate={primary:.1%} "
                f"dead_share={dead:.1%}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    if warn:
        return _result(
            check_id="ME-09",
            status="WARN",
            reason_code="RC-08",
            root_cause_ids=["RC-08", "RC-15"],
            ctx=ctx,
            detail=f"Deliverability concern rate={primary:.1%}.",
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="ME-09",
        status="PASS",
        ctx=ctx,
        detail=f"Deliverability posture OK; rate={primary:.1%}.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_br_02(ctx: FoundationGateContext) -> CheckResult:
    """Inventory freshness SLA — Excel BR-02 (ERP→Shopify→Manago)."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not getattr(ctx, "erp_in_scope", False):
        return _result(
            check_id="BR-02",
            status="NOT_CONNECTED",
            reason_code="ERP_OUT_OF_SCOPE",
            confidence="HIGH",
            ctx=ctx,
        )

    shop_n = int(drift.get("br02_shopify_inventory_n") or 0)
    man_n = int(drift.get("br02_manago_inventory_n") or 0)
    if shop_n == 0 and man_n == 0:
        return _result(
            check_id="BR-02",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:inventory_timestamps",
            confidence="LOW",
            ctx=ctx,
            detail=(
                "ERP in scope but no inventory update timestamps on Shopify/"
                "Manago catalog surfaces (ERP stock snapshot not ingested)."
            ),
        )

    shop_share = float(drift.get("br02_shopify_stale_share") or 0)
    man_share = float(drift.get("br02_manago_stale_share") or 0)
    primary = max(shop_share, man_share)
    inv_source = drift.get("br02_inventory_source") or "missing"
    value = {
        "shopify_inventory_n": shop_n,
        "manago_inventory_n": man_n,
        "inventory_levels_n": drift.get("br02_inventory_levels_n"),
        "inventory_source": inv_source,
        "shopify_stale_share": shop_share,
        "manago_stale_share": man_share,
        "shopify_median_age_hours": drift.get("br02_shopify_median_age_hours"),
        "manago_median_age_hours": drift.get("br02_manago_median_age_hours"),
        "sla_hours": drift.get("br02_sla_hours"),
        "note": (
            "Excel BR-02: prefer inventory_levels.updated_at; else product "
            "variant ages; ERP stock feed still not ingested"
        ),
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="drift.inventory_freshness",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": (
            [{"side": "stale_inventory", "share": primary}] if primary > 0 else []
        ),
    }
    if primary >= BR02_FAIL_STALE_SHARE:
        return _result(
            check_id="BR-02",
            status="FAIL",
            reason_code="RC-05",
            root_cause_ids=["RC-05"],
            ctx=ctx,
            detail=f"Inventory freshness SLA miss stale_share={primary:.1%}.",
            evidence=evidence,
            provenance=provenance,
        )
    if primary >= BR02_WARN_STALE_SHARE:
        return _result(
            check_id="BR-02",
            status="WARN",
            reason_code="RC-05",
            root_cause_ids=["RC-05"],
            ctx=ctx,
            detail=f"Elevated inventory age share={primary:.1%}.",
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="BR-02",
        status="PASS",
        ctx=ctx,
        detail=f"Inventory freshness within SLA; stale_share={primary:.1%}.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_br_12(ctx: FoundationGateContext) -> CheckResult:
    """ERP sync freshness heartbeat — Excel BR-12."""
    snapshot = _snapshot(ctx)
    drift = _drift(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not getattr(ctx, "erp_in_scope", False):
        return _result(
            check_id="BR-12",
            status="NOT_CONNECTED",
            reason_code="ERP_OUT_OF_SCOPE",
            confidence="HIGH",
            ctx=ctx,
        )

    domain_ages = drift.get("br12_domain_ages_hours") or {}
    if not isinstance(domain_ages, dict) or not domain_ages:
        return _result(
            check_id="BR-12",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:erp_heartbeat",
            confidence="LOW",
            ctx=ctx,
            detail="ERP in scope but no per-domain last-success sync timestamps.",
        )

    stalled = list(drift.get("br12_stalled_domains") or [])
    stale_domains = []
    for name, age in domain_ages.items():
        try:
            if age is None or float(age) > BR12_STALE_HOURS:
                stale_domains.append(name)
        except (TypeError, ValueError):
            stale_domains.append(name)
    value = {
        "domain_ages_hours": domain_ages,
        "stale_domains": stale_domains,
        "stalled_vs_prior": stalled,
        "stale_hours": BR12_STALE_HOURS,
        "heartbeat_source": drift.get("br12_heartbeat_source"),
        "note": (
            "Excel BR-12: last-successful-sync per ERP domain vs cadence; "
            "reads erp connector raw/config when present"
        ),
    }
    evidence = [
        _evidence(
            source="erp",
            locator="drift.erp_sync_heartbeat",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": [{"side": "stale_or_stall", "domain": d} for d in stale_domains],
    }
    if stale_domains or stalled:
        return _result(
            check_id="BR-12",
            status="FAIL" if stale_domains else "WARN",
            reason_code="RC-05",
            root_cause_ids=["RC-05", "RC-15"],
            ctx=ctx,
            detail=(
                f"ERP heartbeat stale_domains={stale_domains} "
                f"stalled_vs_prior={stalled}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="BR-12",
        status="PASS",
        ctx=ctx,
        detail="ERP sync heartbeat fresh across domains.",
        evidence=evidence,
        provenance=provenance,
    )


DRIFT_EXECUTORS = {
    "CI-13": evaluate_ci_13,
    "CI-14": evaluate_ci_14,
    "CI-15": evaluate_ci_15,
    "LE-08": evaluate_le_08,
    "LE-11": evaluate_le_11,
    "LE-13": evaluate_le_13,
    "PT-14": evaluate_pt_14,
    "SP-08": evaluate_sp_08,
    "SP-12": evaluate_sp_12,
    "CC-12": evaluate_cc_12,
    "ME-08": evaluate_me_08,
    "ME-09": evaluate_me_09,
    "BR-02": evaluate_br_02,
    "BR-12": evaluate_br_12,
}
