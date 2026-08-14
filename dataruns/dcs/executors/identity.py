"""Customer Identity RULE checks CI-01/02/03/05 (Excel sheet 02 / PRD-DCS-04).

Read frozen scoring snapshot only — never live HTTP.
MVP1 thresholds below are provisional (sheet 02 qualitative); documented for George.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.catalogue import foundation_gate_meta, root_cause_details
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.types import CheckResult, Confidence, Evidence

# Provisional MVP1 bands (PRD-DCS-04 §6) — replace when sheet 02 publishes cutovers.
CI01_PASS_DELTA = 0.10
CI01_WARN_DELTA = 0.25
CI01_MISMATCH_SAMPLE = 50
CI02_WARN_GUEST_SHARE = 0.40
CI02_FAIL_NO_EMAIL_SHARE = 0.05
CI03_WARN_DUP_RATE = 0.01
CI03_FAIL_DUP_RATE = 0.02
CI05_PASS_LINK_COVERAGE = 0.80
CI05_WARN_LINK_COVERAGE = 0.50


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _snapshot(ctx: FoundationGateContext) -> dict[str, Any]:
    raw = ctx.extra.get("scoring_snapshot")
    return raw if isinstance(raw, dict) else {}


def _identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    identity = snapshot.get("identity")
    return identity if isinstance(identity, dict) else {}


def _connector_connected(snapshot: dict[str, Any], platform: str) -> bool:
    connectors = snapshot.get("connectors")
    if not isinstance(connectors, dict):
        return False
    row = connectors.get(platform)
    if not isinstance(row, dict):
        return False
    return str(row.get("status") or "") in {"connected", "degraded"}


def _ci01_contact_mismatches(
    snapshot: dict[str, Any],
    *,
    limit: int = CI01_MISMATCH_SAMPLE,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Real platform-only contacts from frozen snapshot (not join counts).

    ``source=manago_ai`` / ``shopify`` rows from identity_join → mismatch sides.
    ``source=both`` is a match and is omitted here.

    Returns ``(sample, truncated)``. Truncated is True only when more than
    ``limit`` mismatches exist (exactly ``limit`` is not truncation).
    """
    contacts = snapshot.get("contacts")
    if not isinstance(contacts, list) or limit <= 0:
        return [], False
    rows: list[dict[str, Any]] = []
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        source = str(contact.get("source") or "")
        if source == "manago_ai":
            side = "manago_only"
        elif source == "shopify":
            side = "shopify_only"
        else:
            continue
        rows.append(
            {
                "side": side,
                "email": str(contact.get("person.email") or ""),
                "manago_contact_id": str(contact.get("manago_contact_id") or ""),
                "shopify_customer_id": str(contact.get("shopify_customer_id") or ""),
                "external_key": str(contact.get("person.external_key") or ""),
            }
        )
        # One past the limit proves truncation without a second full scan.
        if len(rows) > limit:
            return rows[:limit], True
    return rows, False


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
    # Prefer CheckMaster when seeded; fall back to catalogue JSON / empty.
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


def evaluate_ci_01(ctx: FoundationGateContext) -> CheckResult:
    """Contact count reconciliation — Manago vs Shopify + email overlap."""
    snapshot = _snapshot(ctx)
    identity = _identity(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if not shopify_ok and not manago_ok:
        return _result(
            check_id="CI-01",
            status="NOT_CONNECTED",
            reason_code="NO_CONNECTORS_FOR_IDENTITY",
            ctx=ctx,
            detail="Neither Shopify nor Manago connected for contact reconciliation.",
        )
    if not shopify_ok or not manago_ok:
        return _result(
            check_id="CI-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:both_platforms",
            confidence="LOW",
            ctx=ctx,
            detail="CI-01 needs both Shopify and Manago contact universes.",
            evidence=[
                _evidence(
                    source="snapshot",
                    locator="identity",
                    value={"shopify": shopify_ok, "manago_ai": manago_ok},
                    observed_at=observed,
                )
            ],
        )

    if not identity:
        return _result(
            check_id="CI-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:identity",
            confidence="LOW",
            ctx=ctx,
            detail="Scoring snapshot missing identity join summary.",
        )

    manago_n = int(identity.get("manago_contacts") or 0)
    shopify_n = int(identity.get("shopify_customers") or 0)
    in_both = int(identity.get("in_both") or 0)
    manago_only = int(identity.get("manago_only") or 0)
    shopify_only = int(identity.get("shopify_only") or 0)
    denom = max(manago_n, shopify_n, 1)
    delta = abs(manago_n - shopify_n) / denom
    mismatch_contacts, mismatches_truncated = _ci01_contact_mismatches(snapshot)
    value = {
        "manago_contacts": manago_n,
        "shopify_customers": shopify_n,
        "in_both": in_both,
        "manago_only": manago_only,
        "shopify_only": shopify_only,
        "relative_delta": round(delta, 4),
        "thresholds": {
            "pass_delta": CI01_PASS_DELTA,
            "warn_delta": CI01_WARN_DELTA,
        },
        "mismatch_contacts_sample": mismatch_contacts,
        "mismatch_contacts_truncated": mismatches_truncated,
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="identity.contact_count_reconciliation",
            value=value,
            observed_at=observed,
        )
    ]
    # Explicit provenance so RunIssue.details.mismatches lists real contacts
    # (not only aggregate evidence), including on PASS when sides still differ.
    provenance = {
        "matches": [],
        "mismatches": mismatch_contacts,
    }

    if manago_n == 0 and shopify_n == 0:
        return _result(
            check_id="CI-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:contacts",
            confidence="LOW",
            ctx=ctx,
            detail="No contacts ingested on either platform.",
            evidence=evidence,
            provenance=provenance,
        )

    if delta <= CI01_PASS_DELTA:
        status, reason, rcs = "PASS", None, None
    elif delta <= CI01_WARN_DELTA:
        status, reason, rcs = "WARN", "CI01_COUNT_DELTA", ["RC-01", "RC-03", "RC-09"]
    else:
        status, reason, rcs = "FAIL", "RC-01", ["RC-01", "RC-03", "RC-09"]

    return _result(
        check_id="CI-01",
        status=status,
        reason_code=reason,
        root_cause_ids=rcs,
        confidence="HIGH",
        ctx=ctx,
        detail=(
            f"Manago={manago_n} Shopify={shopify_n} in_both={in_both} "
            f"manago_only={manago_only} shopify_only={shopify_only} "
            f"relative_delta={delta:.2%}"
        ),
        evidence=evidence,
        provenance=provenance,
    )


def evaluate_ci_02(ctx: FoundationGateContext) -> CheckResult:
    """Guest checkout identity share (Shopify)."""
    snapshot = _snapshot(ctx)
    identity = _identity(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "shopify"):
        return _result(
            check_id="CI-02",
            status="NOT_CONNECTED",
            reason_code="SHOPIFY_NOT_CONNECTED",
            ctx=ctx,
            detail="Shopify not connected for guest identity share.",
        )
    if not identity:
        return _result(
            check_id="CI-02",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:identity",
            confidence="LOW",
            ctx=ctx,
        )

    orders = int(identity.get("shopify_orders") or 0)
    guests = int(identity.get("guest_orders") or 0)
    guests_email = int(identity.get("guest_orders_with_email") or 0)
    if orders == 0:
        return _result(
            check_id="CI-02",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:orders",
            confidence="LOW",
            ctx=ctx,
            detail="No Shopify orders in snapshot window.",
        )

    guest_share = guests / orders
    no_email = max(guests - guests_email, 0)
    no_email_share = no_email / orders
    value = {
        "shopify_orders": orders,
        "guest_orders": guests,
        "guest_orders_with_email": guests_email,
        "guest_share": round(guest_share, 4),
        "guest_without_email_share": round(no_email_share, 4),
    }
    evidence = [
        _evidence(
            source="shopify",
            locator="identity.guest_checkout_share",
            value=value,
            observed_at=observed,
        )
    ]

    if no_email_share > CI02_FAIL_NO_EMAIL_SHARE:
        return _result(
            check_id="CI-02",
            status="FAIL",
            reason_code="RC-03",
            root_cause_ids=["RC-03"],
            confidence="HIGH",
            ctx=ctx,
            detail=(
                f"Guest orders without identifiable email share={no_email_share:.2%} "
                f"(guests={guests}, with_email={guests_email})."
            ),
            evidence=evidence,
        )
    if guest_share > CI02_WARN_GUEST_SHARE:
        return _result(
            check_id="CI-02",
            status="WARN",
            reason_code="RC-03",
            root_cause_ids=["RC-03"],
            confidence="HIGH",
            ctx=ctx,
            detail=f"Guest checkout share={guest_share:.2%} above warn band.",
            evidence=evidence,
        )
    return _result(
        check_id="CI-02",
        status="PASS",
        confidence="HIGH",
        ctx=ctx,
        detail=f"Guest share={guest_share:.2%}; email coverage on guests OK.",
        evidence=evidence,
    )


def evaluate_ci_03(ctx: FoundationGateContext) -> CheckResult:
    """Duplicate contacts in Manago (email / phone / externalId)."""
    snapshot = _snapshot(ctx)
    identity = _identity(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    if not _connector_connected(snapshot, "manago_ai"):
        return _result(
            check_id="CI-03",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            ctx=ctx,
        )
    if not identity:
        return _result(
            check_id="CI-03",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:identity",
            confidence="LOW",
            ctx=ctx,
        )

    manago_n = int(identity.get("manago_contacts") or 0)
    clusters = identity.get("duplicate_clusters") or {}
    if not isinstance(clusters, dict):
        clusters = {}
    email_dups = list(clusters.get("email") or [])
    phone_dups = list(clusters.get("phone") or [])
    link_dups = list(clusters.get("externalId") or [])
    cluster_count = len(email_dups) + len(phone_dups) + len(link_dups)
    dup_contacts = sum(
        max(int(c.get("count") or 0) - 1, 0)
        for group in (email_dups, phone_dups, link_dups)
        for c in group
        if isinstance(c, dict)
    )
    rate = dup_contacts / max(manago_n, 1)
    value = {
        "manago_contacts": manago_n,
        "duplicate_clusters": cluster_count,
        "duplicate_extra_contacts": dup_contacts,
        "duplicate_rate": round(rate, 4),
        "clusters": {
            "email": email_dups[:20],
            "phone": phone_dups[:20],
            "externalId": link_dups[:20],
        },
    }
    evidence = [
        _evidence(
            source="manago_ai",
            locator="identity.duplicate_contacts",
            value=value,
            observed_at=observed,
        )
    ]

    if manago_n == 0:
        return _result(
            check_id="CI-03",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:contacts",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
        )
    if rate > CI03_FAIL_DUP_RATE or cluster_count > 10:
        return _result(
            check_id="CI-03",
            status="FAIL",
            reason_code="RC-04",
            root_cause_ids=["RC-04", "RC-08"],
            confidence="HIGH",
            ctx=ctx,
            detail=f"Manago duplicate rate={rate:.2%} clusters={cluster_count}.",
            evidence=evidence,
        )
    if rate > CI03_WARN_DUP_RATE or cluster_count > 0:
        return _result(
            check_id="CI-03",
            status="WARN",
            reason_code="RC-04",
            root_cause_ids=["RC-04", "RC-08"],
            confidence="HIGH",
            ctx=ctx,
            detail=f"Manago near-duplicates detected clusters={cluster_count}.",
            evidence=evidence,
        )
    return _result(
        check_id="CI-03",
        status="PASS",
        confidence="HIGH",
        ctx=ctx,
        evidence=evidence,
    )


def evaluate_ci_05(ctx: FoundationGateContext) -> CheckResult:
    """External ID linkage integrity (Manago externalId ↔ Shopify customers.id)."""
    snapshot = _snapshot(ctx)
    identity = _identity(snapshot)
    observed = ctx.evaluated_at or _utcnow_iso()

    shopify_ok = _connector_connected(snapshot, "shopify")
    manago_ok = _connector_connected(snapshot, "manago_ai")
    if not shopify_ok or not manago_ok:
        return _result(
            check_id="CI-05",
            status="UNKNOWN" if (shopify_ok or manago_ok) else "NOT_CONNECTED",
            reason_code=(
                "MISSING_INPUT:both_platforms"
                if (shopify_ok or manago_ok)
                else "NO_CONNECTORS_FOR_IDENTITY"
            ),
            confidence="LOW",
            ctx=ctx,
        )
    if not identity:
        return _result(
            check_id="CI-05",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:identity",
            confidence="LOW",
            ctx=ctx,
        )

    manago_n = int(identity.get("manago_contacts") or 0)
    with_link = int(identity.get("manago_with_link_key") or 0)
    matched = int(identity.get("link_key_matched") or 0)
    dangling = list(identity.get("link_key_dangling") or [])
    reused = list(identity.get("link_key_reused") or [])
    value = {
        "manago_contacts": manago_n,
        "manago_with_link_key": with_link,
        "link_key_matched": matched,
        "dangling_count": len(dangling),
        "reused_count": len(reused),
        "dangling_sample": dangling[:10],
        "reused_sample": reused[:10],
    }
    evidence = [
        _evidence(
            source="snapshot",
            locator="identity.external_id_linkage",
            value=value,
            observed_at=observed,
        )
    ]

    if manago_n == 0:
        return _result(
            check_id="CI-05",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:contacts",
            confidence="LOW",
            ctx=ctx,
            evidence=evidence,
        )

    # Excel: externalId must be populated — if none ingested → UNKNOWN.
    if with_link == 0:
        return _result(
            check_id="CI-05",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:person.external_key",
            confidence="LOW",
            ctx=ctx,
            detail=(
                "No Manago contact.externalId (link_key) values ingested; "
                "cannot verify bijective Shopify linkage yet."
            ),
            evidence=evidence,
        )

    coverage = matched / max(with_link, 1)
    if reused or dangling:
        return _result(
            check_id="CI-05",
            status="FAIL",
            reason_code="RC-02",
            root_cause_ids=["RC-01", "RC-02"],
            confidence="HIGH",
            ctx=ctx,
            detail=(
                f"Link key integrity broken: reused={len(reused)} "
                f"dangling={len(dangling)} matched={matched}/{with_link}."
            ),
            evidence=evidence,
        )
    if coverage >= CI05_PASS_LINK_COVERAGE:
        return _result(
            check_id="CI-05",
            status="PASS",
            confidence="HIGH",
            ctx=ctx,
            detail=f"Link coverage={coverage:.2%} ({matched}/{with_link}).",
            evidence=evidence,
        )
    if coverage >= CI05_WARN_LINK_COVERAGE:
        return _result(
            check_id="CI-05",
            status="WARN",
            reason_code="RC-01",
            root_cause_ids=["RC-01", "RC-02"],
            confidence="HIGH",
            ctx=ctx,
            detail=f"Partial link coverage={coverage:.2%} ({matched}/{with_link}).",
            evidence=evidence,
        )
    return _result(
        check_id="CI-05",
        status="FAIL",
        reason_code="RC-01",
        root_cause_ids=["RC-01", "RC-02"],
        confidence="HIGH",
        ctx=ctx,
        detail=f"Low link coverage={coverage:.2%} ({matched}/{with_link}).",
        evidence=evidence,
    )


IDENTITY_EXECUTORS = {
    "CI-01": evaluate_ci_01,
    "CI-02": evaluate_ci_02,
    "CI-03": evaluate_ci_03,
    "CI-05": evaluate_ci_05,
}
