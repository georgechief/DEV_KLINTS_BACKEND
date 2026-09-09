"""Pack-aligned OrchestrationTask constants + SM helpers (PRD-GAP-01 Slice A1).

Pack SoT: Klints_MVP1_…/03_Machine_Contracts/orchestration_task.schema.json
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.utils import timezone

from dataruns.orchestration.scoring import normalize_priority_inputs, priority_class_from_score

ORCH_TASK_SCHEMA_VERSION = "1.0.1"
ORCH_TASK_SCHEMA_REL = (
    "Klints_MVP1_Rohan_Build_Pack_v1.2_20260718"
    "/03_Machine_Contracts/orchestration_task.schema.json"
)

# Pack status enum (8)
ORCH_STATUS_PENDING = "PENDING"
ORCH_STATUS_BLOCKED = "BLOCKED"
ORCH_STATUS_READY = "READY"
ORCH_STATUS_IN_PROGRESS = "IN_PROGRESS"
ORCH_STATUS_AWAITING_APPROVAL = "AWAITING_APPROVAL"
ORCH_STATUS_DONE = "DONE"
ORCH_STATUS_FAILED = "FAILED"
ORCH_STATUS_CANCELLED = "CANCELLED"

ORCH_STATUS_ENUM = frozenset(
    {
        ORCH_STATUS_PENDING,
        ORCH_STATUS_BLOCKED,
        ORCH_STATUS_READY,
        ORCH_STATUS_IN_PROGRESS,
        ORCH_STATUS_AWAITING_APPROVAL,
        ORCH_STATUS_DONE,
        ORCH_STATUS_FAILED,
        ORCH_STATUS_CANCELLED,
    }
)

# Pack task_type enum (11)
ORCH_TASK_TYPE_CONNECT = "CONNECT"
ORCH_TASK_TYPE_DISCOVER = "DISCOVER"
ORCH_TASK_TYPE_SCORE = "SCORE"
ORCH_TASK_TYPE_FIX = "FIX"
ORCH_TASK_TYPE_ASSESS = "ASSESS"
ORCH_TASK_TYPE_PLAN = "PLAN"
ORCH_TASK_TYPE_REPORT = "REPORT"
ORCH_TASK_TYPE_EXPORT = "EXPORT"
ORCH_TASK_TYPE_BUILD = "BUILD"
ORCH_TASK_TYPE_QA = "QA"
ORCH_TASK_TYPE_HANDOFF = "HANDOFF"

ORCH_TASK_TYPE_ENUM = frozenset(
    {
        ORCH_TASK_TYPE_CONNECT,
        ORCH_TASK_TYPE_DISCOVER,
        ORCH_TASK_TYPE_SCORE,
        ORCH_TASK_TYPE_FIX,
        ORCH_TASK_TYPE_ASSESS,
        ORCH_TASK_TYPE_PLAN,
        ORCH_TASK_TYPE_REPORT,
        ORCH_TASK_TYPE_EXPORT,
        ORCH_TASK_TYPE_BUILD,
        ORCH_TASK_TYPE_QA,
        ORCH_TASK_TYPE_HANDOFF,
    }
)

ORCH_ALLOWED_STATUS_TRANSITIONS = frozenset(
    {
        (ORCH_STATUS_PENDING, ORCH_STATUS_READY),
        (ORCH_STATUS_PENDING, ORCH_STATUS_BLOCKED),
        (ORCH_STATUS_PENDING, ORCH_STATUS_CANCELLED),
        (ORCH_STATUS_BLOCKED, ORCH_STATUS_READY),
        (ORCH_STATUS_BLOCKED, ORCH_STATUS_CANCELLED),
        (ORCH_STATUS_READY, ORCH_STATUS_IN_PROGRESS),
        (ORCH_STATUS_READY, ORCH_STATUS_CANCELLED),
        (ORCH_STATUS_IN_PROGRESS, ORCH_STATUS_AWAITING_APPROVAL),
        (ORCH_STATUS_IN_PROGRESS, ORCH_STATUS_DONE),
        (ORCH_STATUS_IN_PROGRESS, ORCH_STATUS_FAILED),
        (ORCH_STATUS_AWAITING_APPROVAL, ORCH_STATUS_IN_PROGRESS),
        (ORCH_STATUS_AWAITING_APPROVAL, ORCH_STATUS_DONE),
        (ORCH_STATUS_AWAITING_APPROVAL, ORCH_STATUS_FAILED),
        (ORCH_STATUS_AWAITING_APPROVAL, ORCH_STATUS_CANCELLED),
        (ORCH_STATUS_FAILED, ORCH_STATUS_READY),
        (ORCH_STATUS_FAILED, ORCH_STATUS_CANCELLED),
    }
)

ORCH_TERMINAL_STATUSES = frozenset({ORCH_STATUS_DONE, ORCH_STATUS_CANCELLED})

ORCH_IDEMPOTENT_TARGET_STATUSES = frozenset(
    {
        ORCH_STATUS_AWAITING_APPROVAL,
        ORCH_STATUS_DONE,
        ORCH_STATUS_CANCELLED,
    }
)

ORCH_ERROR_INVALID_TRANSITION = "invalid_transition"
ORCH_ERROR_FORBIDDEN = "forbidden"
ORCH_ERROR_NOT_FOUND = "not_found"
ORCH_ERROR_VALIDATION = "validation_error"

AUDIT_ACTION_ORCH_TASK_CREATED = "workflow.orchestration_task_created"
AUDIT_ACTION_ORCH_TASK_TRANSITIONED = "workflow.orchestration_task_transitioned"

ORCH_TASK_AUDIT_METADATA_KEYS = frozenset(
    {
        "task_id",
        "task_type",
        "status",
        "idempotency_key",
    }
)

ORCH_TASK_TRANSITION_AUDIT_METADATA_KEYS = frozenset(
    {
        "task_id",
        "task_type",
        "from_status",
        "to_status",
        "status",
        "idempotency_key",
    }
)


def _iso_utc(value: datetime | None = None) -> str:
    dt = value or timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    else:
        dt = dt.astimezone(dt_timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def normalize_orch_status(status: str) -> str:
    normalized = str(status or "").strip().upper()
    if normalized not in ORCH_STATUS_ENUM:
        raise ValueError(f"Invalid orchestration task status: {status!r}")
    return normalized


def normalize_orch_task_type(task_type: str) -> str:
    normalized = str(task_type or "").strip().upper()
    if normalized not in ORCH_TASK_TYPE_ENUM:
        raise ValueError(f"Invalid orchestration task_type: {task_type!r}")
    return normalized


def is_allowed_orch_transition(*, from_status: str, to_status: str) -> bool:
    from_norm = str(from_status or "").strip().upper()
    to_norm = str(to_status or "").strip().upper()
    if from_norm in ORCH_TERMINAL_STATUSES:
        return False
    return (from_norm, to_norm) in ORCH_ALLOWED_STATUS_TRANSITIONS


def is_orch_terminal_status(status: str) -> bool:
    return str(status or "").strip().upper() in ORCH_TERMINAL_STATUSES


def is_orch_idempotent_transition(*, current_status: str, target_status: str) -> bool:
    current = str(current_status or "").strip().upper()
    target = str(target_status or "").strip().upper()
    return current == target and current in ORCH_IDEMPOTENT_TARGET_STATUSES


def build_default_provenance(
    *,
    created_by: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    actor = str(created_by or "").strip() or "system"
    return {
        "source_versions": {
            "orchestration_task": ORCH_TASK_SCHEMA_VERSION,
        },
        "created_at": _iso_utc(created_at),
        "created_by": actor,
    }


def normalize_orch_priority_inputs(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ValueError("priority_inputs must be an object.")
    return normalize_priority_inputs(raw)


def build_orch_task_audit_metadata(
    *,
    record_task_id: str,
    task_type: str,
    status: str,
    idempotency_key: str,
    from_status: str | None = None,
    to_status: str | None = None,
    check_id: str | None = None,
    reason: str | None = None,
) -> dict[str, str]:
    """Locked audit metadata for orchestration task create / transition."""
    tid = str(record_task_id or "").strip()
    if not tid:
        raise ValueError("task_id is required for orchestration task audit metadata.")
    type_norm = normalize_orch_task_type(task_type)
    status_norm = normalize_orch_status(status)
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("idempotency_key is required for orchestration task audit metadata.")
    meta: dict[str, str] = {
        "task_id": tid,
        "task_type": type_norm,
        "status": status_norm,
        "idempotency_key": key,
    }
    if from_status is not None:
        if to_status is None:
            raise ValueError("to_status is required when from_status is set for transition audit.")
        meta["from_status"] = normalize_orch_status(from_status)
        meta["to_status"] = normalize_orch_status(to_status)
    if check_id is not None and str(check_id).strip():
        meta["check_id"] = str(check_id).strip().upper()
    if reason is not None and str(reason).strip():
        meta["reason"] = str(reason).strip()
    required = (
        ORCH_TASK_TRANSITION_AUDIT_METADATA_KEYS
        if from_status is not None
        else ORCH_TASK_AUDIT_METADATA_KEYS
    )
    missing = required - set(meta.keys())
    if missing:
        raise ValueError(f"Orchestration task audit metadata missing keys: {sorted(missing)}")
    return meta


def serialize_orch_task(record: Any) -> dict[str, Any]:
    """Pack-shaped GET projection from OrchestrationTask row."""
    from dataruns.orchestration.models import OrchestrationTask

    if not isinstance(record, OrchestrationTask):
        raise TypeError("record must be an OrchestrationTask instance")

    priority_inputs = normalize_orch_priority_inputs(record.priority_inputs)
    score = float(record.priority_score or 0.0)
    priority_class = str(record.priority_class or "").strip().upper()
    if not priority_class:
        priority_class = priority_class_from_score(score)

    depends_on = record.depends_on if isinstance(record.depends_on, list) else []
    capability_dependencies = (
        record.capability_dependencies
        if isinstance(record.capability_dependencies, list)
        else []
    )
    approval = record.approval if isinstance(record.approval, dict) else {}
    provenance = record.provenance if isinstance(record.provenance, dict) else {}
    source_refs = record.source_refs if isinstance(record.source_refs, dict) else {}
    metadata = record.metadata if isinstance(record.metadata, dict) else {}

    payload: dict[str, Any] = {
        "schema_version": ORCH_TASK_SCHEMA_VERSION,
        "id": str(record.id),
        "task_id": str(record.task_id or "").strip(),
        "tenant_id": str(record.company_id),
        "task_type": str(record.task_type or "").strip().upper(),
        "status": str(record.status or ORCH_STATUS_PENDING).strip().upper(),
        "title": str(record.title or "").strip(),
        "check_id": str(record.check_id).strip().upper() if record.check_id else None,
        "priority_class": priority_class,
        "priority_inputs": priority_inputs,
        "priority_score": score,
        "depends_on": list(depends_on),
        "wave": int(record.wave if record.wave is not None else 0),
        "capability_dependencies": list(capability_dependencies),
        "approval": dict(approval),
        "idempotency_key": str(record.idempotency_key or "").strip(),
        "provenance": dict(provenance),
        "source_refs": dict(source_refs),
        "metadata": dict(metadata),
        "created_at": _iso_utc(record.created_at) if record.created_at else None,
        "updated_at": _iso_utc(record.updated_at) if record.updated_at else None,
    }
    return payload
