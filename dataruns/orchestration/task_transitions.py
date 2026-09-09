"""Orchestration task create / transition services (PRD-GAP-01 Slice A1 Phase 2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from dataruns.audit import append_audit_event
from dataruns.models import AuditLog
from dataruns.orchestration.models import OrchestrationTask
from dataruns.orchestration.scoring import compute_priority_score, priority_class_from_score
from dataruns.orchestration.task_constants import (
    AUDIT_ACTION_ORCH_TASK_CREATED,
    AUDIT_ACTION_ORCH_TASK_TRANSITIONED,
    ORCH_ERROR_FORBIDDEN,
    ORCH_ERROR_INVALID_TRANSITION,
    ORCH_ERROR_NOT_FOUND,
    ORCH_ERROR_VALIDATION,
    ORCH_STATUS_AWAITING_APPROVAL,
    ORCH_STATUS_CANCELLED,
    ORCH_STATUS_DONE,
    ORCH_STATUS_PENDING,
    ORCH_TERMINAL_STATUSES,
    build_default_provenance,
    build_orch_task_audit_metadata,
    is_allowed_orch_transition,
    is_orch_idempotent_transition,
    normalize_orch_priority_inputs,
    normalize_orch_status,
    normalize_orch_task_type,
)
from tenants.models import Company, User

PRIORITY_CLASS_ENUM = frozenset({"P0", "P1", "P2"})
WAVE_MIN = 0
WAVE_MAX = 6
SCORE_MIN = 0.0
SCORE_MAX = 3.0


class OrchTransitionError(Exception):
    """Orchestration task create/transition failed (maps to HTTP in views)."""

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
class OrchTransitionOutcome:
    record: OrchestrationTask
    idempotent: bool


def _reload_orchestration_task(record: OrchestrationTask) -> OrchestrationTask:
    refreshed = OrchestrationTask.objects.filter(pk=record.pk).first()
    return refreshed or record


def _assert_can_create_or_operate(actor: User) -> None:
    if actor.role == User.Role.VIEWER:
        raise OrchTransitionError(
            code=ORCH_ERROR_FORBIDDEN,
            detail="Viewers cannot create or transition orchestration tasks.",
            status=403,
        )


def _assert_transition_role(
    actor: User,
    *,
    from_status: str,
    to_status: str,
) -> None:
    _assert_can_create_or_operate(actor)
    if (
        from_status == ORCH_STATUS_AWAITING_APPROVAL
        and to_status == ORCH_STATUS_DONE
        and actor.role != User.Role.ADMIN
    ):
        raise OrchTransitionError(
            code=ORCH_ERROR_FORBIDDEN,
            detail="Only admins can approve orchestration tasks (AWAITING_APPROVAL → DONE).",
            status=403,
        )


def _assert_company_scope(*, record: OrchestrationTask, company: Company) -> None:
    if record.company_id != company.id:
        raise OrchTransitionError(
            code=ORCH_ERROR_NOT_FOUND,
            detail="Orchestration task not found.",
            status=404,
        )


def _lock_orchestration_task(record: OrchestrationTask) -> OrchestrationTask:
    return OrchestrationTask.objects.select_for_update().get(pk=record.pk)


def _normalize_priority_class(
    raw: str | None,
    *,
    score: float,
) -> str:
    if raw is not None and str(raw).strip():
        normalized = str(raw).strip().upper()
        if normalized not in PRIORITY_CLASS_ENUM:
            raise OrchTransitionError(
                code=ORCH_ERROR_VALIDATION,
                detail=f"Invalid priority_class: {raw!r}.",
                status=400,
            )
        return normalized
    return priority_class_from_score(score)


def _normalize_wave(raw: Any) -> int:
    try:
        wave = int(raw if raw is not None else 0)
    except (TypeError, ValueError):
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail="wave must be an integer between 0 and 6.",
            status=400,
        ) from None
    if wave < WAVE_MIN or wave > WAVE_MAX:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=f"wave must be between {WAVE_MIN} and {WAVE_MAX}.",
            status=400,
        )
    return wave


def _normalize_priority_score(raw: float | None, *, inputs: dict[str, int]) -> float:
    if raw is None:
        return compute_priority_score(inputs)
    try:
        score = float(raw)
    except (TypeError, ValueError):
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail="priority_score must be a number.",
            status=400,
        ) from None
    if score < SCORE_MIN or score > SCORE_MAX:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=f"priority_score must be between {SCORE_MIN} and {SCORE_MAX}.",
            status=400,
        )
    return score


def _normalize_json_object(raw: Any, *, field: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=f"{field} must be an object.",
            status=400,
        )
    return dict(raw)


def _normalize_string_list(raw: Any, *, field: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=f"{field} must be a list.",
            status=400,
        )
    return [str(item).strip() for item in raw if str(item).strip()]


def _merge_transition_metadata(
    record: OrchestrationTask,
    *,
    actor: User,
    reason: str | None,
) -> dict[str, Any]:
    metadata = dict(record.metadata) if isinstance(record.metadata, dict) else {}
    metadata["last_transition_by"] = actor.email
    metadata["last_transition_at"] = timezone.now().isoformat()
    if reason is not None and str(reason).strip():
        metadata["last_transition_reason"] = str(reason).strip()
    return metadata


def _audit_orchestration_task_created(
    *,
    record: OrchestrationTask,
    actor: User,
) -> None:
    append_audit_event(
        company=record.company,
        action=AUDIT_ACTION_ORCH_TASK_CREATED,
        summary=f"Orchestration task created ({record.task_id})",
        performed_by=actor.email,
        tone=AuditLog.Tone.INFO,
        actor_user_id=str(actor.id),
        metadata=build_orch_task_audit_metadata(
            record_task_id=record.task_id,
            task_type=record.task_type,
            status=record.status,
            idempotency_key=record.idempotency_key,
            check_id=record.check_id or None,
        ),
    )


def _audit_orchestration_task_transitioned(
    *,
    record: OrchestrationTask,
    actor: User,
    from_status: str,
    to_status: str,
    reason: str | None = None,
) -> None:
    append_audit_event(
        company=record.company,
        action=AUDIT_ACTION_ORCH_TASK_TRANSITIONED,
        summary=(
            f"Orchestration task {record.task_id} "
            f"{from_status} → {to_status}"
        ),
        performed_by=actor.email,
        tone=AuditLog.Tone.INFO,
        actor_user_id=str(actor.id),
        metadata=build_orch_task_audit_metadata(
            record_task_id=record.task_id,
            task_type=record.task_type,
            status=to_status,
            idempotency_key=record.idempotency_key,
            from_status=from_status,
            to_status=to_status,
            check_id=record.check_id or None,
            reason=reason,
        ),
    )


def get_orchestration_task(
    *,
    company: Company,
    task_id,
) -> OrchestrationTask | None:
    """Company-scoped orchestration task load for views."""
    return OrchestrationTask.objects.filter(pk=task_id, company=company).first()


@transaction.atomic
def create_orchestration_task(
    *,
    company: Company,
    actor: User,
    task_id: str,
    task_type: str,
    idempotency_key: str,
    priority_inputs: dict[str, Any],
    status: str | None = None,
    title: str = "",
    check_id: str | None = None,
    priority_score: float | None = None,
    priority_class: str | None = None,
    depends_on: list[str] | None = None,
    wave: int = 0,
    capability_dependencies: list[str] | None = None,
    approval: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    source_refs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> OrchTransitionOutcome:
    """Create a company-scoped orchestration task (idempotent on idempotency_key)."""
    _assert_can_create_or_operate(actor)

    task_id_norm = str(task_id or "").strip()
    if not task_id_norm:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail="task_id is required.",
            status=400,
        )

    key = str(idempotency_key or "").strip()
    if not key:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail="idempotency_key is required.",
            status=400,
        )

    existing = OrchestrationTask.objects.filter(
        company=company,
        idempotency_key=key,
    ).first()
    if existing is not None:
        return OrchTransitionOutcome(record=existing, idempotent=True)

    try:
        type_norm = normalize_orch_task_type(task_type)
    except ValueError as exc:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=str(exc),
            status=400,
        ) from exc

    try:
        status_norm = normalize_orch_status(status or ORCH_STATUS_PENDING)
    except ValueError as exc:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=str(exc),
            status=400,
        ) from exc

    if status_norm in ORCH_TERMINAL_STATUSES:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=f"Cannot create orchestration task in terminal status {status_norm}.",
            status=400,
        )

    try:
        inputs_norm = normalize_orch_priority_inputs(priority_inputs)
    except ValueError as exc:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=str(exc),
            status=400,
        ) from exc

    score = _normalize_priority_score(priority_score, inputs=inputs_norm)
    class_norm = _normalize_priority_class(priority_class, score=score)
    wave_norm = _normalize_wave(wave)
    depends_norm = _normalize_string_list(depends_on, field="depends_on")
    capability_norm = _normalize_string_list(
        capability_dependencies,
        field="capability_dependencies",
    )
    approval_norm = _normalize_json_object(approval, field="approval")
    source_refs_norm = _normalize_json_object(source_refs, field="source_refs")
    metadata_norm = _normalize_json_object(metadata, field="metadata")
    if provenance is not None:
        prov = _normalize_json_object(provenance, field="provenance")
    else:
        prov = build_default_provenance(created_by=actor.email)

    record_kwargs = {
        "company": company,
        "task_id": task_id_norm,
        "task_type": type_norm,
        "status": status_norm,
        "title": str(title or "").strip(),
        "check_id": str(check_id or "").strip().upper() if check_id else "",
        "priority_class": class_norm,
        "priority_inputs": dict(inputs_norm),
        "priority_score": score,
        "depends_on": depends_norm,
        "wave": wave_norm,
        "capability_dependencies": capability_norm,
        "approval": approval_norm,
        "idempotency_key": key,
        "provenance": prov,
        "source_refs": source_refs_norm,
        "metadata": metadata_norm,
    }

    try:
        with transaction.atomic():
            record = OrchestrationTask.objects.create(**record_kwargs)
            _audit_orchestration_task_created(record=record, actor=actor)
    except IntegrityError:
        raced = OrchestrationTask.objects.filter(
            company=company,
            idempotency_key=key,
        ).first()
        if raced is None:
            raise
        return OrchTransitionOutcome(record=raced, idempotent=True)

    return OrchTransitionOutcome(
        record=_reload_orchestration_task(record),
        idempotent=False,
    )


@transaction.atomic
def transition_orchestration_task(
    *,
    record: OrchestrationTask,
    company: Company,
    actor: User,
    to_status: str,
    reason: str | None = None,
) -> OrchTransitionOutcome:
    """Apply a pack-valid orchestration task status transition."""
    _assert_company_scope(record=record, company=company)

    try:
        target_status = normalize_orch_status(to_status)
    except ValueError as exc:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=str(exc),
            status=400,
        ) from exc

    record = _lock_orchestration_task(record)
    _assert_company_scope(record=record, company=company)

    current = str(record.status or ORCH_STATUS_PENDING).strip().upper()
    _assert_transition_role(
        actor,
        from_status=current,
        to_status=target_status,
    )

    if is_orch_idempotent_transition(
        current_status=current,
        target_status=target_status,
    ):
        return OrchTransitionOutcome(
            record=_reload_orchestration_task(record),
            idempotent=True,
        )

    if not is_allowed_orch_transition(
        from_status=current,
        to_status=target_status,
    ):
        raise OrchTransitionError(
            code=ORCH_ERROR_INVALID_TRANSITION,
            detail=f"Cannot transition orchestration task from {current} to {target_status}.",
            status=409,
        )

    record.status = target_status
    record.metadata = _merge_transition_metadata(record, actor=actor, reason=reason)
    record.save(update_fields=["status", "metadata", "updated_at"])

    _audit_orchestration_task_transitioned(
        record=record,
        actor=actor,
        from_status=current,
        to_status=target_status,
        reason=reason,
    )

    return OrchTransitionOutcome(
        record=_reload_orchestration_task(record),
        idempotent=False,
    )
