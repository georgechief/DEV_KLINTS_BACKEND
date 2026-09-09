"""User-facing writeback execute denial copy (PRD-POLISH-01 P0-5)."""

from __future__ import annotations


def writeback_execute_denial_detail(blocked_reason: str | None) -> str:
    """Map pipeline/gate blocked_reason to an accurate HTTP detail string."""
    reason = (blocked_reason or "").strip()
    if not reason:
        return "Writeback execute was blocked."

    exact: dict[str, str] = {
        "writebacks_disabled": (
            "Writebacks are off for this workspace. "
            "Enable Allow writebacks in Settings → Workspace (Admin)."
        ),
        "check_not_allowlisted": "This check is not allowlisted for writeback execute.",
        "approval_id_required": "Approval token is required before execute.",
        "approval_not_found": "Writeback approval token not found.",
        "approval_check_mismatch": "Approval token does not match this check.",
        "approval_diff_hash_mismatch": "Preview changed — run preview again, then approve.",
        "approval_expired": "Writeback approval token expired.",
        "approval_not_approved": "Writeback approval is not approved yet.",
        "approval_already_consumed": "Writeback approval token was already used.",
        "approval_tenant_mismatch": "Approval token does not match this workspace.",
        "individual_tier_single_intent_required": (
            "This check allows only one ready intent per execute."
        ),
        "fix_owner_not_klints_automated": (
            "Automated writeback is not available for this check owner."
        ),
        "consent_namespace_not_clean": (
            "Consent namespace is not clean (SP-07). Preview is read-only."
        ),
        "dcs_run_required": (
            "Run a Data Consistency Score before approving writebacks."
        ),
    }
    if reason in exact:
        return exact[reason]

    if reason.startswith("connector_not_connected:"):
        platform = reason.split(":", 1)[1].replace("_", " ").strip() or "connector"
        return f"{platform.title()} is not connected."

    return reason.replace("_", " ").capitalize()


def writeback_rollback_denial_detail(code: str | None, fallback: str | None = None) -> str:
    """Map rollback error codes to stable HTTP detail strings."""
    reason = (code or "").strip()
    exact: dict[str, str] = {
        "writeback_job_already_rolled_back": (
            "This writeback was already rolled back."
        ),
        "writeback_job_not_rollbackable_failed": (
            "That execute wrote nothing. Preview until ready, execute, "
            "then roll back that job."
        ),
        "writeback_job_not_rollbackable": (
            "Use the job_id from a successful write, not the preview job_id."
        ),
        "writeback_job_not_found": "Writeback job not found.",
    }
    if reason in exact:
        return exact[reason]
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return "Writeback rollback was blocked."
