"""Build FIX orchestration task candidates from DCS worklist (PRD-ORCH-01)."""

from __future__ import annotations

import logging
import math
from typing import Any

from dataruns.dcs.worklist import (
    build_enriched_issues,
    get_latest_terminal_dcs_run,
    load_check_master_by_id,
)
from dataruns.models import CheckMaster, DataRun
from dataruns.orchestration.factors_dcs import (
    map_dcs_issue_to_priority_inputs,
    top_quartile_revenue_threshold,
    worklist_has_open_foundation_fail,
)
from dataruns.orchestration.scoring import (
    build_priority_explain,
    compute_priority_score,
    priority_class_from_score,
    sort_tasks_by_priority,
)
from tenants.models import Company

logger = logging.getLogger(__name__)


def _normalize_check_id(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def load_mvp1_gating_check_ids() -> frozenset[str]:
    """Union of gating_check_ids from seeded UC blueprints. Empty if unavailable."""
    try:
        from dataruns.use_cases.models import UseCaseBlueprint
        from dataruns.use_cases.recommend import _gates_from_blueprint
    except Exception:  # pragma: no cover - import guard
        logger.warning("orch candidates: UC modules unavailable; gating set empty")
        return frozenset()

    try:
        ids: set[str] = set()
        for body in UseCaseBlueprint.objects.values_list("body", flat=True):
            gates = _gates_from_blueprint(body if isinstance(body, dict) else None)
            for check_id in gates.get("gating_check_ids") or []:
                token = _normalize_check_id(check_id)
                if token:
                    # Uppercase so LE-09 and le-09 match issue check_ids.
                    ids.add(token.upper())
        return frozenset(ids)
    except Exception:
        logger.exception("orch candidates: failed loading gating_check_ids")
        return frozenset()


def _issue_check_id(issue: dict[str, Any]) -> str | None:
    return _normalize_check_id(issue.get("check_id"))


def _finite_revenue(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        revenue = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(revenue):
        return 0.0
    return revenue


def build_fix_task_dict(
    *,
    issue: dict[str, Any],
    company_id: str | int,
    data_run_id: int | None,
    priority_inputs: dict[str, int],
    priority_score: float,
    priority_class: str,
    priority_explain: list[dict[str, Any]],
) -> dict[str, Any]:
    check_id = _issue_check_id(issue)
    if not check_id:
        raise ValueError("FIX task requires a non-empty check_id")
    task_id = f"FIX-{check_id}"
    fingerprint = f"dcs:{data_run_id}" if data_run_id is not None else "dcs:none"
    revenue_f = _finite_revenue(issue.get("revenue_impact"))
    currency = issue.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        currency = None

    return {
        "task_id": task_id,
        "task_type": "FIX",
        "status": "READY",
        "title": str(issue.get("title") or check_id),
        "check_id": check_id,
        "priority_class": priority_class,
        "priority_inputs": dict(priority_inputs),
        "priority_score": priority_score,
        "priority_explain": priority_explain,
        "depends_on": [],
        "wave": None,
        "href": f"/fix?issue={check_id}",
        "revenue_impact": revenue_f,
        "currency": currency,
        "idempotency_key": f"{company_id}:{task_id}:{fingerprint}",
    }


def build_fix_tasks_from_issues(
    issues: list[dict[str, Any]],
    *,
    company_id: str | int,
    data_run_id: int | None = None,
    gating_check_ids: frozenset[str] | None = None,
    master_by_id: dict[str, CheckMaster] | None = None,
) -> list[dict[str, Any]]:
    """
    Map enriched FAIL/WARN issues → ranked FIX tasks.

    Skips null/empty check_id. Dedupes by check_id (first wins).
    """
    if gating_check_ids is None:
        gates: frozenset[str] = frozenset()
    else:
        # Normalize for case-insensitive match against issue check_ids.
        gates = frozenset(
            token.upper()
            for token in (_normalize_check_id(c) for c in gating_check_ids)
            if token
        )
    has_foundation_fail = worklist_has_open_foundation_fail(
        issues, master_by_id=master_by_id
    )
    revenues = []
    for issue in issues:
        value = _finite_revenue(issue.get("revenue_impact"))
        if value > 0:
            revenues.append(value)
    quartile = top_quartile_revenue_threshold(revenues)

    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in issues:
        check_id = _issue_check_id(issue)
        if not check_id:
            continue
        if check_id in seen:
            continue
        seen.add(check_id)

        inputs, reasons = map_dcs_issue_to_priority_inputs(
            issue,
            has_open_foundation_fail=has_foundation_fail,
            gating_check_ids=gates,
            master_by_id=master_by_id,
            top_quartile_threshold=quartile,
        )
        score = compute_priority_score(inputs)
        klass = priority_class_from_score(score)
        explain = build_priority_explain(inputs, reasons=reasons)
        tasks.append(
            build_fix_task_dict(
                issue=issue,
                company_id=company_id,
                data_run_id=data_run_id,
                priority_inputs=dict(inputs),
                priority_score=score,
                priority_class=klass,
                priority_explain=list(explain),
            )
        )

    return sort_tasks_by_priority(tasks)


def build_fix_tasks_for_company(
    *,
    company: Company,
    gating_check_ids: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """
    Load latest terminal DCS run → enriched issues → FIX tasks.

    Returns (tasks, data_run_id). data_run_id is None when no run.
    """
    data_run = get_latest_terminal_dcs_run(company=company)
    if data_run is None:
        return [], None

    master_by_id = load_check_master_by_id()
    issues = build_enriched_issues(
        data_run=data_run,
        check_master_by_id=master_by_id,
        cap=None,
    )
    gates = (
        gating_check_ids
        if gating_check_ids is not None
        else load_mvp1_gating_check_ids()
    )
    tasks = build_fix_tasks_from_issues(
        issues,
        company_id=company.id,
        data_run_id=data_run.id,
        gating_check_ids=gates,
        master_by_id=master_by_id,
    )
    return tasks, data_run.id


def build_fix_tasks_for_data_run(
    *,
    company: Company,
    data_run: DataRun,
    gating_check_ids: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Build FIX tasks from a specific terminal DCS run (PRD-RPT-01 plan section)."""
    master_by_id = load_check_master_by_id()
    issues = build_enriched_issues(
        data_run=data_run,
        check_master_by_id=master_by_id,
        cap=None,
    )
    gates = (
        gating_check_ids
        if gating_check_ids is not None
        else load_mvp1_gating_check_ids()
    )
    return build_fix_tasks_from_issues(
        issues,
        company_id=company.id,
        data_run_id=data_run.id,
        gating_check_ids=gates,
        master_by_id=master_by_id,
    )


def empty_candidate_hooks_af_uc() -> list[dict[str, Any]]:
    """Phase G stubs — AF ASSESS / UC PLAN not emitted in A–F."""
    return []
