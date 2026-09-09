"""Shared DCS score enqueue helper (PRD-DCS-01 / PRD-DCS-07)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone

from dataruns.connectors.base import find_latest_bootstrap_data_run, get_connector
from dataruns.dcs.constants import DCS_SCORE_KIND, DCS_SCORING_MODEL_VERSION
from dataruns.models import DataRun, Run
from tenants.models import Company, Connector

# Re-exported for Beat tests / dispatch task (PRD-DCS-07).
DCS_SCORE_DATA_RUN_NAME = "dcs-score"
DAILY_BEAT_TRIGGER = "daily_beat"
ELIGIBLE_CONNECTOR_NAMES = ("shopify", "manago_ai")
ELIGIBLE_CONNECTOR_STATUSES = ("connected", "degraded")
IST = ZoneInfo("Asia/Kolkata")


class DcsAlreadyRunningError(RuntimeError):
    """Raised when a DCS score DataRun is already pending/running for the company."""


class DcsQueueUnavailableError(RuntimeError):
    """Raised when Celery/Redis cannot accept the DCS score task."""


# PENDING (never picked up by a worker) — Celery off but Redis up queues forever.
DCS_PENDING_STALE_AFTER = timedelta(seconds=90)
# Manual re-run: fail orphaned PENDING faster so Re-run is not blocked by 409.
DCS_MANUAL_PENDING_RETRY_AFTER = timedelta(seconds=30)
# RUNNING (worker started) — longer safety net so real scores aren't killed early.
DCS_RUNNING_STALE_AFTER = timedelta(minutes=45)
# Back-compat alias used by FE docs / imports (pending budget).
DCS_ACTIVE_STALE_AFTER = DCS_PENDING_STALE_AFTER


@dataclass(frozen=True)
class DcsEnqueueResult:
    data_run: DataRun | None
    task_queued: bool
    domain_run: Run | None = None
    skipped: bool = False
    skip_reason: str | None = None


def celery_workers_available(*, timeout: float = 1.0) -> bool:
    """
    Return True when at least one Celery worker responds to inspect ping.

    Redis may accept tasks while no worker consumes them — this catches that case.
    """
    from django.conf import settings

    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return True

    try:
        from core.celery import app

        ping = app.control.inspect(timeout=timeout).ping()
    except Exception:  # noqa: BLE001 — broker/inspect failures vary
        return False
    return bool(ping)


def find_active_dcs_data_run(*, company: Company) -> DataRun | None:
    return (
        DataRun.objects.filter(
            tenant=company.tenant,
            status__in=[DataRun.Status.PENDING, DataRun.Status.RUNNING],
            metadata__kind=DCS_SCORE_KIND,
            metadata__company_id=str(company.id),
        )
        .order_by("-created_at")
        .first()
    )


def _mark_dcs_runs_failed(
    *,
    data_run: DataRun,
    domain_run: Run | None,
    error: str,
) -> None:
    """Mark orphaned enqueue/worker runs failed so status unlocks."""
    meta = dict(data_run.metadata or {})
    meta["error"] = error
    data_run.status = DataRun.Status.FAILED
    data_run.finished_at = timezone.now()
    data_run.metadata = meta
    data_run.save(update_fields=["status", "finished_at", "metadata"])
    if domain_run is not None and domain_run.status == Run.Status.RUNNING:
        domain_run.status = Run.Status.COMPLETED
        domain_run.completed_at = timezone.now()
        domain_run.save(update_fields=["status", "completed_at"])


def fail_stale_active_dcs_runs(
    *,
    company: Company,
    older_than: timedelta | None = None,
) -> DataRun | None:
    """
    If an active DCS DataRun is older than its status-specific budget, mark failed.

    - PENDING: default 90s (queue never consumed — Celery off)
    - RUNNING: default 45m (worker hung)

    Returns the failed run when one was stale, else None.
    """
    active = find_active_dcs_data_run(company=company)
    if active is None:
        return None
    started = getattr(active, "started_at", None) or getattr(active, "created_at", None)
    if started is None:
        return None
    if timezone.is_naive(started):
        started = timezone.make_aware(started, timezone.get_current_timezone())

    if older_than is not None:
        limit = older_than
    elif active.status == DataRun.Status.PENDING:
        limit = DCS_PENDING_STALE_AFTER
    else:
        limit = DCS_RUNNING_STALE_AFTER

    if timezone.now() - started < limit:
        return None

    domain_run = None
    run_id = (active.metadata or {}).get("run_id")
    if run_id:
        domain_run = Run.objects.filter(pk=run_id, company=company).first()

    if active.status == DataRun.Status.PENDING:
        error = (
            "DCS score run timed out waiting for a worker. "
            "Start Redis and Celery, then re-run checks."
        )
    else:
        error = (
            "DCS score run timed out while running. "
            "Check Celery workers and re-run checks."
        )

    _mark_dcs_runs_failed(
        data_run=active,
        domain_run=domain_run,
        error=error,
    )
    return active


def fail_stale_pending_for_manual_retry(*, company: Company) -> DataRun | None:
    """Fail a PENDING run older than the manual retry budget (Re-run button)."""
    active = find_active_dcs_data_run(company=company)
    if active is None or active.status != DataRun.Status.PENDING:
        return None
    return fail_stale_active_dcs_runs(
        company=company,
        older_than=DCS_MANUAL_PENDING_RETRY_AFTER,
    )


def company_has_eligible_connector(company: Company) -> bool:
    """Return True when the company has a connected or degraded Shopify/Manago connector."""
    return Connector.objects.filter(
        company=company,
        name__in=ELIGIBLE_CONNECTOR_NAMES,
        status__in=ELIGIBLE_CONNECTOR_STATUSES,
    ).exists()


def company_has_both_commerce_connectors(company: Company) -> bool:
    """True when both Shopify and Manago are connected or degraded."""
    names = set(
        Connector.objects.filter(
            company=company,
            name__in=ELIGIBLE_CONNECTOR_NAMES,
            status__in=ELIGIBLE_CONNECTOR_STATUSES,
        ).values_list("name", flat=True)
    )
    return set(ELIGIBLE_CONNECTOR_NAMES).issubset(names)


def both_platforms_have_succeeded_bootstrap(company: Company) -> bool:
    """True when each commerce platform has a latest succeeded bootstrap DataRun."""
    for platform in ELIGIBLE_CONNECTOR_NAMES:
        try:
            connector = get_connector(company=company, platform=platform)
        except Connector.DoesNotExist:
            return False
        if connector.status not in ELIGIBLE_CONNECTOR_STATUSES:
            return False
        bootstrap = find_latest_bootstrap_data_run(
            company=company,
            connector=connector,
        )
        if bootstrap is None or bootstrap.status != DataRun.Status.SUCCEEDED:
            return False
    return True


def maybe_enqueue_dcs_after_bootstrap(company: Company) -> DcsEnqueueResult | None:
    """
    After a bootstrap succeeds: if both Shopify + Manago are ready, enqueue DCS.

    Returns None when the company is not yet dual-connected / dual-bootstrapped.
    """
    if not company_has_both_commerce_connectors(company):
        return None
    if not both_platforms_have_succeeded_bootstrap(company):
        return None

    from tenants.manago_topology_service import ensure_manago_primary_owner

    ensure_manago_primary_owner(company, allow_multi_owner_inference=True)

    try:
        return enqueue_dcs_score(
            company,
            triggered_by="post_bootstrap",
            queue=True,
        )
    except DcsAlreadyRunningError:
        return DcsEnqueueResult(
            data_run=None,
            task_queued=False,
            skipped=True,
            skip_reason="already_running",
        )
    except DcsQueueUnavailableError:
        return DcsEnqueueResult(
            data_run=None,
            task_queued=False,
            skipped=True,
            skip_reason="queue_unavailable",
        )


def find_eligible_companies():
    """Companies with at least one eligible connector (PRD-DCS-07 §4)."""
    return (
        Company.objects.filter(
            connectors__name__in=ELIGIBLE_CONNECTOR_NAMES,
            connectors__status__in=ELIGIBLE_CONNECTOR_STATUSES,
        )
        .distinct()
        .order_by("created_at")
    )


def resolve_source_runs(company: Company) -> dict[str, str | None]:
    """Latest succeeded bootstrap import Run id per connected platform."""
    source_runs: dict[str, str | None] = {
        "shopify": None,
        "manago_ai": None,
    }
    for platform in ELIGIBLE_CONNECTOR_NAMES:
        try:
            connector = get_connector(company=company, platform=platform)
        except Connector.DoesNotExist:
            continue
        if connector.status not in ELIGIBLE_CONNECTOR_STATUSES:
            continue
        bootstrap = find_latest_bootstrap_data_run(
            company=company,
            connector=connector,
        )
        if bootstrap is None or bootstrap.status != DataRun.Status.SUCCEEDED:
            continue
        run_id = (bootstrap.metadata or {}).get("run_id")
        if isinstance(run_id, str) and run_id:
            source_runs[platform] = run_id
    return source_runs


def _ist_day_bounds(*, moment: datetime | None = None) -> tuple[datetime, datetime]:
    current = (moment or timezone.now()).astimezone(IST)
    start_ist = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end_ist = start_ist + timedelta(days=1)
    return (
        start_ist.astimezone(dt_timezone.utc),
        end_ist.astimezone(dt_timezone.utc),
    )


def has_daily_dcs_run_today(company: Company, *, moment: datetime | None = None) -> bool:
    """
    Return True when a daily-beat DCS run already exists for this company today (IST).

    PRD-DCS-07 §4 idempotency: pending, running, or succeeded counts; failed may retry.
    """
    start_utc, end_utc = _ist_day_bounds(moment=moment)
    return DataRun.objects.filter(
        name=DCS_SCORE_DATA_RUN_NAME,
        metadata__kind=DCS_SCORE_KIND,
        metadata__triggered_by=DAILY_BEAT_TRIGGER,
        metadata__company_id=str(company.id),
        status__in=[
            DataRun.Status.PENDING,
            DataRun.Status.RUNNING,
            DataRun.Status.SUCCEEDED,
        ],
        created_at__gte=start_utc,
        created_at__lt=end_utc,
    ).exists()


def build_dcs_score_metadata(
    *,
    company: Company,
    triggered_by: str,
    erp_in_scope: bool = False,
    actor_user_id: str | None = None,
    source_runs: dict[str, str | None] | None = None,
    live_revalidate: bool = False,
    domain_run_id: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "kind": DCS_SCORE_KIND,
        "scoring_model_version": DCS_SCORING_MODEL_VERSION,
        "erp_in_scope": bool(erp_in_scope),
        "triggered_by": triggered_by,
        "company_id": str(company.id),
        "source_runs": source_runs
        if source_runs is not None
        else resolve_source_runs(company),
        "live_revalidate": bool(live_revalidate),
    }
    if domain_run_id:
        metadata["run_id"] = domain_run_id
    if actor_user_id:
        metadata["actor_user_id"] = actor_user_id
    return metadata


def enqueue_dcs_score(
    company: Company,
    *,
    triggered_by: str = "manual",
    erp_in_scope: bool = False,
    actor_user_id: str | None = None,
    source_runs: dict[str, str | None] | None = None,
    source_run_ids: dict[str, Any] | None = None,
    live_revalidate: bool = False,
    queue: bool = True,
) -> DcsEnqueueResult:
    """
    Create DCS DataRun + domain Run and optionally enqueue Celery task.

    Daily Beat idempotency applies only when ``triggered_by=daily_beat``.
    Raises DcsAlreadyRunningError if a score run is already active (PRD: 409).
    """
    if triggered_by == DAILY_BEAT_TRIGGER and has_daily_dcs_run_today(company):
        return DcsEnqueueResult(
            data_run=None,
            domain_run=None,
            task_queued=False,
            skipped=True,
            skip_reason="already_ran_today",
        )

    fail_stale_active_dcs_runs(company=company)
    if triggered_by == "manual":
        fail_stale_pending_for_manual_retry(company=company)

    if queue and not celery_workers_available():
        raise DcsQueueUnavailableError(
            "No Celery workers are running. Start the worker stack and retry."
        )

    existing = find_active_dcs_data_run(company=company)
    if existing is not None:
        raise DcsAlreadyRunningError(
            f"DCS score already {existing.status} for company {company.id}"
        )

    domain_run = Run.objects.create(
        company=company,
        run_type=Run.RunType.FULL,
        status=Run.Status.RUNNING,
        started_at=timezone.now(),
    )

    resolved_sources = source_runs
    if resolved_sources is None and source_run_ids is not None:
        resolved_sources = {
            "shopify": source_run_ids.get("shopify"),
            "manago_ai": source_run_ids.get("manago_ai"),
        }

    data_run = DataRun.objects.create(
        tenant=company.tenant,
        name=DCS_SCORE_DATA_RUN_NAME,
        status=DataRun.Status.PENDING,
        started_at=timezone.now(),
        metadata=build_dcs_score_metadata(
            company=company,
            triggered_by=triggered_by,
            erp_in_scope=erp_in_scope,
            actor_user_id=actor_user_id,
            source_runs=resolved_sources,
            live_revalidate=live_revalidate,
            domain_run_id=str(domain_run.id),
        ),
    )

    task_queued = False
    if queue:
        from dataruns.tasks import run_dcs_score

        try:
            run_dcs_score.delay(data_run.id)
        except Exception as exc:  # noqa: BLE001 — broker/Redis failures vary by client
            # Never leave PENDING orphans when the broker is unreachable.
            _mark_dcs_runs_failed(
                data_run=data_run,
                domain_run=domain_run,
                error=(
                    "Could not queue DCS score: scoring worker unavailable "
                    "(Redis/Celery). Start the worker stack and retry."
                ),
            )
            raise DcsQueueUnavailableError(
                "Scoring worker queue unavailable (Redis/Celery)."
            ) from exc
        task_queued = True

    return DcsEnqueueResult(
        data_run=data_run,
        domain_run=domain_run,
        task_queued=task_queued,
    )
