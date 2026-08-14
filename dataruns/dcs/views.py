from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.dcs.constants import DCS_SCORING_MODEL_VERSION
from dataruns.dcs.enqueue import (
    DcsAlreadyRunningError,
    company_has_eligible_connector,
    enqueue_dcs_score,
)
from dataruns.dcs.status import resolve_dcs_app_status_for_user
from dataruns.dcs.history import resolve_dcs_score_history_for_user
from dataruns.dcs.worklist import (
    WorklistDetailNotFound,
    build_worklist_detail,
    build_worklist_payload,
)
from tenants.auth.services import get_user_company
from tenants.models import User

_DCS_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)


class DcsStatusView(APIView):
    """GET /api/v1/dcs/status/ — app-gate status for the current company."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _DCS_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view DCS status."},
                status=403,
            )

        return Response(resolve_dcs_app_status_for_user(user=request.user))


class DcsRunsView(APIView):
    """POST /api/v1/dcs/runs/ — start a DCS score run (PRD-DCS-01 / DCS-06)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != User.Role.ADMIN:
            return Response(
                {"detail": "Only admins can start a Data Consistency Score run."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )

        # Match daily beat / enqueue: need a connected/degraded commerce
        # connector. Fresh import runs inside the DCS worker, so a prior
        # connector-bootstrap DataRun is not required for re-run.
        if not company_has_eligible_connector(company):
            return Response(
                {
                    "detail": (
                        "Connect Shopify or Manago.ai before running "
                        "a Data Consistency Score."
                    ),
                },
                status=422,
            )

        body = request.data if isinstance(request.data, dict) else {}
        erp_in_scope = bool(body.get("erp_in_scope", False))
        source_run_ids = body.get("source_run_ids")
        if source_run_ids is not None and not isinstance(source_run_ids, dict):
            return Response(
                {"detail": "source_run_ids must be an object when provided."},
                status=400,
            )

        try:
            result = enqueue_dcs_score(
                company=company,
                triggered_by="manual",
                erp_in_scope=erp_in_scope,
                actor_user_id=str(request.user.id),
                source_run_ids=source_run_ids,
                live_revalidate=True,
                queue=True,
            )
        except DcsAlreadyRunningError:
            return Response(
                {
                    "detail": (
                        "A Data Consistency Score run is already in progress "
                        "for this company."
                    ),
                },
                status=409,
            )

        data_run = result.data_run
        domain_run = result.domain_run
        if data_run is None:
            return Response(
                {"detail": "Could not start a Data Consistency Score run."},
                status=500,
            )

        return Response(
            {
                "data_run_id": data_run.id,
                "dcs_run_id": str(domain_run.id) if domain_run is not None else None,
                "status": data_run.status,
                "scoring_model_version": DCS_SCORING_MODEL_VERSION,
            },
            status=202,
        )


class DcsWorklistView(APIView):
    """GET /api/v1/dcs/worklist/ — FAIL+WARN worklist for latest terminal run."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _DCS_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view DCS worklist."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response(
                {
                    "data_run_id": None,
                    "domain_run_id": None,
                    "run_state": None,
                    "headline_score": None,
                    "business_impact": None,
                    "count": 0,
                    "issues": [],
                }
            )
        return Response(build_worklist_payload(company=company))


class DcsWorklistDetailView(APIView):
    """GET /api/v1/dcs/worklist/{check_id}/ — full evidence for one FAIL/WARN."""

    permission_classes = [IsAuthenticated]

    def get(self, request, check_id: str):
        if request.user.role not in _DCS_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view DCS worklist."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response({"detail": "Worklist issue not found."}, status=404)

        try:
            payload = build_worklist_detail(company=company, check_id=check_id)
        except WorklistDetailNotFound:
            return Response({"detail": "Worklist issue not found."}, status=404)
        return Response(payload)


class DcsHistoryView(APIView):
    """GET /api/v1/dcs/history/ — headline score time series for trend charts."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _DCS_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view DCS history."},
                status=403,
            )

        return Response(
            resolve_dcs_score_history_for_user(
                user=request.user,
                days_raw=request.query_params.get("days"),
                since_raw=request.query_params.get("since"),
                until_raw=request.query_params.get("until"),
            )
        )
