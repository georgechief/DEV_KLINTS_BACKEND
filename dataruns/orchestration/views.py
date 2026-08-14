"""Orchestration HTTP API (PRD-ORCH-01)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.orchestration.plan import build_plan
from tenants.auth.services import get_user_company
from tenants.models import User

_ORCH_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)


class OrchestrationPlanView(APIView):
    """GET /api/v1/orchestration/plan/ — ranked FIX tasks for the company."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _ORCH_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view the orchestration plan."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        return Response(build_plan(company=company))
