"""Writeback domain types (PRD-WB-01 §2.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

WriteMode = Literal["dry_run", "execute", "sandbox_execute"]
WriteIntentStatus = Literal["ready", "skipped", "error", "executed"]
ApprovalTier = Literal["batch", "individual"]
OpKind = Literal[
    "contact_upsert",
    "detail_set",
    "tag_add",
    "tag_remove",
    "contact_merge",
    "event_ingest",
    "event_update",
    "event_correct",
    "product_upsert",
    "coupon_sync",
    "consent_reconcile",
    "shopify_customer_update",
    "shopify_metafield_set",
    "erp_attribute_feed",
    "availability_gate",
]


@dataclass
class WriteIntent:
    check_id: str
    op_kind: str
    operation: str
    target_system: str
    entity_type: str
    entity_key: str
    namespace: str = ""
    template_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    rollback_snapshot: dict[str, Any] = field(default_factory=dict)
    source_evidence_ref: str = ""
    status: WriteIntentStatus = "ready"
    error_reason: str | None = None
    capability_id: str | None = None
    rollback_strategy: str | None = None
    execute_result: dict[str, Any] | None = None

    def to_hash_dict(self) -> dict[str, Any]:
        """Stable subset for diff_hash (no PII-heavy before/after blobs)."""
        return {
            "check_id": self.check_id,
            "op_kind": self.op_kind,
            "operation": self.operation,
            "target_system": self.target_system,
            "entity_type": self.entity_type,
            "entity_key": self.entity_key,
            "namespace": self.namespace,
            "payload": self.payload,
            "status": self.status,
        }


@dataclass
class WritebackSummary:
    ready: int = 0
    skipped: int = 0
    errors: int = 0
    executed: int = 0


@dataclass
class ExecuteEligibility:
    sandbox: bool = False
    production: bool = False


@dataclass
class WritebackResult:
    check_id: str
    mode: WriteMode
    diff_hash: str
    intents: list[WriteIntent]
    summary: WritebackSummary
    execute_eligible: ExecuteEligibility
    blocked_reason: str | None = None
    job_id: str | None = None
    approval_tier: ApprovalTier | None = None
    irreversible: bool = False
    operator_disclosure: str | None = None
