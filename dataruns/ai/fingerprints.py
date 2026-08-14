"""Fingerprinting + cache freshness for AI-01 (PRD §7.2)."""

from __future__ import annotations

import hashlib
from typing import Any

from dataruns.ai.constants import ALLOWLIST_VERSION, POLICY_VERSION, TASK_TYPES_V1
from dataruns.audit import stable_json

# Context keys that affect suggestion wording — changes invalidate cache.
_FIX_SUGGESTION_FINGERPRINT_KEYS = (
    "check_id",
    "check_name",
    "dimension",
    "severity",
    "status",
    "systems_compared",
    "suggested_fix",
    "fix_type",
    "fix_owner",
    "finding_summary",
    "revenue_impact",
    "currency",
    "dcs_run_id",
    "architecture_verdict",
)


def _pick_fingerprint_payload(
    allowlisted_context: dict[str, Any],
    *,
    task_type: str,
) -> dict[str, Any]:
    """Project allowlisted context to fingerprint-relevant fields only."""
    if task_type == "fix_suggestion":
        keys = _FIX_SUGGESTION_FINGERPRINT_KEYS
    else:
        # Report / explain tasks — use full allowlisted body minus metadata stamps.
        keys = tuple(
            k
            for k in allowlisted_context
            if k
            not in {
                "policy_version",
                "allowlist_version",
                "prompt_version",
                "task_type",
                "company_display_name",
                "company_hostname",
                "industry_vertical",
            }
        )
    body: dict[str, Any] = {}
    for key in keys:
        if key in allowlisted_context:
            value = allowlisted_context[key]
            if value is not None and value != "":
                body[key] = value
    return body


def compute_fingerprint(
    *,
    task_type: str,
    prompt_version: str,
    allowlisted_context: dict[str, Any],
    policy_version: str = POLICY_VERSION,
    allowlist_version: str = ALLOWLIST_VERSION,
) -> str:
    """
    sha256(task_type + allowlisted payload + prompt_version + policy versions).

    Invalidates automatically when DCS run, remediation text, or prompt/policy bump.
    """
    if task_type not in TASK_TYPES_V1:
        raise ValueError(f"Unsupported task_type for fingerprint: {task_type}")
    payload = _pick_fingerprint_payload(allowlisted_context, task_type=task_type)
    canonical = stable_json(
        {
            "task_type": task_type,
            "prompt_version": prompt_version,
            "policy_version": policy_version,
            "allowlist_version": allowlist_version,
            "context": payload,
        }
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint_prefix(digest: str, *, length: int = 12) -> str:
    """Short prefix for logs / UI (never use alone as unique id)."""
    token = (digest or "").strip()
    if len(token) <= length:
        return token
    return token[:length]
