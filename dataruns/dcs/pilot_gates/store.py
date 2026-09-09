"""Persist / load pilot supplemental gate evaluations (DCS-09 Step 2).

Uses ``DataRun`` with ``metadata.kind = pilot_gate_eval``. Does **not** touch
DCS worklist / headline score (42).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from dataruns.dcs.pilot_gates.contract import (
    GATE_CATALOG_VERSION,
    PILOT_GATE_EVAL_KIND,
    PILOT_SUPPLEMENTAL_SCOPE,
    SEVERITY_ENUM,
    SUPPLEMENTAL_CHECK_IDS,
    SUPPLEMENTAL_RESULT_STATUS_ENUM,
)
from dataruns.dcs.pilot_gates.master import get_supplemental_check
from dataruns.models import DataRun
from tenants.models import Company

PILOT_GATE_EVAL_DATA_RUN_NAME = "pilot-gate-eval"


class PilotGateStoreError(ValueError):
    """Invalid pilot gate eval payload."""


@dataclass(frozen=True)
class PilotGateEvalBundle:
    """Latest (or saved) supplemental evaluation for a company."""

    data_run_id: int
    company_id: str
    scope: str
    gate_catalog_version: str
    data_run_id_score: int | None
    erp_in_scope: bool
    results: tuple[dict[str, Any], ...]
    evaluated_at: str | None
    status_by_check_id: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_run_id": self.data_run_id,
            "company_id": self.company_id,
            "scope": self.scope,
            "gate_catalog_version": self.gate_catalog_version,
            "data_run_id_score": self.data_run_id_score,
            "erp_in_scope": self.erp_in_scope,
            "results": [deepcopy(r) for r in self.results],
            "evaluated_at": self.evaluated_at,
            "status_by_check_id": dict(self.status_by_check_id),
            "count": len(self.results),
        }


def _normalize_severity(value: str, *, check_id: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    titled = text[:1].upper() + text[1:].lower()
    if titled in SEVERITY_ENUM:
        return titled
    if text in SEVERITY_ENUM:
        return text
    raise PilotGateStoreError(
        f"Invalid severity for {check_id}: {value!r} (expected High|Medium|Low)"
    )


def _normalize_result_row(
    row: dict[str, Any],
    *,
    evaluated_at: str,
) -> dict[str, Any]:
    check_id = str(row.get("check_id") or "").strip().upper()
    if check_id not in SUPPLEMENTAL_CHECK_IDS:
        raise PilotGateStoreError(f"Unknown supplemental check_id: {check_id!r}")
    status = str(row.get("status") or "").strip().upper()
    if status not in SUPPLEMENTAL_RESULT_STATUS_ENUM:
        raise PilotGateStoreError(
            f"Invalid status for {check_id}: {row.get('status')!r}"
        )
    master = get_supplemental_check(check_id)
    severity_raw = str(row.get("severity") or "").strip()
    if severity_raw:
        severity = _normalize_severity(severity_raw, check_id=check_id)
    elif master is not None:
        severity = master.severity
    else:
        severity = "Medium"
    required_by = row.get("required_by")
    if not isinstance(required_by, list) or not required_by:
        required_by = list(master.required_by) if master is not None else []
    else:
        required_by = [str(u).strip().upper() for u in required_by if str(u).strip()]
    evidence = row.get("evidence")
    if evidence is None:
        evidence = []
    if not isinstance(evidence, list):
        raise PilotGateStoreError(f"evidence for {check_id} must be a list")
    evaluated = str(row.get("evaluated_at") or "").strip() or evaluated_at
    out: dict[str, Any] = {
        "check_id": check_id,
        "status": status,
        "severity": severity,
        "evidence": deepcopy(evidence),
        "required_by": required_by,
        "evaluated_at": evaluated,
    }
    reason = row.get("reason_code")
    if reason not in (None, ""):
        out["reason_code"] = str(reason).strip()
    message = row.get("message")
    if message not in (None, ""):
        out["message"] = str(message).strip()
    return out


def _results_to_status_map(results: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("check_id") or "").strip().upper()
        status = str(row.get("status") or "").strip().upper()
        if cid and status:
            out[cid] = status
    return out


def _merge_results(
    previous: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Overlay incoming rows onto previous by check_id (sorted for stability)."""
    by_id: dict[str, dict[str, Any]] = {}
    for row in previous:
        if isinstance(row, dict):
            cid = str(row.get("check_id") or "").strip().upper()
            if cid:
                by_id[cid] = deepcopy(row)
    for row in incoming:
        cid = str(row.get("check_id") or "").strip().upper()
        if cid:
            by_id[cid] = deepcopy(row)
    return [by_id[cid] for cid in sorted(by_id)]


def _company_pilot_gate_runs(*, company: Company):
    return DataRun.objects.filter(
        tenant=company.tenant,
        name=PILOT_GATE_EVAL_DATA_RUN_NAME,
        metadata__kind=PILOT_GATE_EVAL_KIND,
        metadata__scope=PILOT_SUPPLEMENTAL_SCOPE,
        metadata__company_id=str(company.id),
    ).order_by("-created_at")


def _bundle_from_data_run(data_run: DataRun) -> PilotGateEvalBundle:
    meta = data_run.metadata if isinstance(data_run.metadata, dict) else {}
    results_raw = meta.get("results")
    results: list[dict[str, Any]] = []
    if isinstance(results_raw, list):
        for row in results_raw:
            if isinstance(row, dict):
                results.append(deepcopy(row))
    score_id = meta.get("data_run_id_score")
    try:
        score_id_int = int(score_id) if score_id is not None else None
    except (TypeError, ValueError):
        score_id_int = None
    evaluated_at = meta.get("evaluated_at")
    if not evaluated_at and data_run.finished_at is not None:
        evaluated_at = data_run.finished_at.isoformat()
    return PilotGateEvalBundle(
        data_run_id=int(data_run.pk),
        company_id=str(meta.get("company_id") or ""),
        scope=str(meta.get("scope") or PILOT_SUPPLEMENTAL_SCOPE),
        gate_catalog_version=str(
            meta.get("gate_catalog_version") or GATE_CATALOG_VERSION
        ),
        data_run_id_score=score_id_int,
        erp_in_scope=bool(meta.get("erp_in_scope")),
        results=tuple(results),
        evaluated_at=str(evaluated_at) if evaluated_at else None,
        status_by_check_id=_results_to_status_map(results),
    )


def get_latest_pilot_gate_eval(*, company: Company) -> PilotGateEvalBundle | None:
    """Latest succeeded supplemental eval for company (recommend merge SoT)."""
    data_run = (
        _company_pilot_gate_runs(company=company)
        .filter(status=DataRun.Status.SUCCEEDED)
        .first()
    )
    if data_run is None:
        return None
    return _bundle_from_data_run(data_run)


def get_latest_supplemental_status_map(*, company: Company) -> dict[str, str]:
    """check_id → status from latest eval (empty dict if none)."""
    bundle = get_latest_pilot_gate_eval(company=company)
    if bundle is None:
        return {}
    return dict(bundle.status_by_check_id)


@transaction.atomic
def save_pilot_gate_eval(
    *,
    company: Company,
    results: list[dict[str, Any]],
    data_run_id_score: int | None = None,
    erp_in_scope: bool | None = None,
    merge_with_previous: bool = True,
    triggered_by: str = "manual",
    actor_user_id: str | None = None,
) -> PilotGateEvalBundle:
    """
    Persist a new ``pilot_gate_eval`` DataRun for the company.

    By default merges ``results`` onto the previous latest succeeded bundle so
    partial evaluates (Slice A) do not wipe earlier check statuses.

    When ``data_run_id_score`` / ``erp_in_scope`` are omitted (``None``), values
    from the previous succeeded eval are preserved on merge.
    """
    if not isinstance(results, list):
        raise PilotGateStoreError("results must be a list")
    if not results:
        raise PilotGateStoreError("results must be a non-empty list")

    now = timezone.now()
    evaluated_at = now.isoformat()
    normalized = [
        _normalize_result_row(row, evaluated_at=evaluated_at)
        for row in results
        if isinstance(row, dict)
    ]
    if not normalized:
        raise PilotGateStoreError("results contained no valid objects")

    previous_rows: list[dict[str, Any]] = []
    prev_bundle: PilotGateEvalBundle | None = None
    if merge_with_previous:
        prev_bundle = get_latest_pilot_gate_eval(company=company)
        if prev_bundle is not None:
            previous_rows = [deepcopy(r) for r in prev_bundle.results]

    merged = _merge_results(previous_rows, normalized)

    resolved_score_id = data_run_id_score
    if resolved_score_id is None and prev_bundle is not None:
        resolved_score_id = prev_bundle.data_run_id_score

    if erp_in_scope is None:
        resolved_erp = bool(prev_bundle.erp_in_scope) if prev_bundle else False
    else:
        resolved_erp = bool(erp_in_scope)

    metadata: dict[str, Any] = {
        "kind": PILOT_GATE_EVAL_KIND,
        "scope": PILOT_SUPPLEMENTAL_SCOPE,
        "company_id": str(company.id),
        "gate_catalog_version": GATE_CATALOG_VERSION,
        "data_run_id_score": resolved_score_id,
        "erp_in_scope": resolved_erp,
        "triggered_by": triggered_by,
        "evaluated_at": evaluated_at,
        "results": merged,
        "count": len(merged),
    }
    if actor_user_id:
        metadata["actor_user_id"] = str(actor_user_id)

    data_run = DataRun.objects.create(
        tenant=company.tenant,
        name=PILOT_GATE_EVAL_DATA_RUN_NAME,
        status=DataRun.Status.SUCCEEDED,
        started_at=now,
        finished_at=now,
        metadata=metadata,
    )
    return _bundle_from_data_run(data_run)
