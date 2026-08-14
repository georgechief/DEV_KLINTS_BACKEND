"""Approval token REST API (BL-017)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.writebacks.approvals.exceptions import (
    ApprovalJobNotFound,
    ApprovalTokenError,
    ApprovalTokenNotFound,
)
from dataruns.writebacks.approvals.service import (
    approve_token,
    get_approval_token,
    reject_token,
    request_approval,
    serialize_token,
)
from tenants.auth.services import get_user_company
from tenants.models import User


class WritebackApprovalRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in (User.Role.ADMIN, User.Role.ANALYST):
            return Response(
                {"detail": "You do not have permission to request writeback approval."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response({"detail": "No company is associated with this account."}, status=400)

        body = request.data if isinstance(request.data, dict) else {}
        job_id = body.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            return Response({"detail": "job_id is required."}, status=400)

        try:
            token = request_approval(
                company=company,
                job_id=job_id.strip(),
                actor=request.user,
            )
        except ApprovalJobNotFound:
            return Response({"detail": "Writeback preview job not found."}, status=404)
        except ApprovalTokenError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=400)

        return Response(serialize_token(token), status=201)


class WritebackApprovalDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, approval_id: str):
        if request.user.role not in (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER):
            return Response(
                {"detail": "You do not have permission to view writeback approvals."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response({"detail": "No company is associated with this account."}, status=400)

        try:
            token = get_approval_token(company=company, approval_id=approval_id)
        except ApprovalTokenNotFound:
            return Response({"detail": "Approval token not found."}, status=404)

        return Response(serialize_token(token))


class WritebackApprovalApproveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, approval_id: str):
        if request.user.role != User.Role.ADMIN:
            return Response(
                {"detail": "Only admins can approve writebacks."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response({"detail": "No company is associated with this account."}, status=400)

        try:
            token = approve_token(
                company=company,
                approval_id=approval_id,
                actor=request.user,
            )
        except ApprovalTokenNotFound:
            return Response({"detail": "Approval token not found."}, status=404)
        except ApprovalTokenError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=400)

        return Response(serialize_token(token))


class WritebackApprovalRejectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, approval_id: str):
        if request.user.role != User.Role.ADMIN:
            return Response(
                {"detail": "Only admins can reject writebacks."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response({"detail": "No company is associated with this account."}, status=400)

        try:
            token = reject_token(
                company=company,
                approval_id=approval_id,
                actor=request.user,
            )
        except ApprovalTokenNotFound:
            return Response({"detail": "Approval token not found."}, status=404)
        except ApprovalTokenError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=400)

        return Response(serialize_token(token))
