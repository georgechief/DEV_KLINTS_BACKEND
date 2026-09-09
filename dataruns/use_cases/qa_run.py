"""QA run orchestrator — evaluate, score §6, persist, audit (PRD-QA-01 Step 4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from dataruns.audit import append_audit_event
from dataruns.models import AuditLog
from dataruns.use_cases.handoff_stage import (
    HandoffStageError,
    create_or_get_staged_handoff,
)
from dataruns.use_cases.models import WorkflowBuildPackage, WorkflowQaResult
from dataruns.use_cases.qa_evaluators import (
    STATUS_PASS,
    HardTestResult,
    collect_evidence_for_payload,
    evaluate_hard_tests,
    strip_evidence_ids_for_schema,
)
from dataruns.use_cases.qa_result import (
    QA_STATUS_FAIL,
    QA_STATUS_PASS,
    build_qa_result_payload,
    serialize_qa_result,
)
from tenants.models import User

DEFAULT_MINIMUM_SCORE = 80.0
AUDIT_ACTION_QA_RUN_COMPLETED = "workflow.qa_run_completed"


class QaRunError(Exception):
    """Package cannot be QA-evaluated (maps to HTTP status in Step 5)."""

    def __init__(
        self,
        *,
        code: str,
        detail: str,
        status: int = 409,
    ) -> None:
        self.code = code
        self.detail = detail
        self.status = status
        super().__init__(detail)


@dataclass
class QaRunOutcome:
    record: WorkflowQaResult
    payload: dict[str, Any]


def resolve_qa_requirements(
    package_payload: dict[str, Any],
) -> tuple[list[str] | None, float]:
    """
    Read qa_requirements from package payload.

    Raises QaRunError(409) when the block is missing (PRD-QA-01 §7.2).
    Returns:
      - hard_test_ids list (may be empty → §6 score 0 / FAIL)
      - None only when hard_tests key is absent (evaluator uses pack default 7)
      - minimum_score
    """
    qa_req = package_payload.get("qa_requirements")
    if not isinstance(qa_req, dict):
        raise QaRunError(
            code="qa_requirements_missing",
            detail="Package payload missing qa_requirements.",
            status=409,
        )

    hard_tests: list[str] | None
    if "hard_tests" not in qa_req:
        hard_tests = None
    else:
        raw_tests = qa_req.get("hard_tests")
        if not isinstance(raw_tests, list):
            raise QaRunError(
                code="qa_requirements_invalid",
                detail="qa_requirements.hard_tests must be a list.",
                status=409,
            )
        # Explicit [] stays [] — do not substitute pack defaults (PRD §6).
        hard_tests = [str(t).strip() for t in raw_tests if str(t).strip()]

    minimum_score = qa_req.get("minimum_score", DEFAULT_MINIMUM_SCORE)
    try:
        minimum_score_f = float(minimum_score)
    except (TypeError, ValueError):
        minimum_score_f = DEFAULT_MINIMUM_SCORE

    return hard_tests, minimum_score_f


def compute_qa_score(
    results: list[HardTestResult],
    *,
    minimum_score: float,
) -> tuple[float, str, list[str]]:
    """
    Score and overall status per PRD-QA-01 §6.

    score = round(100 * hard_pass_count / hard_total); 0 if hard_total == 0.
    Any hard FAIL forces overall FAIL even when numeric score ≥ minimum.
    """
    hard_total = len(results)
    if hard_total == 0:
        return 0.0, QA_STATUS_FAIL, []

    hard_pass_count = sum(1 for r in results if r.status == STATUS_PASS)
    score = float(round(100 * hard_pass_count / hard_total))
    hard_fail_ids = [r.test_id for r in results if r.status != STATUS_PASS]

    if hard_fail_ids:
        status = QA_STATUS_FAIL
    elif score >= float(minimum_score):
        status = QA_STATUS_PASS
    else:
        status = QA_STATUS_FAIL

    return score, status, hard_fail_ids


def _blueprint_body_for_package(
    package: WorkflowBuildPackage,
) -> dict[str, Any] | None:
    pilot = getattr(package, "pilot", None)
    if pilot is None:
        return None
    blueprint = getattr(pilot, "blueprint", None)
    if blueprint is None:
        return None
    body = getattr(blueprint, "body", None)
    return body if isinstance(body, dict) else None


@transaction.atomic
def run_qa_for_package(
    *,
    package: WorkflowBuildPackage,
    created_by: User | None = None,
) -> QaRunOutcome:
    """
    Evaluate hard tests, score, append WorkflowQaResult, audit completion.

    Append-history lock (PRD §7.1): always creates a new row; never overwrites.
    """
    raw_payload = package.payload if isinstance(package.payload, dict) else {}
    hard_test_ids, minimum_score = resolve_qa_requirements(raw_payload)

    now = timezone.now()
    results = evaluate_hard_tests(
        raw_payload,
        hard_test_ids=hard_test_ids,
        blueprint_body=_blueprint_body_for_package(package),
        now=now,
    )
    score, status, hard_fail_ids = compute_qa_score(
        results,
        minimum_score=minimum_score,
    )
    hard_rows, evidence_with_ids = collect_evidence_for_payload(results)
    evidence = strip_evidence_ids_for_schema(evidence_with_ids)

    qa_run_id = uuid.uuid4()
    use_case_id = str(package.use_case_id).strip().upper()

    # Create first so auto_now_add sets created_at; then stamp payload with
    # that same timestamp (passing created_at= into create is ignored).
    record = WorkflowQaResult.objects.create(
        id=qa_run_id,
        company_id=package.company_id,
        package=package,
        use_case_id=use_case_id,
        score=score,
        status=status,
        payload={},
        created_by=created_by,
    )
    schema_payload = build_qa_result_payload(
        qa_run_id=record.id,
        company_id=package.company_id,
        package_id=package.id,
        use_case_id=use_case_id,
        score=score,
        status=status,
        hard_tests=hard_rows,
        evidence=evidence,
        minimum_score=minimum_score,
        created_at=record.created_at,
    )
    record.payload = schema_payload
    record.save(update_fields=["payload"])

    append_audit_event(
        company=package.company,
        action=AUDIT_ACTION_QA_RUN_COMPLETED,
        summary=f"QA run {status} for {use_case_id} (score {score:g})",
        performed_by=created_by.email if created_by else "system",
        tone=(
            AuditLog.Tone.REVENUE
            if status == QA_STATUS_PASS
            else AuditLog.Tone.RISK
        ),
        actor_user_id=str(created_by.id) if created_by else None,
        metadata={
            "package_id": str(package.id),
            "qa_run_id": str(qa_run_id),
            "use_case_id": use_case_id,
            "score": score,
            "status": status,
            "minimum_score": minimum_score,
            "hard_fail_ids": hard_fail_ids,
        },
    )

    # PRD-HO-01 §4.1 — auto-stage handoff when QA PASS (same transaction).
    # Map staging failures to QaRunError so the QA HTTP API returns 409, not 500.
    if status == QA_STATUS_PASS:
        try:
            create_or_get_staged_handoff(
                package=package,
                qa_result=record,
                created_by=created_by,
            )
        except HandoffStageError as exc:
            raise QaRunError(
                code=exc.code,
                detail=exc.detail,
                status=exc.status,
            ) from exc

    return QaRunOutcome(
        record=record,
        payload=serialize_qa_result(record),
    )
