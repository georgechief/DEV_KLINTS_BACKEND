"""Append-only company audit log with hash chain (PRD-AUDIT-01)."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from django.db import transaction
from django.utils import timezone

from dataruns.models import AuditLog, Run
from tenants.models import Company, User

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64
_SECRET_METADATA_KEYS = frozenset(
    {
        "api_key",
        "api_v3_key",
        "access_token",
        "refresh_token",
        "password",
        "config",
        "authorization",
    }
)


def stable_json(metadata: dict[str, Any] | None) -> str:
    return json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))


def sanitize_audit_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        if key in _SECRET_METADATA_KEYS:
            continue
        if isinstance(value, dict):
            nested = sanitize_audit_metadata(value)
            if nested:
                sanitized[key] = nested
            continue
        sanitized[key] = value
    return sanitized


def compute_entry_hash(
    *,
    prev_hash: str,
    company_id: str,
    action: str,
    summary: str,
    performed_by: str,
    created_at_iso: str,
    metadata: dict[str, Any],
) -> str:
    payload = "|".join(
        [
            prev_hash,
            company_id,
            action,
            summary,
            performed_by,
            created_at_iso,
            stable_json(metadata),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit_meta_short_string(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    from dataruns.dcs.run_diff import format_audit_at_stake_meta

    at_stake = format_audit_at_stake_meta(metadata)
    if at_stake:
        return at_stake
    report_id = metadata.get("report_id")
    if isinstance(report_id, str) and report_id:
        parts: list[str] = []
        email = metadata.get("email")
        ip_address = metadata.get("ip_address")
        if isinstance(email, str) and email:
            parts.append(email)
        if isinstance(ip_address, str) and ip_address:
            parts.append(ip_address)
        parts.append(report_id)
        return " · ".join(parts)
    for key in ("platform", "connector_name", "run_state", "email", "ip_address"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def resolve_performed_by_email(actor_user_id: str | None) -> str:
    if not actor_user_id:
        return "system"
    try:
        user = User.objects.filter(pk=actor_user_id).only("email").first()
    except (ValueError, TypeError):
        return "system"
    if user is None:
        return "system"
    return user.email


@transaction.atomic
def append_audit_event(
    *,
    company: Company,
    action: str,
    summary: str,
    performed_by: str,
    tone: str = AuditLog.Tone.INFO,
    actor_user_id: str | None = None,
    run: Run | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Append a company-scoped audit event with hash chain (PRD-AUDIT-01 §5)."""
    safe_metadata = sanitize_audit_metadata(metadata)
    created_at = timezone.now()
    created_at_iso = created_at.isoformat().replace("+00:00", "Z")
    company_id = str(company.id)

    last_entry = (
        AuditLog.objects.select_for_update()
        .filter(company=company)
        .order_by("-created_at", "-id")
        .first()
    )
    prev_hash = last_entry.entry_hash if last_entry is not None else GENESIS_HASH

    entry_hash = compute_entry_hash(
        prev_hash=prev_hash,
        company_id=company_id,
        action=action,
        summary=summary,
        performed_by=performed_by,
        created_at_iso=created_at_iso,
        metadata=safe_metadata,
    )

    parsed_actor_id = None
    if actor_user_id:
        try:
            parsed_actor_id = uuid.UUID(str(actor_user_id))
        except (ValueError, TypeError):
            parsed_actor_id = None

    try:
        return AuditLog.objects.create(
            company=company,
            run=run,
            action=action,
            tone=tone,
            summary=summary,
            performed_by=performed_by,
            actor_user_id=parsed_actor_id,
            metadata=safe_metadata,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            created_at=created_at,
        )
    except Exception:
        logger.exception("Failed to append audit event company_id=%s action=%s", company_id, action)
        raise


def count_unread_audit_events(*, company: Company) -> int:
    return AuditLog.objects.filter(company=company, audit_read=False).count()


def mark_all_audit_events_read(*, company: Company) -> int:
    return AuditLog.objects.filter(company=company, audit_read=False).update(
        audit_read=True
    )


def mark_audit_event_read(*, company: Company, event_id: uuid.UUID) -> AuditLog | None:
    entry = AuditLog.objects.filter(pk=event_id, company=company).first()
    if entry is None:
        return None
    if not entry.audit_read:
        AuditLog.objects.filter(pk=entry.pk).update(audit_read=True)
        entry.audit_read = True
    return entry


def verify_audit_chain_for_company(*, company: Company) -> list[str]:
    """Return a list of integrity errors; empty when the chain is valid."""
    errors: list[str] = []
    entries = list(
        AuditLog.objects.filter(company=company).order_by("created_at", "id")
    )
    expected_prev = GENESIS_HASH
    for entry in entries:
        if entry.prev_hash != expected_prev:
            errors.append(
                f"Broken chain at {entry.id}: expected prev_hash {expected_prev}, "
                f"got {entry.prev_hash}"
            )
        created_at_iso = entry.created_at.isoformat().replace("+00:00", "Z")
        recomputed = compute_entry_hash(
            prev_hash=entry.prev_hash,
            company_id=str(entry.company_id),
            action=entry.action,
            summary=entry.summary,
            performed_by=entry.performed_by,
            created_at_iso=created_at_iso,
            metadata=entry.metadata or {},
        )
        if recomputed != entry.entry_hash:
            errors.append(
                f"Hash mismatch at {entry.id}: expected {recomputed}, got {entry.entry_hash}"
            )
        expected_prev = entry.entry_hash
    return errors
