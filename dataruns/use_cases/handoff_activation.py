"""Handoff approve / reject / confirm-activated services (PRD-HO-02 Phase 2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from dataruns.audit import append_audit_event
from dataruns.capabilities.contract import PACKAGE_ROUTE_HUMAN_FALLBACK
from dataruns.models import AuditLog
from dataruns.use_cases.handoff_package import (
    ACTIVATION_PATH_HUMAN_MANAGO_UI,
    AUDIT_ACTION_HANDOFF_ACTIVATED,
    AUDIT_ACTION_HANDOFF_APPROVED,
    AUDIT_ACTION_HANDOFF_REJECTED,
    HANDOFF_ERROR_FORBIDDEN,
    HANDOFF_ERROR_INVALID_TRANSITION,
    HANDOFF_ERROR_MANIFEST_MISMATCH,
    HANDOFF_ERROR_NOT_STAGED,
    HANDOFF_ERROR_QA_NOT_PASS,
    HANDOFF_STATUS_ACTIVATED,
    HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
    HANDOFF_STATUS_REJECTED,
    HANDOFF_STATUS_STAGED,
    MANIFEST_HASH_RE,
    build_activation_approval_ref,
    build_activation_meta_for_approve,
    build_activation_meta_for_confirm,
    build_activation_meta_for_reject,
    build_handoff_activation_audit_metadata,
    is_allowed_handoff_transition,
    is_handoff_idempotent_transition,
    normalize_activation_meta,
    resolve_mcp_publish_status_at_send,
    sync_handoff_payload_status,
)
from dataruns.use_cases.models import HandoffPackage
from dataruns.use_cases.qa_result import QA_STATUS_PASS
from tenants.models import Company, User

ACTIVATION_GUIDE_SUMMARY = (
    "Build/activate this workflow in Manago UI using the package guide."
)
MANAGO_ACTIVATION_HINT = (
    "Automations → Automation Processes → Workflow → New / edit matching blueprint"
)


class HandoffActivationError(Exception):
    """Handoff activation transition failed (maps to HTTP in views)."""

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
class HandoffActivationOutcome:
    record: HandoffPackage
    idempotent: bool
    activation_guide: dict[str, Any] | None = None
    capability: dict[str, Any] | None = None


def _assert_activation_actor(actor: User) -> None:
    if actor.role != User.Role.ADMIN:
        raise HandoffActivationError(
            code=HANDOFF_ERROR_FORBIDDEN,
            detail="Only admins can approve, reject, or confirm handoff activation.",
            status=403,
        )


def _lock_handoff(record: HandoffPackage) -> HandoffPackage:
    """Row lock for HO-02 transitions (avoid duplicate audits under concurrency)."""
    return (
        HandoffPackage.objects.select_for_update()
        .select_related(
            "package",
            "package__pilot",
            "qa_result",
            "company",
        )
        .get(pk=record.pk)
    )


def _assert_manifest_hash(*, record: HandoffPackage, manifest_hash: str) -> None:
    expected = str(record.manifest_hash or "").strip().lower()
    provided = str(manifest_hash or "").strip().lower()
    if not MANIFEST_HASH_RE.match(provided) or provided != expected:
        raise HandoffActivationError(
            code=HANDOFF_ERROR_MANIFEST_MISMATCH,
            detail="manifest_hash does not match handoff package.",
            status=409,
        )


def _assert_qa_still_pass(record: HandoffPackage) -> None:
    qa = getattr(record, "qa_result", None)
    if qa is None or str(qa.status or "").strip().upper() != QA_STATUS_PASS:
        raise HandoffActivationError(
            code=HANDOFF_ERROR_QA_NOT_PASS,
            detail="Linked QA must still be PASS before handoff activation.",
            status=409,
        )


def _package_payload(record: HandoffPackage) -> dict[str, Any]:
    package = getattr(record, "package", None)
    if package is None:
        return {}
    raw = package.payload
    return raw if isinstance(raw, dict) else {}


def build_activation_guide(record: HandoffPackage) -> dict[str, Any]:
    """PRD §6.1 activation_guide block for approve response."""
    package_body = _package_payload(record)
    human_guide = package_body.get("human_guide")
    if not isinstance(human_guide, dict):
        human_guide = {}
    return {
        "path": ACTIVATION_PATH_HUMAN_MANAGO_UI,
        "summary": ACTIVATION_GUIDE_SUMMARY,
        "human_guide": human_guide,
        "use_case_id": str(record.use_case_id or "").strip().upper(),
        "package_id": str(record.package_id),
        "manago_hint": MANAGO_ACTIVATION_HINT,
    }


def build_capability_honesty(record: HandoffPackage) -> dict[str, Any]:
    """PRD §6.1 capability block — honest MCP publish status at send."""
    package_body = _package_payload(record)
    route = str(package_body.get("route") or "").strip().upper()
    if not route:
        route = PACKAGE_ROUTE_HUMAN_FALLBACK
    return {
        "mcp_publish_status": resolve_mcp_publish_status_at_send(),
        "route": route,
    }


def build_approve_response(outcome: HandoffActivationOutcome) -> dict[str, Any]:
    """PRD §6.1 approve API response envelope (Phase 3 views)."""
    record = outcome.record
    guide = outcome.activation_guide or build_activation_guide(record)
    capability = outcome.capability or build_capability_honesty(record)
    return {
        "handoff_id": str(record.id),
        "status": str(record.status or HANDOFF_STATUS_APPROVED_FOR_ACTIVATION),
        "activation_meta": normalize_activation_meta(record.activation_meta),
        "activation_guide": guide,
        "capability": capability,
    }


def build_confirm_response(outcome: HandoffActivationOutcome) -> dict[str, Any]:
    """Confirm-activated API response envelope (Phase 3 views)."""
    record = outcome.record
    return {
        "handoff_id": str(record.id),
        "status": str(record.status or HANDOFF_STATUS_ACTIVATED),
        "activation_meta": normalize_activation_meta(record.activation_meta),
    }


def build_reject_response(outcome: HandoffActivationOutcome) -> dict[str, Any]:
    """Reject API response envelope (Phase 3 views)."""
    record = outcome.record
    return {
        "handoff_id": str(record.id),
        "status": str(record.status or HANDOFF_STATUS_REJECTED),
        "activation_meta": normalize_activation_meta(record.activation_meta),
    }


def _reload_handoff(record: HandoffPackage) -> HandoffPackage:
    refreshed = (
        HandoffPackage.objects.select_related(
            "package",
            "package__pilot",
            "qa_result",
            "company",
        )
        .filter(pk=record.pk)
        .first()
    )
    return refreshed or record


def _audit_activation_transition(
    *,
    record: HandoffPackage,
    actor: User,
    action: str,
    status: str,
    summary: str,
) -> None:
    append_audit_event(
        company=record.company,
        action=action,
        summary=summary,
        performed_by=actor.email,
        tone=AuditLog.Tone.REVENUE,
        actor_user_id=str(actor.id),
        metadata=build_handoff_activation_audit_metadata(
            handoff_id=record.id,
            package_id=record.package_id,
            qa_run_id=record.qa_result_id,
            use_case_id=record.use_case_id,
            status=status,
            manifest_hash=record.manifest_hash,
        ),
    )


@transaction.atomic
def approve_handoff_for_activation(
    *,
    record: HandoffPackage,
    actor: User,
    manifest_hash: str,
    notes: str | None = None,
    approval_token_id: str | None = None,
) -> HandoffActivationOutcome:
    """
    STAGED → APPROVED_FOR_ACTIVATION (PRD §4.2, §5, §6.1).

    Idempotent when already APPROVED_FOR_ACTIVATION (no duplicate audit).
    """
    _assert_activation_actor(actor)
    record = _lock_handoff(record)
    _assert_manifest_hash(record=record, manifest_hash=manifest_hash)

    current = str(record.status or "").strip().upper()
    if is_handoff_idempotent_transition(
        current_status=current,
        target_status=HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
    ):
        reloaded = _reload_handoff(record)
        return HandoffActivationOutcome(
            record=reloaded,
            idempotent=True,
            activation_guide=build_activation_guide(reloaded),
            capability=build_capability_honesty(reloaded),
        )

    _assert_qa_still_pass(record)

    if current != HANDOFF_STATUS_STAGED:
        code = (
            HANDOFF_ERROR_NOT_STAGED
            if current in {HANDOFF_STATUS_REJECTED, HANDOFF_STATUS_ACTIVATED}
            else HANDOFF_ERROR_INVALID_TRANSITION
        )
        raise HandoffActivationError(
            code=code,
            detail=f"Cannot approve handoff in status {current}.",
            status=409,
        )

    activation_meta = build_activation_meta_for_approve(
        user_id=actor.id,
        notes=notes,
        approval_token_id=approval_token_id,
    )
    approval_ref = build_activation_approval_ref(user_id=actor.id)

    record.status = HandoffPackage.Status.APPROVED_FOR_ACTIVATION
    record.activation_meta = activation_meta
    sync_handoff_payload_status(record, approval_ref=approval_ref)
    record.save(update_fields=["status", "activation_meta", "payload"])

    _audit_activation_transition(
        record=record,
        actor=actor,
        action=AUDIT_ACTION_HANDOFF_APPROVED,
        status=HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
        summary=(
            f"Handoff approved for activation ({record.use_case_id})"
        ),
    )

    reloaded = _reload_handoff(record)
    return HandoffActivationOutcome(
        record=reloaded,
        idempotent=False,
        activation_guide=build_activation_guide(reloaded),
        capability=build_capability_honesty(reloaded),
    )


@transaction.atomic
def reject_handoff(
    *,
    record: HandoffPackage,
    actor: User,
    manifest_hash: str,
    reason: str | None = None,
) -> HandoffActivationOutcome:
    """STAGED or APPROVED_FOR_ACTIVATION → REJECTED (PRD §4.2, §5).

    Reject does not require QA PASS — operators must be able to reject when QA
    regresses after staging (PRD §5 reject path).
    """
    _assert_activation_actor(actor)
    record = _lock_handoff(record)
    _assert_manifest_hash(record=record, manifest_hash=manifest_hash)

    current = str(record.status or "").strip().upper()
    if current == HANDOFF_STATUS_REJECTED:
        return HandoffActivationOutcome(record=_reload_handoff(record), idempotent=True)

    if not is_allowed_handoff_transition(
        from_status=current,
        to_status=HANDOFF_STATUS_REJECTED,
    ):
        raise HandoffActivationError(
            code=HANDOFF_ERROR_INVALID_TRANSITION,
            detail=f"Cannot reject handoff in status {current}.",
            status=409,
        )

    activation_meta = build_activation_meta_for_reject(
        existing_meta=normalize_activation_meta(record.activation_meta),
        user_id=actor.id,
        reason=reason,
    )
    record.status = HandoffPackage.Status.REJECTED
    record.activation_meta = activation_meta
    sync_handoff_payload_status(record)
    record.save(update_fields=["status", "activation_meta", "payload"])

    _audit_activation_transition(
        record=record,
        actor=actor,
        action=AUDIT_ACTION_HANDOFF_REJECTED,
        status=HANDOFF_STATUS_REJECTED,
        summary=f"Handoff rejected ({record.use_case_id})",
    )

    return HandoffActivationOutcome(
        record=_reload_handoff(record),
        idempotent=False,
    )


@transaction.atomic
def confirm_handoff_activated(
    *,
    record: HandoffPackage,
    actor: User,
    manifest_hash: str,
    manago_workflow_external_id: str | None = None,
    notes: str | None = None,
) -> HandoffActivationOutcome:
    """
    APPROVED_FOR_ACTIVATION → ACTIVATED (PRD §4.2, §6.2).

    Idempotent when already ACTIVATED (no duplicate audit).
    """
    _assert_activation_actor(actor)
    record = _lock_handoff(record)
    _assert_manifest_hash(record=record, manifest_hash=manifest_hash)

    current = str(record.status or "").strip().upper()
    if is_handoff_idempotent_transition(
        current_status=current,
        target_status=HANDOFF_STATUS_ACTIVATED,
    ):
        return HandoffActivationOutcome(
            record=_reload_handoff(record),
            idempotent=True,
        )

    _assert_qa_still_pass(record)

    if current != HANDOFF_STATUS_APPROVED_FOR_ACTIVATION:
        code = (
            HANDOFF_ERROR_NOT_STAGED
            if current == HANDOFF_STATUS_STAGED
            else HANDOFF_ERROR_INVALID_TRANSITION
        )
        raise HandoffActivationError(
            code=code,
            detail=f"Cannot confirm activation for handoff in status {current}.",
            status=409,
        )

    try:
        activation_meta = build_activation_meta_for_confirm(
            existing_meta=normalize_activation_meta(record.activation_meta),
            user_id=actor.id,
            manago_workflow_external_id=manago_workflow_external_id,
            notes=notes,
        )
    except ValueError as exc:
        raise HandoffActivationError(
            code=HANDOFF_ERROR_INVALID_TRANSITION,
            detail=str(exc),
            status=409,
        ) from exc

    record.status = HandoffPackage.Status.ACTIVATED
    record.activation_meta = activation_meta
    sync_handoff_payload_status(record)
    record.save(update_fields=["status", "activation_meta", "payload"])

    _audit_activation_transition(
        record=record,
        actor=actor,
        action=AUDIT_ACTION_HANDOFF_ACTIVATED,
        status=HANDOFF_STATUS_ACTIVATED,
        summary=f"Handoff activated ({record.use_case_id})",
    )

    return HandoffActivationOutcome(
        record=_reload_handoff(record),
        idempotent=False,
    )


def get_handoff_for_activation(
    *,
    company: Company,
    handoff_id,
) -> HandoffPackage | None:
    """Company-scoped handoff load for activation views."""
    return (
        HandoffPackage.objects.select_related(
            "package",
            "package__pilot",
            "qa_result",
            "company",
        )
        .filter(pk=handoff_id, company=company)
        .first()
    )
