"""Architecture Assessment runner (PRD-AF-01 Phase A–F)."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from dataruns.architecture.graph import run_phase_c_graph
from dataruns.architecture.inventory import run_phase_b_inventory
from dataruns.architecture.models import (
    ArchitectureAssessment,
    ArchitectureAsset,
    ArchitectureAssetVerdict,
    ArchitectureEdge,
    ArchitectureProbeResult,
)
from dataruns.architecture.verdicts import run_phase_d_verdicts
from dataruns.architecture.wf12 import run_phase_f_coverage
from dataruns.models import DataRun

logger = logging.getLogger(__name__)


def _persist_inventory(assessment: ArchitectureAssessment, inventory) -> None:
    ArchitectureAsset.objects.filter(assessment=assessment).delete()

    ArchitectureAsset.objects.bulk_create(
        [
            ArchitectureAsset(
                assessment=assessment,
                asset_id=asset.asset_id,
                asset_type=asset.asset_type,
                name=asset.name,
                status=asset.status,
                definition=asset.definition,
                lifecycle_stage=getattr(asset, "lifecycle_stage", None),
                capability_path=asset.capability_path,
                provenance=asset.provenance,
            )
            for asset in inventory.assets
        ]
    )


def _persist_graph(assessment: ArchitectureAssessment, graph) -> None:
    ArchitectureEdge.objects.filter(assessment=assessment).delete()
    ArchitectureEdge.objects.bulk_create(
        [
            ArchitectureEdge(
                assessment=assessment,
                source_asset_id=edge.source_asset_id,
                target_asset_id=edge.target_asset_id,
                edge_type=edge.edge_type,
                rule_id=edge.rule_id,
                evidence=edge.evidence,
            )
            for edge in graph.edges
        ]
    )


def _persist_verdicts(assessment: ArchitectureAssessment, verdict_result) -> None:
    ArchitectureAssetVerdict.objects.filter(assessment=assessment).delete()
    ArchitectureAssetVerdict.objects.bulk_create(
        [
            ArchitectureAssetVerdict(
                assessment=assessment,
                asset_id=row.asset_id,
                verdict=row.verdict,
                evidence_ids=row.evidence_ids,
                blocked_reason=row.blocked_reason,
                failure_code=row.failure_code,
                dcs_check_ids=row.dcs_check_ids,
            )
            for row in verdict_result.verdicts
        ]
    )


def _persist_probes(assessment: ArchitectureAssessment, probes) -> None:
    ArchitectureProbeResult.objects.filter(assessment=assessment).delete()
    ArchitectureProbeResult.objects.bulk_create(
        [
            ArchitectureProbeResult(
                assessment=assessment,
                probe_id=probe.probe_id,
                status=probe.status,
                evidence=probe.evidence,
            )
            for probe in probes
        ]
    )


def _blend_coverage(*parts: float) -> float:
    values = [float(p) for p in parts if p is not None]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def run_architecture_assessment_job(assessment_id: str) -> dict[str, Any]:
    """
    Run Architecture Assessment.

    Phase B: inventory → assets
    Phase C: dependency graph → edges
    Phase D: DCS join + per-asset verdicts + mode rollup (BL-009)
    """
    assessment = (
        ArchitectureAssessment.objects.select_related(
            "data_run",
            "company",
            "source_dcs_data_run",
        )
        .filter(id=assessment_id)
        .first()
    )
    if assessment is None:
        return {"ok": False, "error": "assessment_not_found"}

    data_run = assessment.data_run
    now = timezone.now()

    try:
        assessment.status = ArchitectureAssessment.Status.RUNNING
        assessment.save(update_fields=["status", "updated_at"])

        data_run.status = DataRun.Status.RUNNING
        data_run.started_at = data_run.started_at or now
        data_run.save(update_fields=["status", "started_at", "updated_at"])

        inventory = run_phase_b_inventory(company=assessment.company)
        wf12 = run_phase_f_coverage(assets=inventory.assets)
        # Replace inventory assets with stage-tagged copies for graph/verdicts/persist.
        inventory.assets = wf12.assets
        graph = run_phase_c_graph(assets=inventory.assets)
        coverage = _blend_coverage(
            inventory.evidence_coverage,
            graph.evidence_coverage,
            wf12.evidence_coverage,
        )
        verdicts = run_phase_d_verdicts(
            assets=inventory.assets,
            edges=graph.edges,
            graph_complete=graph.graph_complete,
            evidence_coverage=coverage,
            source_dcs_data_run=assessment.source_dcs_data_run,
        )
        all_probes = (
            list(inventory.probes)
            + list(graph.probes)
            + list(verdicts.probes)
            + list(wf12.probes)
        )

        with transaction.atomic():
            _persist_inventory(assessment, inventory)
            _persist_graph(assessment, graph)
            _persist_verdicts(assessment, verdicts)
            _persist_probes(assessment, all_probes)

            probe_coverage = {
                "phase": "F",
                "probes": {
                    p.probe_id: {"status": p.status, **(p.evidence or {})}
                    for p in all_probes
                },
                "asset_count": len(inventory.assets),
                "edge_count": len(graph.edges),
                "verdict_count": len(verdicts.verdicts),
                "graph_complete": graph.graph_complete,
                "lifecycle_covered_stage_count": len(wf12.covered_stage_ids),
                "lifecycle_gap_count": len(wf12.gap_stage_ids),
                "lifecycle_gaps": [
                    {
                        "stage": g.stage,
                        "stage_id": g.stage_id,
                        "phase": g.phase,
                        "customer_state": g.customer_state,
                        "uc_group": g.uc_group,
                        "job": g.job,
                    }
                    for g in wf12.gaps
                ],
                "mode_detail": verdicts.evidence,
                "note": (
                    "WF-12 coverage gaps ready for Opportunities / UC Library. "
                    + (
                        "Retire/Consolidate remain gated while graph_complete is false."
                        if not graph.graph_complete
                        else "Graph complete; verdicts + coverage map persisted."
                    )
                ),
            }

            assessment.status = ArchitectureAssessment.Status.SUCCEEDED
            assessment.mode = verdicts.mode
            assessment.weighted_score = (
                Decimal(str(verdicts.weighted_score))
                if verdicts.weighted_score is not None
                else None
            )
            assessment.critical_defects = verdicts.critical_defects
            assessment.evidence_coverage = Decimal(str(coverage))
            assessment.probe_coverage = probe_coverage
            assessment.finished_at = timezone.now()
            assessment.error_message = ""
            assessment.save(
                update_fields=[
                    "status",
                    "mode",
                    "weighted_score",
                    "critical_defects",
                    "evidence_coverage",
                    "probe_coverage",
                    "finished_at",
                    "error_message",
                    "updated_at",
                ]
            )

            data_run.status = DataRun.Status.SUCCEEDED
            data_run.finished_at = timezone.now()
            meta = dict(data_run.metadata or {})
            meta["architecture_assessment_id"] = str(assessment.id)
            meta["mode"] = assessment.mode
            meta["asset_count"] = len(inventory.assets)
            meta["edge_count"] = len(graph.edges)
            meta["verdict_count"] = len(verdicts.verdicts)
            meta["graph_complete"] = graph.graph_complete
            meta["lifecycle_gap_count"] = len(wf12.gap_stage_ids)
            meta["lifecycle_covered_stage_count"] = len(wf12.covered_stage_ids)
            data_run.metadata = meta
            data_run.save(
                update_fields=["status", "finished_at", "metadata", "updated_at"]
            )

        return {
            "ok": True,
            "assessment_id": str(assessment.id),
            "mode": assessment.mode,
            "status": assessment.status,
            "asset_count": len(inventory.assets),
            "edge_count": len(graph.edges),
            "verdict_count": len(verdicts.verdicts),
            "graph_complete": graph.graph_complete,
            "lifecycle_gap_count": len(wf12.gap_stage_ids),
            "lifecycle_covered_stage_count": len(wf12.covered_stage_ids),
            "weighted_score": verdicts.weighted_score,
            "critical_defects": verdicts.critical_defects,
            "evidence_coverage": coverage,
            "probes": {p.probe_id: p.status for p in all_probes},
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("architecture_assessment failed id=%s", assessment_id)
        assessment.status = ArchitectureAssessment.Status.FAILED
        assessment.error_message = str(exc)[:2000]
        assessment.finished_at = timezone.now()
        assessment.save(
            update_fields=["status", "error_message", "finished_at", "updated_at"]
        )
        data_run.status = DataRun.Status.FAILED
        data_run.finished_at = timezone.now()
        data_run.save(update_fields=["status", "finished_at", "updated_at"])
        return {"ok": False, "error": str(exc)}
