"""Serialize writeback results for REST responses."""

from __future__ import annotations

from typing import Any

from dataruns.writebacks.pii import mask_entity_key
from dataruns.writebacks.types import WriteIntent, WritebackResult


def serialize_intent(intent: WriteIntent) -> dict[str, Any]:
    return {
        "op_kind": intent.op_kind,
        "operation": intent.operation,
        "target": intent.target_system,
        "namespace": intent.namespace,
        "entity_key": mask_entity_key(intent.entity_key),
        "before": intent.before,
        "after": intent.after,
        "status": intent.status,
        "error_reason": intent.error_reason,
        "execute_result": intent.execute_result,
    }


def serialize_result(result: WritebackResult) -> dict[str, Any]:
    return {
        "check_id": result.check_id,
        "mode": result.mode,
        "diff_hash": result.diff_hash,
        "blocked_reason": result.blocked_reason,
        "job_id": result.job_id,
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
