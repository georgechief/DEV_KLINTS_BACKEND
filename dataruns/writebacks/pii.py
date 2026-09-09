"""PII masking for writeback API responses (PRD-WB-01 / PRD-WB-07 §4)."""

from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_EMAIL_LIKE_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def mask_email(value: str | None) -> str:
    text = (value or "").strip()
    if "@" not in text:
        return text or "—"
    local, domain = text.split("@", 1)
    if not local:
        return f"***@{domain}"
    if len(local) <= 1:
        masked_local = "*"
    else:
        masked_local = f"{local[0]}***"
    return f"{masked_local}@{domain}"


def mask_entity_key(value: str | None) -> str:
    text = (value or "").strip()
    if "@" in text:
        return mask_email(text)
    if len(text) <= 4:
        return text
    return f"{text[:2]}…{text[-2:]}"


def _mask_string(value: str) -> str:
    stripped = value.strip()
    if _EMAIL_RE.match(stripped):
        return mask_email(stripped)
    if "@" in stripped and _EMAIL_LIKE_RE.search(stripped):
        return _EMAIL_LIKE_RE.sub(lambda m: mask_email(m.group(0)), stripped)
    return value


def mask_mapping_values(data: Any) -> Any:
    """Recursively mask email-shaped strings in dict/list payloads for API clients."""
    if isinstance(data, dict):
        return {key: mask_mapping_values(value) for key, value in data.items()}
    if isinstance(data, list):
        return [mask_mapping_values(item) for item in data]
    if isinstance(data, str):
        return _mask_string(data)
    return data


def sanitize_execute_result_for_client(result: Any) -> Any:
    """Drop raw exception strings; keep stable ok/idempotency fields only."""
    if not isinstance(result, dict):
        return None
    cleaned: dict[str, Any] = {}
    if "ok" in result:
        cleaned["ok"] = bool(result.get("ok"))
    if result.get("idempotency_key"):
        cleaned["idempotency_key"] = result.get("idempotency_key")
    # Never forward raw platform error bodies / str(exc).
    return cleaned or {"ok": False}


_ROLLBACK_CLIENT_KEYS = frozenset(
    {
        "ok",
        "skipped",
        "removed_tag",
        "cleared_backfill_marker",
    }
)


def sanitize_rollback_outcome_for_client(outcome: Any) -> dict[str, Any]:
    """Drop adapter/platform bodies from rollback outcomes (PRD-WB-07 §5)."""
    if not isinstance(outcome, dict):
        return {"ok": False}
    cleaned: dict[str, Any] = {}
    if "ok" in outcome:
        cleaned["ok"] = bool(outcome.get("ok"))
    for key in _ROLLBACK_CLIENT_KEYS:
        if key == "ok" or key not in outcome:
            continue
        cleaned[key] = outcome[key]
    return cleaned or {"ok": False}
