"""Load company-scoped DCS issue context for AI tasks."""

from __future__ import annotations

from typing import Any

from dataruns.ai.exceptions import AiNotFoundError
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.worklist import (
    INCLUDE_STATUSES,
    build_enriched_issue,
    extract_dcs_payload,
    get_latest_terminal_dcs_run,
    load_check_master_by_id,
    load_optional_check_ids,
    load_run_issues_by_check_id,
    should_include_check_result,
)
from dataruns.models import DataRun
from tenants.models import Company


def _normalize_check_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().upper()
    return token or None


def resolve_dcs_run_for_ai(
    *,
    company: Company,
    dcs_run_id: int | None = None,
) -> DataRun:
    if dcs_run_id is not None:
        run = (
            DataRun.objects.filter(
                id=dcs_run_id,
                tenant=company.tenant,
                name=DCS_SCORE_DATA_RUN_NAME,
                metadata__kind=DCS_SCORE_KIND,
                metadata__company_id=str(company.id),
                status__in=(
                    DataRun.Status.SUCCEEDED,
                    DataRun.Status.FAILED,
                ),
            )
            .order_by("-created_at")
            .first()
        )
        if run is None:
            raise AiNotFoundError("DCS run not found for this company.")
        return run

    run = get_latest_terminal_dcs_run(company=company)
    if run is None:
        raise AiNotFoundError("No scored DCS run available.")
    return run


def load_issue_for_ai(
    *,
    company: Company,
    check_id: str,
    dcs_run_id: int | None = None,
) -> tuple[DataRun, dict[str, Any]]:
    """
    Return (data_run, enriched issue dict) for a FAIL/WARN check.

    Raises AiNotFoundError when the check is not an open worklist issue.
    """
    check_id = (check_id or "").strip().upper()
    if not check_id:
        raise AiNotFoundError("check_id is required.")

    data_run = resolve_dcs_run_for_ai(company=company, dcs_run_id=dcs_run_id)
    optional_check_ids = load_optional_check_ids()
    check_master_by_id = load_check_master_by_id()
    metadata = data_run.metadata if isinstance(data_run.metadata, dict) else {}
    payload = extract_dcs_payload(metadata)
    check_results = [
        row for row in payload.get("check_results") or [] if isinstance(row, dict)
    ]
    results_by_id: dict[str, dict[str, Any]] = {}
    for row in check_results:
        row_check_id = _normalize_check_id(row.get("check_id"))
        if row_check_id:
            results_by_id[row_check_id] = row
    run_issues_raw = load_run_issues_by_check_id(payload.get("domain_run_id"))
    run_issues: dict[str, Any] = {}
    for key, issue in run_issues_raw.items():
        issue_check_id = _normalize_check_id(key)
        if issue_check_id is None and isinstance(issue.details, dict):
            issue_check_id = _normalize_check_id(issue.details.get("check_id"))
        if issue_check_id and issue_check_id not in run_issues:
            run_issues[issue_check_id] = issue

    result = results_by_id.get(check_id)
    run_issue = run_issues.get(check_id)

    status: str | None = None
    if isinstance(result, dict) and should_include_check_result(result):
        status = str(result.get("status") or "").upper()
    elif run_issue is not None:
        details = run_issue.details if isinstance(run_issue.details, dict) else {}
        candidate = str(details.get("status") or "").upper()
        if candidate in INCLUDE_STATUSES:
            status = candidate

    if status not in INCLUDE_STATUSES:
        raise AiNotFoundError("Worklist issue not found.")

    master = check_master_by_id.get(check_id)
    enriched = build_enriched_issue(
        check_id=check_id,
        status=status,
        result=result,
        run_issue=run_issue,
        master=master,
        optional_check_ids=optional_check_ids,
    )

    # Attach mismatch shapes for allowlist sanitizer (values dropped later).
    details = (
        run_issue.details
        if run_issue is not None and isinstance(run_issue.details, dict)
        else {}
    )
    mismatches = details.get("mismatches")
    if (not isinstance(mismatches, list) or len(mismatches) == 0) and isinstance(result, dict):
        provenance = result.get("provenance")
        if isinstance(provenance, dict) and isinstance(provenance.get("mismatches"), list):
            provenance_mismatches = provenance["mismatches"]
            if provenance_mismatches:
                mismatches = provenance_mismatches
    if isinstance(mismatches, list) and mismatches:
        enriched["mismatches"] = mismatches
    return data_run, enriched
