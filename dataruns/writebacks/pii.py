"""PII masking for writeback API responses."""

from __future__ import annotations


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
