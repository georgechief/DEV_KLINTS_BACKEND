"""Segment & Property RULE checks SP-03 / SP-07 (Excel sheet 02 / PRD-DCS-04 §4c)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.catalogue import foundation_gate_meta, root_cause_details
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.types import CheckResult, Confidence, Evidence

SP_SAMPLE = 50


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _snapshot(ctx: FoundationGateContext) -> dict[str, Any]:
    raw = ctx.extra.get("scoring_snapshot")
    return raw if isinstance(raw, dict) else {}


def _segment(snapshot: dict[str, Any]) -> dict[str, Any]:
    s = snapshot.get("segment")
    return s if isinstance(s, dict) else {}


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


def evaluate_sp_03(ctx: FoundationGateContext) -> CheckResult:
    """Standard detail schema consistency (Excel SP-03)."""
    snapshot = _snapshot(ctx)
    segment = _segment(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()
    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="SP-03",
            status="NOT_CONNECTED",
            reason_code="NO_CONNECTOR:manago_ai",
            confidence="LOW",
            ctx=ctx,
        )
    raw = segment.get("raw_enrichment") or {}
    if not raw.get("manago_contacts_from_raw"):
        return _result(
            check_id="SP-03",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:manago_contacts",
            confidence="LOW",
            ctx=ctx,
        )
    keys = int(segment.get("detail_key_count") or 0)
    inconsistent = int(segment.get("inconsistent_keys") or 0)
    semantic = int(segment.get("semantic_duplicate_groups") or 0)
    samples = list(segment.get("inconsistent_sample") or [])
    semantic_samples = list(segment.get("semantic_duplicate_sample") or [])
    value = {
        "contacts_scanned": segment.get("contacts_scanned"),
        "contacts_with_details": segment.get("contacts_with_details"),
        "detail_key_count": keys,
        "inconsistent_keys": inconsistent,
        "semantic_duplicate_groups": semantic,
        "shopify_metafield_keys": (segment.get("shopify_metafield_keys") or [])[:20],
        "shopify_metafield_overlap": (segment.get("shopify_metafield_overlap") or [])[
            :20
        ],
        "inconsistent_sample": samples[:20],
        "semantic_duplicate_sample": semantic_samples[:20],
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="segment.detail_schema_consistency",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": [
            {
                "side": "inconsistent_detail_format",
                "key": s.get("key"),
                "format_distribution": s.get("format_distribution"),
                "samples": s.get("samples"),
            }
            for s in samples[:SP_SAMPLE]
            if isinstance(s, dict)
        ]
        + [
            {
                "side": "semantic_duplicate_keys",
                "normalized": s.get("normalized"),
                "keys": s.get("keys"),
            }
            for s in semantic_samples[:SP_SAMPLE]
            if isinstance(s, dict)
        ],
    }
    if keys == 0:
        # No details populated — schema consistency N/A → PASS (nothing drifted).
        return _result(
            check_id="SP-03",
            status="PASS",
            ctx=ctx,
            detail="No Manago detail keys in snapshot — schema consistency N/A.",
            evidence=evidence,
            provenance=provenance,
        )
    if inconsistent > 0 or semantic > 0:
        return _result(
            check_id="SP-03",
            status="FAIL",
            reason_code="RC-06",
            root_cause_ids=["RC-06", "RC-08"],
            ctx=ctx,
            detail=(
                f"Detail schema issues: mixed_formats={inconsistent}/{keys} "
                f"semantic_dupes={semantic}."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="SP-03",
        status="PASS",
        ctx=ctx,
        detail=f"Detail schema consistent across {keys} keys.",
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_sp_07(ctx: FoundationGateContext) -> CheckResult:
    """klints_ namespace availability (Excel SP-07)."""
    snapshot = _snapshot(ctx)
    segment = _segment(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()
    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="SP-07",
            status="NOT_CONNECTED",
            reason_code="NO_CONNECTOR:manago_ai",
            confidence="LOW",
            ctx=ctx,
        )
    raw = segment.get("raw_enrichment") or {}
    if not raw.get("manago_contacts_from_raw"):
        return _result(
            check_id="SP-07",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:manago_contacts",
            confidence="LOW",
            ctx=ctx,
        )
    collisions = int(segment.get("klints_collision_count") or 0)
    detail_hits = list(segment.get("klints_detail_collisions") or [])
    tag_hits = list(segment.get("klints_tag_collisions") or [])
    value = {
        "klints_collision_count": collisions,
        "klints_detail_collisions": detail_hits[:20],
        "klints_tag_collisions": tag_hits[:20],
        "detail_key_count": segment.get("detail_key_count"),
        "tag_count": segment.get("tag_count"),
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="segment.klints_namespace",
            value=value,
            observed_at=observed,
        )
    ]
    provenance = {
        "matches": [],
        "mismatches": [
            {"side": "klints_detail_collision", "key": k} for k in detail_hits[:SP_SAMPLE]
        ]
        + [{"side": "klints_tag_collision", "tag": t} for t in tag_hits[:SP_SAMPLE]],
    }
    if collisions > 0:
        return _result(
            check_id="SP-07",
            status="FAIL",
            reason_code="RC-04",
            root_cause_ids=["RC-04"],
            ctx=ctx,
            detail=(
                f"Pre-existing klints_ / klints: collisions={collisions} "
                f"(details={len(detail_hits)}, tags={len(tag_hits)})."
            ),
            evidence=evidence,
            provenance=provenance,
        )
    return _result(
        check_id="SP-07",
        status="PASS",
        ctx=ctx,
        detail="klints_ / klints: namespace is free of pre-existing collisions.",
        evidence=evidence,
        provenance=provenance,
    )


SEGMENT_EXECUTORS = {
    "SP-03": evaluate_sp_03,
    "SP-07": evaluate_sp_07,
}
