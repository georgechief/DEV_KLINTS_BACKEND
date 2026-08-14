"""Use Case Library HTTP API (PRD-UC-01 §9)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.use_cases.models import UseCasePilot
from dataruns.use_cases.recommend import (
    build_recommendations_payload,
    build_single_recommendation_payload,
)
from dataruns.use_cases.serialize import list_catalogue_payload, serialize_pilot_detail
from tenants.auth.services import get_user_company
from tenants.models import User

_UC_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)


class UseCaseCatalogueView(APIView):
    """GET /api/v1/use-cases/ — list 16 MVP1 pilots."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _UC_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view use cases."},
                status=403,
            )
        return Response(list_catalogue_payload())


class UseCaseDetailView(APIView):
    """GET /api/v1/use-cases/{use_case_id}/ — pilot + blueprint summary."""

    permission_classes = [IsAuthenticated]

    def get(self, request, use_case_id: str):
        if request.user.role not in _UC_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view use cases."},
                status=403,
            )
        pilot = (
            UseCasePilot.objects.select_related("blueprint")
            .prefetch_related("stage_maps")
            .filter(use_case_id=use_case_id.upper())
            .first()
        )
        if pilot is None:
            return Response({"detail": "Use case not found."}, status=404)
        return Response(serialize_pilot_detail(pilot))


class UseCaseRecommendationsView(APIView):
    """GET /api/v1/use-cases/recommendations/ — company-scoped evaluation."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _UC_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view use cases."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        return Response(build_recommendations_payload(company=company))


class UseCaseRecommendationDetailView(APIView):
    """GET /api/v1/use-cases/recommendations/{use_case_id}/."""

    permission_classes = [IsAuthenticated]

    def get(self, request, use_case_id: str):
        if request.user.role not in _UC_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view use cases."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        payload = build_single_recommendation_payload(
            company=company,
            use_case_id=use_case_id,
        )
        if payload is None:
            return Response({"detail": "Use case not found."}, status=404)
        return Response(payload)
