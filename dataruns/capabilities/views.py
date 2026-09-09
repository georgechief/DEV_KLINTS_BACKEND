"""Capability Matrix HTTP API (PRD-CAP-01 Step 6) — read-only."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.capabilities.registry import get_capability, list_capabilities
from tenants.models import User

# PRD §6: Admin / Analyst / Viewer (read-only). No POST/PATCH in v1.
_CAP_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)


def _forbid_if_not_reader(request) -> Response | None:
    if request.user.role not in _CAP_READ_ROLES:
        return Response(
            {"detail": "You do not have permission to view capabilities."},
            status=403,
        )
    return None


class CapabilityListView(APIView):
    """GET /api/v1/capabilities/ — Matrix seed list (+ optional filters)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        denied = _forbid_if_not_reader(request)
        if denied is not None:
            return denied
        return Response(
            list_capabilities(
                channel=request.query_params.get("channel"),
                status=request.query_params.get("status"),
                q=request.query_params.get("q"),
            )
        )


class CapabilityDetailView(APIView):
    """GET /api/v1/capabilities/{capability_id}/ — one Matrix record."""

    permission_classes = [IsAuthenticated]

    def get(self, request, capability_id: str):
        denied = _forbid_if_not_reader(request)
        if denied is not None:
            return denied
        row = get_capability(capability_id)
        if row is None:
            return Response({"detail": "Capability not found."}, status=404)
        return Response(row)
