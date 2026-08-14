"""Writeback REST API (PRD-WB-01 §5)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.writebacks.capabilities import list_supported_op_kinds
from dataruns.writebacks.exceptions import DiffHashMismatchError
from dataruns.writebacks.gates import is_sandbox_company
from dataruns.writebacks.registry import list_mappings
from dataruns.writebacks.rollback import WritebackJobNotFound, WritebackRollbackError
from dataruns.writebacks.serializers import serialize_result
from dataruns.writebacks.service import writeback_rollback_job, writeback_run
from tenants.auth.services import get_user_company
from tenants.models import User

_WRITEBACK_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)


class WritebackMappingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _WRITEBACK_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view writeback mappings."},
                status=403,
            )
        rows = [
            {
                "check_id": item.check_id,
                "enabled": item.enabled,
                "schema_version": item.schema_version,
                "title": item.title,
                "template_id": item.template_id,
                "op_kinds": item.op_kinds,
                "approval_tier": item.approval_tier,
            }
            for item in list_mappings()
        ]
        return Response({"count": len(rows), "mappings": rows})


class WritebackKindsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _WRITEBACK_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view writeback kinds."},
                status=403,
            )
        kinds = list_supported_op_kinds()
        return Response({"count": len(kinds), "kinds": kinds})


class WritebackPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in (User.Role.ADMIN, User.Role.ANALYST):
            return Response(
                {"detail": "You do not have permission to preview writebacks."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )

        body = request.data if isinstance(request.data, dict) else {}
        check_id = body.get("check_id")
        if not isinstance(check_id, str) or not check_id.strip():
            return Response({"detail": "check_id is required."}, status=400)

        batch_size = body.get("batch_size")
        max_rows = body.get("max_rows")
        if batch_size is not None and not isinstance(batch_size, int):
            return Response({"detail": "batch_size must be an integer."}, status=400)
        if max_rows is not None and not isinstance(max_rows, int):
            return Response({"detail": "max_rows must be an integer."}, status=400)

        try:
            result = writeback_run(
                company=company,
                check_id=check_id.strip(),
                mode="dry_run",
                batch_size=batch_size,
                max_rows=max_rows,
                actor=request.user,
            )
        except ValueError as exc:
            message = str(exc)
            status = 404 if "mapping" in message.lower() else 400
            return Response({"detail": message}, status=status)

        return Response(serialize_result(result))


class WritebackExecuteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != User.Role.ADMIN:
            return Response(
                {"detail": "Only admins can execute writebacks."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )

        body = request.data if isinstance(request.data, dict) else {}
        check_id = body.get("check_id")
        diff_hash = body.get("diff_hash")
        if not isinstance(check_id, str) or not check_id.strip():
            return Response({"detail": "check_id is required."}, status=400)
        if not isinstance(diff_hash, str) or len(diff_hash.strip()) != 64:
            return Response({"detail": "diff_hash is required."}, status=400)

        batch_size = body.get("batch_size")
        max_rows = body.get("max_rows")
        approval_id = body.get("approval_id")
        if batch_size is not None and not isinstance(batch_size, int):
            return Response({"detail": "batch_size must be an integer."}, status=400)
        if max_rows is not None and not isinstance(max_rows, int):
            return Response({"detail": "max_rows must be an integer."}, status=400)

        mode = "sandbox_execute" if is_sandbox_company(company) else "execute"

        try:
            result = writeback_run(
                company=company,
                check_id=check_id.strip(),
                mode=mode,
                batch_size=batch_size,
                max_rows=max_rows,
                approval_id=str(approval_id) if approval_id else None,
                actor=request.user,
                expected_diff_hash=diff_hash.strip(),
            )
        except DiffHashMismatchError as exc:
            return Response(
                {
                    "detail": "diff_hash mismatch.",
                    "expected": exc.expected,
                    "actual": exc.actual,
                },
                status=409,
            )
        except ValueError as exc:
            message = str(exc)
            status = 404 if "mapping" in message.lower() else 400
            return Response({"detail": message}, status=status)

        if result.blocked_reason:
            return Response(
                {"detail": "Writebacks are disabled.", "reason": result.blocked_reason},
                status=403,
            )

        payload = serialize_result(result)
        if result.summary.errors and result.summary.executed == 0:
            return Response(payload, status=501)
        return Response(payload)


class WritebackRollbackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != User.Role.ADMIN:
            return Response(
                {"detail": "Only admins can rollback writebacks."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )

        body = request.data if isinstance(request.data, dict) else {}
        job_id = body.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            return Response({"detail": "job_id is required."}, status=400)

        try:
            result = writeback_rollback_job(
                company=company,
                job_id=job_id.strip(),
                actor=request.user,
            )
        except WritebackJobNotFound:
            return Response({"detail": "Writeback job not found."}, status=404)
        except WritebackRollbackError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(result)
