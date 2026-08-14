"""Compose and persist assessment reports (PRD-RPT-01 Phase A)."""

from __future__ import annotations

import uuid
from typing import Any

from django.db import transaction

from dataruns.audit import append_audit_event
from dataruns.dcs.worklist import build_enriched_issues, load_check_master_by_id
from dataruns.models import AssessmentReport
from dataruns.orchestration.candidates import build_fix_tasks_for_data_run
from dataruns.reports.constants import TEMPLATE_VERSION
from dataruns.reports.payload import build_report_payload
from dataruns.reports.resolve import (
    RunResolutionError,
    resolve_architecture_assessment_for_run,
    resolve_compose_window,
    resolve_dcs_run_for_compose,
)
from tenants.models import Company, User


class ComposeReportError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"false", "0", "no", "off"}:
            return False
        if token in {"true", "1", "yes", "on"}:
            return True
        return default
    return bool(value)


def _has_explicit_window(
    *,
    period: dict[str, Any] | None,
    since_raw: str | None,
    until_raw: str | None,
) -> bool:
    if since_raw or until_raw:
        return True
    if isinstance(period, dict) and (period.get("from") or period.get("to")):
        return True
    return False


@transaction.atomic
def compose_assessment_report(
    *,
    company: Company,
    user: User,
    body: dict[str, Any],
) -> AssessmentReport:
    period = body.get("period") if isinstance(body.get("period"), dict) else None
    since_raw = body.get("since") if isinstance(body.get("since"), str) else None
    until_raw = body.get("until") if isinstance(body.get("until"), str) else None
    include_architecture = _as_bool(body.get("include_architecture"), default=True)
    include_plan = _as_bool(body.get("include_plan"), default=True)
    dcs_run_id = body.get("dcs_run_id")

    try:
        data_run = resolve_dcs_run_for_compose(
            company=company,
            dcs_run_id=dcs_run_id,
            period=period,
            since_raw=since_raw,
            until_raw=until_raw,
        )
        since = until = period_from = period_to = None
        period_from_label = period_to_label = None
        if _has_explicit_window(
            period=period,
            since_raw=since_raw,
            until_raw=until_raw,
        ):
            since, until, period_from, period_to = resolve_compose_window(
                period=period,
                since_raw=since_raw,
                until_raw=until_raw,
            )
            period_from_label = period_from.isoformat()
            period_to_label = period_to.isoformat()
    except RunResolutionError as exc:
        status = 404 if exc.code == "not_found" else 422
        raise ComposeReportError(
            code=exc.code,
            message=exc.message,
            status_code=status,
        ) from exc

    architecture = None
    if include_architecture:
        architecture = resolve_architecture_assessment_for_run(
            company=company,
            dcs_run=data_run,
        )

    plan_tasks: list[dict[str, Any]] = []
    if include_plan:
        plan_tasks = build_fix_tasks_for_data_run(
            company=company,
            data_run=data_run,
        )

    open_issues = build_enriched_issues(
        data_run=data_run,
        check_master_by_id=load_check_master_by_id(),
        cap=None,
    )

    report_id = uuid.uuid4()
    payload = build_report_payload(
        report_id=report_id,
        company=company,
        dcs_run=data_run,
        architecture_assessment=architecture,
        open_issues=open_issues,
        plan_tasks=plan_tasks,
        created_by_email=user.email,
        include_architecture=include_architecture,
        include_plan=include_plan,
        period_from=period_from_label,
        period_to=period_to_label,
    )

    report = AssessmentReport.objects.create(
        id=report_id,
        company=company,
        variant=AssessmentReport.Variant.PAID_FULL,
        status=AssessmentReport.Status.READY,
        dcs_data_run=data_run,
        architecture_assessment=architecture,
        period_from=period_from,
        period_to=period_to,
        window_since=since,
        window_until=until,
        payload=payload,
        payload_hash=payload["payload_hash"],
        template_version=TEMPLATE_VERSION,
        created_by=user,
    )

    append_audit_event(
        company=company,
        action="report.composed",
        summary="Assessment report composed",
        performed_by=user.email,
        actor_user_id=str(user.id),
        metadata={
            "report_id": str(report.id),
            "payload_hash": report.payload_hash,
            "dcs_run_id": data_run.id,
        },
    )
    return report


def serialize_report_metadata(report: AssessmentReport) -> dict[str, Any]:
    return {
        "report_id": str(report.id),
        "status": report.status,
        "variant": report.variant,
        "payload_hash": report.payload_hash,
        "template_version": report.template_version,
        "dcs_run_id": report.dcs_data_run_id,
        "af_assessment_id": (
            str(report.architecture_assessment_id)
            if report.architecture_assessment_id
            else None
        ),
        "period": {
            "from": report.period_from.isoformat() if report.period_from else None,
            "to": report.period_to.isoformat() if report.period_to else None,
        },
        "window": {
            "since": (
                report.window_since.isoformat().replace("+00:00", "Z")
                if report.window_since
                else None
            ),
            "until": (
                report.window_until.isoformat().replace("+00:00", "Z")
                if report.window_until
                else None
            ),
        },
        "created_at": report.created_at.isoformat().replace("+00:00", "Z"),
        "created_by": report.created_by.email if report.created_by else None,
    }
