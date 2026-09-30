"""Shared DB setup for writeback gate tests + WB-21 sandbox contract harness."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from dataruns.models import WritebackAllowedCheck
from tenants.models import Company

DEFAULT_WRITEBACK_ALLOWLIST = ("CI-01", "CC-03", "WB-SHOP-01", "LE-01", "LE-09")

# PRD-WB-21 §3 — first-wave dual-connector sandbox proof.
PHASE_A_SANDBOX_CHECK_IDS = ("CI-01", "CC-03", "WB-SHOP-01")

# PRD-WB-21 §3 Tier A — full execute sandbox (Phase A + later waves).
TIER_A_SANDBOX_CHECK_IDS = (
    "CI-01",
    "CC-03",
    "WB-SHOP-01",
    "CI-05",
    "LE-01",
    "LE-02",
    "LE-05",
    "LE-09",
    "SP-03",
    "SP-07",
    "PT-04",
)

TIER_B_PLAN_ONLY_CHECK_IDS = ("CI-03", "CC-01", "CC-02")
TIER_C_EXECUTE_BLOCKED_CHECK_IDS = ("PT-03",)
TIER_D_DISABLED_CHECK_IDS = ("LE-04", "SP-01")


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


def run_sandbox_preview(
    *,
    company: Company,
    check_id: str,
    actor,
    max_rows: int = 1,
):
    """PRD-WB-21 — Allow writebacks path preview (dry_run)."""
    from dataruns.writebacks.service import writeback_run

    return writeback_run(
        company=company,
        check_id=check_id,
        mode="dry_run",
        max_rows=max_rows,
        actor=actor,
    )


def run_sandbox_execute(
    *,
    company: Company,
    check_id: str,
    actor,
    diff_hash: str,
    approval_id: str,
    max_rows: int = 1,
):
    """PRD-WB-21 — execute after approved token (legacy sandbox_execute alias OK)."""
    from dataruns.writebacks.service import writeback_run

    return writeback_run(
        company=company,
        check_id=check_id,
        mode="execute",
        expected_diff_hash=diff_hash,
        approval_id=str(approval_id),
        max_rows=max_rows,
        actor=actor,
    )


def run_sandbox_rollback(*, company: Company, job_id: str, actor) -> dict[str, Any]:
    """PRD-WB-21 — rollback execute job."""
    from dataruns.writebacks.service import writeback_rollback_job

    return writeback_rollback_job(company=company, job_id=str(job_id), actor=actor)


def assert_tier_b_plan_only_blocks_execute(
    test_case,
    *,
    company: Company,
    check_id: str,
    actor,
    expected_blocked_reason: str,
    intents: list | None = None,
    require_preview_ready: bool = False,
    max_rows: int = 50,
) -> dict[str, Any]:
    """PRD-WB-21 §2.2 — plan_only: preview OK; execute blocked; no mutate."""
    from dataruns.writebacks.service import writeback_run

    with writeback_execute_company(company):
        preview = writeback_run(
            company=company,
            check_id=check_id,
            mode="dry_run",
            max_rows=max_rows,
            actor=actor,
            intents=intents,
        )
        test_case.assertIsNone(
            preview.blocked_reason,
            f"{check_id}: preview must not be blocked ({preview.blocked_reason})",
        )
        if require_preview_ready:
            test_case.assertGreaterEqual(
                preview.summary.ready,
                1,
                f"{check_id}: preview ready must be >= 1",
            )

        # plan_only hard-stops before approval/allowlist mutate (WB-16/17/18).
        blocked = writeback_run(
            company=company,
            check_id=check_id,
            mode="execute",
            max_rows=max_rows,
            actor=actor,
            intents=intents,
            expected_diff_hash=preview.diff_hash,
            approval_id="plan-only-probe",
        )
        test_case.assertEqual(
            blocked.blocked_reason,
            expected_blocked_reason,
            f"{check_id}: expected {expected_blocked_reason}, got {blocked.blocked_reason}",
        )
        test_case.assertEqual(
            blocked.summary.executed,
            0,
            f"{check_id}: plan_only must not execute rows",
        )

    return {"preview": preview, "execute": blocked}


def assert_tier_c_execute_blocked(
    test_case,
    *,
    company: Company,
    check_id: str,
    actor,
    intents: list | None = None,
    allowed_blocked_reasons: set[str] | None = None,
    max_rows: int = 50,
) -> dict[str, Any]:
    """PRD-WB-21 §2.3 — preview OK; execute must not write (capability/allowlist)."""
    from dataruns.writebacks.service import writeback_run

    reasons = allowed_blocked_reasons or {
        "check_not_allowlisted",
        "capability_not_confirmed",
        "writebacks_disabled",
        "approval_id_required",
    }

    with writeback_execute_company(company):
        preview = writeback_run(
            company=company,
            check_id=check_id,
            mode="dry_run",
            max_rows=max_rows,
            actor=actor,
            intents=intents,
        )
        test_case.assertIsNone(preview.blocked_reason, preview.blocked_reason)
        test_case.assertGreaterEqual(
            preview.summary.ready,
            1,
            f"{check_id}: preview ready must be >= 1 for Tier C",
        )

        token = issue_approved_writeback_token(
            company=company,
            job_id=preview.job_id,
            requester=actor,
            approver=actor,
        )
        blocked = writeback_run(
            company=company,
            check_id=check_id,
            mode="execute",
            max_rows=max_rows,
            actor=actor,
            intents=intents,
            expected_diff_hash=preview.diff_hash,
            approval_id=str(token.id),
        )
        # Prefer explicit blocked_reason; else require zero executed writes.
        if blocked.blocked_reason:
            test_case.assertIn(
                blocked.blocked_reason,
                reasons,
                f"{check_id}: unexpected blocked_reason={blocked.blocked_reason}",
            )
        test_case.assertEqual(
            blocked.summary.executed,
            0,
            f"{check_id}: Tier C must not execute (got {blocked.summary.executed})",
        )

    return {"preview": preview, "execute": blocked}


def assert_tier_d_mapping_disabled(test_case, *, check_id: str) -> None:
    """PRD-WB-21 §2.4 — disabled registry mapping; no execute claim."""
    from dataruns.writebacks.registry import MappingDisabled, get_check_mapping, list_mapping_entries

    entries = {row["check_id"]: row for row in list_mapping_entries()}
    test_case.assertIn(check_id, entries)
    test_case.assertFalse(
        entries[check_id].get("enabled"),
        f"{check_id}: registry must be disabled",
    )
    with test_case.assertRaises(MappingDisabled):
        get_check_mapping(check_id)


def assert_tier_a_sandbox_pass(
    test_case,
    *,
    company: Company,
    check_id: str,
    actor,
    max_rows: int = 1,
    intents: list | None = None,
    expect_rollback: bool = True,
    expect_irreversible: bool | None = None,
    expect_rollback_supported: bool | None = None,
) -> dict[str, Any]:
    """
    PRD-WB-21 §2.1 — Tier A sandbox pass on current gates.

    Caller must: seed allowlist + evidence (or pass ready ``intents``),
    and patch connector transports before calling.
    """
    from dataruns.writebacks.serializers import execute_rollback_supported
    from dataruns.writebacks.service import writeback_run

    with writeback_execute_company(company):
        preview = writeback_run(
            company=company,
            check_id=check_id,
            mode="dry_run",
            max_rows=max_rows,
            actor=actor,
            intents=intents,
        )
        test_case.assertIsNone(preview.blocked_reason, preview.blocked_reason)
        test_case.assertGreaterEqual(
            preview.summary.ready,
            1,
            f"{check_id}: preview ready must be >= 1 (got {preview.summary.ready})",
        )
        test_case.assertTrue(preview.job_id)
        test_case.assertTrue(preview.diff_hash)
        test_case.assertTrue(
            preview.execute_eligible.sandbox
            or getattr(preview.execute_eligible, "company", False),
            f"{check_id}: execute_eligible.company/sandbox must be True when Allow writebacks ON",
        )

        token = issue_approved_writeback_token(
            company=company,
            job_id=preview.job_id,
            requester=actor,
            approver=actor,
        )
        executed = writeback_run(
            company=company,
            check_id=check_id,
            mode="execute",
            expected_diff_hash=preview.diff_hash,
            approval_id=str(token.id),
            max_rows=max_rows,
            actor=actor,
            intents=intents,
        )
        test_case.assertIsNone(executed.blocked_reason, executed.blocked_reason)
        test_case.assertEqual(executed.mode, "execute")
        test_case.assertGreaterEqual(
            executed.summary.executed,
            1,
            f"{check_id}: executed must be >= 1 (got {executed.summary.executed})",
        )
        test_case.assertTrue(executed.job_id)
        if expect_irreversible is not None:
            test_case.assertEqual(
                bool(executed.irreversible),
                expect_irreversible,
                f"{check_id}: irreversible={executed.irreversible}",
            )
        if expect_rollback_supported is not None:
            test_case.assertEqual(
                execute_rollback_supported(executed),
                expect_rollback_supported,
                f"{check_id}: rollback.supported mismatch",
            )

        rollback_result: dict[str, Any] | None = None
        if expect_rollback:
            rollback_result = run_sandbox_rollback(
                company=company,
                job_id=executed.job_id,
                actor=actor,
            )
            test_case.assertIn(
                rollback_result.get("status"),
                {"rolled_back", "rollback_partial"},
                rollback_result,
            )
            test_case.assertGreaterEqual(
                int(rollback_result.get("rolled_back") or 0),
                1,
                rollback_result,
            )

    return {
        "preview": preview,
        "execute": executed,
        "rollback": rollback_result,
    }
