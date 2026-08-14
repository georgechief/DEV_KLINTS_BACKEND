"""DCS run progress stages for gated dashboard (PRD-FE-04)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.master import (
    CheckDefinition,
    CheckMaster,
    CheckMasterNotSeededError,
    load_check_master,
    load_check_master_from_json,
)
from dataruns.dcs.types import CheckResult
from dataruns.models import DataRun, DimensionMaster

STAGE_DIMENSION_ORDER: tuple[str, ...] = (
    "00",
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
)

_STAGE_KEYS: dict[str, str] = {
    "00": "foundation",
    "01": "identity",
    "02": "lifecycle",
    "03": "product",
    "04": "segment",
    "05": "channel",
    "06": "measurement",
    "07": "business",
}

_STAGE_LABELS: dict[str, str] = {
    "00": "Foundation Gate",
    "01": "Customer Identity",
    "02": "Lifecycle Event",
    "03": "Product & Transaction",
    "04": "Segment & Property",
    "05": "Channel & Consent",
    "06": "Measurement",
    "07": "Business Reality",
}


def _dimension_id_from_label(label: str) -> str:
    token = label.strip().split(" ", 1)[0]
    if len(token) == 2 and token.isdigit():
        return token
    return "00"


def _resolve_progress_master(master: CheckMaster | None = None) -> CheckMaster:
    if master is not None:
        return master
    try:
        return load_check_master()
    except CheckMasterNotSeededError:
        return load_check_master_from_json()
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            return load_check_master_from_json()
        raise


def _static_stage_catalog() -> list[dict[str, str]]:
    return [
        {
            "dimension_id": dimension_id,
            "key": _STAGE_KEYS[dimension_id],
            "label": _STAGE_LABELS[dimension_id],
        }
        for dimension_id in STAGE_DIMENSION_ORDER
    ]


def _stage_catalog() -> list[dict[str, str]]:
    static = _static_stage_catalog()
    try:
        rows = list(
            DimensionMaster.objects.filter(
                is_active=True,
                dimension_id__in=STAGE_DIMENSION_ORDER,
            ).order_by("dimension_id")
        )
    except Exception:
        return static

    if len(rows) < len(STAGE_DIMENSION_ORDER):
        return static

    catalog: list[dict[str, str]] = []
    by_id = {row.dimension_id: row for row in rows}
    for dimension_id in STAGE_DIMENSION_ORDER:
        row = by_id.get(dimension_id)
        if row is None:
            continue
        catalog.append(
            {
                "dimension_id": dimension_id,
                "key": _STAGE_KEYS.get(dimension_id, dimension_id),
                "label": row.name or _STAGE_LABELS[dimension_id],
            }
        )
    return catalog or static


def group_checks_by_dimension(master: CheckMaster) -> dict[str, list[CheckDefinition]]:
    grouped: dict[str, list[CheckDefinition]] = {
        dimension_id: [] for dimension_id in STAGE_DIMENSION_ORDER
    }
    for definition in master.checks:
        dimension_id = _dimension_id_from_label(definition.dimension)
        grouped.setdefault(dimension_id, []).append(definition)
    return grouped


def _results_by_check_id(check_results: list[CheckResult | dict[str, Any]]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for item in check_results:
        if isinstance(item, CheckResult):
            payload = item.to_dict()
        elif isinstance(item, dict):
            payload = item
        else:
            continue
        check_id = payload.get("check_id")
        if isinstance(check_id, str):
            indexed[check_id] = payload
    return indexed


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _count_statuses(results: list[dict[str, Any]]) -> tuple[int, int]:
    fail_count = sum(1 for row in results if row.get("status") == "FAIL")
    warn_count = sum(1 for row in results if row.get("status") == "WARN")
    return fail_count, warn_count


def _stage_state_for_dimension(
    *,
    dimension_id: str,
    check_ids: list[str],
    results_by_check_id: dict[str, dict[str, Any]],
    current_dimension_id: str | None,
    run_status: str,
) -> str:
    results = [
        results_by_check_id[check_id]
        for check_id in check_ids
        if check_id in results_by_check_id
    ]
    evaluated_count = len(results)
    check_count = len(check_ids)
    is_active = run_status in {DataRun.Status.PENDING, DataRun.Status.RUNNING}
    is_terminal = run_status in {DataRun.Status.SUCCEEDED, DataRun.Status.FAILED}

    if evaluated_count == 0:
        if is_terminal:
            return "skipped"
        if is_active and current_dimension_id == dimension_id:
            return "running"
        return "pending"

    if any(row.get("status") == "FAIL" for row in results):
        return "failed"

    if evaluated_count >= check_count:
        return "passed"

    if is_active and current_dimension_id == dimension_id:
        return "running"

    if is_terminal:
        return "skipped"

    return "pending"


def build_stage_progress_payload(
    *,
    check_results: list[CheckResult | dict[str, Any]],
    current_dimension_id: str | None,
    run_status: str,
    master: CheckMaster | None = None,
) -> dict[str, Any]:
    """Build metadata.stage_progress snapshot (PRD-FE-04 §3.1)."""
    master = _resolve_progress_master(master)
    grouped = group_checks_by_dimension(master)
    results_by_check_id = _results_by_check_id(check_results)
    stages: list[dict[str, Any]] = []

    for stage_def in _stage_catalog():
        dimension_id = stage_def["dimension_id"]
        check_ids = [row.check_id for row in grouped.get(dimension_id, [])]
        dim_results = [
            results_by_check_id[check_id]
            for check_id in check_ids
            if check_id in results_by_check_id
        ]
        fail_count, warn_count = _count_statuses(dim_results)
        stages.append(
            {
                **stage_def,
                "state": _stage_state_for_dimension(
                    dimension_id=dimension_id,
                    check_ids=check_ids,
                    results_by_check_id=results_by_check_id,
                    current_dimension_id=current_dimension_id,
                    run_status=run_status,
                ),
                "fail_count": fail_count,
                "warn_count": warn_count,
                "check_count": len(check_ids),
                "evaluated_count": len(dim_results),
            }
        )

    return {
        "updated_at": _utcnow_iso(),
        "current_dimension_id": current_dimension_id,
        "stages": stages,
    }


def persist_stage_progress(
    data_run: DataRun,
    *,
    check_results: list[CheckResult | dict[str, Any]],
    current_dimension_id: str | None,
    run_status: str | None = None,
) -> None:
    status_value = run_status or data_run.status
    snapshot = build_stage_progress_payload(
        check_results=check_results,
        current_dimension_id=current_dimension_id,
        run_status=status_value,
    )
    data_run.metadata = {
        **(data_run.metadata or {}),
        "stage_progress": snapshot,
    }
    data_run.save(update_fields=["metadata", "updated_at"])


def persist_import_stage_running(data_run: DataRun) -> None:
    """Option A: Foundation shows running during connector import (PRD-FE-04 §3.4)."""
    persist_stage_progress(
        data_run,
        check_results=[],
        current_dimension_id="00",
        run_status=DataRun.Status.RUNNING,
    )


def finalize_stage_progress_on_failure(
    data_run: DataRun,
    *,
    check_results: list[CheckResult | dict[str, Any]],
) -> None:
    persist_stage_progress(
        data_run,
        check_results=check_results,
        current_dimension_id=None,
        run_status=DataRun.Status.FAILED,
    )


def build_run_progress(
    data_run: DataRun | None,
    *,
    lock_reason: str | None = None,
) -> dict[str, Any] | None:
    """Build GET /dcs/status/ run_progress payload (PRD-FE-04 §3.3)."""
    if data_run is None:
        if lock_reason == "no_run":
            return None
        catalog = _stage_catalog()
        return {
            "data_run_id": None,
            "data_run_status": "pending",
            "current_dimension_id": None,
            "stages": [
                {
                    **stage_def,
                    "state": "pending",
                    "fail_count": 0,
                    "warn_count": 0,
                    "check_count": 0,
                    "evaluated_count": 0,
                }
                for stage_def in catalog
            ],
        }

    metadata = data_run.metadata or {}
    stage_progress = metadata.get("stage_progress")
    check_results = metadata.get("check_results")
    if not isinstance(check_results, list):
        check_results = []

    if isinstance(stage_progress, dict) and isinstance(stage_progress.get("stages"), list):
        stages = stage_progress["stages"]
        current_dimension_id = stage_progress.get("current_dimension_id")
    else:
        payload = build_stage_progress_payload(
            check_results=check_results,
            current_dimension_id=None,
            run_status=data_run.status,
        )
        stages = payload["stages"]
        current_dimension_id = payload["current_dimension_id"]

    return {
        "data_run_id": data_run.id,
        "data_run_status": data_run.status,
        "current_dimension_id": current_dimension_id,
        "stages": stages,
    }
