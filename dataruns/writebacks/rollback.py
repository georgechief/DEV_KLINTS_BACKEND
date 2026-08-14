"""Rollback executed writeback jobs (PRD-WB-01 §5.3 / §10.1)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from dataruns.audit import append_audit_event
from dataruns.models import WritebackJob
from dataruns.writebacks.adapters.manago import ManagoWriteAdapter
from dataruns.writebacks.pipeline import deserialize_intents
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.types import WriteIntent

if TYPE_CHECKING:
    from tenants.models import Company, User


class WritebackRollbackError(Exception):
    pass


class WritebackJobNotFound(WritebackRollbackError):
    pass


def writeback_rollback(
    *,
    company: Company,
    job_id: str | uuid.UUID,
    actor: "User | None" = None,
) -> dict:
    try:
        job_uuid = uuid.UUID(str(job_id))
    except (ValueError, TypeError) as exc:
        raise WritebackJobNotFound(str(job_id)) from exc

    job = WritebackJob.objects.filter(pk=job_uuid, company=company).first()
    if job is None:
        raise WritebackJobNotFound(str(job_id))

    if job.status not in {"executed", "partial", "sandbox_execute"}:
        raise WritebackRollbackError(f"job status {job.status} is not rollbackable")

    intents = deserialize_intents(job.intents or [])
    adapter = ManagoWriteAdapter()
    results: list[dict] = []
    errors: list[dict] = []

    for intent in intents:
        if intent.status != "executed":
            continue
        supported, reason = rollback_supported(intent)
        if not supported:
            errors.append(
                {
                    "operation": intent.operation,
                    "error": reason or "rollback_not_supported",
                }
            )
            continue
        if intent.op_kind not in ("detail_set", "tag_add", "contact_upsert"):
            errors.append(
                {
                    "operation": intent.operation,
                    "error": "rollback_not_supported",
                }
            )
            continue
        try:
            outcome = adapter.rollback_intent(company, intent)
            results.append({"operation": intent.operation, **outcome})
        except Exception as exc:
            errors.append(
                {
                    "operation": intent.operation,
                    "error": str(exc),
                }
            )

    job.status = "rolled_back" if not errors else "rollback_partial"
    job.metadata = {
        **(job.metadata or {}),
        "rollback_results": results,
        "rollback_errors": errors,
    }
    job.save(update_fields=["status", "metadata"])

    append_audit_event(
        company=company,
        action="writeback.rollback",
        summary=f"Writeback rollback for job {job.id}",
        performed_by=actor.email if actor else "system",
        actor_user_id=str(actor.id) if actor else None,
        metadata={
            "job_id": str(job.id),
            "check_id": job.check_id,
            "rolled_back": len(results),
            "errors": len(errors),
        },
    )

    return {
        "job_id": str(job.id),
        "status": job.status,
        "rolled_back": len(results),
        "errors": errors,
        "results": results,
    }
