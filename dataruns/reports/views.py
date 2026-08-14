"""Assessment report HTTP API (PRD-RPT-01)."""

from __future__ import annotations

import logging
import re

from django.http import HttpResponse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.audit import append_audit_event
from dataruns.models import AssessmentReport
from dataruns.reports.compose import (
    ComposeReportError,
    compose_assessment_report,
    serialize_report_metadata,
)
from dataruns.reports.ip import extract_client_ip
from dataruns.reports.render_pdf import render_assessment_pdf
from tenants.auth.services import get_user_company
from tenants.models import User

logger = logging.getLogger(__name__)

_REPORT_WRITE_ROLES = (User.Role.ADMIN, User.Role.ANALYST)
_REPORT_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)
_REPORT_DOWNLOAD_ROLES = (User.Role.ADMIN, User.Role.ANALYST)
_USER_AGENT_MAX = 256
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _company_or_error(request, *, allowed_roles):
    if request.user.role not in allowed_roles:
        return None, Response(
            {"detail": "You do not have permission to access assessment reports."},
            status=403,
        )
    company = get_user_company(request.user)
    if company is None:
        return None, Response(
            {"detail": "No company is associated with this account."},
            status=400,
        )
    return company, None


def _load_report(*, company, report_id) -> AssessmentReport | None:
    return (
        AssessmentReport.objects.select_related("company", "company__tenant")
        .filter(pk=report_id, company=company)
        .first()
    )


def _safe_filename_slug(value: str) -> str:
    token = _SLUG_RE.sub("-", (value or "").lower()).strip("-")
    return token or "company"


def _pdf_filename(report: AssessmentReport) -> str:
    slug = _safe_filename_slug(report.company.tenant.slug or report.company.domain)
    day = report.created_at.date().isoformat() if report.created_at else "report"
    return f"klints-assessment-{slug}-{day}.pdf"


def _download_audit_metadata(request, report: AssessmentReport, *, extra: dict | None = None) -> dict:
    ip_address, ip_resolution = extract_client_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT") or ""
    if not isinstance(user_agent, str):
        user_agent = str(user_agent)
    metadata = {
        "report_id": str(report.id),
        "payload_hash": report.payload_hash,
        "email": request.user.email,
        "ip_address": ip_address,
        "ip_resolution": ip_resolution,
        "user_agent": user_agent[:_USER_AGENT_MAX],
        "downloaded_at": timezone.now().isoformat().replace("+00:00", "Z"),
    }
    if extra:
        metadata.update(extra)
    return metadata


class AssessmentReportListCreateView(APIView):
    """GET list metadata · POST compose."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        company, error = _company_or_error(request, allowed_roles=_REPORT_READ_ROLES)
        if error is not None:
            return error
        reports = AssessmentReport.objects.filter(company=company).order_by(
            "-created_at"
        )
        total = reports.count()
        page = list(reports[:20])
        return Response(
            {
                "results": [serialize_report_metadata(row) for row in page],
                "count": total,
            }
        )

    def post(self, request):
        company, error = _company_or_error(request, allowed_roles=_REPORT_WRITE_ROLES)
        if error is not None:
            return error
        body = request.data if isinstance(request.data, dict) else {}
        try:
            report = compose_assessment_report(
                company=company,
                user=request.user,
                body=body,
            )
        except ComposeReportError as exc:
            return Response(
                {"detail": exc.message, "code": exc.code},
                status=exc.status_code,
            )
        metadata = serialize_report_metadata(report)
        return Response(
            {
                **metadata,
                "payload_hash": report.payload_hash,
            },
            status=201,
        )


class AssessmentReportDetailView(APIView):
    """GET report metadata (+ stored payload for render)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, report_id):
        company, error = _company_or_error(request, allowed_roles=_REPORT_READ_ROLES)
        if error is not None:
            return error
        report = _load_report(company=company, report_id=report_id)
        if report is None:
            return Response({"detail": "Not found."}, status=404)
        return Response(
            {
                **serialize_report_metadata(report),
                "payload": report.payload,
            }
        )


class AssessmentReportPdfView(APIView):
    """GET PDF stream from stored payload; audit download (PRD-RPT-01 §4–§5)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, report_id):
        company, error = _company_or_error(request, allowed_roles=_REPORT_DOWNLOAD_ROLES)
        if error is not None:
            return error
        report = _load_report(company=company, report_id=report_id)
        if report is None:
            return Response({"detail": "Not found."}, status=404)
        payload = report.payload if isinstance(report.payload, dict) else None
        content = payload.get("content") if payload else None
        if (
            report.status != AssessmentReport.Status.READY
            or not isinstance(content, dict)
            or not content
        ):
            return Response(
                {"detail": "Report is not ready to render.", "code": "not_ready"},
                status=409,
            )

        try:
            pdf_bytes = render_assessment_pdf(report.payload)
        except Exception:
            logger.exception("Assessment PDF render failed report_id=%s", report.id)
            append_audit_event(
                company=company,
                action="report.download_failed",
                summary="Assessment report PDF download failed",
                performed_by=request.user.email,
                actor_user_id=str(request.user.id),
                metadata=_download_audit_metadata(
                    request,
                    report,
                    extra={"error_code": "render_failed"},
                ),
            )
            return Response(
                {"detail": "Could not render the assessment PDF.", "code": "render_failed"},
                status=500,
            )

        append_audit_event(
            company=company,
            action="report.downloaded",
            summary="Assessment report PDF downloaded",
            performed_by=request.user.email,
            actor_user_id=str(request.user.id),
            metadata=_download_audit_metadata(request, report),
        )
        filename = _pdf_filename(report)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Content-Length"] = str(len(pdf_bytes))
        return response
