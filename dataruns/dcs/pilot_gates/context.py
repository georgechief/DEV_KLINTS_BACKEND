"""Supplemental gate evaluation context (DCS-09 Step 3).

Reuses a DCS score ``run_snapshot`` when available. Never writes into assemble.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import DataRun
from tenants.models import Company


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


@dataclass
class SupplementalGateContext:
    """Inputs for one supplemental gate evaluation pass."""

    company: Company
    erp_in_scope: bool = False
    data_run_id_score: int | None = None
    scoring_snapshot: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = ""
    run_id: str = ""
    evaluated_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return self.scoring_snapshot if isinstance(self.scoring_snapshot, dict) else {}


def get_latest_succeeded_dcs_score_run(*, company: Company) -> DataRun | None:
    """Latest succeeded headline DCS score DataRun for the company."""
    return (
        DataRun.objects.filter(
            tenant=company.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata__kind=DCS_SCORE_KIND,
            metadata__company_id=str(company.id),
        )
        .order_by("-created_at")
        .first()
    )


def resolve_dcs_score_run(
    *,
    company: Company,
    data_run_id: int | None = None,
) -> DataRun | None:
    """
    Explicit score run id, else latest succeeded DCS score for company.

    Explicit ids must still be a **succeeded** headline ``dcs-score`` run for
    this company (same tenant + ``metadata.company_id``). Failed / running /
    wrong-kind rows are rejected so gates never read a partial snapshot.
    """
    if data_run_id is not None:
        try:
            run = DataRun.objects.get(pk=int(data_run_id))
        except (DataRun.DoesNotExist, TypeError, ValueError):
            return None
        meta = run.metadata if isinstance(run.metadata, dict) else {}
        if run.name != DCS_SCORE_DATA_RUN_NAME:
            return None
        if str(meta.get("kind") or "") != DCS_SCORE_KIND:
            return None
        if run.status != DataRun.Status.SUCCEEDED:
            return None
        if str(meta.get("company_id") or "") != str(company.id):
            return None
        if run.tenant_id != company.tenant_id:
            return None
        return run
    return get_latest_succeeded_dcs_score_run(company=company)


def build_supplemental_gate_context(
    *,
    company: Company,
    erp_in_scope: bool = False,
    data_run_id: int | None = None,
    scoring_snapshot: dict[str, Any] | None = None,
) -> SupplementalGateContext:
    """
    Build context for supplemental executors.

    Always resolve the DCS score run for ``data_run_id_score`` linkage
    (explicit id or latest succeeded). Snapshot preference:
    1. Explicit ``scoring_snapshot`` (override; still links score run when found)
    2. ``run_snapshot`` on resolved DCS score DataRun
    3. Empty dict (executors must degrade to UNKNOWN / MISSING_INPUT)
    """
    score_run = resolve_dcs_score_run(company=company, data_run_id=data_run_id)
    if scoring_snapshot is not None:
        snapshot = scoring_snapshot if isinstance(scoring_snapshot, dict) else {}
    elif score_run is not None and isinstance(score_run.run_snapshot, dict):
        snapshot = score_run.run_snapshot
    else:
        snapshot = {}

    return SupplementalGateContext(
        company=company,
        erp_in_scope=bool(erp_in_scope),
        data_run_id_score=int(score_run.pk) if score_run is not None else None,
        scoring_snapshot=snapshot,
        tenant_id=str(company.tenant_id),
        run_id=str(score_run.pk) if score_run is not None else "",
        evaluated_at=_utcnow_iso(),
    )
