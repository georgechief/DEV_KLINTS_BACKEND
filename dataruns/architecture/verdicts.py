"""Phase D verdict engine + mode rollup (PRD-AF-01 BL-009 / sheets 03 + 06)."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from dataruns.architecture.graph import GraphEdge
from dataruns.architecture.inventory import InventoryAsset, ProbeOutcome
from dataruns.architecture.models import ArchitectureAssessment, ArchitectureAssetVerdict
from dataruns.models import DataRun, QaCheck, RunScore

logger = logging.getLogger(__name__)

# Sheet 06 weights (PRD §6.3).
_WEIGHT_LIFECYCLE = 0.25
_WEIGHT_DATA_SAFE = 0.25
_WEIGHT_COLLISION = 0.15
_WEIGHT_MEASUREMENT = 0.15
_WEIGHT_MAINTAINABILITY = 0.20

_COVERAGE_GATE = 0.80

_CONSENT_PREFIXES = ("CC-",)
_PROPERTY_CHECKS = frozenset({"SP-03", "SP-04", "SP-05"})
_TAG_CHECKS = frozenset({"SP-01", "SP-08"})
_MEASUREMENT_CHECKS = frozenset({"ME-02"})

_DORMANT_STATUSES = frozenset(
    {
        "inactive",
        "disabled",
        "dormant",
        "paused",
        "stopped",
        "archived",
        "retired",
    }
)

_TRIGGER_NORM_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class ImpairedCheck:
    check_id: str
    status: str  # FAIL | WARN


@dataclass
class DcsJoin:
    checks: list[ImpairedCheck] = field(default_factory=list)
    source_dcs_data_run_id: int | None = None
    domain_run_id: str | None = None

    @property
    def by_id(self) -> dict[str, ImpairedCheck]:
        return {c.check_id: c for c in self.checks}

    def ids(self, *, statuses: set[str] | None = None) -> list[str]:
        out = []
        for c in self.checks:
            if statuses is None or c.status in statuses:
                out.append(c.check_id)
        return out


@dataclass(frozen=True)
class AssetVerdictRow:
    asset_id: str
    verdict: str
    evidence_ids: list[str] = field(default_factory=list)
    blocked_reason: str = ""
    failure_code: str = ""
    dcs_check_ids: list[str] = field(default_factory=list)


@dataclass
class VerdictResult:
    verdicts: list[AssetVerdictRow]
    probes: list[ProbeOutcome]
    mode: str
    weighted_score: float | None
    critical_defects: int
    evidence: dict[str, Any] = field(default_factory=dict)


def load_dcs_join(source_dcs_data_run: DataRun | None) -> DcsJoin:
    """Load FAIL/WARN check results from the triggering DCS DataRun (PRD §10)."""
    if source_dcs_data_run is None:
        return DcsJoin()

    meta = source_dcs_data_run.metadata or {}
    domain_run_id = meta.get("run_id")
    checks: list[ImpairedCheck] = []

    if domain_run_id:
        for row in QaCheck.objects.filter(
            run_id=domain_run_id,
            result__in=("FAIL", "WARN"),
        ).only("check_type", "result"):
            cid = str(row.check_type or "").strip()
            if cid:
                checks.append(ImpairedCheck(check_id=cid, status=str(row.result)))

    if not checks:
        # Fallback: RunScore.breakdown.check_results on the domain run.
        score = None
        if domain_run_id:
            score = (
                RunScore.objects.filter(run_id=domain_run_id)
                .order_by("-id")
                .first()
            )
        if score and isinstance(score.breakdown, dict):
            for raw in score.breakdown.get("check_results") or []:
                if not isinstance(raw, dict):
                    continue
                status = str(raw.get("status") or "")
                if status not in {"FAIL", "WARN"}:
                    continue
                cid = str(raw.get("check_id") or "").strip()
                if cid:
                    checks.append(ImpairedCheck(check_id=cid, status=status))

    # Deduplicate by check_id (prefer FAIL over WARN).
    by_id: dict[str, ImpairedCheck] = {}
    for item in checks:
        prev = by_id.get(item.check_id)
        if prev is None or (prev.status != "FAIL" and item.status == "FAIL"):
            by_id[item.check_id] = item

    return DcsJoin(
        checks=list(by_id.values()),
        source_dcs_data_run_id=source_dcs_data_run.id,
        domain_run_id=str(domain_run_id) if domain_run_id else None,
    )


def _is_consent(check_id: str) -> bool:
    return any(check_id.startswith(p) for p in _CONSENT_PREFIXES)


def _norm_trigger(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        text = str(value)
    else:
        text = str(value)
    return _TRIGGER_NORM_RE.sub(" ", text.strip().lower()).strip()


def _is_dormant(asset: InventoryAsset) -> bool:
    status = (asset.status or "").strip().lower()
    if status in _DORMANT_STATUSES:
        return True
    if status in {"false", "0"}:
        return True
    return False


def _dependents_of(
    asset_id: str,
    edges: list[GraphEdge],
) -> list[str]:
    """Incoming edges: other assets that depend on this asset."""
    return [
        e.source_asset_id
        for e in edges
        if e.target_asset_id == asset_id
    ]


def _reads_targets(
    source_asset_id: str,
    edges: list[GraphEdge],
) -> set[str]:
    return {
        e.target_asset_id
        for e in edges
        if e.source_asset_id == source_asset_id
        and e.edge_type in {"READS", "USES", "WRITES"}
    }


def _build_fix_first_map(
    *,
    assets: list[InventoryAsset],
    edges: list[GraphEdge],
    dcs: DcsJoin,
) -> dict[str, list[str]]:
    """
    Map asset_id → responsible DCS check IDs for FIX_FIRST (WF-05 / WF-06 / PROP/TAG joins).
    """
    from dataruns.architecture.models import ArchitectureAsset

    fix: dict[str, set[str]] = defaultdict(set)
    by_id = {a.asset_id: a for a in assets}

    tag_ids = {
        a.asset_id
        for a in assets
        if a.asset_type == ArchitectureAsset.AssetType.TAG
    }
    prop_ids = {
        a.asset_id
        for a in assets
        if a.asset_type == ArchitectureAsset.AssetType.PROPERTY
    }
    workflow_ids = {
        a.asset_id
        for a in assets
        if a.asset_type == ArchitectureAsset.AssetType.WORKFLOW
    }

    consent_ids = [c.check_id for c in dcs.checks if _is_consent(c.check_id)]
    prop_checks = [
        c.check_id for c in dcs.checks if c.check_id in _PROPERTY_CHECKS
    ]
    tag_checks = [c.check_id for c in dcs.checks if c.check_id in _TAG_CHECKS]
    # Remaining FAIL (not measurement) → broad WF-05 join.
    other_fail = [
        c.check_id
        for c in dcs.checks
        if c.status == "FAIL"
        and not _is_consent(c.check_id)
        and c.check_id not in _PROPERTY_CHECKS
        and c.check_id not in _TAG_CHECKS
        and c.check_id not in _MEASUREMENT_CHECKS
    ]

    # WF-06 — consent impairs workflows.
    for wf_id in workflow_ids:
        for cid in consent_ids:
            fix[wf_id].add(cid)

    # PROP-02 join — impaired properties + workflows that READ them.
    for prop_id in prop_ids:
        for cid in prop_checks:
            fix[prop_id].add(cid)
    if prop_checks:
        for wf_id in workflow_ids:
            targets = _reads_targets(wf_id, edges)
            if targets & prop_ids:
                for cid in prop_checks:
                    fix[wf_id].add(cid)
            elif not edges:
                # No graph refs — still flag workflows when property checks fail (WF-05).
                for cid in prop_checks:
                    fix[wf_id].add(cid)

    # TAG-02 / TAG-03 join
    for tag_id in tag_ids:
        for cid in tag_checks:
            fix[tag_id].add(cid)
    if tag_checks:
        for wf_id in workflow_ids:
            targets = _reads_targets(wf_id, edges)
            if targets & tag_ids:
                for cid in tag_checks:
                    fix[wf_id].add(cid)
            elif not edges:
                for cid in tag_checks:
                    fix[wf_id].add(cid)

    # WF-05 — other FAIL checks impair workflows.
    for wf_id in workflow_ids:
        for cid in other_fail:
            fix[wf_id].add(cid)

    return {aid: sorted(ids) for aid, ids in fix.items() if ids and aid in by_id}


def _overlap_clusters(
    workflows: list[InventoryAsset],
) -> dict[str, list[str]]:
    """Group workflow asset_ids by normalized trigger (WF-07)."""
    buckets: dict[str, list[str]] = defaultdict(list)
    for wf in workflows:
        definition = wf.definition if isinstance(wf.definition, dict) else {}
        trigger = _norm_trigger(definition.get("trigger"))
        if not trigger:
            continue
        buckets[trigger].append(wf.asset_id)
    return {k: v for k, v in buckets.items() if len(v) >= 2}


def assign_asset_verdicts(
    *,
    assets: list[InventoryAsset],
    edges: list[GraphEdge],
    dcs: DcsJoin,
    graph_complete: bool,
) -> tuple[list[AssetVerdictRow], list[ProbeOutcome]]:
    """
    Sheet 03 order per asset:
    FIX_FIRST → CONSOLIDATE (graph gate) → RETIRE (graph gate) → KEEP_IMPROVE → KEEP
    """
    from dataruns.architecture.models import ArchitectureAsset

    fix_map = _build_fix_first_map(assets=assets, edges=edges, dcs=dcs)
    workflows = [
        a for a in assets if a.asset_type == ArchitectureAsset.AssetType.WORKFLOW
    ]
    clusters = _overlap_clusters(workflows)
    in_cluster = {aid for members in clusters.values() for aid in members}

    measurement_impaired = [
        c.check_id
        for c in dcs.checks
        if c.check_id in _MEASUREMENT_CHECKS
    ]

    verdicts: list[AssetVerdictRow] = []
    consolidate_assigned = 0
    retire_assigned = 0
    retire_blocked = 0
    consolidate_blocked = 0
    fix_first_count = 0

    for asset in assets:
        aid = asset.asset_id
        dcs_ids = fix_map.get(aid, [])

        # 1) FIX_FIRST
        if dcs_ids:
            fix_first_count += 1
            verdicts.append(
                AssetVerdictRow(
                    asset_id=aid,
                    verdict=ArchitectureAssetVerdict.Verdict.FIX_FIRST,
                    evidence_ids=["WF-05", "WF-06"] if asset.asset_type == "WORKFLOW" else ["DCS_JOIN"],
                    dcs_check_ids=dcs_ids,
                )
            )
            continue

        # 2) CONSOLIDATE (workflows in overlap clusters)
        if aid in in_cluster:
            if graph_complete:
                consolidate_assigned += 1
                verdicts.append(
                    AssetVerdictRow(
                        asset_id=aid,
                        verdict=ArchitectureAssetVerdict.Verdict.CONSOLIDATE,
                        evidence_ids=["WF-07", "WF-09"],
                    )
                )
            else:
                consolidate_blocked += 1
                verdicts.append(
                    AssetVerdictRow(
                        asset_id=aid,
                        verdict=ArchitectureAssetVerdict.Verdict.KEEP_IMPROVE,
                        evidence_ids=["WF-07"],
                        blocked_reason=(
                            "Overlap detected but dependency graph incomplete; "
                            "Consolidate blocked (sheet 01/08)."
                        ),
                        failure_code="GRAPH_GATE",
                    )
                )
            continue

        # 3) RETIRE_CANDIDATE — dormant + zero dependents
        dependents = _dependents_of(aid, edges)
        orphan_candidate = (
            asset.asset_type
            in {
                ArchitectureAsset.AssetType.TAG,
                ArchitectureAsset.AssetType.PROPERTY,
                ArchitectureAsset.AssetType.SEGMENT,
            }
            and len(dependents) == 0
        )
        dormant = _is_dormant(asset) or (
            orphan_candidate and asset.asset_type != ArchitectureAsset.AssetType.WORKFLOW
        )

        if dormant and len(dependents) == 0:
            if graph_complete:
                retire_assigned += 1
                verdicts.append(
                    AssetVerdictRow(
                        asset_id=aid,
                        verdict=ArchitectureAssetVerdict.Verdict.RETIRE_CANDIDATE,
                        evidence_ids=["WF-03", "WF-09"] if asset.asset_type == "WORKFLOW" else ["TAG-05", "PROP-05", "WF-09"],
                    )
                )
            else:
                retire_blocked += 1
                verdicts.append(
                    AssetVerdictRow(
                        asset_id=aid,
                        verdict=ArchitectureAssetVerdict.Verdict.KEEP,
                        evidence_ids=["WF-09"],
                        blocked_reason=(
                            "Retire candidate blocked: dependency graph incomplete "
                            "(zero-dependent proof not trusted)."
                        ),
                        failure_code="GRAPH_GATE",
                    )
                )
            continue

        if dependents and _is_dormant(asset):
            # Has dependents — cannot retire; keep baseline.
            verdicts.append(
                AssetVerdictRow(
                    asset_id=aid,
                    verdict=ArchitectureAssetVerdict.Verdict.KEEP,
                    evidence_ids=["WF-09"],
                    blocked_reason="Dormant but has dependents; Retire disqualified.",
                    failure_code="HAS_DEPENDENTS",
                )
            )
            continue

        # 4) KEEP_IMPROVE — weak measurement / incomplete definition
        definition = asset.definition if isinstance(asset.definition, dict) else {}
        weak = False
        evidence = []
        if asset.asset_type == ArchitectureAsset.AssetType.WORKFLOW and measurement_impaired:
            weak = True
            evidence.append("WF-10")
        if asset.asset_type == ArchitectureAsset.AssetType.WORKFLOW and not definition.get(
            "trigger"
        ):
            weak = True
            evidence.append("WF-04")
        if weak:
            verdicts.append(
                AssetVerdictRow(
                    asset_id=aid,
                    verdict=ArchitectureAssetVerdict.Verdict.KEEP_IMPROVE,
                    evidence_ids=evidence or ["KEEP_IMPROVE"],
                    dcs_check_ids=list(measurement_impaired)
                    if measurement_impaired and asset.asset_type == "WORKFLOW"
                    else [],
                )
            )
            continue

        # 5) KEEP
        verdicts.append(
            AssetVerdictRow(
                asset_id=aid,
                verdict=ArchitectureAssetVerdict.Verdict.KEEP,
                evidence_ids=["BASELINE"],
            )
        )

    probes = [
        ProbeOutcome(
            probe_id="WF-05",
            # Join ran if a source DCS DataRun is linked — empty FAIL/WARN is healthy.
            status=(
                "succeeded"
                if dcs.source_dcs_data_run_id is not None
                else "incomplete"
            ),
            evidence={
                "impaired_checks": len(dcs.checks),
                "fix_first_assets": fix_first_count,
                "source_dcs_data_run_id": dcs.source_dcs_data_run_id,
            },
        ),
        ProbeOutcome(
            probe_id="WF-06",
            status="succeeded"
            if any(_is_consent(c.check_id) for c in dcs.checks) or not dcs.checks
            else "partial",
            evidence={
                "consent_checks": [c.check_id for c in dcs.checks if _is_consent(c.check_id)],
            },
        ),
        ProbeOutcome(
            probe_id="WF-07",
            status="partial" if clusters and not graph_complete else (
                "succeeded" if clusters or not workflows else "succeeded"
            ),
            evidence={
                "overlap_clusters": len(clusters),
                "consolidate_assigned": consolidate_assigned,
                "consolidate_blocked": consolidate_blocked,
                "graph_complete": graph_complete,
            },
        ),
        ProbeOutcome(
            probe_id="WF-03",
            status="succeeded",
            evidence={
                "retire_assigned": retire_assigned,
                "retire_blocked": retire_blocked,
                "graph_complete": graph_complete,
            },
        ),
        ProbeOutcome(
            probe_id="WF-10",
            status="succeeded" if measurement_impaired or not dcs.checks else "partial",
            evidence={"measurement_checks": measurement_impaired},
        ),
    ]
    return verdicts, probes


def _score_component(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def rollup_mode(
    *,
    evidence_coverage: float,
    graph_complete: bool,
    verdicts: list[AssetVerdictRow],
    assets: list[InventoryAsset],
    dcs: DcsJoin,
) -> tuple[str, float | None, int, dict[str, Any]]:
    """
    Sheet 06 decision order:
    1) coverage < 0.80 → INCOMPLETE
    2) consent critical → assets already FIX_FIRST; continue
    3) graph incomplete → INCOMPLETE
    4) weighted score → AUGMENT / SELECTIVE_REBUILD / REBUILD
    """
    consent_fail = [
        c.check_id for c in dcs.checks if _is_consent(c.check_id) and c.status == "FAIL"
    ]
    critical_defects = len(consent_fail)

    # Collision critical: treat large consolidate pressure as a defect cluster.
    consolidate_n = sum(
        1
        for v in verdicts
        if v.verdict == ArchitectureAssetVerdict.Verdict.CONSOLIDATE
        or (
            v.failure_code == "GRAPH_GATE"
            and "Overlap" in (v.blocked_reason or "")
        )
    )
    if consolidate_n >= 3:
        critical_defects += 1

    detail: dict[str, Any] = {
        "evidence_coverage": evidence_coverage,
        "graph_complete": graph_complete,
        "consent_fail": consent_fail,
        "critical_defects": critical_defects,
    }

    if evidence_coverage < _COVERAGE_GATE:
        detail["gate"] = "coverage"
        return (
            ArchitectureAssessment.Mode.INCOMPLETE,
            None,
            critical_defects,
            detail,
        )

    if not graph_complete:
        detail["gate"] = "graph_incomplete"
        return (
            ArchitectureAssessment.Mode.INCOMPLETE,
            None,
            critical_defects,
            detail,
        )

    total = max(len(verdicts), 1)
    fix_n = sum(
        1 for v in verdicts if v.verdict == ArchitectureAssetVerdict.Verdict.FIX_FIRST
    )
    keep_n = sum(
        1
        for v in verdicts
        if v.verdict
        in {
            ArchitectureAssetVerdict.Verdict.KEEP,
            ArchitectureAssetVerdict.Verdict.KEEP_IMPROVE,
        }
    )
    staged = sum(1 for a in assets if getattr(a, "lifecycle_stage", None))
    lifecycle_score = _score_component((staged / max(len(assets), 1)) * 100.0)
    # Without Phase F stage map, treat empty stages as mid coverage (neutral 50).
    if staged == 0:
        lifecycle_score = 50.0

    data_safe_score = _score_component(((total - fix_n) / total) * 100.0)
    collision_score = _score_component(
        ((total - consolidate_n) / total) * 100.0
    )
    measurement_ok = not any(
        c.check_id in _MEASUREMENT_CHECKS and c.status == "FAIL" for c in dcs.checks
    )
    measurement_score = 100.0 if measurement_ok else 40.0
    maintainability_score = _score_component((keep_n / total) * 100.0)

    weighted = (
        lifecycle_score * _WEIGHT_LIFECYCLE
        + data_safe_score * _WEIGHT_DATA_SAFE
        + collision_score * _WEIGHT_COLLISION
        + measurement_score * _WEIGHT_MEASUREMENT
        + maintainability_score * _WEIGHT_MAINTAINABILITY
    )
    weighted = round(weighted, 2)
    detail.update(
        {
            "gate": "weighted_score",
            "lifecycle_score": lifecycle_score,
            "data_safe_score": data_safe_score,
            "collision_score": collision_score,
            "measurement_score": measurement_score,
            "maintainability_score": maintainability_score,
            "weighted_score": weighted,
        }
    )

    if critical_defects >= 2 or weighted < 50:
        mode = ArchitectureAssessment.Mode.REBUILD
    elif critical_defects == 1 or 50 <= weighted < 70:
        mode = ArchitectureAssessment.Mode.SELECTIVE_REBUILD
    else:
        # AUGMENT: score ≥ 70, <2 critical, no unmitigated consent breach
        if consent_fail:
            mode = ArchitectureAssessment.Mode.SELECTIVE_REBUILD
        else:
            mode = ArchitectureAssessment.Mode.AUGMENT

    return mode, weighted, critical_defects, detail


def run_phase_d_verdicts(
    *,
    assets: list[InventoryAsset],
    edges: list[GraphEdge],
    graph_complete: bool,
    evidence_coverage: float,
    source_dcs_data_run: DataRun | None,
) -> VerdictResult:
    """Assign per-asset verdicts and account mode (BL-009)."""
    dcs = load_dcs_join(source_dcs_data_run)
    verdicts, probes = assign_asset_verdicts(
        assets=assets,
        edges=edges,
        dcs=dcs,
        graph_complete=graph_complete,
    )
    mode, weighted, critical, detail = rollup_mode(
        evidence_coverage=evidence_coverage,
        graph_complete=graph_complete,
        verdicts=verdicts,
        assets=assets,
        dcs=dcs,
    )
    detail["dcs_impaired_count"] = len(dcs.checks)
    detail["verdict_count"] = len(verdicts)
    return VerdictResult(
        verdicts=verdicts,
        probes=probes,
        mode=mode,
        weighted_score=weighted,
        critical_defects=critical,
        evidence=detail,
    )
