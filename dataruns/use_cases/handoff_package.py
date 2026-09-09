"""Handoff package schema helpers (PRD-HO-01 / PRD-HO-02).

HO-01: pack-shaped payload + STAGED create path.
HO-02: activation metadata, audit actions, payload sync on status transitions.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone as dt_timezone
from typing import Any
from uuid import UUID

from django.utils import timezone

from dataruns.audit import stable_json
from dataruns.capabilities.contract import CAP_ID_MCP_WORKFLOW_PUBLISH

# Pack SoT: Klints_MVP1_…/03_Machine_Contracts/handoff_package.schema.json
HANDOFF_PACKAGE_SCHEMA_VERSION = "1.0.0"
HANDOFF_PACKAGE_SCHEMA_REL = (
    "Klints_MVP1_Rohan_Build_Pack_v1.2_20260718"
    "/03_Machine_Contracts/handoff_package.schema.json"
)

# Pack status enum (full). HO-01 only *emits* STAGED.
HANDOFF_STATUS_STAGED = "STAGED"
HANDOFF_STATUS_APPROVED_FOR_ACTIVATION = "APPROVED_FOR_ACTIVATION"
HANDOFF_STATUS_REJECTED = "REJECTED"
HANDOFF_STATUS_ACTIVATED = "ACTIVATED"

HANDOFF_STATUS_ENUM = frozenset(
    {
        HANDOFF_STATUS_STAGED,
        HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
        HANDOFF_STATUS_REJECTED,
        HANDOFF_STATUS_ACTIVATED,
    }
)

# Blueprint / build-package stub uses STAGED_NOT_LIVE — map to pack enum STAGED.
BLUEPRINT_ACTIVATION_STAGED_NOT_LIVE = "STAGED_NOT_LIVE"

# approval_ref locked defaults (PRD-HO-01 §4.2)
APPROVAL_REF_HUMAN_FALLBACK = "HUMAN_FALLBACK"
APPROVAL_REF_NOT_REQUIRED_FOR_STAGED = "NOT_REQUIRED_FOR_STAGED"
APPROVAL_REF_HUMAN_ACTIVATION_APPROVED_PREFIX = "HUMAN_ACTIVATION_APPROVED:"

# HO-02 activation path (PRD §4.4)
ACTIVATION_PATH_HUMAN_MANAGO_UI = "HUMAN_MANAGO_UI"
ACTIVATION_CAPABILITY_CHECKED = CAP_ID_MCP_WORKFLOW_PUBLISH
ACTIVATION_REF_CONFIRMED_PREFIX = "HUMAN_ACTIVATION_CONFIRMED:"

# activation_meta keys (PRD §4.4 — stored on HandoffPackage.activation_meta column)
ACTIVATION_META_PATH = "path"
ACTIVATION_META_CAPABILITY_CHECKED = "capability_checked"
ACTIVATION_META_CAPABILITY_STATUS_AT_SEND = "capability_status_at_send"
ACTIVATION_META_APPROVED_AT = "approved_at"
ACTIVATION_META_APPROVED_BY_USER_ID = "approved_by_user_id"
ACTIVATION_META_APPROVAL_TOKEN_ID = "approval_token_id"
ACTIVATION_META_ACTIVATED_AT = "activated_at"
ACTIVATION_META_ACTIVATED_BY_USER_ID = "activated_by_user_id"
ACTIVATION_META_ACTIVATION_REF = "activation_ref"
ACTIVATION_META_MANAGO_WORKFLOW_EXTERNAL_ID = "manago_workflow_external_id"
ACTIVATION_META_NOTES = "notes"
ACTIVATION_META_REJECTED_AT = "rejected_at"
ACTIVATION_META_REJECTED_BY_USER_ID = "rejected_by_user_id"
ACTIVATION_META_REJECTION_REASON = "rejection_reason"

ACTIVATION_META_APPROVE_KEYS = frozenset(
    {
        ACTIVATION_META_PATH,
        ACTIVATION_META_CAPABILITY_CHECKED,
        ACTIVATION_META_CAPABILITY_STATUS_AT_SEND,
        ACTIVATION_META_APPROVED_AT,
        ACTIVATION_META_APPROVED_BY_USER_ID,
        ACTIVATION_META_APPROVAL_TOKEN_ID,
    }
)

# HO-02 API error codes (PRD §6.1 — Phase 2 views map to HTTP)
HANDOFF_ERROR_NOT_STAGED = "handoff_not_staged"
HANDOFF_ERROR_MANIFEST_MISMATCH = "manifest_mismatch"
HANDOFF_ERROR_QA_NOT_PASS = "qa_not_pass"
HANDOFF_ERROR_FORBIDDEN = "forbidden"
HANDOFF_ERROR_INVALID_TRANSITION = "invalid_transition"

# Terminal / idempotent statuses (PRD §4.2)
HANDOFF_TERMINAL_STATUSES = frozenset({HANDOFF_STATUS_ACTIVATED})
HANDOFF_IDEMPOTENT_TARGET_STATUSES = frozenset(
    {
        HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
        HANDOFF_STATUS_ACTIVATED,
    }
)

# Audit (PRD-HO-01 §7, PRD-HO-02 §9)
AUDIT_ACTION_HANDOFF_STAGED = "workflow.handoff_staged"
AUDIT_ACTION_HANDOFF_APPROVED = "workflow.handoff_approved_for_activation"
AUDIT_ACTION_HANDOFF_REJECTED = "workflow.handoff_rejected"
AUDIT_ACTION_HANDOFF_ACTIVATED = "workflow.handoff_activated"

HANDOFF_STAGED_AUDIT_METADATA_KEYS = frozenset(
    {
        "handoff_id",
        "package_id",
        "qa_run_id",
        "use_case_id",
        "status",
    }
)
HANDOFF_ACTIVATION_AUDIT_METADATA_KEYS = frozenset(
    {
        "handoff_id",
        "package_id",
        "qa_run_id",
        "use_case_id",
        "status",
        "manifest_hash",
        "path",
    }
)

# Allowed HO-02 status transitions (from_status, to_status)
HANDOFF_ALLOWED_STATUS_TRANSITIONS = frozenset(
    {
        (HANDOFF_STATUS_STAGED, HANDOFF_STATUS_APPROVED_FOR_ACTIVATION),
        (HANDOFF_STATUS_STAGED, HANDOFF_STATUS_REJECTED),
        (HANDOFF_STATUS_APPROVED_FOR_ACTIVATION, HANDOFF_STATUS_ACTIVATED),
        (HANDOFF_STATUS_APPROVED_FOR_ACTIVATION, HANDOFF_STATUS_REJECTED),
    }
)

MANIFEST_HASH_RE = re.compile(r"^[a-f0-9]{64}$")


def _iso_utc(value: datetime | None = None) -> str:
    dt = value or timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    else:
        dt = dt.astimezone(dt_timezone.utc)
    return dt.isoformat()


def build_handoff_staged_audit_metadata(
    *,
    handoff_id: str | UUID,
    package_id: str | UUID,
    qa_run_id: str | UUID,
    use_case_id: str,
) -> dict[str, str]:
    """
    Locked audit metadata for workflow.handoff_staged (PRD-HO-01 §7).

    Emitted only on create (not idempotent re-get). Status is always STAGED in HO-01.
    """
    uc = str(use_case_id or "").strip().upper()
    if not uc:
        raise ValueError("use_case_id is required for handoff staged audit metadata.")
    meta = {
        "handoff_id": str(handoff_id),
        "package_id": str(package_id),
        "qa_run_id": str(qa_run_id),
        "use_case_id": uc,
        "status": HANDOFF_STATUS_STAGED,
    }
    missing = HANDOFF_STAGED_AUDIT_METADATA_KEYS - set(meta.keys())
    if missing:
        raise ValueError(f"Handoff audit metadata missing keys: {sorted(missing)}")
    return meta


def build_handoff_activation_audit_metadata(
    *,
    handoff_id: str | UUID,
    package_id: str | UUID,
    qa_run_id: str | UUID,
    use_case_id: str,
    status: str,
    manifest_hash: str,
    path: str = ACTIVATION_PATH_HUMAN_MANAGO_UI,
) -> dict[str, str]:
    """Locked audit metadata for HO-02 approve/reject/activate actions (PRD §9)."""
    uc = str(use_case_id or "").strip().upper()
    if not uc:
        raise ValueError("use_case_id is required for handoff activation audit metadata.")
    status_norm = str(status or "").strip().upper()
    if status_norm not in HANDOFF_STATUS_ENUM:
        raise ValueError(f"Invalid handoff status for audit: {status!r}")
    hash_norm = str(manifest_hash or "").strip().lower()
    if not MANIFEST_HASH_RE.match(hash_norm):
        raise ValueError(f"manifest_hash must match pack pattern, got {manifest_hash!r}")
    path_norm = str(path or "").strip().upper()
    if not path_norm:
        raise ValueError("path is required for handoff activation audit metadata.")
    meta = {
        "handoff_id": str(handoff_id),
        "package_id": str(package_id),
        "qa_run_id": str(qa_run_id),
        "use_case_id": uc,
        "status": status_norm,
        "manifest_hash": hash_norm,
        "path": path_norm,
    }
    missing = HANDOFF_ACTIVATION_AUDIT_METADATA_KEYS - set(meta.keys())
    if missing:
        raise ValueError(f"Handoff activation audit metadata missing keys: {sorted(missing)}")
    return meta


def build_activation_approval_ref(*, user_id: str | UUID) -> str:
    """approval_ref value after HO-02 approve (PRD §4.3)."""
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required for activation approval_ref.")
    return f"{APPROVAL_REF_HUMAN_ACTIVATION_APPROVED_PREFIX}{uid}"


def build_activation_ref_for_confirm(*, user_id: str | UUID) -> str:
    """activation_ref stored in activation_meta on confirm (PRD §4.3 extension)."""
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required for activation_ref.")
    return f"{ACTIVATION_REF_CONFIRMED_PREFIX}{uid}"


def resolve_mcp_publish_status_at_send() -> str:
    """Matrix status for MCP.WORKFLOW.PUBLISH at approve time (PRD §4.4)."""
    from dataruns.capabilities.contract import (
        CAP_ID_MCP_WORKFLOW_PUBLISH,
        CAP_STATUS_DISCOVERY_REQUIRED,
        CAP_STATUS_ENUM,
    )
    from dataruns.capabilities.registry import get_capability

    row = get_capability(CAP_ID_MCP_WORKFLOW_PUBLISH)
    if not isinstance(row, dict):
        return CAP_STATUS_DISCOVERY_REQUIRED
    status = str(row.get("status") or "").strip().upper()
    if status in CAP_STATUS_ENUM:
        return status
    return CAP_STATUS_DISCOVERY_REQUIRED


def build_activation_meta_for_approve(
    *,
    user_id: str | UUID,
    approved_at: datetime | None = None,
    approval_token_id: str | None = None,
    notes: str | None = None,
    capability_status_at_send: str | None = None,
) -> dict[str, Any]:
    """Build activation_meta on approve (PRD §4.4)."""
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required for activation_meta approve block.")
    cap_status = (
        str(capability_status_at_send or "").strip().upper()
        or resolve_mcp_publish_status_at_send()
    )
    meta: dict[str, Any] = {
        ACTIVATION_META_PATH: ACTIVATION_PATH_HUMAN_MANAGO_UI,
        ACTIVATION_META_CAPABILITY_CHECKED: ACTIVATION_CAPABILITY_CHECKED,
        ACTIVATION_META_CAPABILITY_STATUS_AT_SEND: cap_status,
        ACTIVATION_META_APPROVED_AT: _iso_utc(approved_at),
        ACTIVATION_META_APPROVED_BY_USER_ID: uid,
        ACTIVATION_META_APPROVAL_TOKEN_ID: (
            str(approval_token_id).strip() if approval_token_id else None
        ),
        ACTIVATION_META_ACTIVATED_AT: None,
        ACTIVATION_META_ACTIVATED_BY_USER_ID: None,
        ACTIVATION_META_MANAGO_WORKFLOW_EXTERNAL_ID: None,
        ACTIVATION_META_NOTES: str(notes).strip() if notes else None,
    }
    return meta


def build_activation_meta_for_confirm(
    *,
    existing_meta: dict[str, Any] | None,
    user_id: str | UUID,
    activated_at: datetime | None = None,
    manago_workflow_external_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Merge activation_meta on confirm-activated (PRD §4.4)."""
    meta = dict(normalize_activation_meta(existing_meta))
    if ACTIVATION_META_APPROVED_AT not in meta:
        raise ValueError("Cannot confirm activation without prior approve metadata.")
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required for activation_meta confirm block.")
    meta[ACTIVATION_META_ACTIVATED_AT] = _iso_utc(activated_at)
    meta[ACTIVATION_META_ACTIVATED_BY_USER_ID] = uid
    meta[ACTIVATION_META_ACTIVATION_REF] = build_activation_ref_for_confirm(
        user_id=uid
    )
    if manago_workflow_external_id is not None and str(manago_workflow_external_id).strip():
        meta[ACTIVATION_META_MANAGO_WORKFLOW_EXTERNAL_ID] = str(
            manago_workflow_external_id
        ).strip()
    if notes is not None and str(notes).strip():
        meta[ACTIVATION_META_NOTES] = str(notes).strip()
    return meta


def build_activation_meta_for_reject(
    *,
    existing_meta: dict[str, Any] | None,
    user_id: str | UUID,
    rejected_at: datetime | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Merge activation_meta on reject (optional audit trail in column)."""
    meta = dict(normalize_activation_meta(existing_meta))
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required for activation_meta reject block.")
    meta[ACTIVATION_META_REJECTED_AT] = _iso_utc(rejected_at)
    meta[ACTIVATION_META_REJECTED_BY_USER_ID] = uid
    if reason is not None and str(reason).strip():
        meta[ACTIVATION_META_REJECTION_REASON] = str(reason).strip()
    return meta


def normalize_activation_meta(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def is_allowed_handoff_transition(*, from_status: str, to_status: str) -> bool:
    from_norm = str(from_status or "").strip().upper()
    to_norm = str(to_status or "").strip().upper()
    return (from_norm, to_norm) in HANDOFF_ALLOWED_STATUS_TRANSITIONS


def is_handoff_terminal_status(status: str) -> bool:
    return str(status or "").strip().upper() in HANDOFF_TERMINAL_STATUSES


def is_handoff_idempotent_transition(*, current_status: str, target_status: str) -> bool:
    """PRD §4.2 — approve/confirm may no-op when already at target status."""
    current = str(current_status or "").strip().upper()
    target = str(target_status or "").strip().upper()
    return current == target and current in HANDOFF_IDEMPOTENT_TARGET_STATUSES


def normalize_handoff_status(status: str) -> str:
    normalized = str(status or "").strip().upper()
    if normalized not in HANDOFF_STATUS_ENUM:
        raise ValueError(f"Invalid handoff status: {status!r}")
    return normalized


def sync_handoff_payload_status(
    record: "HandoffPackage",
    *,
    approval_ref: str | None = None,
) -> None:
    """
    Keep pack body ``status`` / ``approval_ref`` aligned with HO-02 column state.

    Does not persist — caller saves ``payload`` (and optionally ``activation_meta``).
    """
    from dataruns.use_cases.models import HandoffPackage as HandoffPackageModel

    if not isinstance(record, HandoffPackageModel):
        raise TypeError("record must be a HandoffPackage instance")

    payload = dict(record.payload) if isinstance(record.payload, dict) else {}
    payload["status"] = str(record.status or HANDOFF_STATUS_STAGED)
    if approval_ref is not None:
        approval = str(approval_ref).strip()
        if approval:
            payload["approval_ref"] = approval
    record.payload = payload


HANDOFF_PACKAGE_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "handoff_id",
        "tenant_id",
        "package_version",
        "artifact_refs",
        "qa_ref",
        "approval_ref",
        "manifest_hash",
        "status",
        "created_at",
        "provenance",
    }
)

PROVENANCE_REQUIRED_FIELDS = frozenset(
    {
        "source_versions",
        "created_at",
        "created_by",
    }
)

# FE needs title / QA score / route for /handoff live bind — fetch via package_id
# + qa_ref (schema additionalProperties=false; do not stuff extras into body).
HANDOFF_FE_SIBLING_KEYS = frozenset(
    {
        "use_case_id",
        "package_id",
        "qa_run_id",
        "title",
        "route",
        "qa_score",
        "qa_status",
        "activation_meta",
        "activation_guide",
        "capability",
    }
)


def map_activation_state_to_handoff_status(activation_state: str | None) -> str:
    """
    Map blueprint/handoff_stub activation_state → pack status.

    HO-01 always stages: STAGED_NOT_LIVE and any other pack enum collapse to STAGED.
    Later PRDs (HO-02) may emit ACTIVATED without changing this helper's HO-01 callers.
    """
    raw = str(activation_state or "").strip().upper()
    if raw == BLUEPRINT_ACTIVATION_STAGED_NOT_LIVE or raw == HANDOFF_STATUS_STAGED:
        return HANDOFF_STATUS_STAGED
    # Unknown / future statuses are still staged in HO-01 (no auto-activation).
    return HANDOFF_STATUS_STAGED


def resolve_approval_ref(
    *,
    package_route: str | None = None,
    writeback_approval_id: str | None = None,
) -> str:
    """
    HO-01 approval_ref policy (PRD §4.2):

    1. Explicit writeback approval id if present
    2. Else HUMAN_FALLBACK when package route is HUMAN_FALLBACK
    3. Else NOT_REQUIRED_FOR_STAGED
    """
    if writeback_approval_id and str(writeback_approval_id).strip():
        return str(writeback_approval_id).strip()
    route = str(package_route or "").strip().upper()
    if route == APPROVAL_REF_HUMAN_FALLBACK:
        return APPROVAL_REF_HUMAN_FALLBACK
    return APPROVAL_REF_NOT_REQUIRED_FOR_STAGED


def build_artifact_refs(
    *,
    package_id: str | UUID,
    human_guide_ref: str | None = None,
    agent_spec_ref: str | None = None,
) -> list[str]:
    """artifact_refs: ≥1 unique strings; always include build package id."""
    refs: list[str] = [str(package_id)]
    for extra in (human_guide_ref, agent_spec_ref):
        value = str(extra or "").strip()
        if value and value not in refs:
            refs.append(value)
    return refs


def compute_manifest_hash(canonical_body: dict[str, Any]) -> str:
    """sha256 hex of stable_json(canonical package body) — pack pattern ^[a-f0-9]{64}$."""
    if not isinstance(canonical_body, dict):
        raise TypeError("canonical_body must be a dict")
    digest = hashlib.sha256(stable_json(canonical_body).encode("utf-8")).hexdigest()
    if not MANIFEST_HASH_RE.match(digest):
        raise ValueError(f"Invalid manifest_hash produced: {digest!r}")
    return digest


def _normalize_source_versions(
    source_versions: dict[str, Any] | None,
) -> dict[str, str]:
    """Pack provenance.source_versions values must be strings."""
    if not source_versions:
        return {}
    if not isinstance(source_versions, dict):
        raise TypeError("source_versions must be a dict")
    return {str(key): str(value) for key, value in source_versions.items()}


def build_handoff_package_payload(
    *,
    handoff_id: str | UUID,
    tenant_id: str | UUID,
    package_version: str,
    artifact_refs: list[str],
    qa_ref: str | UUID,
    approval_ref: str,
    manifest_hash: str,
    status: str = HANDOFF_STATUS_STAGED,
    created_at: datetime | None = None,
    created_by: str,
    source_versions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build a pack-schema-shaped handoff package body (PRD-HO-01 §4.2).

    Emits only schema-required keys (additionalProperties=false).
    HO-01 forces status=STAGED regardless of caller intent beyond staging.
    """
    created_iso = _iso_utc(created_at)
    normalized_status = map_activation_state_to_handoff_status(status)

    refs = [str(r).strip() for r in artifact_refs if str(r).strip()]
    # Preserve order, unique
    seen: set[str] = set()
    unique_refs: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            unique_refs.append(ref)
    if not unique_refs:
        raise ValueError("artifact_refs must contain at least one entry.")

    hash_norm = str(manifest_hash).strip().lower()
    if not MANIFEST_HASH_RE.match(hash_norm):
        raise ValueError(
            f"manifest_hash must match ^[a-f0-9]{{64}}$, got {manifest_hash!r}"
        )

    approval = str(approval_ref).strip()
    if not approval:
        raise ValueError("approval_ref is required.")

    created_by_norm = str(created_by).strip()
    if not created_by_norm:
        raise ValueError("provenance.created_by is required.")

    package_version_norm = str(package_version).strip()
    if not package_version_norm:
        raise ValueError("package_version is required.")

    versions = _normalize_source_versions(source_versions)
    payload: dict[str, Any] = {
        "schema_version": HANDOFF_PACKAGE_SCHEMA_VERSION,
        "handoff_id": str(handoff_id),
        "tenant_id": str(tenant_id),
        "package_version": package_version_norm,
        "artifact_refs": unique_refs,
        "qa_ref": str(qa_ref),
        "approval_ref": approval,
        "manifest_hash": hash_norm,
        "status": normalized_status,
        "created_at": created_iso,
        "provenance": {
            "source_versions": versions,
            "created_at": created_iso,
            "created_by": created_by_norm,
        },
    }

    missing = HANDOFF_PACKAGE_REQUIRED_FIELDS - set(payload.keys())
    if missing:
        raise ValueError(f"Handoff payload missing required fields: {sorted(missing)}")

    prov_missing = PROVENANCE_REQUIRED_FIELDS - set(payload["provenance"].keys())
    if prov_missing:
        raise ValueError(
            f"Handoff provenance missing required fields: {sorted(prov_missing)}"
        )

    return payload


def serialize_handoff(record: "HandoffPackage") -> dict[str, Any]:
    """
    API response for a persisted handoff (PRD-HO-01 §5).

    Prefer stored schema payload; force identity/status from columns; add FE
    siblings (not stored in pack body): use_case_id, package_id, qa_run_id,
    plus title/route/qa_* when relations are loaded.
    """
    from dataruns.use_cases.models import HandoffPackage as HandoffPackageModel

    if not isinstance(record, HandoffPackageModel):
        raise TypeError("record must be a HandoffPackage instance")

    payload = dict(record.payload) if isinstance(record.payload, dict) else {}

    # Identity / gate fields always come from columns (not stale payload).
    payload["schema_version"] = (
        str(payload.get("schema_version") or "").strip()
        or HANDOFF_PACKAGE_SCHEMA_VERSION
    )
    payload["handoff_id"] = str(record.id)
    payload["tenant_id"] = str(record.company_id)
    payload["qa_ref"] = str(record.qa_result_id)
    payload["manifest_hash"] = str(record.manifest_hash or "")
    payload["status"] = str(record.status or HANDOFF_STATUS_STAGED)
    if record.created_at is not None:
        created_iso = _iso_utc(record.created_at)
        payload["created_at"] = created_iso
        # Keep provenance.created_at aligned with column (API honesty).
        provenance = payload.get("provenance")
        if isinstance(provenance, dict):
            payload["provenance"] = {**provenance, "created_at": created_iso}

    # FE siblings (API envelope — not part of stored pack body).
    payload["use_case_id"] = str(record.use_case_id or "").strip().upper()
    payload["package_id"] = str(record.package_id)
    payload["qa_run_id"] = str(record.qa_result_id)

    package = getattr(record, "package", None)
    if package is not None:
        pkg_body = package.payload if isinstance(package.payload, dict) else {}
        payload["route"] = str(pkg_body.get("route") or "")
        title = str(pkg_body.get("title") or "").strip()
        pilot = getattr(package, "pilot", None)
        if pilot is not None:
            pilot_title = str(getattr(pilot, "title", None) or "").strip()
            if pilot_title:
                title = pilot_title
        if title:
            payload["title"] = title

    qa = getattr(record, "qa_result", None)
    if qa is not None:
        payload["qa_status"] = str(qa.status or "").strip().upper()
        if qa.score is not None:
            payload["qa_score"] = float(qa.score)

    activation_meta = normalize_activation_meta(getattr(record, "activation_meta", None))
    payload["activation_meta"] = activation_meta

    status_norm = str(record.status or HANDOFF_STATUS_STAGED).strip().upper()
    if status_norm in (
        HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
        HANDOFF_STATUS_ACTIVATED,
    ):
        # PRD-HO-02 §6 GET + §7.2 — guide refs for approved/activated handoffs.
        from dataruns.use_cases.handoff_activation import (
            build_activation_guide,
            build_capability_honesty,
        )

        payload["activation_guide"] = build_activation_guide(record)
        payload["capability"] = build_capability_honesty(record)

    return payload


def latest_handoff_for_package(
    *,
    company_id: str | UUID,
    package_id: str | UUID,
) -> "HandoffPackage | None":
    """Latest staged handoff for a company-scoped package."""
    from dataruns.use_cases.models import HandoffPackage

    return (
        HandoffPackage.objects.filter(
            company_id=company_id,
            package_id=package_id,
        )
        .select_related("package", "package__pilot", "qa_result", "company")
        .order_by("-created_at", "-id")
        .first()
    )
