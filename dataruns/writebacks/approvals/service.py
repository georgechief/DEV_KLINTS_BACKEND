"""Issue, approve, and validate writeback approval tokens (BL-017)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from dataruns.audit import append_audit_event
from dataruns.models import WritebackApprovalToken, WritebackJob
from dataruns.writebacks.approvals.exceptions import (
    ApprovalJobNotFound,
    ApprovalTokenError,
    ApprovalTokenNotFound,
)
from tenants.models import Company, User

_DEFAULT_SCOPE = ("writeback:execute",)
_SCHEMA_VERSION = "1.0.0"


def request_approval(
    *,
    company: Company,
    job_id: str,
    actor: User,
) -> WritebackApprovalToken:
    job = (
        WritebackJob.objects.filter(company=company, pk=job_id, mode="dry_run")
        .order_by("-created_at")
        .first()
    )
    if job is None:
        raise ApprovalJobNotFound()
    if job.status not in ("previewed", "partial"):
        raise ApprovalTokenError("job_not_previewed", "Writeback job is not previewed.")

    if job.approval_tier == "individual":
        ready_count = int((job.summary or {}).get("ready") or 0)
        if ready_count > 1:
            raise ApprovalTokenError(
                "individual_tier_single_intent_required",
                "Individual approval tier allows one ready intent per job.",
            )

    binds = job.token_binds if isinstance(job.token_binds, dict) else {}
    now = timezone.now()
    expires_at = now + timedelta(minutes=settings.WRITEBACK_APPROVAL_TTL_MINUTES)

    with transaction.atomic():
        token = WritebackApprovalToken.objects.create(
            company=company,
            writeback_job=job,
            schema_version=_SCHEMA_VERSION,
            actor_user=actor,
            actor_id=str(actor.id),
            actor_role=str(actor.role),
            scope=list(_DEFAULT_SCOPE),
            object_id=str(binds.get("object_id") or job.check_id).upper(),
            object_version=str(binds.get("object_version") or _SCHEMA_VERSION),
            diff_hash=job.diff_hash,
            status=WritebackApprovalToken.Status.PENDING,
            issued_at=now,
            expires_at=expires_at,
            metadata={
                "approval_tier": job.approval_tier,
                "job_id": str(job.id),
            },
        )
        append_audit_event(
            company=company,
            action="writeback.approval_requested",
            summary=f"Writeback approval requested for {job.check_id}",
            performed_by=actor.email,
            actor_user_id=str(actor.id),
            metadata={
                "approval_id": str(token.id),
                "check_id": job.check_id,
                "diff_hash": job.diff_hash,
            },
        )
    return token


def approve_token(
    *,
    company: Company,
    approval_id: str,
    actor: User,
) -> WritebackApprovalToken:
    with transaction.atomic():
        token = _get_token_for_update(company=company, approval_id=approval_id)
        _expire_if_needed(token)
        if token.status != WritebackApprovalToken.Status.PENDING:
            raise ApprovalTokenError(
                "approval_not_pending", "Approval token is not pending."
            )

        now = timezone.now()
        token.status = WritebackApprovalToken.Status.APPROVED
        token.approved_at = now
        token.approver_user = actor
        token.save(update_fields=["status", "approved_at", "approver_user"])

    append_audit_event(
        company=company,
        action="writeback.approval_granted",
        summary=f"Writeback approval granted for {token.object_id}",
        performed_by=actor.email,
        actor_user_id=str(actor.id),
        metadata={
            "approval_id": str(token.id),
            "check_id": token.object_id,
            "diff_hash": token.diff_hash,
        },
    )
    return token


def reject_token(
    *,
    company: Company,
    approval_id: str,
    actor: User,
    reason: str | None = None,
) -> WritebackApprovalToken:
    cleaned_reason = (reason or "").strip()
    with transaction.atomic():
        token = _get_token_for_update(company=company, approval_id=approval_id)
        _expire_if_needed(token)
        if token.status != WritebackApprovalToken.Status.PENDING:
            raise ApprovalTokenError(
                "approval_not_pending", "Approval token is not pending."
            )

        token.status = WritebackApprovalToken.Status.REJECTED
        token.approver_user = actor
        metadata = dict(token.metadata) if isinstance(token.metadata, dict) else {}
        if cleaned_reason:
            metadata["rejection_reason"] = cleaned_reason
        token.metadata = metadata
        token.save(update_fields=["status", "approver_user", "metadata"])

    append_audit_event(
        company=company,
        action="writeback.approval_rejected",
        summary=f"Writeback approval rejected for {token.object_id}",
        performed_by=actor.email,
        actor_user_id=str(actor.id),
        metadata={
            "approval_id": str(token.id),
            "check_id": token.object_id,
            "diff_hash": token.diff_hash,
            **({"rejection_reason": cleaned_reason} if cleaned_reason else {}),
        },
    )
    return token


def validate_approval_for_execute(
    *,
    company: Company,
    check_id: str,
    diff_hash: str,
    approval_id: str,
) -> tuple[bool, str | None]:
    try:
        token = _get_token(company=company, approval_id=approval_id)
    except ApprovalTokenNotFound:
        return False, "approval_not_found"

    _expire_if_needed(token)
    normalized_check = (check_id or "").strip().upper()
    if token.object_id != normalized_check:
        return False, "approval_check_mismatch"
    if token.diff_hash != diff_hash:
        return False, "approval_diff_hash_mismatch"
    if token.status == WritebackApprovalToken.Status.EXPIRED:
        return False, "approval_expired"
    if token.status != WritebackApprovalToken.Status.APPROVED:
        return False, "approval_not_approved"
    if token.consumed_at is not None:
        return False, "approval_already_consumed"
    job_binds = token.writeback_job.token_binds if token.writeback_job else {}
    if isinstance(job_binds, dict) and job_binds.get("tenant_id"):
        if str(job_binds["tenant_id"]) != str(company.tenant_id):
            return False, "approval_tenant_mismatch"
    return True, None


def consume_approval_token(*, company: Company, approval_id: str) -> None:
    # Atomic no-op if already consumed (safe even without outer company lock).
    WritebackApprovalToken.objects.filter(
        company=company,
        pk=approval_id,
        consumed_at__isnull=True,
    ).update(consumed_at=timezone.now())


def revoke_approval_on_diff_hash_mismatch(
    *,
    company: Company,
    approval_id: str | None,
) -> bool:
    """
    C2 — execute saw a stale preview hash; revoke APPROVED unconsumed grant so
    status stops hydrating Approve & write against the dead preview.
    """
    if not approval_id or not str(approval_id).strip():
        return False
    try:
        with transaction.atomic():
            token = _get_token_for_update(
                company=company, approval_id=str(approval_id).strip()
            )
            if token.status != WritebackApprovalToken.Status.APPROVED:
                return False
            if token.consumed_at is not None:
                return False
            token.status = WritebackApprovalToken.Status.REVOKED
            metadata = dict(token.metadata) if isinstance(token.metadata, dict) else {}
            metadata["revoke_reason"] = "diff_hash_mismatch"
            token.metadata = metadata
            token.save(update_fields=["status", "metadata"])
    except ApprovalTokenNotFound:
        return False
    return True


def revoke_superseded_grants_for_new_preview(
    *,
    company: Company,
    check_id: str,
    preview_job: WritebackJob,
) -> int:
    """
    C4 — a newer dry-run must kill older APPROVED unconsumed grants for this
    check/run so identical-hash re-previews cannot execute via the old token.
    """
    normalized = (check_id or "").strip().upper()
    if not normalized or preview_job is None:
        return 0
    qs = WritebackApprovalToken.objects.filter(
        company=company,
        object_id=normalized,
        status=WritebackApprovalToken.Status.APPROVED,
        consumed_at__isnull=True,
    ).exclude(writeback_job_id=preview_job.id)
    if preview_job.dcs_data_run_id is not None:
        qs = qs.filter(writeback_job__dcs_data_run_id=preview_job.dcs_data_run_id)
    revoked = 0
    with transaction.atomic():
        for token in qs.select_for_update():
            token.status = WritebackApprovalToken.Status.REVOKED
            metadata = dict(token.metadata) if isinstance(token.metadata, dict) else {}
            metadata["revoke_reason"] = "superseded_by_new_preview"
            metadata["superseded_by_job_id"] = str(preview_job.id)
            token.metadata = metadata
            token.save(update_fields=["status", "metadata"])
            revoked += 1
    return revoked


def serialize_token(token: WritebackApprovalToken) -> dict[str, Any]:
    return {
        "schema_version": token.schema_version,
        "approval_id": str(token.id),
        "tenant_id": str(token.company.tenant_id),
        "actor_id": token.actor_id,
        "actor_role": token.actor_role,
        "scope": token.scope,
        "object_id": token.object_id,
        "object_version": token.object_version,
        "diff_hash": token.diff_hash,
        "issued_at": token.issued_at.isoformat(),
        "expires_at": token.expires_at.isoformat(),
        "status": token.status,
        "approved_at": token.approved_at.isoformat() if token.approved_at else None,
        "consumed_at": token.consumed_at.isoformat() if token.consumed_at else None,
        "job_id": str(token.writeback_job_id),
        "approval_tier": token.metadata.get("approval_tier"),
    }


def get_approval_token(*, company: Company, approval_id: str) -> WritebackApprovalToken:
    return _get_token(company=company, approval_id=approval_id)


def _get_token(*, company: Company, approval_id: str) -> WritebackApprovalToken:
    try:
        return WritebackApprovalToken.objects.select_related("writeback_job").get(
            company=company,
            pk=approval_id,
        )
    except (WritebackApprovalToken.DoesNotExist, ValueError, TypeError):
        raise ApprovalTokenNotFound() from None


def _get_token_for_update(*, company: Company, approval_id: str) -> WritebackApprovalToken:
    """Row lock for approve/reject — call inside transaction.atomic()."""
    try:
        return (
            WritebackApprovalToken.objects.select_for_update()
            .select_related("writeback_job")
            .get(company=company, pk=approval_id)
        )
    except (WritebackApprovalToken.DoesNotExist, ValueError, TypeError):
        raise ApprovalTokenNotFound() from None


def _expire_if_needed(token: WritebackApprovalToken) -> None:
    """Expire PENDING or unconsumed APPROVED when past expires_at (C3)."""
    if token.consumed_at is not None:
        return
    if token.status not in (
        WritebackApprovalToken.Status.PENDING,
        WritebackApprovalToken.Status.APPROVED,
    ):
        return
    if timezone.now() >= token.expires_at:
        token.status = WritebackApprovalToken.Status.EXPIRED
        token.save(update_fields=["status"])
