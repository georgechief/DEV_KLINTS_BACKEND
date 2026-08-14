"""Architecture Assessment serialization / latest payload (PRD-AF-01 §8–§9)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from dataruns.architecture.models import ArchitectureAssessment, ArchitectureAsset
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.models import DataRun


def _graph_complete(assessment: ArchitectureAssessment) -> bool:
    return bool((assessment.probe_coverage or {}).get("graph_complete"))


def serialize_architecture_assessment(
    assessment: ArchitectureAssessment,
) -> dict[str, Any]:
    verdict_counts = Counter(
        assessment.asset_verdicts.values_list("verdict", flat=True)
    )
    asset_count = assessment.assets.count()
    edge_count = assessment.edges.count()
    workflow_count = assessment.assets.filter(
        asset_type=ArchitectureAsset.AssetType.WORKFLOW
    ).count()
    workflow_fix_first = assessment.asset_verdicts.filter(
        asset_id__in=assessment.assets.filter(
            asset_type=ArchitectureAsset.AssetType.WORKFLOW
        ).values_list("asset_id", flat=True),
        verdict="FIX_FIRST",
    ).count()

    source = assessment.source_dcs_data_run
    coverage = (
        float(assessment.evidence_coverage)
        if assessment.evidence_coverage is not None
        else None
    )
    return {
        "assessment_id": str(assessment.id),
        "status": assessment.status,
        "mode": assessment.mode,
        "weighted_score": (
            float(assessment.weighted_score)
            if assessment.weighted_score is not None
            else None
        ),
        "critical_defects": assessment.critical_defects,
        "evidence_coverage": coverage,
        "probe_coverage": assessment.probe_coverage or {},
        "graph_complete": _graph_complete(assessment),
        "asset_count": asset_count,
        "edge_count": edge_count,
        "workflow_count": workflow_count,
        "workflow_fix_first_count": workflow_fix_first,
        "verdict_counts": {
            "KEEP": verdict_counts.get("KEEP", 0),
            "KEEP_IMPROVE": verdict_counts.get("KEEP_IMPROVE", 0),
            "FIX_FIRST": verdict_counts.get("FIX_FIRST", 0),
            "CONSOLIDATE": verdict_counts.get("CONSOLIDATE", 0),
            "RETIRE_CANDIDATE": verdict_counts.get("RETIRE_CANDIDATE", 0),
        },
        "data_run_id": assessment.data_run_id,
        "source_dcs_data_run_id": source.id if source is not None else None,
        "created_at": assessment.created_at.isoformat() if assessment.created_at else None,
        "finished_at": (
            assessment.finished_at.isoformat() if assessment.finished_at else None
        ),
        "error_message": assessment.error_message or None,
    }


def serialize_architecture_graph(
    assessment: ArchitectureAssessment,
) -> dict[str, Any]:
    """Nodes + edges payload for GET …/graph/ (PRD §8)."""
    nodes = [
        {
            "asset_id": row.asset_id,
            "asset_type": row.asset_type,
            "name": row.name,
            "status": row.status,
            "lifecycle_stage": row.lifecycle_stage,
        }
        for row in assessment.assets.all()[:2000]
    ]
    edges = [
        {
            "source_asset_id": row.source_asset_id,
            "target_asset_id": row.target_asset_id,
            "edge_type": row.edge_type,
            "rule_id": row.rule_id,
            "evidence": row.evidence,
        }
        for row in assessment.edges.all()[:5000]
    ]
    return {
        "assessment_id": str(assessment.id),
        "mode": assessment.mode,
        "graph_complete": _graph_complete(assessment),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


def resolve_ui_status(
    *,
    company,
    latest: ArchitectureAssessment | None,
    active: ArchitectureAssessment | None,
) -> tuple[str, str]:
    """
    Lifecycle status chip (PRD §9.1) — no Run button.
    Values: updating | up_to_date | waiting_for_score | incomplete_map | failed
    """
    if active is not None and active.status in {
        ArchitectureAssessment.Status.PENDING,
        ArchitectureAssessment.Status.RUNNING,
    }:
        return "updating", "Updating…"

    if latest is None:
        has_dcs = DataRun.objects.filter(
            tenant=company.tenant,
            status=DataRun.Status.SUCCEEDED,
            metadata__kind=DCS_SCORE_KIND,
            metadata__company_id=str(company.id),
        ).exists()
        if not has_dcs:
            return "waiting_for_score", "Waiting for score"
        # DCS finished but AF not created yet (worker lag / enqueue pending).
        return "updating", "Updating…"

    if latest.status == ArchitectureAssessment.Status.FAILED:
        return "failed", "Assessment failed"

    if latest.status in {
        ArchitectureAssessment.Status.PENDING,
        ArchitectureAssessment.Status.RUNNING,
    }:
        return "updating", "Updating…"

    if (
        latest.mode == ArchitectureAssessment.Mode.INCOMPLETE
        or not _graph_complete(latest)
    ):
        return "incomplete_map", "Incomplete map"

    return "up_to_date", "Up to date"


def build_overview_summary(assessment: ArchitectureAssessment) -> dict[str, Any]:
    """Overview /dashboard architecture block (PRD §9.2)."""
    payload = serialize_architecture_assessment(assessment)
    vc = payload["verdict_counts"]
    coverage = payload["evidence_coverage"]
    coverage_pct = int(round((coverage or 0.0) * 100))
    fix_first = vc.get("FIX_FIRST", 0)
    consolidate = vc.get("CONSOLIDATE", 0)
    asset_count = payload["asset_count"]

    summary_line = (
        f"{asset_count} assets · {fix_first} fix-first · coverage {coverage_pct}%"
    )
    incomplete_message = None
    if (
        assessment.mode == ArchitectureAssessment.Mode.INCOMPLETE
        or not payload["graph_complete"]
    ):
        incomplete_message = (
            "Architecture map incomplete — Retire/Consolidate hidden"
        )

    return {
        "mode": assessment.mode,
        "summary_line": summary_line,
        "asset_count": asset_count,
        "fix_first_count": fix_first,
        "consolidate_count": consolidate,
        "coverage_pct": coverage_pct,
        "graph_complete": payload["graph_complete"],
        "incomplete_message": incomplete_message,
        "cta": {
            "label": "Open Lifecycle cockpit",
            "href": "/lifecycle",
        },
    }


def build_lifecycle_summary(assessment: ArchitectureAssessment) -> dict[str, Any]:
    """Lifecycle cockpit helpers (PRD §9.1) — counts only, no invented €."""
    payload = serialize_architecture_assessment(assessment)
    vc = payload["verdict_counts"]
    fix_first = vc.get("FIX_FIRST", 0)
    consolidate = vc.get("CONSOLIDATE", 0)
    probe = assessment.probe_coverage or {}
    coverage_gaps = int(probe.get("lifecycle_gap_count") or 0)
    gaps_total = fix_first + consolidate + coverage_gaps
    wf_n = payload["workflow_count"]
    wf_blocked = payload["workflow_fix_first_count"]
    as_of = payload["finished_at"] or payload["created_at"]
    return {
        "as_of": as_of,
        "workflow_count": wf_n,
        "workflow_fix_first_count": wf_blocked,
        "workflow_line": f"{wf_n} workflows · {wf_blocked} blocked (Fix-first)",
        "gaps": {
            "fix_first": fix_first,
            "consolidate": consolidate,
            "coverage_gaps": coverage_gaps,
            "total": gaps_total,
        },
        "verdict_counts": vc,
        "graph_complete": payload["graph_complete"],
        "lifecycle_covered_stage_count": probe.get("lifecycle_covered_stage_count"),
        "lifecycle_gap_count": coverage_gaps,
    }


def build_opportunities_summary(assessment: ArchitectureAssessment) -> dict[str, Any]:
    """
    BL-010 prep — WF-12 coverage gaps for Opportunities tracker (PRD §2.3 / Phase F).

    Does not invent € impact; returns stage gaps + AF mode for filtering.
    """
    probe = assessment.probe_coverage or {}
    gaps = probe.get("lifecycle_gaps") or []
    if not isinstance(gaps, list):
        gaps = []
    covered = int(probe.get("lifecycle_covered_stage_count") or 0)
    gap_count = int(probe.get("lifecycle_gap_count") or len(gaps))
    vc = Counter(assessment.asset_verdicts.values_list("verdict", flat=True))
    return {
        "assessment_id": str(assessment.id),
        "mode": assessment.mode,
        "graph_complete": _graph_complete(assessment),
        "covered_stage_count": covered,
        "gap_count": gap_count,
        "fix_first_count": vc.get("FIX_FIRST", 0),
        "consolidate_count": vc.get("CONSOLIDATE", 0),
        "gaps": gaps,
        "cta": {
            "label": "Open Lifecycle cockpit",
            "href": "/lifecycle",
        },
        "note": (
            "Coverage gaps from WF-12 feed the Use Case Library later. "
            "No invented € in v1."
        ),
    }


def build_gaps_payload(assessment: ArchitectureAssessment) -> dict[str, Any]:
    """GET …/gaps/ — Opportunities-facing uncovered stages."""
    summary = build_opportunities_summary(assessment)
    return {
        **summary,
        "results": summary["gaps"],
        "count": len(summary["gaps"]),
    }


def build_latest_architecture_payload(
    *,
    company,
) -> dict[str, Any]:
    from dataruns.architecture.enqueue import (
        find_active_architecture_assessment,
        find_latest_architecture_assessment,
    )

    latest = find_latest_architecture_assessment(company=company)
    active = find_active_architecture_assessment(company=company)
    ui_status, ui_label = resolve_ui_status(
        company=company,
        latest=latest,
        active=active,
    )

    if latest is None:
        return {
            "assessment": None,
            "active_assessment": None,
            "ui_status": ui_status,
            "ui_status_label": ui_label,
            "overview": None,
            "lifecycle": None,
            "opportunities": None,
            "message": (
                "Architecture updates automatically after your "
                "Data Consistency Score finishes."
            ),
        }

    return {
        "assessment": serialize_architecture_assessment(latest),
        "active_assessment": (
            serialize_architecture_assessment(active) if active is not None else None
        ),
        "ui_status": ui_status,
        "ui_status_label": ui_label,
        "overview": build_overview_summary(latest),
        "lifecycle": build_lifecycle_summary(latest),
        "opportunities": build_opportunities_summary(latest),
        "message": None,
    }
