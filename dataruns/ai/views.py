"""AI suggestion APIs (PRD-AI-01 §9)."""

from __future__ import annotations

import logging

from django.db.utils import OperationalError, ProgrammingError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.ai.exceptions import (
    AiDisabledError,
    AiGateDeniedError,
    AiJsonRetryExhaustedError,
    AiNotFoundError,
    AiProviderError,
)
from dataruns.ai.runner import serialize_ai_result
from dataruns.ai.service import (
    attach_narratives_to_report,
    get_or_create_explain_finding,
    get_or_create_fix_suggestion,
    get_or_create_nba_blurb,
    get_or_create_report_narrative,
    serialize_fix_suggestion_result,
)
from dataruns.models import AssessmentReport
from tenants.auth.services import get_user_company
from tenants.models import User

_AI_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)
logger = logging.getLogger(__name__)


def _company_or_error(request):
    if request.user.role not in _AI_READ_ROLES:
        return None, Response(
            {"detail": "You do not have permission to view AI suggestions."},
            status=403,
        )
    company = get_user_company(request.user)
    if company is None:
        return None, Response(
            {"detail": "No company is associated with this account."},
            status=400,
        )
    return company, None


def _parse_check_id(body: dict) -> tuple[str | None, Response | None]:
    check_id_raw = body.get("check_id")
    if isinstance(check_id_raw, str):
        check_id = check_id_raw.strip()
    elif check_id_raw is not None:
        check_id = str(check_id_raw).strip()
    else:
        check_id = ""
    if not check_id:
        return None, Response({"detail": "check_id is required."}, status=400)
    return check_id, None


def _parse_optional_int(body: dict, key: str) -> tuple[int | None, Response | None]:
    raw = body.get(key)
    if raw is None or raw == "":
        return None, None
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, Response({"detail": f"{key} must be an integer."}, status=400)


def _ai_exception_response(exc) -> Response:
    if isinstance(exc, AiNotFoundError):
        return Response({"detail": exc.message, "code": exc.code}, status=404)
    if isinstance(exc, AiGateDeniedError):
        return Response(
            {"detail": exc.message, "code": exc.code, "reason": exc.reason},
            status=422,
        )
    if isinstance(exc, (AiDisabledError, AiJsonRetryExhaustedError, AiProviderError)):
        return Response({"detail": exc.message, "code": exc.code}, status=503)
    raise exc


class FixSuggestionView(APIView):
    """POST /api/v1/ai/suggestions/fix/ — get or create Fix AI suggestion."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        company, error = _company_or_error(request)
        if error is not None:
            return error

        body = request.data if isinstance(request.data, dict) else {}
        check_id, error = _parse_check_id(body)
        if error is not None:
            return error
        dcs_run_id, error = _parse_optional_int(body, "dcs_run_id")
        if error is not None:
            return error

        try:
            result = get_or_create_fix_suggestion(
                company=company,
                check_id=check_id,
                dcs_run_id=dcs_run_id,
            )
        except (
            AiNotFoundError,
            AiGateDeniedError,
            AiDisabledError,
            AiJsonRetryExhaustedError,
            AiProviderError,
        ) as exc:
            return _ai_exception_response(exc)
        except (ProgrammingError, OperationalError):
            logger.exception("ai_fix_suggestion_db_error")
            return Response(
                {"detail": "AI suggestion unavailable.", "code": "ai_unavailable"},
                status=503,
            )

        return Response(serialize_fix_suggestion_result(result), status=200)


class ExplainFindingView(APIView):
    """POST /api/v1/ai/suggestions/explain/ — Diagnose drawer explanation."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        company, error = _company_or_error(request)
        if error is not None:
            return error

        body = request.data if isinstance(request.data, dict) else {}
        check_id, error = _parse_check_id(body)
        if error is not None:
            return error
        dcs_run_id, error = _parse_optional_int(body, "dcs_run_id")
        if error is not None:
            return error

        try:
            result = get_or_create_explain_finding(
                company=company,
                check_id=check_id,
                dcs_run_id=dcs_run_id,
            )
        except (
            AiNotFoundError,
            AiGateDeniedError,
            AiDisabledError,
            AiJsonRetryExhaustedError,
            AiProviderError,
        ) as exc:
            return _ai_exception_response(exc)
        except (ProgrammingError, OperationalError):
            logger.exception("ai_explain_finding_db_error")
            return Response(
                {"detail": "AI suggestion unavailable.", "code": "ai_unavailable"},
                status=503,
            )

        return Response(serialize_ai_result(result), status=200)


class NbaBlurbView(APIView):
    """POST /api/v1/ai/suggestions/nba/ — Overview next-best-action one-liner."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        company, error = _company_or_error(request)
        if error is not None:
            return error

        body = request.data if isinstance(request.data, dict) else {}
        check_id, error = _parse_check_id(body)
        if error is not None:
            return error
        dcs_run_id, error = _parse_optional_int(body, "dcs_run_id")
        if error is not None:
            return error
        plan_rank, error = _parse_optional_int(body, "plan_rank")
        if error is not None:
            return error
        if plan_rank is not None and plan_rank < 1:
            return Response({"detail": "plan_rank must be a positive integer."}, status=400)

        try:
            result = get_or_create_nba_blurb(
                company=company,
                check_id=check_id,
                dcs_run_id=dcs_run_id,
                plan_rank=plan_rank,
            )
        except (
            AiNotFoundError,
            AiGateDeniedError,
            AiDisabledError,
            AiJsonRetryExhaustedError,
            AiProviderError,
        ) as exc:
            return _ai_exception_response(exc)
        except (ProgrammingError, OperationalError):
            logger.exception("ai_nba_blurb_db_error")
            return Response(
                {"detail": "AI suggestion unavailable.", "code": "ai_unavailable"},
                status=503,
            )

        return Response(serialize_ai_result(result), status=200)


class ReportNarrativeView(APIView):
    """POST /api/v1/ai/narratives/report/ — assessment exec summary."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        company, error = _company_or_error(request)
        if error is not None:
            return error

        body = request.data if isinstance(request.data, dict) else {}
        dcs_run_id, error = _parse_optional_int(body, "dcs_run_id")
        if error is not None:
            return error

        report = None
        assessment_report_id = body.get("assessment_report_id")
        if assessment_report_id not in (None, ""):
            report = (
                AssessmentReport.objects.filter(
                    pk=assessment_report_id,
                    company=company,
                )
                .select_related("company")
                .first()
            )
            if report is None:
                return Response(
                    {"detail": "Assessment report not found.", "code": "not_found"},
                    status=404,
                )
            if dcs_run_id is None:
                dcs_run_id = report.dcs_data_run_id

        try:
            result = get_or_create_report_narrative(
                company=company,
                dcs_run_id=dcs_run_id,
            )
            if report is not None:
                attach_narratives_to_report(report, result)
        except (
            AiNotFoundError,
            AiGateDeniedError,
            AiDisabledError,
            AiJsonRetryExhaustedError,
            AiProviderError,
        ) as exc:
            return _ai_exception_response(exc)
        except (ProgrammingError, OperationalError):
            logger.exception("ai_report_narrative_db_error")
            return Response(
                {"detail": "AI suggestion unavailable.", "code": "ai_unavailable"},
                status=503,
            )

        return Response(serialize_ai_result(result), status=200)
