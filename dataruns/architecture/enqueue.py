"""Enqueue Architecture Assessment jobs (PRD-AF-01 §5)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from dataruns.architecture.constants import (
    ARCHITECTURE_ASSESSMENT_DATA_RUN_NAME,
    ARCHITECTURE_ASSESSMENT_KIND,
    MANAGO_CONNECTOR_NAME,
    MANAGO_ELIGIBLE_STATUSES,
)
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.models import DataRun
from tenants.models import Company, Connector

logger = logging.getLogger(__name__)

ACTIVE_AF_STATUSES = (
    ArchitectureAssessment.Status.PENDING,
    ArchitectureAssessment.Status.RUNNING,
)


@dataclass(frozen=True)
class ArchitectureEnqueueResult:
    assessment: ArchitectureAssessment | None
    data_run: DataRun | None
    task_queued: bool
    skipped: bool = False
    skip_reason: str | None = None


def company_has_eligible_manago(company: Company) -> bool:
    return Connector.objects.filter(
        company=company,
        name=MANAGO_CONNECTOR_NAME,
        status__in=MANAGO_ELIGIBLE_STATUSES,
    ).exists()


def find_active_architecture_assessment(
    *,
    company: Company,
) -> ArchitectureAssessment | None:
    return (
        ArchitectureAssessment.objects.filter(
            company=company,
            status__in=ACTIVE_AF_STATUSES,
        )
        .select_related("data_run")
        .order_by("-created_at")
        .first()
    )


def find_latest_architecture_assessment(
    *,
    company: Company,
) -> ArchitectureAssessment | None:
    return (
        ArchitectureAssessment.objects.filter(company=company)
        .select_related("data_run", "source_dcs_data_run")
        .order_by("-created_at")
        .first()
    )


def build_architecture_metadata(
    *,
    company: Company,
    triggered_by: str,
    source_dcs_data_run_id: int | None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "kind": ARCHITECTURE_ASSESSMENT_KIND,
        "company_id": str(company.id),
        "triggered_by": triggered_by,
        "source_dcs_data_run_id": source_dcs_data_run_id,
    }
    if actor_user_id:
        meta["actor_user_id"] = actor_user_id
    return meta


def enqueue_architecture_assessment(
    company: Company,
    *,
    source_dcs_data_run: DataRun | None = None,
    source_dcs_data_run_id: int | None = None,
    triggered_by: str = "dcs_succeeded",
    actor_user_id: str | None = None,
    queue: bool = True,
) -> ArchitectureEnqueueResult:
    """
    Create AF DataRun + ArchitectureAssessment and optionally enqueue Celery.

    Prerequisites (PRD §5.1):
    - Manago connected/degraded
    - Coalesce if an AF job is already pending/running
    """
    if not company_has_eligible_manago(company):
        return ArchitectureEnqueueResult(
            assessment=None,
            data_run=None,
            task_queued=False,
            skipped=True,
            skip_reason="manago_not_eligible",
        )

    resolved_source: DataRun | None = source_dcs_data_run
    if resolved_source is None and source_dcs_data_run_id is not None:
        resolved_source = DataRun.objects.filter(id=source_dcs_data_run_id).first()

    if resolved_source is not None:
        kind = (resolved_source.metadata or {}).get("kind")
        if kind != DCS_SCORE_KIND:
            return ArchitectureEnqueueResult(
                assessment=None,
                data_run=None,
                task_queued=False,
                skipped=True,
                skip_reason="source_not_dcs_score",
            )
        if resolved_source.status != DataRun.Status.SUCCEEDED:
            return ArchitectureEnqueueResult(
                assessment=None,
                data_run=None,
                task_queued=False,
                skipped=True,
                skip_reason="source_dcs_not_succeeded",
            )

    active = find_active_architecture_assessment(company=company)
    if active is not None:
        # Coalesce: keep the running/pending job; refresh source pointer.
        if resolved_source is not None and active.source_dcs_data_run_id != resolved_source.id:
            active.source_dcs_data_run = resolved_source
            active.save(update_fields=["source_dcs_data_run", "updated_at"])
            meta = dict(active.data_run.metadata or {})
            meta["source_dcs_data_run_id"] = resolved_source.id
            meta["coalesced_at"] = timezone.now().isoformat()
            active.data_run.metadata = meta
            active.data_run.save(update_fields=["metadata", "updated_at"])
        return ArchitectureEnqueueResult(
            assessment=active,
            data_run=active.data_run,
            task_queued=False,
            skipped=True,
            skip_reason="already_running",
        )

    with transaction.atomic():
        data_run = DataRun.objects.create(
            tenant=company.tenant,
            name=ARCHITECTURE_ASSESSMENT_DATA_RUN_NAME,
            status=DataRun.Status.PENDING,
            metadata=build_architecture_metadata(
                company=company,
                triggered_by=triggered_by,
                source_dcs_data_run_id=(
                    resolved_source.id if resolved_source is not None else None
                ),
                actor_user_id=actor_user_id,
            ),
        )
        assessment = ArchitectureAssessment.objects.create(
            company=company,
            tenant=company.tenant,
            data_run=data_run,
            source_dcs_data_run=resolved_source,
            status=ArchitectureAssessment.Status.PENDING,
        )

    task_queued = False
    if queue:
        from dataruns.tasks import run_architecture_assessment

        try:
            run_architecture_assessment.delay(str(assessment.id))
            task_queued = True
        except Exception as exc:
            logger.exception(
                "architecture_assessment_celery_dispatch_failed assessment_id=%s",
                assessment.id,
            )
            finished = timezone.now()
            assessment.status = ArchitectureAssessment.Status.FAILED
            assessment.error_message = f"Failed to queue assessment task: {exc}"
            assessment.finished_at = finished
            assessment.save(
                update_fields=["status", "error_message", "finished_at", "updated_at"]
            )
            data_run.status = DataRun.Status.FAILED
            data_run.error_message = assessment.error_message
            data_run.finished_at = finished
            data_run.save(update_fields=["status", "error_message", "finished_at"])
            raise

    return ArchitectureEnqueueResult(
        assessment=assessment,
        data_run=data_run,
        task_queued=task_queued,
    )


def maybe_enqueue_architecture_after_dcs(
    *,
    company: Company,
    source_dcs_data_run: DataRun,
) -> ArchitectureEnqueueResult | None:
    """Best-effort AF enqueue after DCS SUCCEEDED — never raises into DCS."""
    try:
        result = enqueue_architecture_assessment(
            company,
            source_dcs_data_run=source_dcs_data_run,
            triggered_by="dcs_succeeded",
            queue=True,
        )
        if result.skipped:
            logger.info(
                "architecture_assessment skipped company=%s reason=%s",
                company.id,
                result.skip_reason,
            )
        else:
            logger.info(
                "architecture_assessment enqueued company=%s assessment=%s queued=%s",
                company.id,
                result.assessment.id if result.assessment else None,
                result.task_queued,
            )
        return result
    except Exception:  # noqa: BLE001 — DCS success path must not fail on AF
        logger.exception(
            "architecture_assessment enqueue failed company=%s dcs_run=%s",
            company.id,
            source_dcs_data_run.id,
        )
        return None
