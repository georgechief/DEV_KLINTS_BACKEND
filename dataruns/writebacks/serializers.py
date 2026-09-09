"""Serialize writeback results for REST responses (PRD-WB-07 §4 — mask PII)."""

from __future__ import annotations

from typing import Any

from dataruns.writebacks.pii import (
    mask_entity_key,
    mask_mapping_values,
    sanitize_execute_result_for_client,
)
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.types import WriteIntent, WritebackResult


def serialize_intent(intent: WriteIntent) -> dict[str, Any]:
    """API-facing intent — entity_key / emails masked (full values stay in DB job)."""
    return {
        "op_kind": intent.op_kind,
        "operation": intent.operation,
        "target": intent.target_system,
        "namespace": intent.namespace,
        "entity_key": mask_entity_key(intent.entity_key),
        "before": mask_mapping_values(intent.before),
        "after": mask_mapping_values(intent.after),
        "status": intent.status,
        "error_reason": intent.error_reason,
        "execute_result": sanitize_execute_result_for_client(intent.execute_result),
    }


def execute_rollback_supported(result: WritebackResult) -> bool:
    if result.irreversible:
        return False
    for intent in result.intents:
        if intent.status not in {"ready", "executed"}:
            continue
        supported, _reason = rollback_supported(intent)
        if supported:
            return True
    return False


def serialize_result(
    result: WritebackResult,
    *,
    action: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "check_id": result.check_id,
        "mode": result.mode,
        "diff_hash": result.diff_hash,
        "blocked_reason": result.blocked_reason,
        "job_id": result.job_id,
        "data_run_id": result.data_run_id,
        "approval_tier": result.approval_tier,
        "irreversible": result.irreversible,
        "operator_disclosure": result.operator_disclosure,
        "intents": [serialize_intent(intent) for intent in result.intents],
        "summary": {
            "ready": result.summary.ready,
            "skipped": result.summary.skipped,
            "errors": result.summary.errors,
            "executed": result.summary.executed,
        },
        "execute_eligible": {
            "sandbox": result.execute_eligible.sandbox,
            "production": result.execute_eligible.production,
        },
    }
    if action:
        payload["action"] = action
    if action == "execute":
        payload["rollback"] = {"supported": execute_rollback_supported(result)}
    return payload
