"""Resolve DCS runs and AF assessments for report compose (PRD-RPT-01 §4.1)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone as dt_timezone
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.status import _company_dcs_runs_in_window
from dataruns.dcs.worklist import (
    TERMINAL_STATUSES,
    coerce_headline_score,
    extract_dcs_payload,
)
from dataruns.models import DataRun
from tenants.models import Company


class RunResolutionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _aware_datetime(value: datetime) -> datetime:
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone=dt_timezone.utc)
    return value


def _parse_period_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    if "T" in token:
        parsed_dt = parse_datetime(token)
        if parsed_dt is not None:
            return _aware_datetime(parsed_dt).date()
    return parse_date(token[:10])


def _parse_iso_datetime(value: Any, *, end_of_day: bool = False) -> datetime | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    parsed = parse_datetime(token)
    if parsed is not None:
        return _aware_datetime(parsed)
    parsed_date = parse_date(token[:10])
    if parsed_date is None:
        return None
    clock = time.max if end_of_day else time.min
    return timezone.make_aware(datetime.combine(parsed_date, clock), dt_timezone.utc)


def resolve_compose_window(
    *,
    period: dict[str, Any] | None = None,
    since_raw: str | None = None,
    until_raw: str | None = None,
) -> tuple[datetime, datetime, date, date]:
    """
    Resolve an explicit inclusive compose window.

    Prefers ISO since/until (Overview history alignment), else period.from/to.
    Does not invent a default lookback.
    """
    period_from = None
    period_to = None
    if isinstance(period, dict):
        raw_from = period.get("from")
        raw_to = period.get("to")
        if raw_from or raw_to:
            period_from = _parse_period_date(raw_from)
            period_to = _parse_period_date(raw_to)
            if period_from is None or period_to is None:
                raise RunResolutionError(
                    code="invalid_period",
                    message="period.from and period.to must be valid dates.",
                )
            if period_from > period_to:
                raise RunResolutionError(
                    code="invalid_period",
                    message="period.from must be on or before period.to.",
                )

    since = _parse_iso_datetime(since_raw, end_of_day=False) if since_raw else None
    until = _parse_iso_datetime(until_raw, end_of_day=True) if until_raw else None
    if since_raw and since is None:
        raise RunResolutionError(code="invalid_period", message="Invalid since timestamp.")
    if until_raw and until is None:
        raise RunResolutionError(code="invalid_period", message="Invalid until timestamp.")

    if since is not None and until is None and not until_raw:
        until = timezone.now()

    if since is None and until is None and period_from is not None and period_to is not None:
        since = timezone.make_aware(
            datetime.combine(period_from, time.min),
            timezone=dt_timezone.utc,
        )
        until = timezone.make_aware(
            datetime.combine(period_to, time.max),
            timezone=dt_timezone.utc,
        )

    if since is None or until is None:
        raise RunResolutionError(
            code="missing_period",
            message="Provide period.from/to or since/until.",
        )
    if since > until:
        raise RunResolutionError(
            code="invalid_period",
            message="since must be on or before until.",
        )

    if period_from is None:
        period_from = since.astimezone(dt_timezone.utc).date()
    if period_to is None:
        period_to = until.astimezone(dt_timezone.utc).date()
    return since, until, period_from, period_to


def resolve_dcs_run_for_compose(
    *,
    company: Company,
    dcs_run_id: int | None = None,
    period: dict[str, Any] | None = None,
    since_raw: str | None = None,
    until_raw: str | None = None,
) -> DataRun:
    """
    Resolve terminal scored DCS run for report compose.

    1. Explicit dcs_run_id (company-scoped)
    2. Latest succeeded run with headline score in [since, until]
    """
    if dcs_run_id is not None:
        try:
            run_id = int(dcs_run_id)
        except (TypeError, ValueError) as exc:
            raise RunResolutionError(
                code="invalid_run_id",
                message="Invalid dcs_run_id.",
            ) from exc
        data_run = DataRun.objects.filter(
            pk=run_id,
            tenant=company.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            metadata__kind=DCS_SCORE_KIND,
            metadata__company_id=str(company.id),
        ).first()
        if data_run is None:
            raise RunResolutionError(
                code="not_found",
                message="DCS run not found for this company.",
            )
        if data_run.status not in TERMINAL_STATUSES:
            raise RunResolutionError(
                code="invalid_run",
                message="DCS run is not in a terminal state.",
            )
        payload = extract_dcs_payload(data_run.metadata or {})
        if coerce_headline_score(payload.get("headline_score")) is None:
            raise RunResolutionError(
                code="not_scored",
                message="DCS run has no headline score.",
            )
        return data_run

    since, until, _period_from, _period_to = resolve_compose_window(
        period=period,
        since_raw=since_raw,
        until_raw=until_raw,
    )

    last_qualifying: DataRun | None = None
    for data_run in _company_dcs_runs_in_window(
        company=company,
        since=since,
        until=until,
    ):
        metadata = data_run.metadata if isinstance(data_run.metadata, dict) else {}
        payload = extract_dcs_payload(metadata)
        if coerce_headline_score(payload.get("headline_score")) is not None:
            last_qualifying = data_run

    if last_qualifying is None:
        raise RunResolutionError(
            code="no_run_in_period",
            message="No scored DCS run in selected period.",
        )
    return last_qualifying


def resolve_architecture_assessment_for_run(
    *,
    company: Company,
    dcs_run: DataRun,
) -> ArchitectureAssessment | None:
    """Prefer AF linked to the composed DCS run, else latest succeeded AF."""
    linked = (
        ArchitectureAssessment.objects.filter(
            company=company,
            source_dcs_data_run_id=dcs_run.id,
            status=ArchitectureAssessment.Status.SUCCEEDED,
        )
        .order_by("-created_at")
        .first()
    )
    if linked is not None:
        return linked
    return (
        ArchitectureAssessment.objects.filter(
            company=company,
            status=ArchitectureAssessment.Status.SUCCEEDED,
        )
        .order_by("-created_at")
        .first()
    )
