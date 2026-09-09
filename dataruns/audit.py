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
_CONNECTOR_ACTION_PREFIX = "connector."
_DCS_ACTIONS = frozenset({"dcs.score_completed", "dcs.score_failed"})
_REPORT_ACTION_PREFIX = "report."
_QA_ACTION_PREFIX = "qa."
_HANDOFF_ACTION_PREFIX = "workflow.handoff"
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


def _normalize_check_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    return normalized or None


def _normalize_link_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _is_same_origin_path(href: str) -> bool:
    candidate = href.strip()
    if not candidate.startswith("/"):
        return False
    return not candidate.startswith("//")


def extract_audit_link_fields(metadata: dict[str, Any] | None) -> dict[str, str | None]:
    """Deep-link ids from audit metadata (PRD-FE-13 §5 / M2-OPS-01 job focus)."""
    meta = metadata if isinstance(metadata, dict) else {}
    check_id = _normalize_check_id(meta.get("check_id"))
    if check_id is None:
        check_id = _normalize_check_id(meta.get("object_id"))
    # Writeback execute/rollback audits store job_id; accept execute_job_id alias.
    job_id = _normalize_link_string(meta.get("job_id"))
    if job_id is None:
        job_id = _normalize_link_string(meta.get("execute_job_id"))
    return {
        "check_id": check_id,
        "package_id": _normalize_link_string(meta.get("package_id")),
        "use_case_id": _normalize_link_string(meta.get("use_case_id")),
        "report_id": _normalize_link_string(meta.get("report_id")),
        "job_id": job_id,
        "handoff_id": _normalize_link_string(meta.get("handoff_id")),
        "qa_run_id": _normalize_link_string(meta.get("qa_run_id")),
    }


def _build_handoff_href(fields: dict[str, str | None]) -> str | None:
    """PRD-HO-02 §7.3 / §9 — audit bell → /handoff with package + optional ids."""
    package_id = fields.get("package_id")
    if not package_id:
        return None
    params: list[str] = []
    use_case_id = fields.get("use_case_id")
    if use_case_id:
        params.append(f"uc={use_case_id}")
    params.append(f"package_id={package_id}")
    handoff_id = fields.get("handoff_id")
    if handoff_id:
        params.append(f"handoff_id={handoff_id}")
    qa_run_id = fields.get("qa_run_id")
    if qa_run_id:
        params.append(f"qa_run_id={qa_run_id}")
    return f"/handoff?{'&'.join(params)}"


def resolve_audit_href(
    *,
    action: str,
    metadata: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> str:
    """Resolve a same-origin deep-link path for an audit event (PRD-FE-13 §5)."""
    meta = metadata if isinstance(metadata, dict) else {}
    explicit = meta.get("href")
    if isinstance(explicit, str) and _is_same_origin_path(explicit):
        return explicit.strip()

    fields = extract_audit_link_fields(meta)
    check_id = fields["check_id"]
    package_id = fields["package_id"]
    use_case_id = fields["use_case_id"]
    report_id = fields["report_id"]
    normalized_action = (action or "").strip()

    if check_id:
        return f"/fix?issue={check_id}"

    if normalized_action.startswith(_HANDOFF_ACTION_PREFIX):
        handoff_href = _build_handoff_href(fields)
        if handoff_href:
            return handoff_href

    if package_id and use_case_id:
        if normalized_action.startswith(_QA_ACTION_PREFIX) or ".qa_" in normalized_action:
            return f"/qa?uc={use_case_id}&package_id={package_id}"
        return f"/workflow?uc={use_case_id}&package_id={package_id}"

    if report_id or normalized_action.startswith(_REPORT_ACTION_PREFIX):
        return "/activity"

    if run_id or normalized_action in _DCS_ACTIONS:
        return "/data-consistency#dcs-score"

    if normalized_action.startswith(_CONNECTOR_ACTION_PREFIX):
        return "/integrations"

    return "/activity"


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
