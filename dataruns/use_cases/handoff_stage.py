"""Staged handoff create / idempotent get (PRD-HO-01 Step 3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction

from dataruns.audit import append_audit_event
from dataruns.models import AuditLog
from dataruns.use_cases.handoff_package import (
    AUDIT_ACTION_HANDOFF_STAGED,
    HANDOFF_STATUS_STAGED,
    build_artifact_refs,
    build_handoff_package_payload,
    build_handoff_staged_audit_metadata,
    compute_manifest_hash,
    resolve_approval_ref,
)
from dataruns.use_cases.models import HandoffPackage, WorkflowBuildPackage, WorkflowQaResult
from dataruns.use_cases.qa_result import QA_STATUS_PASS, latest_qa_result_for_package
from tenants.models import User


class HandoffStageError(Exception):
    """Handoff cannot be staged (maps to HTTP status in Step 4)."""

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
class HandoffStageOutcome:
    record: HandoffPackage
    created: bool
    payload: dict[str, Any]


def _package_payload(package: WorkflowBuildPackage) -> dict[str, Any]:
    raw = package.payload
    return raw if isinstance(raw, dict) else {}


def _existing_handoff(
    *,
    company_id,
    package_id,
    qa_result_id,
) -> HandoffPackage | None:
    return HandoffPackage.objects.filter(
        company_id=company_id,
        package_id=package_id,
        qa_result_id=qa_result_id,
    ).first()


def _outcome_from_existing(existing: HandoffPackage) -> HandoffStageOutcome:
    # Prefer a relation-warmed row so callers (serialize) get title/route/qa_*.
    record = (
        HandoffPackage.objects.select_related(
            "package",
            "package__pilot",
            "qa_result",
            "company",
        )
        .filter(pk=existing.pk)
        .first()
        or existing
    )
    payload = dict(record.payload) if isinstance(record.payload, dict) else {}
    return HandoffStageOutcome(
        record=record,
        created=False,
        payload=payload,
    )


def _validate_stage_inputs(
    *,
    package: WorkflowBuildPackage,
    qa_result: WorkflowQaResult | None,
) -> None:
    if qa_result is None:
        raise HandoffStageError(
            code="qa_missing",
            detail="QA has not been run for this package.",
            status=409,
        )

    if str(qa_result.package_id) != str(package.id):
        raise HandoffStageError(
            code="qa_package_mismatch",
            detail="QA run does not belong to this build package.",
            status=409,
        )

    if str(qa_result.company_id) != str(package.company_id):
        raise HandoffStageError(
            code="qa_company_mismatch",
            detail="QA run company does not match build package company.",
            status=409,
        )

    if str(qa_result.status).strip().upper() != QA_STATUS_PASS:
        raise HandoffStageError(
            code="qa_not_pass",
            detail="Clear QA (≥80, all hard tests) before staging handoff.",
            status=409,
        )


@transaction.atomic
def create_or_get_staged_handoff(
    *,
    package: WorkflowBuildPackage,
    qa_result: WorkflowQaResult,
    created_by: User | None = None,
) -> HandoffStageOutcome:
    """
    Persist STAGED handoff for a QA PASS run (PRD-HO-01 §4).

    Idempotent on (company, package, qa_result): returns existing without
    re-auditing when already staged. Safe under concurrent create (unique).
    """
    _validate_stage_inputs(package=package, qa_result=qa_result)

    existing = _existing_handoff(
        company_id=package.company_id,
        package_id=package.id,
        qa_result_id=qa_result.id,
    )
    if existing is not None:
        return _outcome_from_existing(existing)

    use_case_id = (
        str(qa_result.use_case_id or package.use_case_id or "").strip().upper()
    )
    if not use_case_id:
        raise HandoffStageError(
            code="use_case_missing",
            detail="Cannot stage handoff without use_case_id.",
            status=409,
        )

    package_body = _package_payload(package)
    manifest_hash = compute_manifest_hash(package_body)
    package_version = (
        str(package.package_content_hash or "").strip() or manifest_hash
    )
    package_version_short = (
        package_version[:12] if len(package_version) > 12 else package_version
    )

    route = str(package_body.get("route") or "").strip()
    approval_ref = resolve_approval_ref(package_route=route)
    created_by_label = (
        created_by.email
        if created_by is not None and getattr(created_by, "email", None)
        else "system"
    )

    handoff_id = uuid.uuid4()
    try:
        # Nested atomic: IntegrityError from unique constraint rolls back only
        # this savepoint so we can return the winner row.
        with transaction.atomic():
            record = HandoffPackage.objects.create(
                id=handoff_id,
                company_id=package.company_id,
                package=package,
                qa_result=qa_result,
                use_case_id=use_case_id,
                status=HandoffPackage.Status.STAGED,
                payload={},
                manifest_hash=manifest_hash,
                created_by=created_by,
            )
            schema_payload = build_handoff_package_payload(
                handoff_id=record.id,
                tenant_id=package.company_id,
                package_version=package_version_short,
                artifact_refs=build_artifact_refs(package_id=package.id),
                qa_ref=qa_result.id,
                approval_ref=approval_ref,
                manifest_hash=manifest_hash,
                status=HANDOFF_STATUS_STAGED,
                created_at=record.created_at,
                created_by=created_by_label,
                source_versions={
                    "blueprint": str(package.blueprint_content_hash or ""),
                    "package": str(package.package_content_hash or ""),
                },
            )
            record.payload = schema_payload
            record.save(update_fields=["payload"])

            append_audit_event(
                company=package.company,
                action=AUDIT_ACTION_HANDOFF_STAGED,
                summary=f"Handoff staged for {use_case_id} (STAGED)",
                performed_by=created_by_label,
                tone=AuditLog.Tone.REVENUE,
                actor_user_id=str(created_by.id) if created_by else None,
                metadata=build_handoff_staged_audit_metadata(
                    handoff_id=record.id,
                    package_id=package.id,
                    qa_run_id=qa_result.id,
                    use_case_id=use_case_id,
                ),
            )
    except IntegrityError:
        raced = _existing_handoff(
            company_id=package.company_id,
            package_id=package.id,
            qa_result_id=qa_result.id,
        )
        if raced is None:
            raise
        return _outcome_from_existing(raced)

    record = (
        HandoffPackage.objects.select_related(
            "package",
            "package__pilot",
            "qa_result",
            "company",
        )
        .filter(pk=record.pk)
        .first()
        or record
    )
    return HandoffStageOutcome(
        record=record,
        created=True,
        payload=dict(record.payload) if isinstance(record.payload, dict) else {},
    )


@transaction.atomic
def stage_handoff_for_package(
    *,
    package: WorkflowBuildPackage,
    created_by: User | None = None,
    qa_run_id: str | uuid.UUID | None = None,
) -> HandoffStageOutcome:
    """
    Stage handoff for a package (POST path).

    Uses explicit qa_run_id when provided; otherwise latest QA for the package.
    Requires that QA to be PASS.
    """
    if qa_run_id is not None:
        qa_result = WorkflowQaResult.objects.filter(
            pk=qa_run_id,
            company_id=package.company_id,
        ).first()
        if qa_result is None:
            raise HandoffStageError(
                code="qa_missing",
                detail="QA run not found for this package.",
                status=409,
            )
    else:
        qa_result = latest_qa_result_for_package(
            company_id=package.company_id,
            package_id=package.id,
        )
        if qa_result is None:
            raise HandoffStageError(
                code="qa_missing",
                detail="QA has not been run for this package.",
                status=409,
            )

    return create_or_get_staged_handoff(
        package=package,
        qa_result=qa_result,
        created_by=created_by,
    )
