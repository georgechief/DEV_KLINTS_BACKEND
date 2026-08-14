"""Execute gates and sandbox eligibility (PRD-WB-01 §5.2–5.3)."""

from __future__ import annotations

import uuid

from django.conf import settings

from dataruns.writebacks.approvals.service import validate_approval_for_execute
from tenants.models import Company


def is_sandbox_company(company: Company) -> bool:
    company_id = str(company.id)
    return company_id in {str(value) for value in settings.WRITEBACK_SANDBOX_COMPANY_IDS}


def is_check_allowlisted(check_id: str) -> bool:
    normalized = (check_id or "").strip().upper()
    allowlist = {str(value).strip().upper() for value in settings.WRITEBACK_CHECK_ALLOWLIST}
    return normalized in allowlist


def execute_allowed(
    *,
    company: Company,
    check_id: str,
    approval_id: str | None = None,
    diff_hash: str | None = None,
) -> tuple[bool, str | None]:
    if not is_check_allowlisted(check_id):
        return False, "check_not_allowlisted"
    if is_sandbox_company(company):
        return True, None
    if settings.WRITEBACKS_ENABLED:
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


def parse_sandbox_company_ids() -> set[uuid.UUID]:
    parsed: set[uuid.UUID] = set()
    for raw in settings.WRITEBACK_SANDBOX_COMPANY_IDS:
        try:
            parsed.add(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    return parsed
