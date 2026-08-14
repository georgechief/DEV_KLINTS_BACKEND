"""Build company orchestration plan payload (PRD-ORCH-01 §7)."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.utils import timezone

from dataruns.orchestration.candidates import (
    build_fix_tasks_for_company,
    empty_candidate_hooks_af_uc,
)
from dataruns.orchestration.scoring import sort_tasks_by_priority
from tenants.models import Company


def _as_of_iso(value: datetime | None = None) -> str:
    as_of = value or timezone.now()
    if timezone.is_naive(as_of):
        as_of = timezone.make_aware(as_of, dt_timezone.utc)
    return as_of.isoformat().replace("+00:00", "Z")


def build_plan(*, company: Company) -> dict[str, Any]:
    """
    Compute-on-GET ranked plan for a company.

    A–F: DCS FIX tasks only. AF/UC hooks stay empty.
    """
    as_of = _as_of_iso()
    fix_tasks, data_run_id = build_fix_tasks_for_company(company=company)
    extra = empty_candidate_hooks_af_uc()
    # Always re-sort after merge so phase-G AF/UC tasks cannot break order.
    tasks = sort_tasks_by_priority(list(fix_tasks) + list(extra))

    if data_run_id is None:
        reason: str | None = "no_dcs"
    elif not tasks:
        reason = "no_open_issues"
    else:
        reason = None

    fix_count = sum(1 for t in tasks if t.get("task_type") == "FIX")
    max_score = None
    if tasks:
        max_score = max(float(t.get("priority_score") or 0.0) for t in tasks)

    return {
        "as_of": as_of,
        "reason": reason,
        "sources": {
            "dcs_data_run_id": data_run_id,
            "af_assessment_id": None,
            "uc_as_of": None,
        },
        "summary": {
            "task_count": len(tasks),
            "fix_count": fix_count,
            "max_priority_score": max_score,
        },
        "tasks": tasks,
    }
