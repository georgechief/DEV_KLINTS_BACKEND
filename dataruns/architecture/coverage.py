"""Sheet 07 coverage map for Lifecycle / Overview (PRD-AF-01 Phase E)."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from dataruns.architecture.lifecycle_model import (
    FE_PHASE_CARD_KEYS,
    LIFECYCLE_STAGES,
    PHASE_ORDER,
    normalize_lifecycle_stage,
)
from dataruns.architecture.models import ArchitectureAssessment


def build_coverage_payload(
    assessment: ArchitectureAssessment,
    *,
    horizon: str | None = None,
) -> dict[str, Any]:
    """
    GET …/coverage/ — canonical stage map + verdict counts.

    ``horizon`` is presentation-only (quarter|year); does not change architecture
    facts. Impact € fields are omitted until real economics exist (PRD §9.1.1).
    """
    verdict_by_asset = {
        row.asset_id: row.verdict for row in assessment.asset_verdicts.all()
    }

    # stage_id → list of asset summaries
    by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unassigned: list[dict[str, Any]] = []

    for asset in assessment.assets.all():
        stage_id = normalize_lifecycle_stage(asset.lifecycle_stage)
        item = {
            "asset_id": asset.asset_id,
            "asset_type": asset.asset_type,
            "name": asset.name,
            "status": asset.status,
            "verdict": verdict_by_asset.get(asset.asset_id),
        }
        if stage_id:
            by_stage[stage_id].append(item)
        else:
            unassigned.append(item)

    stages_out: list[dict[str, Any]] = []
    phase_buckets: dict[str, dict[str, Any]] = {
        phase: {
            "phase": phase,
            "fe_phase_key": FE_PHASE_CARD_KEYS.get(phase),
            "stage_ids": [],
            "asset_count": 0,
            "verdict_counts": Counter(),
            "gap": True,
        }
        for phase in PHASE_ORDER
    }

    coverage_gaps = 0
    for meta in LIFECYCLE_STAGES:
        stage_id = meta["stage_id"]
        assets = by_stage.get(stage_id, [])
        counts: Counter[str] = Counter()
        for row in assets:
            if row.get("verdict"):
                counts[row["verdict"]] += 1
        is_gap = len(assets) == 0
        if is_gap:
            coverage_gaps += 1

        stage_payload = {
            **meta,
            "fe_phase_key": FE_PHASE_CARD_KEYS.get(meta["phase"]),
            "asset_count": len(assets),
            "verdict_counts": {
                "KEEP": counts.get("KEEP", 0),
                "KEEP_IMPROVE": counts.get("KEEP_IMPROVE", 0),
                "FIX_FIRST": counts.get("FIX_FIRST", 0),
                "CONSOLIDATE": counts.get("CONSOLIDATE", 0),
                "RETIRE_CANDIDATE": counts.get("RETIRE_CANDIDATE", 0),
            },
            "gap": is_gap,
            "assets": assets[:100],
        }
        stages_out.append(stage_payload)

        bucket = phase_buckets[meta["phase"]]
        bucket["stage_ids"].append(stage_id)
        bucket["asset_count"] += len(assets)
        bucket["verdict_counts"].update(counts)
        if not is_gap:
            bucket["gap"] = False

    phases_out = []
    for phase in PHASE_ORDER:
        bucket = phase_buckets[phase]
        vc = bucket["verdict_counts"]
        phases_out.append(
            {
                "phase": phase,
                "fe_phase_key": bucket["fe_phase_key"],
                "stage_ids": bucket["stage_ids"],
                "asset_count": bucket["asset_count"],
                "verdict_counts": {
                    "KEEP": vc.get("KEEP", 0),
                    "KEEP_IMPROVE": vc.get("KEEP_IMPROVE", 0),
                    "FIX_FIRST": vc.get("FIX_FIRST", 0),
                    "CONSOLIDATE": vc.get("CONSOLIDATE", 0),
                    "RETIRE_CANDIDATE": vc.get("RETIRE_CANDIDATE", 0),
                },
                "gap": bucket["gap"],
            }
        )

    # FE 5-card rollup (acq/act/exp/loy/ret)
    fe_cards: dict[str, dict[str, Any]] = {}
    for phase_row in phases_out:
        key = phase_row["fe_phase_key"] or "other"
        card = fe_cards.setdefault(
            key,
            {
                "fe_phase_key": key,
                "phases": [],
                "asset_count": 0,
                "verdict_counts": Counter(),
                "gap_stages": 0,
                "stage_count": 0,
            },
        )
        card["phases"].append(phase_row["phase"])
        card["asset_count"] += phase_row["asset_count"]
        card["verdict_counts"].update(phase_row["verdict_counts"])
        card["stage_count"] += len(phase_row["stage_ids"])
        for sid in phase_row["stage_ids"]:
            if by_stage.get(sid) in (None, []):
                card["gap_stages"] += 1

    fe_phase_cards = []
    for key in ("acq", "act", "exp", "loy", "ret"):
        card = fe_cards.get(key)
        if not card:
            fe_phase_cards.append(
                {
                    "fe_phase_key": key,
                    "phases": [],
                    "asset_count": 0,
                    "verdict_counts": {
                        "KEEP": 0,
                        "KEEP_IMPROVE": 0,
                        "FIX_FIRST": 0,
                        "CONSOLIDATE": 0,
                        "RETIRE_CANDIDATE": 0,
                    },
                    "gap_stages": 0,
                    "stage_count": 0,
                }
            )
            continue
        vc = card["verdict_counts"]
        fe_phase_cards.append(
            {
                "fe_phase_key": key,
                "phases": card["phases"],
                "asset_count": card["asset_count"],
                "verdict_counts": {
                    "KEEP": vc.get("KEEP", 0),
                    "KEEP_IMPROVE": vc.get("KEEP_IMPROVE", 0),
                    "FIX_FIRST": vc.get("FIX_FIRST", 0),
                    "CONSOLIDATE": vc.get("CONSOLIDATE", 0),
                    "RETIRE_CANDIDATE": vc.get("RETIRE_CANDIDATE", 0),
                },
                "gap_stages": card["gap_stages"],
                "stage_count": card["stage_count"],
            }
        )

    covered_stages = 16 - coverage_gaps
    probe_coverage = assessment.probe_coverage or {}
    horizon_norm = (horizon or "").strip().lower()
    if horizon_norm not in {"quarter", "year", "q", "y"}:
        horizon_norm = None
    elif horizon_norm in {"q", "quarter"}:
        horizon_norm = "quarter"
    else:
        horizon_norm = "year"

    return {
        "assessment_id": str(assessment.id),
        "mode": assessment.mode,
        "graph_complete": bool(probe_coverage.get("graph_complete")),
        "horizon": horizon_norm,
        "note": (
            "Horizon is display-only; architecture snapshot does not change. "
            "Impact € omitted until economics exist (PRD §9.1.1)."
        ),
        "stage_count": 16,
        "covered_stage_count": covered_stages,
        "coverage_gap_count": coverage_gaps,
        "coverage_ratio": round(covered_stages / 16.0, 4),
        "unassigned_asset_count": len(unassigned),
        "unassigned_assets": unassigned[:100],
        # BL-010 / Opportunities prep — uncovered stages from WF-12.
        "opportunities_gaps": probe_coverage.get("lifecycle_gaps")
        or [
            {
                "stage": s["stage"],
                "stage_id": s["stage_id"],
                "phase": s["phase"],
                "uc_group": s["uc_group"],
                "job": s["job"],
            }
            for s in stages_out
            if s.get("gap")
        ],
        "phases": phases_out,
        "fe_phase_cards": fe_phase_cards,
        "stages": stages_out,
    }
