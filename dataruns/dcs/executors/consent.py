"""Channel & Consent RULE checks CC-01/02/03/05 (Excel sheet 02 / PRD-DCS-04 §4b).

Read frozen scoring snapshot only. Quadrant matrix + provenance + opt-out
propagation from consent_join (Shopify/Manago raw).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.catalogue import foundation_gate_meta, root_cause_details
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.types import CheckResult, Confidence, Evidence

# Sheet 02 qualitative; MVP1: any compliance out/in → FAIL; any other mismatch → FAIL.
# Provenance share cutovers provisional — flag George (sheet 02 silent on %).
CC03_PASS_PROVENANCE_SHARE = 0.95
CC03_WARN_PROVENANCE_SHARE = 0.80
# Propagation lag WARN band provisional — flag George (sheet 02: "measure lag" only).
CC05_LAG_WARN_SECONDS = 24 * 3600
CC_SAMPLE = 50


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _snapshot(ctx: FoundationGateContext) -> dict[str, Any]:
    raw = ctx.extra.get("scoring_snapshot")
    return raw if isinstance(raw, dict) else {}


def _consent(snapshot: dict[str, Any]) -> dict[str, Any]:
    c = snapshot.get("consent")
    return c if isinstance(c, dict) else {}


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


def _require_consent_inputs(
    *,
    check_id: str,
    ctx: FoundationGateContext,
    need_both: bool = True,
) -> CheckResult | tuple[dict[str, Any], dict[str, Any], str]:
    snapshot = _snapshot(ctx)
    consent = _consent(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()
    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if need_both:
        if not shopify_ok and not manago_ok:
            return _result(
                check_id=check_id,
                status="NOT_CONNECTED",
                reason_code="NO_CONNECTORS_FOR_CONSENT",
                ctx=ctx,
            )
        if not shopify_ok or not manago_ok:
            return _result(
                check_id=check_id,
                status="UNKNOWN",
                reason_code="MISSING_INPUT:both_platforms",
                confidence="LOW",
                ctx=ctx,
            )
    elif not manago_ok:
        return _result(
            check_id=check_id,
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            ctx=ctx,
        )
    raw = consent.get("raw_enrichment") or {}
    if need_both and not raw.get("consent_fields_present"):
        return _result(
            check_id=check_id,
            status="UNKNOWN",
            reason_code="MISSING_INPUT:consent_raw",
            confidence="LOW",
            ctx=ctx,
            detail="Consent fields require Shopify customers + Manago contacts in ConnectorSnapshot raw.",
        )
    if not need_both and not raw.get("manago_contacts_from_raw"):
        return _result(
            check_id=check_id,
            status="UNKNOWN",
            reason_code="MISSING_INPUT:manago_consent_raw",
            confidence="LOW",
            ctx=ctx,
        )
    if not consent:
        return _result(
            check_id=check_id,
            status="UNKNOWN",
            reason_code="MISSING_INPUT:consent",
            confidence="LOW",
            ctx=ctx,
        )
    return snapshot, consent, observed


def evaluate_cc_01(ctx: FoundationGateContext) -> CheckResult:
    """Email opt-in parity — four-quadrant matrix (Excel CC-01)."""
    loaded = _require_consent_inputs(check_id="CC-01", ctx=ctx, need_both=True)
    if isinstance(loaded, CheckResult):
        return loaded
    _snapshot_data, consent, observed = loaded
    matrix = consent.get("email_quadrant_matrix") or {}
    linked = int(consent.get("linked_identities") or 0)
    compliance = int(consent.get("compliance_exposure_email") or 0)
    lost = int(consent.get("lost_reach_email") or 0)
    mismatches = int(consent.get("email_mismatches") or 0)
    samples = (consent.get("mismatch_samples") or {}).get("email_out_in") or []
    samples += (consent.get("mismatch_samples") or {}).get("email_in_out") or []
    field_cov = (
        consent.get("email_field_coverage")
        if isinstance(consent.get("email_field_coverage"), dict)
        else {}
    )
    value = {
        "linked_identities": linked,
        "email_quadrant_matrix": matrix,
        "compliance_exposure_out_in": compliance,
        "lost_reach_in_out": lost,
        "mismatches": mismatches,
        # Excel CC-01 inputs: state + opt_in_level + consent_updated_at
        "opt_in_level_distribution": field_cov.get("opt_in_level_distribution") or {},
        "consent_updated_at_present": field_cov.get("consent_updated_at_present"),
        "consent_updated_at_share": field_cov.get("consent_updated_at_share"),
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="consent.email_opt_in_parity",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": [
            {
                "side": s.get("email_quadrant"),
                "person.email": s.get("person.email"),
                "shopify_customer_id": s.get("shopify_customer_id"),
                "manago_contact_id": s.get("manago_contact_id"),
                "channel": "email",
                "shopify_email_opt_in_level": s.get("shopify_email_opt_in_level"),
                "shopify_email_consent_updated_at": s.get(
                    "shopify_email_consent_updated_at"
                ),
                "manago_modified_on": s.get("manago_modified_on"),
            }
            for s in samples[:CC_SAMPLE]
        ],
    }
    if linked == 0:
        return _result(
            check_id="CC-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:linked_identities",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            provenance=provenance,
        )
    if compliance > 0:
        return _result(
            check_id="CC-01",
            status="FAIL",
            reason_code="RC-07",
            root_cause_ids=["RC-07", "RC-05", "RC-01"],
            ctx=ctx,
            detail=(
                f"Email consent compliance exposure: out_in={compliance} "
                f"(Shopify out / Manago in). matrix={matrix}"
            ),
            evidence=evidence,
            provenance=provenance,
        )
    if mismatches > 0:
        return _result(
            check_id="CC-01",
            status="FAIL",
            reason_code="RC-07",
            root_cause_ids=["RC-07", "RC-05", "RC-01"],
            ctx=ctx,
            detail=(
                f"Email consent quadrant mismatches={mismatches} "
                f"lost_reach_in_out={lost} matrix={matrix}"
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="CC-01",
        status="PASS",
        ctx=ctx,
        detail=f"Email consent parity on {linked} linked identities.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_cc_02(ctx: FoundationGateContext) -> CheckResult:
    """SMS / mobile consent parity — four-quadrant (Excel CC-02)."""
    loaded = _require_consent_inputs(check_id="CC-02", ctx=ctx, need_both=True)
    if isinstance(loaded, CheckResult):
        return loaded
    _snapshot_data, consent, observed = loaded
    matrix = consent.get("sms_quadrant_matrix") or {}
    linked = int(consent.get("linked_identities") or 0)
    compliance = int(consent.get("compliance_exposure_sms") or 0)
    lost = int(consent.get("lost_reach_sms") or 0)
    mismatches = int(consent.get("sms_mismatches") or 0)
    samples = (consent.get("mismatch_samples") or {}).get("sms_out_in") or []
    samples += (consent.get("mismatch_samples") or {}).get("sms_in_out") or []
    reach = (
        consent.get("sms_phone_reachability")
        if isinstance(consent.get("sms_phone_reachability"), dict)
        else {}
    )
    unreachable = int(reach.get("consented_but_unreachable") or 0)
    unreachable_samples = (consent.get("mismatch_samples") or {}).get(
        "consented_unreachable_sms"
    ) or []
    value = {
        "linked_identities": linked,
        "sms_quadrant_matrix": matrix,
        "compliance_exposure_out_in": compliance,
        "lost_reach_in_out": lost,
        "mismatches": mismatches,
        # Excel CC-02: phone validity (CI-09) checked jointly — soft surface only.
        "sms_phone_reachability": reach,
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="consent.sms_opt_in_parity",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": [
            {
                "side": s.get("sms_quadrant"),
                "person.email": s.get("person.email"),
                "shopify_customer_id": s.get("shopify_customer_id"),
                "manago_contact_id": s.get("manago_contact_id"),
                "channel": "sms",
            }
            for s in samples[:CC_SAMPLE]
        ]
        + [
            {
                "side": "consented_but_unreachable",
                "person.email": s.get("person.email"),
                "person.phone": s.get("person.phone"),
                "shopify_customer_id": s.get("shopify_customer_id"),
                "manago_contact_id": s.get("manago_contact_id"),
                "channel": "sms",
                "phone_valid": s.get("phone_valid"),
                "note": "CI-09-lite joint surface (not a scored CI-09 result)",
            }
            for s in unreachable_samples[:CC_SAMPLE]
        ],
    }
    if linked == 0:
        return _result(
            check_id="CC-02",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:linked_identities",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            provenance=provenance,
        )
    if compliance > 0:
        return _result(
            check_id="CC-02",
            status="FAIL",
            reason_code="RC-07",
            root_cause_ids=["RC-07", "RC-05"],
            ctx=ctx,
            detail=(
                f"SMS consent compliance exposure: out_in={compliance} matrix={matrix}"
            ),
            evidence=evidence,
            provenance=provenance,
        )
    if mismatches > 0:
        return _result(
            check_id="CC-02",
            status="FAIL",
            reason_code="RC-07",
            root_cause_ids=["RC-07", "RC-05"],
            ctx=ctx,
            detail=(
                f"SMS consent mismatches={mismatches} lost_reach={lost} matrix={matrix}"
                + (
                    f"; consented_but_unreachable={unreachable} (CI-09-lite)"
                    if unreachable
                    else ""
                )
            ),
            evidence=evidence,
            provenance=provenance,
        )
    detail = f"SMS consent parity on {linked} linked identities."
    if unreachable:
        detail += (
            f" Surfaced consented-but-unreachable={unreachable} (CI-09-lite joint)."
        )
    return _result(
        check_id="CC-02",
        status="PASS",
        ctx=ctx,
        detail=detail,
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_cc_03(ctx: FoundationGateContext) -> CheckResult:
    """Consent provenance completeness on Manago opted-in contacts (Excel CC-03)."""
    loaded = _require_consent_inputs(check_id="CC-03", ctx=ctx, need_both=False)
    if isinstance(loaded, CheckResult):
        return loaded
    _snapshot_data, consent, observed = loaded
    opted_in = int(consent.get("opted_in_manago_email") or 0)
    with_prov = int(consent.get("opted_in_with_provenance") or 0)
    weak = int(consent.get("opted_in_weak_or_missing_provenance") or 0)
    share = float(consent.get("provenance_share") or 0)
    shopify_backfill = int(consent.get("shopify_evidence_backfill_candidates") or 0)
    manago_only = int(consent.get("manago_only_unevidenced_optins") or 0)
    samples = (consent.get("mismatch_samples") or {}).get("weak_provenance") or []
    shopify_samples = (consent.get("mismatch_samples") or {}).get(
        "shopify_holds_evidence"
    ) or []
    unevidenced_samples = (consent.get("mismatch_samples") or {}).get(
        "manago_only_unevidenced"
    ) or []
    value = {
        "opted_in_manago_email": opted_in,
        "with_provenance": with_prov,
        "weak_or_missing_provenance": weak,
        "provenance_share": share,
        # Excel: customers.consent_updated_at cross-ref cohorts
        "shopify_evidence_backfill_candidates": shopify_backfill,
        "manago_only_unevidenced_optins": manago_only,
        "thresholds": {
            "pass_share": CC03_PASS_PROVENANCE_SHARE,
            "warn_share": CC03_WARN_PROVENANCE_SHARE,
            "note": (
                "Provisional MVP1; agent-set opt-ins = empty consents[] (Excel NOTE); "
                "flag George for share cutovers"
            ),
        },
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="consent.provenance_completeness",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": [
            {
                "side": "weak_provenance",
                "person.email": s.get("person.email"),
                "manago_contact_id": s.get("manago_contact_id"),
                "provenance_note": s.get("provenance_note"),
            }
            for s in samples[:CC_SAMPLE]
        ]
        + [
            {
                "side": "shopify_holds_evidence",
                "person.email": s.get("person.email"),
                "manago_contact_id": s.get("manago_contact_id"),
                "shopify_customer_id": s.get("shopify_customer_id"),
                "shopify_email_consent_updated_at": s.get(
                    "shopify_email_consent_updated_at"
                ),
                "shopify_email_opt_in_level": s.get("shopify_email_opt_in_level"),
                "note": "Backfill candidate — Shopify has evidence, Manago does not",
            }
            for s in shopify_samples[:CC_SAMPLE]
        ]
        + [
            {
                "side": "manago_only_unevidenced",
                "person.email": s.get("person.email"),
                "manago_contact_id": s.get("manago_contact_id"),
                "provenance_note": s.get("provenance_note"),
                "note": "Re-permission cohort — no Shopify consent_updated_at evidence",
            }
            for s in unevidenced_samples[:CC_SAMPLE]
        ],
    }
    if opted_in == 0:
        return _result(
            check_id="CC-03",
            status="PASS",
            ctx=ctx,
            detail="No Manago email opt-ins in snapshot — provenance N/A.",
            evidence=evidence,
            provenance=provenance,
        )
    cohort_note = (
        f" shopify_backfill={shopify_backfill} manago_only_unevidenced={manago_only}."
    )
    if share >= CC03_PASS_PROVENANCE_SHARE:
        return _result(
            check_id="CC-03",
            status="PASS",
            ctx=ctx,
            detail=f"Provenance share={share:.2%} ({with_prov}/{opted_in}).{cohort_note}",
            evidence=evidence,
            provenance=provenance,
        )
    if share >= CC03_WARN_PROVENANCE_SHARE:
        return _result(
            check_id="CC-03",
            status="WARN",
            reason_code="RC-08",
            root_cause_ids=["RC-08", "RC-09"],
            ctx=ctx,
            detail=f"Partial provenance share={share:.2%} weak={weak}.{cohort_note}",
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="CC-03",
        status="FAIL",
        reason_code="RC-08",
        root_cause_ids=["RC-08", "RC-09"],
        ctx=ctx,
        detail=(
            f"Unevidenced opt-ins: provenance_share={share:.2%} "
            f"weak_or_missing={weak}/{opted_in} (agent-set / empty consents)."
            f"{cohort_note}"
        ),
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_cc_05(ctx: FoundationGateContext) -> CheckResult:
    """Opt-out propagation loop (Excel CC-05)."""
    loaded = _require_consent_inputs(check_id="CC-05", ctx=ctx, need_both=True)
    if isinstance(loaded, CheckResult):
        return loaded
    _snapshot_data, consent, observed = loaded
    prop = consent.get("propagation") if isinstance(consent.get("propagation"), dict) else {}
    email_m_out = int(prop.get("email_manago_out_shopify_in") or 0)
    email_s_out = int(prop.get("email_shopify_out_manago_in") or 0)
    sms_m_out = int(prop.get("sms_manago_out_shopify_in") or 0)
    sms_s_out = int(prop.get("sms_shopify_out_manago_in") or 0)
    gaps = email_m_out + email_s_out + sms_m_out + sms_s_out
    linked = int(consent.get("linked_identities") or 0)
    bounce_available = bool(consent.get("hard_bounce_complaint_available"))
    lag = (
        consent.get("propagation_lag")
        if isinstance(consent.get("propagation_lag"), dict)
        else {}
    )
    suppression = (
        consent.get("suppression") if isinstance(consent.get("suppression"), dict) else {}
    )
    invalid_still_in = int(suppression.get("invalid_still_subscribed_shopify") or 0)
    samples = []
    for key in ("email_in_out", "email_out_in", "sms_in_out", "sms_out_in"):
        samples.extend((consent.get("mismatch_samples") or {}).get(key) or [])
    invalid_samples = (consent.get("mismatch_samples") or {}).get(
        "invalid_still_in_shopify"
    ) or []
    median_lag = lag.get("median_seconds")
    value = {
        "linked_identities": linked,
        "propagation": prop,
        "propagation_gap_total": gaps,
        "propagation_lag": lag,
        "suppression": suppression,
        "hard_bounce_complaint_available": bounce_available,
        "thresholds": {
            "lag_warn_seconds": CC05_LAG_WARN_SECONDS,
            "note": "Provisional MVP1 lag WARN band — flag George",
        },
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="consent.opt_out_propagation",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": [
            {
                "side": "propagation_gap",
                "person.email": s.get("person.email"),
                "shopify_customer_id": s.get("shopify_customer_id"),
                "manago_contact_id": s.get("manago_contact_id"),
                "channel": s.get("channel"),
                "email_quadrant": s.get("email_quadrant"),
                "sms_quadrant": s.get("sms_quadrant"),
                "email_propagation_lag_seconds": s.get("email_propagation_lag_seconds"),
                "sms_propagation_lag_seconds": s.get("sms_propagation_lag_seconds"),
            }
            for s in samples[:CC_SAMPLE]
        ]
        + [
            {
                "side": "suppression_gap_invalid_still_in",
                "person.email": s.get("person.email"),
                "shopify_customer_id": s.get("shopify_customer_id"),
                "manago_contact_id": s.get("manago_contact_id"),
                "manago_invalid": s.get("manago_invalid"),
                "channel": "email",
            }
            for s in invalid_samples[:CC_SAMPLE]
        ],
    }
    if linked == 0:
        return _result(
            check_id="CC-05",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:linked_identities",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
            provenance=provenance,
        )
    if gaps > 0 or invalid_still_in > 0:
        return _result(
            check_id="CC-05",
            status="FAIL",
            reason_code="RC-01",
            root_cause_ids=["RC-01", "RC-05", "RC-07"],
            ctx=ctx,
            detail=(
                f"Opt-out propagation gaps={gaps} "
                f"(email manago_out/shopify_in={email_m_out}, "
                f"shopify_out/manago_in={email_s_out}; "
                f"sms {sms_m_out}/{sms_s_out}); "
                f"invalid_still_subscribed_shopify={invalid_still_in}; "
                f"lag_median_s={median_lag}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    lag_warn = (
        isinstance(median_lag, (int, float)) and float(median_lag) > CC05_LAG_WARN_SECONDS
    )
    if lag_warn:
        return _result(
            check_id="CC-05",
            status="WARN",
            reason_code="RC-05",
            root_cause_ids=["RC-01", "RC-05"],
            confidence="MEDIUM",
            ctx=ctx,
            detail=(
                f"State parity OK but propagation lag median={median_lag}s "
                f"exceeds provisional {CC05_LAG_WARN_SECONDS}s band."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    # State parity OK; bounce/complaint stream still missing → WARN for incomplete loop.
    if not bounce_available:
        return _result(
            check_id="CC-05",
            status="WARN",
            reason_code="MISSING_INPUT:suppression_events",
            root_cause_ids=["RC-01", "RC-05"],
            confidence="MEDIUM",
            ctx=ctx,
            detail=(
                "Opt-out state parity OK on linked identities, but hard-bounce/"
                "complaint suppression stream not available to verify full CC-05 loop."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="CC-05",
        status="PASS",
        ctx=ctx,
        detail=(
            "Opt-out propagation parity OK including Manago invalid suppression proxy; "
            f"lag_median_s={median_lag}."
        ),
        evidence=evidence,
        provenance=provenance,
    )


CONSENT_EXECUTORS = {
    "CC-01": evaluate_cc_01,
    "CC-02": evaluate_cc_02,
    "CC-03": evaluate_cc_03,
    "CC-05": evaluate_cc_05,
}
