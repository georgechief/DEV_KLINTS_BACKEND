"""Once-per-DCS-run execute gate (PRD-WB-04 / PRD-WB-07) + status helpers (PRD-WB-06)."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from dataruns.audit import append_audit_event
from dataruns.dcs.worklist import get_latest_terminal_dcs_run
from dataruns.models import AuditLog, WritebackApprovalToken, WritebackJob
from tenants.models import Company

logger = logging.getLogger(__name__)

_EXECUTE_MODES = frozenset({"execute", "sandbox_execute"})
_IN_FLIGHT_STATUS = "executing"
_NO_DCS_RUN_GATE = "no_dcs_run"
# Align with FE isFixFlowCheckOrMappingId (DCS XX-NN + sandbox WB-*-NN).
_DCS_CHECK_ID_RE = re.compile(r"^[A-Z]{2}-\d{2}$", re.I)
_WRITEBACK_SANDBOX_CHECK_ID_RE = re.compile(r"^WB-[A-Z]+-\d{2}$", re.I)


def is_valid_writeback_status_check_id(check_id: str) -> bool:
    token = (check_id or "").strip()
    if not token:
        return False
    return bool(
        _DCS_CHECK_ID_RE.match(token) or _WRITEBACK_SANDBOX_CHECK_ID_RE.match(token)
    )


def resolve_latest_dcs_data_run_id(*, company: Company) -> int | None:
    latest = get_latest_terminal_dcs_run(company=company)
    return latest.id if latest is not None else None


def is_successful_execute_job(job: WritebackJob) -> bool:
    """True only when an execute job actually wrote rows (PRD-WB-04 §4.2)."""
    if job.mode not in _EXECUTE_MODES:
        return False
    if job.status == _IN_FLIGHT_STATUS:
        return False
    summary = job.summary if isinstance(job.summary, dict) else {}
    try:
        executed = int(summary.get("executed") or 0)
    except (TypeError, ValueError):
        executed = 0
    return executed > 0


def is_in_flight_execute_job(job: WritebackJob) -> bool:
    """Claimed execute still running (PRD-WB-07 §3.1) — blocks second Approve."""
    if job.mode not in _EXECUTE_MODES:
        return False
    if job.rolled_back_at is not None:
        return False
    return job.status == _IN_FLIGHT_STATUS


def _executing_stale_after() -> timedelta:
    minutes = int(getattr(settings, "WRITEBACK_EXECUTING_STALE_MINUTES", 15) or 15)
    return timedelta(minutes=max(1, minutes))


def _rollback_policy_fields() -> dict[str, Any]:
    """
    GAP-01 Slice C / W6-03 — honest rollback policy for status + Fix copy.

    ``WRITEBACK_PARTIAL_ROLLBACK_MINUTES`` is persisted on execute job metadata only;
    no scheduler auto-rolls back partial writes. Undo is manual admin rollback.
    """
    stale_minutes = int(getattr(settings, "WRITEBACK_EXECUTING_STALE_MINUTES", 15) or 15)
    window_minutes = int(getattr(settings, "WRITEBACK_PARTIAL_ROLLBACK_MINUTES", 15) or 15)
    return {
        "rollback_policy": "manual_admin_only",
        "rollback_auto_on_error": False,
        "stale_executing_reclaim_minutes": max(1, stale_minutes),
        "rollback_window_minutes": max(1, window_minutes),
        "rollback_window_minutes_purpose": "metadata_only",
    }


def reclaim_stale_executing_jobs(
    *,
    company: Company,
    check_id: str,
    dcs_data_run_id: int,
) -> int:
    """
    Mark stale ``executing`` claims as failed (executed=0) so a new claim can proceed.

    PRD-WB-07 §3.5 — default older than 15 minutes.
    """
    normalized = (check_id or "").strip().upper()
    cutoff = timezone.now() - _executing_stale_after()
    stale = list(
        WritebackJob.objects.filter(
            company=company,
            check_id=normalized,
            mode__in=_EXECUTE_MODES,
            dcs_data_run_id=dcs_data_run_id,
            status=_IN_FLIGHT_STATUS,
            rolled_back_at__isnull=True,
            created_at__lt=cutoff,
        ).order_by("created_at")
    )
    reclaimed = 0
    for job in stale:
        summary = dict(job.summary) if isinstance(job.summary, dict) else {}
        summary["executed"] = 0
        summary.setdefault("errors", int(summary.get("errors") or 0))
        metadata = dict(job.metadata) if isinstance(job.metadata, dict) else {}
        metadata["stale_reclaimed_at"] = timezone.now().isoformat().replace("+00:00", "Z")
        metadata["stale_reclaim_reason"] = "stale_executing_reclaimed"
        job.status = "failed"
        job.summary = summary
        job.metadata = metadata
        job.save(update_fields=["status", "summary", "metadata"])
        append_audit_event(
            company=company,
            action="writeback.execute_failed",
            summary=f"Writeback execute claim reclaimed (stale) for {normalized}",
            performed_by="system",
            actor_user_id=None,
            metadata={
                "check_id": normalized,
                "job_id": str(job.id),
                "reason": "stale_executing_reclaimed",
                "data_run_id": dcs_data_run_id,
            },
            tone=AuditLog.Tone.RISK,
        )
        reclaimed += 1
        logger.info(
            "reclaimed stale writeback executing job_id=%s check=%s company=%s",
            job.id,
            normalized,
            company.id,
        )
    return reclaimed


def find_blocking_execute_job(
    *,
    company: Company,
    check_id: str,
    dcs_data_run_id: int | None,
) -> WritebackJob | None:
    """
    Return a non-rolled-back job that locks the gate.

    Blocks on successful execute (executed > 0) OR in-flight ``executing`` claim
    (PRD-WB-07 §3.1). Failed with executed==0 does not block.
    """
    if dcs_data_run_id is None:
        return None
    normalized = (check_id or "").strip().upper()
    if not normalized:
        return None
    candidates = WritebackJob.objects.filter(
        company=company,
        check_id=normalized,
        mode__in=_EXECUTE_MODES,
        dcs_data_run_id=dcs_data_run_id,
        rolled_back_at__isnull=True,
    ).order_by("-created_at")
    for job in candidates:
        if is_in_flight_execute_job(job) or is_successful_execute_job(job):
            return job
    return None


def acquire_company_execute_lock(*, company: Company) -> Company:
    """
    Serialize execute claims for a company (PRD-WB-07 §3.2 Option A).

    Locks the company row with ``select_for_update`` so concurrent Approves
    cannot both pass the gate before an ``executing`` job is visible.
    """
    return Company.objects.select_for_update().get(pk=company.pk)


def _serialize_execute_job(job: WritebackJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    from dataruns.writebacks.pipeline import deserialize_intents
    from dataruns.writebacks.serializers import serialize_intent

    summary = job.summary if isinstance(job.summary, dict) else {}
    actor_email = job.actor_user.email if job.actor_user_id else None
    intents = [
        serialize_intent(intent)
        for intent in deserialize_intents(job.intents if isinstance(job.intents, list) else [])
    ]
    return {
        "job_id": str(job.id),
        "status": job.status,
        "diff_hash": job.diff_hash,
        "summary": {
            "ready": int(summary.get("ready") or 0),
            "skipped": int(summary.get("skipped") or 0),
            "errors": int(summary.get("errors") or 0),
            "executed": int(summary.get("executed") or 0),
        },
        "intents": intents,
        "created_at": job.created_at.isoformat().replace("+00:00", "Z")
        if job.created_at
        else None,
        "rolled_back_at": job.rolled_back_at.isoformat().replace("+00:00", "Z")
        if job.rolled_back_at
        else None,
        "actor_email": actor_email,
        "data_run_id": job.dcs_data_run_id,
    }


def _serialize_preview_job(job: WritebackJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    from django.conf import settings

    from dataruns.writebacks.pipeline import deserialize_intents
    from dataruns.writebacks.serializers import serialize_intent

    summary = job.summary if isinstance(job.summary, dict) else {}
    metadata = job.metadata if isinstance(job.metadata, dict) else {}
    raw_disclosure = metadata.get("operator_disclosure")
    operator_disclosure = (
        str(raw_disclosure).strip()
        if isinstance(raw_disclosure, str) and raw_disclosure.strip()
        else None
    )
    intents = [
        serialize_intent(intent)
        for intent in deserialize_intents(job.intents if isinstance(job.intents, list) else [])
    ]
    return {
        "job_id": str(job.id),
        "check_id": job.check_id,
        "mode": "dry_run",
        "created_at": job.created_at.isoformat().replace("+00:00", "Z")
        if job.created_at
        else None,
        "data_run_id": job.dcs_data_run_id,
        "diff_hash": job.diff_hash,
        "blocked_reason": None,
        "approval_tier": job.approval_tier or None,
        "irreversible": bool(metadata.get("irreversible")),
        "operator_disclosure": operator_disclosure,
        "intents": intents,
        "summary": {
            "ready": int(summary.get("ready") or 0),
            "skipped": int(summary.get("skipped") or 0),
            "errors": int(summary.get("errors") or 0),
            "executed": int(summary.get("executed") or 0),
        },
        "execute_eligible": {
            "sandbox": bool(job.sandbox),
            "production": bool(settings.WRITEBACKS_ENABLED),
        },
    }


def _serialize_status_approval(
    token: WritebackApprovalToken | None,
) -> dict[str, Any] | None:
    if token is None:
        return None
    if token.status not in (
        WritebackApprovalToken.Status.PENDING,
        WritebackApprovalToken.Status.APPROVED,
    ):
        return None
    if (
        token.status == WritebackApprovalToken.Status.APPROVED
        and token.consumed_at is not None
    ):
        return None
    metadata = token.metadata if isinstance(token.metadata, dict) else {}
    return {
        "approval_id": str(token.id),
        "status": token.status,
        "diff_hash": token.diff_hash,
        "job_id": str(token.writeback_job_id),
        "object_id": token.object_id,
        "issued_at": token.issued_at.isoformat().replace("+00:00", "Z")
        if token.issued_at
        else None,
        "expires_at": token.expires_at.isoformat().replace("+00:00", "Z")
        if token.expires_at
        else None,
        "rejection_reason": metadata.get("rejection_reason"),
    }


def _serialize_pending_approval(
    token: WritebackApprovalToken | None,
) -> dict[str, Any] | None:
    if token is None:
        return None
    if token.status != WritebackApprovalToken.Status.PENDING:
        return None
    return _serialize_status_approval(token)


def _latest_pending_approval(
    *,
    company: Company,
    check_id: str,
    data_run_id: int | None,
    preview_job: WritebackJob | None,
) -> WritebackApprovalToken | None:
    normalized = (check_id or "").strip().upper()
    if not normalized:
        return None
    # TTL elapsed but still PENDING in DB until approve/reject — do not hydrate as live.
    qs = WritebackApprovalToken.objects.filter(
        company=company,
        object_id=normalized,
        status=WritebackApprovalToken.Status.PENDING,
        expires_at__gt=timezone.now(),
    ).select_related("writeback_job")
    if data_run_id is not None:
        qs = qs.filter(writeback_job__dcs_data_run_id=data_run_id)
    if preview_job is not None:
        # Prefer token bound to the latest preview; else keep older in-flight PENDING
        # so cross-session admin still sees the open request.
        bound = qs.filter(writeback_job_id=preview_job.id).order_by("-created_at").first()
        if bound is not None:
            return bound
    return qs.order_by("-created_at").first()


def _latest_granted_approval(
    *,
    company: Company,
    check_id: str,
    data_run_id: int | None,
    preview_job: WritebackJob | None,
) -> WritebackApprovalToken | None:
    """
    APPROVED + unconsumed token — recovery after approve succeeded but execute failed.

    C3 — same TTL as PENDING: past expires_at must not hydrate Approve & write.
    C4 — when a newer dry-run preview exists, do not fall back to a grant bound to an
    older job (that hid the new preview in status and re-stuck Approve & write).
    """
    normalized = (check_id or "").strip().upper()
    if not normalized:
        return None
    qs = WritebackApprovalToken.objects.filter(
        company=company,
        object_id=normalized,
        status=WritebackApprovalToken.Status.APPROVED,
        consumed_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).select_related("writeback_job")
    if data_run_id is not None:
        qs = qs.filter(writeback_job__dcs_data_run_id=data_run_id)
    if preview_job is not None:
        return qs.filter(writeback_job_id=preview_job.id).order_by("-created_at").first()
    return qs.order_by("-created_at").first()


def resolve_writeback_gate(
    *,
    company: Company,
    check_id: str,
    data_run_id: int | None = None,
) -> str:
    normalized = (check_id or "").strip().upper()
    if not normalized:
        return "open"
    effective_run_id = data_run_id
    if effective_run_id is None:
        effective_run_id = resolve_latest_dcs_data_run_id(company=company)
    if effective_run_id is None:
        return _NO_DCS_RUN_GATE

    blocking = find_blocking_execute_job(
        company=company,
        check_id=normalized,
        dcs_data_run_id=effective_run_id,
    )
    if blocking is not None:
        return "locked"

    # WB-06: surface rolled_back when the latest successful write was rolled back.
    for job in WritebackJob.objects.filter(
        company=company,
        check_id=normalized,
        mode__in=_EXECUTE_MODES,
        dcs_data_run_id=effective_run_id,
    ).order_by("-created_at"):
        if is_successful_execute_job(job) and job.rolled_back_at is not None:
            return "rolled_back"
        if is_successful_execute_job(job):
            return "locked"
    return "open"


def writeback_status_payload(
    *,
    company: Company,
    check_id: str,
    data_run_id: int | None = None,
) -> dict[str, Any]:
    normalized = (check_id or "").strip().upper()
    if not normalized:
        raise ValueError("check_id is required")

    effective_run_id = data_run_id
    if effective_run_id is None:
        effective_run_id = resolve_latest_dcs_data_run_id(company=company)

    gate = resolve_writeback_gate(
        company=company,
        check_id=normalized,
        data_run_id=effective_run_id,
    )

    latest_execute = None
    if effective_run_id is not None:
        latest_execute = find_blocking_execute_job(
            company=company,
            check_id=normalized,
            dcs_data_run_id=effective_run_id,
        )
        if latest_execute is None:
            # Surface last successful/rolled-back execute for provenance even if open.
            for job in WritebackJob.objects.filter(
                company=company,
                check_id=normalized,
                mode__in=_EXECUTE_MODES,
                dcs_data_run_id=effective_run_id,
            ).order_by("-created_at"):
                if is_successful_execute_job(job) or job.rolled_back_at is not None:
                    latest_execute = job
                    break

    preview_qs = WritebackJob.objects.filter(
        company=company,
        check_id=normalized,
        mode="dry_run",
    )
    if effective_run_id is not None:
        preview_qs = preview_qs.filter(dcs_data_run_id=effective_run_id)
    latest_preview = preview_qs.order_by("-created_at").first()
    pending_approval = _latest_pending_approval(
        company=company,
        check_id=normalized,
        data_run_id=effective_run_id,
        preview_job=latest_preview,
    )
    granted_approval = None
    if pending_approval is None:
        granted_approval = _latest_granted_approval(
            company=company,
            check_id=normalized,
            data_run_id=effective_run_id,
            preview_job=latest_preview,
        )
    preview_job_for_status = latest_preview
    active_approval = pending_approval or granted_approval
    if active_approval is not None:
        pending_job = active_approval.writeback_job
        if pending_job is not None:
            preview_job_for_status = pending_job

    return {
        "check_id": normalized,
        "data_run_id": effective_run_id,
        "gate": gate,
        "execute_blocked_reason": (
            "dcs_run_required" if effective_run_id is None else None
        ),
        "latest_execute": _serialize_execute_job(latest_execute),
        "latest_preview": _serialize_preview_job(preview_job_for_status),
        "latest_pending_approval": _serialize_pending_approval(pending_approval),
        "latest_granted_approval": _serialize_status_approval(granted_approval),
        **_rollback_policy_fields(),
    }


# Re-export for callers that claim under an outer atomic.
__all__ = [
    "acquire_company_execute_lock",
    "find_blocking_execute_job",
    "is_in_flight_execute_job",
    "is_successful_execute_job",
    "is_valid_writeback_status_check_id",
    "reclaim_stale_executing_jobs",
    "resolve_latest_dcs_data_run_id",
    "resolve_writeback_gate",
    "transaction",
    "writeback_status_payload",
]
