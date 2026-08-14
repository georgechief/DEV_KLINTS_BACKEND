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


@dataclass(frozen=True)
class DcsEnqueueResult:
    data_run: DataRun | None
    task_queued: bool
    domain_run: Run | None = None
    skipped: bool = False
    skip_reason: str | None = None


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

        run_dcs_score.delay(data_run.id)
        task_queued = True

    return DcsEnqueueResult(
        data_run=data_run,
        domain_run=domain_run,
        task_queued=task_queued,
    )
