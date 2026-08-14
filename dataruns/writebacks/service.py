"""Writeback service entrypoint — HTTP, Celery, and tests call this (PRD-WB-01 §2.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from dataruns.writebacks.pipeline import run_writeback_pipeline
from dataruns.writebacks.rollback import writeback_rollback
from dataruns.writebacks.types import WriteIntent, WriteMode, WritebackResult

if TYPE_CHECKING:
    from tenants.models import Company, User


def writeback_run(
    *,
    company: "Company",
    check_id: str | None = None,
    intents: list[WriteIntent] | None = None,
    mode: WriteMode = "dry_run",
    batch_size: int | None = None,
    max_rows: int | None = None,
    approval_id: str | None = None,
    actor: "User | None" = None,
    expected_diff_hash: str | None = None,
) -> WritebackResult:
    if not check_id and not intents:
        raise ValueError("check_id or intents is required")

    effective_batch = batch_size or settings.WRITEBACK_DEFAULT_BATCH_SIZE
    return run_writeback_pipeline(
        company=company,
        check_id=check_id or (intents[0].check_id if intents else ""),
        mode=mode,
        batch_size=effective_batch,
        max_rows=max_rows,
        approval_id=approval_id,
        actor=actor,
        intents=intents,
        expected_diff_hash=expected_diff_hash,
    )


def writeback_rollback_job(
    *,
    company: "Company",
    job_id: str,
    actor: "User | None" = None,
) -> dict:
    return writeback_rollback(company=company, job_id=job_id, actor=actor)
