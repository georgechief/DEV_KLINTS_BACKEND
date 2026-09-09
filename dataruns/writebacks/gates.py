"""Execute gates and company writeback eligibility (PRD-WB-01 §5.2, PRD-WB-03)."""

from __future__ import annotations

from django.conf import settings

from dataruns.writebacks.approvals.service import validate_approval_for_execute
from tenants.models import Company


def is_writeback_execute_enabled(company: Company) -> bool:
    """True when this workspace opted in to Fix Approve → execute (PRD-WB-03)."""
    return bool(company.writeback_execute_enabled)


def is_check_allowlisted(check_id: str) -> bool:
    normalized = (check_id or "").strip().upper()
    if not normalized:
        return False
    from dataruns.models import WritebackAllowedCheck

    return WritebackAllowedCheck.objects.filter(
        check_id=normalized,
        enabled=True,
    ).exists()


def execute_allowed(
    *,
    company: Company,
    check_id: str,
    approval_id: str | None = None,
    diff_hash: str | None = None,
) -> tuple[bool, str | None]:
    if not is_check_allowlisted(check_id):
        return False, "check_not_allowlisted"
    # Company opt-in (WB-03) still requires approval + diff bind — FE always sends
    # approval_id; do not skip the chain for direct API callers.
    if is_writeback_execute_enabled(company) or settings.WRITEBACKS_ENABLED:
        if not approval_id:
            return False, "approval_id_required"
        valid, reason = validate_approval_for_execute(
            company=company,
            check_id=check_id,
            diff_hash=diff_hash or "",
            approval_id=approval_id,
        )
        if not valid:
            return False, reason
        return True, None
    return False, "writebacks_disabled"
