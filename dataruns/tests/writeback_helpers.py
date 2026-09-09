"""Shared DB setup for writeback gate tests."""

from __future__ import annotations

from contextlib import contextmanager

from dataruns.models import WritebackAllowedCheck
from tenants.models import Company

DEFAULT_WRITEBACK_ALLOWLIST = ("CI-01", "CC-03", "WB-SHOP-01")


def clear_writeback_allowlist() -> None:
    WritebackAllowedCheck.objects.all().delete()


def seed_writeback_allowlist(*check_ids: str) -> None:
    clear_writeback_allowlist()
    for check_id in check_ids:
        normalized = str(check_id).strip().upper()
        if not normalized:
            continue
        WritebackAllowedCheck.objects.create(check_id=normalized, enabled=True)


def seed_default_writeback_allowlist() -> None:
    seed_writeback_allowlist(*DEFAULT_WRITEBACK_ALLOWLIST)


def enable_company_writeback_execute(company: Company) -> None:
    if not company.writeback_execute_enabled:
        company.writeback_execute_enabled = True
        company.save(update_fields=["writeback_execute_enabled"])


def issue_approved_writeback_token(
    *,
    company: Company,
    job_id: str,
    requester,
    approver,
):
    """Preview job → request approval → approve; return token for execute."""
    from dataruns.writebacks.approvals.service import approve_token, request_approval

    token = request_approval(
        company=company,
        job_id=str(job_id),
        actor=requester,
    )
    approve_token(
        company=company,
        approval_id=str(token.id),
        actor=approver,
    )
    return token


@contextmanager
def writeback_execute_company(company: Company):
    was_enabled = company.writeback_execute_enabled
    enable_company_writeback_execute(company)
    try:
        yield company
    finally:
        if not was_enabled:
            company.writeback_execute_enabled = False
            company.save(update_fields=["writeback_execute_enabled"])


# Backward-compatible aliases for existing tests/helpers.
def enable_company_sandbox(company: Company) -> None:
    enable_company_writeback_execute(company)


@contextmanager
def sandbox_company(company: Company):
    with writeback_execute_company(company) as enabled:
        yield enabled
