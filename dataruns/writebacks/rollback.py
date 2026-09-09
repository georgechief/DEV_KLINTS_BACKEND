"""Rollback executed writeback jobs (PRD-WB-01 §5.3 / §10.1)."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from django.utils import timezone

from dataruns.audit import append_audit_event
from dataruns.models import WritebackJob
from dataruns.writebacks.adapters import get_adapter
from dataruns.writebacks.pii import sanitize_rollback_outcome_for_client
from dataruns.writebacks.pipeline import _serialize_intents, deserialize_intents
from dataruns.writebacks.rollback_strategy import rollback_supported

if TYPE_CHECKING:
    from tenants.models import Company, User

logger = logging.getLogger(__name__)

_ROLLBACKABLE_OP_KINDS = frozenset(
    {
        "detail_set",
        "tag_add",
        "contact_upsert",
        "shopify_customer_update",
    }
)

_ROLLBACKABLE_JOB_STATUSES = frozenset(
    {"executed", "partial", "sandbox_execute", "rollback_partial"}
)


class WritebackRollbackError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class WritebackJobNotFound(WritebackRollbackError):
    def __init__(self) -> None:
        super().__init__("writeback_job_not_found", "Writeback job not found.")


def writeback_rollback(
    *,
    company: Company,
    job_id: str | uuid.UUID,
    actor: "User | None" = None,
) -> dict:
    try:
        job_uuid = uuid.UUID(str(job_id))
    except (ValueError, TypeError) as exc:
        raise WritebackJobNotFound() from exc

    job = WritebackJob.objects.filter(pk=job_uuid, company=company).first()
    if job is None:
        raise WritebackJobNotFound()

    if job.status == "rolled_back":
        raise WritebackRollbackError(
            "writeback_job_already_rolled_back",
            "This writeback was already rolled back.",
        )

    if job.status not in _ROLLBACKABLE_JOB_STATUSES:
        if job.status == "failed":
            raise WritebackRollbackError(
                "writeback_job_not_rollbackable_failed",
                (
                    "That execute wrote nothing. Preview until ready, execute, "
                    "then roll back that job."
                ),
            )
        raise WritebackRollbackError(
            "writeback_job_not_rollbackable",
            (
                "Use the job_id from a successful write, not the preview job_id."
            ),
        )

    prior_metadata = dict(job.metadata) if isinstance(job.metadata, dict) else {}
    prior_results = list(prior_metadata.get("rollback_results") or [])

    intents = deserialize_intents(job.intents or [])
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
        if intent.op_kind not in _ROLLBACKABLE_OP_KINDS:
            errors.append(
                {
                    "operation": intent.operation,
                    "error": "rollback_not_supported",
                }
            )
            continue
        adapter = get_adapter(intent.target_system)
        if adapter is None or not hasattr(adapter, "rollback_intent"):
            errors.append(
                {
                    "operation": intent.operation,
                    "error": "rollback_not_supported",
                }
            )
            continue
        try:
            outcome = adapter.rollback_intent(company, intent)
            intent.status = "rolled_back"
            client_outcome = sanitize_rollback_outcome_for_client(outcome)
            results.append({"operation": intent.operation, **client_outcome})
        except Exception as exc:
            logger.exception(
                "writeback rollback failed job=%s op=%s",
                job.id,
                intent.operation,
            )
            errors.append(
                {
                    "operation": intent.operation,
                    "error": "upstream_error",
                }
            )
            del exc

    still_executed = any(intent.status == "executed" for intent in intents)
    job.status = "rolled_back" if not still_executed and not errors else "rollback_partial"
    job.intents = _serialize_intents(intents)
    job.metadata = {
        **prior_metadata,
        "rollback_results": prior_results + results,
        "rollback_errors": errors,
    }
    # Only successful rollback unlocks the once-per-run gate (PRD-WB-04 §4.2).
    update_fields = ["status", "metadata", "intents"]
    if not errors:
        job.rolled_back_at = timezone.now()
        update_fields.append("rolled_back_at")
    job.save(update_fields=update_fields)

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
            "data_run_id": job.dcs_data_run_id,
        },
    )

    return {
        "job_id": str(job.id),
        "check_id": job.check_id,
        "status": job.status,
        "data_run_id": job.dcs_data_run_id,
        "rolled_back": len(results),
        "errors": errors,
        "results": results,
    }
