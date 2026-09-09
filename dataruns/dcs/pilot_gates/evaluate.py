"""DCS-09 Step 5 — evaluate orchestration (resolve → run → persist).

Does **not** touch headline assemble / 42 worklist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dataruns.dcs.pilot_gates.context import build_supplemental_gate_context
from dataruns.dcs.pilot_gates.contract import (
    STATUS_NOT_EVALUATED,
    supplemental_status_is_ready,
)
from dataruns.dcs.pilot_gates.executors import (
    check_result_to_store_row,
    run_supplemental_checks,
)
from dataruns.dcs.pilot_gates.master import (
    get_supplemental_checks_for_use_case,
    resolve_check_ids_for_evaluate,
)
from dataruns.dcs.pilot_gates.store import (
    PilotGateEvalBundle,
    get_latest_pilot_gate_eval,
    get_latest_supplemental_status_map,
    save_pilot_gate_eval,
)
from dataruns.dcs.types import CheckResult
from tenants.models import Company


class PilotGateEvaluateError(ValueError):
    """Invalid evaluate request."""


@dataclass(frozen=True)
class PilotGateEvaluateResult:
    """Outcome of one on-demand supplemental evaluate pass."""

    company_id: str
    check_ids: tuple[str, ...]
    results: tuple[dict[str, Any], ...]
    status_by_check_id: dict[str, str]
    data_run_id_score: int | None
    erp_in_scope: bool
    bundle: PilotGateEvalBundle | None
    readiness: tuple[dict[str, Any], ...] = ()
    skipped: bool = False
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "check_ids": list(self.check_ids),
            "results": [dict(r) for r in self.results],
            "status_by_check_id": dict(self.status_by_check_id),
            "data_run_id_score": self.data_run_id_score,
            "erp_in_scope": self.erp_in_scope,
            "bundle": self.bundle.to_dict() if self.bundle is not None else None,
            "readiness": [dict(r) for r in self.readiness],
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            # This-pass result count (merged map may be larger after partial eval).
            "count": len(self.results),
            "merged_count": (
                len(self.bundle.results) if self.bundle is not None else len(self.results)
            ),
        }


def supplemental_readiness_for_use_case(
    *,
    use_case_id: str,
    status_by_check_id: dict[str, str] | None = None,
    company: Company | None = None,
) -> dict[str, Any]:
    """
    PRD §7 readiness row for one pilot.

    ``supplemental_ready`` is True only when every required supplemental gate
    has a stored **PASS**. Missing → not_evaluated; non-PASS → blocked_by.
    Pilots with zero supplemental gates are ready on the supplemental side.

    Pass ``status_by_check_id=None`` to load latest from store when ``company``
    is set. An explicit empty dict means “no statuses” (do not fall through).
    """
    uc = str(use_case_id or "").strip().upper()
    required = list(get_supplemental_checks_for_use_case(uc))
    if status_by_check_id is None:
        status_map = (
            get_latest_supplemental_status_map(company=company)
            if company is not None
            else {}
        )
    else:
        status_map = dict(status_by_check_id)

    blocked_by: list[dict[str, str]] = []
    not_evaluated: list[str] = []
    for check_id in required:
        status = status_map.get(check_id)
        if (
            status is None
            or str(status).strip() == ""
            or str(status).strip().lower() == STATUS_NOT_EVALUATED
        ):
            not_evaluated.append(check_id)
            continue
        if not supplemental_status_is_ready(status):
            blocked_by.append(
                {"check_id": check_id, "status": str(status).strip().upper()}
            )

    supplemental_ready = (not required) or (not blocked_by and not not_evaluated)
    return {
        "use_case_id": uc,
        "required_check_ids": required,
        "supplemental_ready": supplemental_ready,
        "blocked_by": blocked_by,
        "not_evaluated": not_evaluated,
    }


def build_readiness_rows(
    *,
    use_case_ids: list[str] | None,
    status_by_check_id: dict[str, str],
    company: Company | None = None,
) -> list[dict[str, Any]]:
    """Build readiness[] for evaluate / API responses."""
    if not use_case_ids:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in use_case_ids:
        uc = str(raw or "").strip().upper()
        if not uc or uc in seen:
            continue
        seen.add(uc)
        rows.append(
            supplemental_readiness_for_use_case(
                use_case_id=uc,
                status_by_check_id=status_by_check_id,
                company=company,
            )
        )
    return rows


def evaluate_pilot_gates(
    *,
    company: Company,
    use_case_ids: list[str] | None = None,
    check_ids: list[str] | None = None,
    data_run_id: int | None = None,
    erp_in_scope: bool = False,
    scoring_snapshot: dict[str, Any] | None = None,
    merge_with_previous: bool = True,
    triggered_by: str = "manual",
    actor_user_id: str | None = None,
    readiness_use_case_ids: list[str] | None = None,
) -> PilotGateEvaluateResult:
    """
    Resolve check set → run supplemental executors → persist (merge by default).

    Resolution matches ``resolve_check_ids_for_evaluate`` / PRD §7:
    - ``check_ids is not None`` → exact subset (empty → skip persist)
    - else ``use_case_ids is not None`` → union for those UCs
    - both ``None`` → all 12

    Never writes into ``assemble_dcs_score`` or the headline DCS score DataRun.

    Raises ``PilotGateEvaluateError`` when an explicit ``data_run_id`` does not
    resolve to a succeeded DCS score for ``company``.
    """
    if company is None:
        raise PilotGateEvaluateError("company is required")

    resolved = resolve_check_ids_for_evaluate(
        use_case_ids=use_case_ids,
        check_ids=check_ids,
    )
    readiness_ucs = readiness_use_case_ids
    if readiness_ucs is None and use_case_ids is not None:
        readiness_ucs = list(use_case_ids)

    ctx = build_supplemental_gate_context(
        company=company,
        erp_in_scope=bool(erp_in_scope),
        data_run_id=data_run_id,
        scoring_snapshot=scoring_snapshot,
    )
    # Explicit score-run id must resolve; silent empty snapshot is a footgun.
    if data_run_id is not None and ctx.data_run_id_score is None:
        raise PilotGateEvaluateError(
            f"data_run_id={data_run_id!r} is not a succeeded DCS score "
            f"DataRun for company {company.id}"
        )

    if not resolved:
        # Empty explicit subset — do not invent results or wipe store.
        status_map = get_latest_supplemental_status_map(company=company)
        readiness = build_readiness_rows(
            use_case_ids=readiness_ucs,
            status_by_check_id=status_map,
            company=company,
        )
        return PilotGateEvaluateResult(
            company_id=str(company.id),
            check_ids=(),
            results=(),
            status_by_check_id=status_map,
            data_run_id_score=ctx.data_run_id_score,
            erp_in_scope=bool(erp_in_scope),
            bundle=get_latest_pilot_gate_eval(company=company),
            readiness=tuple(readiness),
            skipped=True,
            skip_reason="empty_check_set",
        )

    check_results: list[CheckResult] = run_supplemental_checks(
        resolved,
        context=ctx,
    )
    rows = [check_result_to_store_row(r) for r in check_results]
    bundle = save_pilot_gate_eval(
        company=company,
        results=rows,
        data_run_id_score=ctx.data_run_id_score,
        erp_in_scope=bool(erp_in_scope),
        merge_with_previous=merge_with_previous,
        triggered_by=triggered_by,
        actor_user_id=actor_user_id,
    )
    # Return store-normalized rows for this pass (not pre-normalize executor rows).
    resolved_set = set(resolved)
    this_pass_results = tuple(
        dict(r) for r in bundle.results if r.get("check_id") in resolved_set
    )
    readiness = build_readiness_rows(
        use_case_ids=readiness_ucs,
        status_by_check_id=bundle.status_by_check_id,
        company=company,
    )
    return PilotGateEvaluateResult(
        company_id=str(company.id),
        check_ids=tuple(resolved),
        results=this_pass_results,
        status_by_check_id=dict(bundle.status_by_check_id),
        data_run_id_score=bundle.data_run_id_score,
        erp_in_scope=bundle.erp_in_scope,
        bundle=bundle,
        readiness=tuple(readiness),
        skipped=False,
        skip_reason=None,
    )


__all__ = [
    "PilotGateEvaluateError",
    "PilotGateEvaluateResult",
    "build_readiness_rows",
    "evaluate_pilot_gates",
    "supplemental_readiness_for_use_case",
]
