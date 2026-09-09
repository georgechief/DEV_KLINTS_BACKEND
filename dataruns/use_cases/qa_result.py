"""QA result schema helpers (PRD-QA-01 / pack qa_result.schema.json)."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from typing import Any
from uuid import UUID

from django.utils import timezone

from dataruns.use_cases.models import WorkflowQaResult

QA_RESULT_SCHEMA_VERSION = "1.0.0"
QA_STATUS_PASS = WorkflowQaResult.Status.PASS
QA_STATUS_FAIL = WorkflowQaResult.Status.FAIL


def _iso_utc(value: datetime | None = None) -> str:
    dt = value or timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt.isoformat()


def build_qa_result_payload(
    *,
    qa_run_id: str | UUID,
    company_id: str | UUID,
    package_id: str | UUID,
    use_case_id: str,
    score: float,
    status: str,
    hard_tests: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    minimum_score: float | int,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """
    Build a pack-schema-shaped QA result body (PRD-QA-01 §7.3).

    Required schema fields: schema_version, qa_run_id, tenant_id, object_id,
    score, hard_tests, status, evidence, created_at.

    FE siblings (documented): package_id, use_case_id, minimum_score.
    """
    normalized_status = str(status).strip().upper()
    if normalized_status not in {QA_STATUS_PASS, QA_STATUS_FAIL}:
        raise ValueError(f"Invalid QA status: {status}")

    package_id_str = str(package_id)
    return {
        "schema_version": QA_RESULT_SCHEMA_VERSION,
        "qa_run_id": str(qa_run_id),
        "tenant_id": str(company_id),
        "object_id": package_id_str,
        "package_id": package_id_str,
        "use_case_id": str(use_case_id).strip().upper(),
        "score": float(score),
        "minimum_score": float(minimum_score),
        "hard_tests": list(hard_tests),
        "status": normalized_status,
        "evidence": list(evidence),
        "created_at": _iso_utc(created_at),
    }


def serialize_qa_result(record: WorkflowQaResult) -> dict[str, Any]:
    """
    API response for a persisted QA run.

    Prefer stored payload (full schema body); fill required siblings from columns
    so GET stays honest if payload was written thinly.
    """
    payload = dict(record.payload) if isinstance(record.payload, dict) else {}
    package_id = str(record.package_id)
    company_id = str(record.company_id)

    hard_tests = payload.get("hard_tests")
    if not isinstance(hard_tests, list):
        hard_tests = []

    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        evidence = []

    minimum_score = payload.get("minimum_score", 80)
    try:
        minimum_score_f = float(minimum_score)
    except (TypeError, ValueError):
        minimum_score_f = 80.0

    return build_qa_result_payload(
        qa_run_id=record.id,
        company_id=company_id,
        package_id=package_id,
        use_case_id=record.use_case_id or payload.get("use_case_id") or "",
        score=record.score if record.score is not None else payload.get("score", 0),
        status=record.status or payload.get("status") or QA_STATUS_FAIL,
        hard_tests=hard_tests,
        evidence=evidence,
        minimum_score=minimum_score_f,
        created_at=record.created_at,
    )


def latest_qa_result_for_package(
    *,
    company_id: str | UUID,
    package_id: str | UUID,
) -> WorkflowQaResult | None:
    """Latest appended QA run for a company-scoped package (PRD-QA-01 §7.1)."""
    return (
        WorkflowQaResult.objects.filter(
            company_id=company_id,
            package_id=package_id,
        )
        .order_by("-created_at", "-id")
        .first()
    )
