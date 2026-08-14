"""Rollback strategy helpers (PRD-WB-01 §10.1)."""

from __future__ import annotations

from dataruns.writebacks.types import WriteIntent

_STRATEGY_BY_OP = {
    "contact_upsert": frozenset({"tagged_backfill_delete", "restore_prior_field"}),
    "detail_set": frozenset({"revert_detail"}),
    "tag_add": frozenset({"remove_tag"}),
    "tag_remove": frozenset({"remove_tag"}),
}


def rollback_supported(intent: WriteIntent) -> tuple[bool, str | None]:
    strategy = intent.rollback_strategy
    if strategy == "tagged_backfill_delete" and intent.op_kind == "event_ingest":
        return False, "rollback_not_supported"

    allowed = _STRATEGY_BY_OP.get(intent.op_kind)
    if allowed is None:
        return False, "rollback_not_supported"
    if strategy is None:
        return True, None
    if strategy in allowed:
        return True, None
    return False, "rollback_strategy_mismatch"
