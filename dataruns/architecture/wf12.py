"""Phase F — WF-12 lifecycle coverage map (PRD-AF-01 §7.2 / sheet 07)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dataruns.architecture.inventory import InventoryAsset, ProbeOutcome
from dataruns.architecture.lifecycle_model import (
    LIFECYCLE_STAGES,
    stage_id_for_number,
)
from dataruns.architecture.models import ArchitectureAsset

# Ordered keyword rules: first match wins. Patterns are lowercase substrings.
_STAGE_RULES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (16, ("paid media", "roas", "audience sync", "facebook ads", "google ads", "ad audience")),
    (15, ("upsell", "upgrade", "premium", "aov lift")),
    (14, ("cross-sell", "cross sell", "crosssell", "complementary", "bundle")),
    (13, ("birthday", "anniversary", "milestone", "nth order", "loyalty point")),
    (12, ("vip", "loyalty program", "loyalty", "tier")),
    (11, ("post-return", "return", "refund", "exchange")),
    (10, ("winback", "win-back", "lapsed", "lapse", "reactivat", "inactive customer")),
    (9, ("at risk", "churn", "save flow", "retention risk", "rfm")),
    (8, ("price drop", "price alert", "price change", "markdown")),
    (7, ("back in stock", "waitlist", "stock alert", "oos", "availability")),
    (6, ("replenish", "refill", "reorder", "consumable", "subscription")),
    (5, ("second purchase", "second order", "2nd purchase", "habit")),
    (4, ("welcome", "onboard", "onboarding", "new customer", "first purchase", "education")),
    (3, ("abandon", "cart", "checkout", "browse abandon", "purchase intent")),
    (2, ("consent", "opt-in", "optin", "opt in", "subscribe", "newsletter", "double opt")),
    (1, ("lead capture", "popup", "pop-up", "landing", "utm", "visitor", "anonymous", "form fill")),
)

# Property-key heuristics (name/key match).
_PROP_RULES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (5, ("order_number", "order_count", "orders_count", "purchase_count")),
    (4, ("order_avg", "order_summary", "aov", "first_order", "last_order")),
    (6, ("next_refill", "refill", "reorder")),
    (12, ("vip", "loyalty", "ltv", "clv")),
    (9, ("churn", "risk", "rfm")),
    (2, ("consent", "opt_in", "optin", "marketing_consent")),
    (1, ("utm", "source", "campaign")),
)

_TAG_RULES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (12, ("vip", "loyalty")),
    (10, ("lapsed", "winback", "inactive")),
    (9, ("at_risk", "atrisk", "churn")),
    (4, ("welcome", "new_customer", "onboard")),
    (2, ("subscriber", "optin", "opt_in", "newsletter")),
    (1, ("lead", "prospect")),
)


@dataclass
class CoverageGap:
    stage: int
    stage_id: str
    phase: str
    customer_state: str
    uc_group: str
    job: str


@dataclass
class Wf12Result:
    assets: list[InventoryAsset]
    probes: list[ProbeOutcome]
    covered_stage_ids: list[str] = field(default_factory=list)
    gap_stage_ids: list[str] = field(default_factory=list)
    gaps: list[CoverageGap] = field(default_factory=list)
    evidence_coverage: float = 0.0


def _haystack(asset: InventoryAsset) -> str:
    parts = [asset.name or "", asset.asset_id or ""]
    definition = asset.definition if isinstance(asset.definition, dict) else {}
    for key in ("trigger", "engine", "tags", "segments", "properties", "key"):
        value = definition.get(key)
        if value is None:
            continue
        parts.append(str(value))
    return " ".join(parts).lower()


def infer_lifecycle_stage(asset: InventoryAsset) -> str | None:
    """Best-effort map of an inventoried asset onto sheet 07 (WF-12)."""
    name_text = f"{asset.name or ''} {asset.asset_id or ''}".lower()
    full_text = _haystack(asset)
    if not full_text.strip():
        return None

    if asset.asset_type == ArchitectureAsset.AssetType.PROPERTY:
        key = (asset.name or "").strip().lower().replace("-", "_").replace(" ", "_")
        for stage, needles in _PROP_RULES:
            if any(n in key or n in full_text for n in needles):
                return stage_id_for_number(stage)
        if key in {"note", "notes", "comment"}:
            return stage_id_for_number(2)
        return None

    if asset.asset_type == ArchitectureAsset.AssetType.TAG:
        for stage, needles in _TAG_RULES:
            if any(n in name_text or n in full_text for n in needles):
                return stage_id_for_number(stage)
        return None

    # WORKFLOW / SEGMENT / other — prefer name match so tag refs in triggers
    # do not steal the workflow's own stage (e.g. Welcome + tag:vip).
    # Pass 2 uses trigger/engine only — not tags/segments/properties haystack.
    definition = asset.definition if isinstance(asset.definition, dict) else {}
    trigger_text = " ".join(
        filter(
            None,
            [
                str(definition.get("trigger") or ""),
                str(definition.get("engine") or ""),
            ],
        )
    ).lower()
    for stage, needles in _STAGE_RULES:
        if any(n in name_text for n in needles):
            return stage_id_for_number(stage)
    for stage, needles in _STAGE_RULES:
        if any(n in trigger_text for n in needles):
            return stage_id_for_number(stage)
    return None


def run_phase_f_coverage(*, assets: list[InventoryAsset]) -> Wf12Result:
    """
    WF-12 — Map inventoried assets onto the 16-stage lifecycle model and
    emit coverage gaps for the Use Case Library / Opportunities later.
    """
    mapped: list[InventoryAsset] = []
    covered: set[str] = set()
    mapped_count = 0

    for asset in assets:
        stage_id = infer_lifecycle_stage(asset)
        # Copy with lifecycle_stage (InventoryAsset gains optional field).
        updated = InventoryAsset(
            asset_id=asset.asset_id,
            asset_type=asset.asset_type,
            name=asset.name,
            status=asset.status,
            definition=asset.definition,
            capability_path=asset.capability_path,
            provenance=asset.provenance,
            lifecycle_stage=stage_id,
        )
        mapped.append(updated)
        if stage_id:
            covered.add(stage_id)
            mapped_count += 1

    gaps: list[CoverageGap] = []
    gap_ids: list[str] = []
    for meta in LIFECYCLE_STAGES:
        sid = meta["stage_id"]
        if sid in covered:
            continue
        gap_ids.append(sid)
        gaps.append(
            CoverageGap(
                stage=int(meta["stage"]),
                stage_id=sid,
                phase=str(meta["phase"]),
                customer_state=str(meta["customer_state"]),
                uc_group=str(meta["uc_group"]),
                job=str(meta["job"]),
            )
        )

    if len(mapped) == 0:
        status = "incomplete"
        note = "No workflows/assets to map onto the lifecycle model."
    elif mapped_count == 0:
        status = "partial"
        note = "Assets inventoried but none matched lifecycle keywords (heuristic map)."
    elif gap_ids:
        status = "partial"
        note = "Coverage gaps remain for Use Case Library / Opportunities."
    else:
        status = "succeeded"
        note = "All 16 lifecycle stages have at least one mapped asset."

    covered_ratio = round(len(covered) / 16.0, 4)
    probe = ProbeOutcome(
        probe_id="WF-12",
        status=status,
        evidence={
            "mapped_asset_count": mapped_count,
            "total_asset_count": len(mapped),
            "covered_stage_count": len(covered),
            "coverage_gap_count": len(gap_ids),
            "covered_stage_ids": sorted(covered),
            "gap_stage_ids": gap_ids,
            "gaps": [
                {
                    "stage": g.stage,
                    "stage_id": g.stage_id,
                    "phase": g.phase,
                    "customer_state": g.customer_state,
                    "uc_group": g.uc_group,
                    "job": g.job,
                }
                for g in gaps
            ],
            "note": note,
            "method": "keyword_heuristic_v1",
        },
    )

    return Wf12Result(
        assets=mapped,
        probes=[probe],
        covered_stage_ids=sorted(covered),
        gap_stage_ids=gap_ids,
        gaps=gaps,
        evidence_coverage=covered_ratio if mapped else 0.2,
    )
