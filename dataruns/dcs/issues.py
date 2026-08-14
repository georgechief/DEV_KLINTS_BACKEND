"""Persist RunIssue + RunIssueImpact rows for every DCS check result."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils import timezone

from dataruns.dcs.catalogue import foundation_gate_meta
from dataruns.dcs.types import CheckResult, Evidence
from dataruns.models import Run, RunIssue, RunIssueImpact

_SEVERITY_RISK: dict[str, Decimal] = {
    "Critical": Decimal("1.0"),
    "High": Decimal("0.75"),
    "Medium": Decimal("0.5"),
    "Low": Decimal("0.25"),
    "Informational": Decimal("0.1"),
}

_STATUS_SEVERITY_FALLBACK: dict[str, str] = {
    "FAIL": "High",
    "WARN": "Medium",
    "PASS": "Informational",
    "UNKNOWN": "Informational",
    "NOT_CONNECTED": "Informational",
    "NOT_APPLICABLE": "Informational",
}


def _resolve_severity(result: CheckResult) -> str:
    if result.severity:
        return str(result.severity)
    meta = foundation_gate_meta(result.check_id)
    if meta.get("severity"):
        return str(meta["severity"])
    return _STATUS_SEVERITY_FALLBACK.get(result.status, "Informational")


def _evidence_to_dict(item: Evidence | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, Evidence):
        return item.to_dict()
    if isinstance(item, dict):
        return dict(item)
    return {"value": str(item)}


def _partition_matches_mismatches(
    result: CheckResult,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Map check evidence into matches vs mismatches.

    FAIL/WARN evidence → mismatches; PASS evidence → matches.
    Explicit provenance keys (matches/mismatches) win when present.
    """
    provenance = result.provenance if isinstance(result.provenance, dict) else {}
    if "matches" in provenance or "mismatches" in provenance:
        matches = [
            item if isinstance(item, dict) else {"value": item}
            for item in (provenance.get("matches") or [])
        ]
        mismatches = [
            item if isinstance(item, dict) else {"value": item}
            for item in (provenance.get("mismatches") or [])
        ]
        return matches, mismatches

    evidence_rows = [_evidence_to_dict(e) for e in (result.evidence or [])]
    if result.status == "PASS":
        return evidence_rows, []
    if result.status in {"FAIL", "WARN"}:
        return [], evidence_rows
    return [], []


def _revenue_from_evidence(result: CheckResult) -> Decimal:
    provenance = result.provenance if isinstance(result.provenance, dict) else {}
    raw = provenance.get("revenue_impact")
    if raw is not None:
        try:
            return Decimal(str(raw))
        except Exception:  # noqa: BLE001
            pass
    for item in result.evidence or []:
        value = item.value if isinstance(item, Evidence) else None
        if isinstance(value, dict) and value.get("revenue_impact") is not None:
            try:
                return Decimal(str(value["revenue_impact"]))
            except Exception:  # noqa: BLE001
                continue
    return Decimal("0")


def _risk_score(*, status: str, severity: str) -> Decimal:
    if status == "PASS":
        return Decimal("0")
    return _SEVERITY_RISK.get(severity, Decimal("0.1"))


def build_issue_details(result: CheckResult) -> dict[str, Any]:
    matches, mismatches = _partition_matches_mismatches(result)
    return {
        "check_id": result.check_id,
        "status": result.status,
        "reason_code": result.reason_code,
        "message": result.message,
        "root_cause_ids": list(result.root_cause_ids or []),
        "evidence": [_evidence_to_dict(e) for e in (result.evidence or [])],
        "matches": matches,
        "mismatches": mismatches,
        "suggested_fix": result.suggested_fix,
        "fix_type": result.fix_type,
        "fix_owner": result.fix_owner,
        "fix_in_klints": result.fix_in_klints,
    }


def persist_dcs_issues(
    *,
    company,
    domain_run: Run,
    check_results: list[CheckResult],
) -> list[RunIssue]:
    """
    Write one RunIssue + one RunIssueImpact per evaluated check.

    Skips stubs that were never implemented
    (``UNKNOWN`` + ``EXECUTOR_NOT_IMPLEMENTED``). ``QaCheck`` still stores
    the full 42-check set for audit; RunIssue is findings/evaluated only.
    """
    now = timezone.now()
    issues: list[RunIssue] = []
    impacts: list[RunIssueImpact] = []
    persisted_results: list[CheckResult] = []

    for result in check_results:
        if (
            result.status == "UNKNOWN"
            and result.reason_code == "EXECUTOR_NOT_IMPLEMENTED"
        ):
            continue
        persisted_results.append(result)
        severity = _resolve_severity(result)
        issue = RunIssue(
            run=domain_run,
            entity_type="dcs_check",
            entity_id=company.id,
            issue_type=result.check_id,
            severity=severity,
            detected_at=now,
            details=build_issue_details(result),
        )
        issues.append(issue)

    if not issues:
        return []

    created = RunIssue.objects.bulk_create(issues)
    for issue, result in zip(created, persisted_results, strict=True):
        impacts.append(
            RunIssueImpact(
                run_issue=issue,
                revenue_impact=_revenue_from_evidence(result),
                risk_score=_risk_score(
                    status=result.status,
                    severity=issue.severity,
                ),
            )
        )
    RunIssueImpact.objects.bulk_create(impacts)
    return created
