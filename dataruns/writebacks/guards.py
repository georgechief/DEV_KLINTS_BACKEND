"""Row-level validation guards for write intents."""

from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def apply_guards(
    *,
    guards: list[str],
    entity_key: str,
    namespace: str,
    fields: dict[str, Any],
) -> str | None:
    for guard in guards:
        reason = _run_guard(
            guard,
            entity_key=entity_key,
            namespace=namespace,
            fields=fields,
        )
        if reason:
            return reason
    return None


def _run_guard(
    guard: str,
    *,
    entity_key: str,
    namespace: str,
    fields: dict[str, Any],
) -> str | None:
    if guard == "entity_key_required":
        if not str(entity_key or "").strip():
            return "entity_key_required"
        return None
    if guard == "email_format":
        if "@" in str(entity_key) and not _EMAIL_RE.match(str(entity_key).strip()):
            return "email_format"
        return None
    if guard == "klints_prefix":
        detail_key = str(fields.get("detail_key") or "")
        tag = str(fields.get("tag") or "")
        if detail_key and namespace == "klints_" and not detail_key.startswith("klints_"):
            return "klints_prefix"
        if tag and namespace == "klints:" and not tag.startswith("klints:"):
            return "klints_prefix"
        return None
    # PRD-WB-16 Phase A: plan_only is documentary on the intent (pipeline enforces).
    if guard == "plan_only":
        return None
    # Phase B guards (wired early so mapping strings are not silent no-ops).
    if guard == "safety_class_safe_delete":
        if str(fields.get("safety_class") or "").strip() != "SAFE_DELETE":
            return "safety_class_not_safe_delete"
        return None
    if guard == "cluster_size_eq_2":
        losers = fields.get("loser_manago_ids")
        if not isinstance(losers, list) or len(losers) != 1:
            return "cluster_size_not_2"
        return None
    if guard == "loser_contact_id_required":
        losers = fields.get("loser_manago_ids")
        if not isinstance(losers, list) or not any(
            str(x or "").strip() for x in losers
        ):
            return "loser_contact_id_required"
        return None
    return None
