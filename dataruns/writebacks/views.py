"""Writeback REST API (PRD-WB-01 §5 / PRD-WB-01C §3–4 / PRD-WB-07 hygiene)."""

from __future__ import annotations

import logging
from typing import Any

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.writebacks.capabilities import list_supported_op_kinds
from dataruns.writebacks.exceptions import (
    DiffHashMismatchError,
    WritebackAlreadyExecutedForRunError,
    WritebackDcsRunRequiredError,
)
from dataruns.writebacks.approvals.service import revoke_approval_on_diff_hash_mismatch
from dataruns.writebacks.possible_sheet import PossibleSheetError, possible_sheet_payload
from dataruns.writebacks.registry import list_mappings
from dataruns.writebacks.rollback import WritebackJobNotFound, WritebackRollbackError
from dataruns.writebacks.messages import (
    writeback_execute_denial_detail,
    writeback_rollback_denial_detail,
)
from dataruns.writebacks.run_gate import (
    is_valid_writeback_status_check_id,
    writeback_status_payload,
)
from dataruns.writebacks.serializers import serialize_result
from dataruns.writebacks.service import writeback_rollback_job, writeback_run
from tenants.auth.services import get_user_company
from tenants.models import User

logger = logging.getLogger(__name__)

_WRITEBACK_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)
_PREVIEW_ROLES = (User.Role.ADMIN, User.Role.ANALYST)
_RUN_REQUIRED_KEYS = {
    "preview": ("check_id",),
    "execute": ("check_id", "diff_hash"),
    "rollback": ("job_id",),
}


def _json_body(request) -> dict[str, Any]:
    return request.data if isinstance(request.data, dict) else {}


def _company_response(request):
    company = get_user_company(request.user)
    if company is None:
        return None, Response(
            {"detail": "No company is associated with this account."},
            status=400,
        )
    return company, None


def _optional_int(body: dict[str, Any], key: str):
    value = body.get(key)
    if value is not None and not isinstance(value, int):
        return None, Response({"detail": f"{key} must be an integer."}, status=400)
    return value, None


def _missing_run_keys(action: str, body: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in _RUN_REQUIRED_KEYS[action]:
        value = body.get(key)
        if key == "diff_hash":
            if not isinstance(value, str) or len(value.strip()) != 64:
                missing.append(key)
            continue
        if not isinstance(value, str) or not value.strip():
            missing.append(key)
    return missing


def _handle_preview(request) -> Response:
    if request.user.role not in _PREVIEW_ROLES:
        return Response(
            {"detail": "You do not have permission to preview writebacks."},
            status=403,
        )

    company, error = _company_response(request)
    if error is not None:
        return error

    body = _json_body(request)
    check_id = body.get("check_id")
    if not isinstance(check_id, str) or not check_id.strip():
        return Response({"detail": "check_id is required."}, status=400)

    batch_size, error = _optional_int(body, "batch_size")
    if error is not None:
        return error
    max_rows, error = _optional_int(body, "max_rows")
    if error is not None:
        return error

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

    return Response(serialize_result(result, action="preview"))


def _handle_execute(request) -> Response:
    if request.user.role != User.Role.ADMIN:
        return Response(
            {"detail": "Only admins can execute writebacks."},
            status=403,
        )

    company, error = _company_response(request)
    if error is not None:
        return error

    body = _json_body(request)
    check_id = body.get("check_id")
    diff_hash = body.get("diff_hash")
    if not isinstance(check_id, str) or not check_id.strip():
        return Response({"detail": "check_id is required."}, status=400)
    if not isinstance(diff_hash, str) or len(diff_hash.strip()) != 64:
        return Response({"detail": "diff_hash is required."}, status=400)

    batch_size, error = _optional_int(body, "batch_size")
    if error is not None:
        return error
    max_rows, error = _optional_int(body, "max_rows")
    if error is not None:
        return error
    approval_id = body.get("approval_id")

    # PRD-WB-03 §6 — prefer `execute` naming when company Allow writebacks is on
    # (gates still enforce writeback_execute_enabled / WRITEBACKS_ENABLED).
    mode = "execute"

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
        logger.info(
            "writeback diff_hash mismatch expected=%s actual=%s",
            exc.expected,
            exc.actual,
        )
        # C2 — drop stale APPROVED grant so FE status cannot re-hydrate Approve & write.
        revoked = revoke_approval_on_diff_hash_mismatch(
            company=company,
            approval_id=str(approval_id) if approval_id else None,
        )
        if revoked:
            logger.info(
                "writeback approval revoked after diff_hash_mismatch approval_id=%s",
                approval_id,
            )
        return Response(
            {
                "detail": "Preview changed — run preview again.",
                "code": "diff_hash_mismatch",
                "action": "execute",
            },
            status=409,
        )
    except WritebackDcsRunRequiredError as exc:
        return Response(
            {
                "detail": str(exc),
                "code": exc.code,
                "action": "execute",
            },
            status=409,
        )
    except WritebackAlreadyExecutedForRunError as exc:
        return Response(
            {
                "detail": (
                    "Writeback already executed for this check on the current "
                    "Data Consistency Score. Re-run the score if the issue appears again."
                ),
                "code": exc.code,
                "check_id": exc.check_id,
                "data_run_id": exc.data_run_id,
                "execute_job_id": exc.execute_job_id,
                "action": "execute",
            },
            status=409,
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "mapping" in message.lower() else 400
        return Response({"detail": message, "action": "execute"}, status=status)

    if result.blocked_reason:
        return Response(
            {
                "detail": writeback_execute_denial_detail(result.blocked_reason),
                "reason": result.blocked_reason,
                "action": "execute",
            },
            status=403,
        )

    payload = serialize_result(result, action="execute")
    if result.summary.errors and result.summary.executed == 0:
        return Response(payload, status=501)
    return Response(payload)


def _handle_rollback(request) -> Response:
    if request.user.role != User.Role.ADMIN:
        return Response(
            {"detail": "Only admins can rollback writebacks."},
            status=403,
        )

    company, error = _company_response(request)
    if error is not None:
        return error

    body = _json_body(request)
    job_id = body.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        return Response({"detail": "job_id is required."}, status=400)

    try:
        result = writeback_rollback_job(
            company=company,
            job_id=job_id.strip(),
            actor=request.user,
        )
    except WritebackJobNotFound as exc:
        return Response(
            {
                "detail": writeback_rollback_denial_detail(exc.code, exc.message),
                "code": exc.code,
            },
            status=404,
        )
    except WritebackRollbackError as exc:
        return Response(
            {
                "detail": writeback_rollback_denial_detail(exc.code, exc.message),
                "code": exc.code,
            },
            status=400,
        )

    result["action"] = "rollback"
    return Response(result)


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
                "irreversible": item.irreversible,
                "operator_disclosure": item.operator_disclosure,
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


class WritebackPossibleView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _WRITEBACK_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view writeback possibility."},
                status=403,
            )
        try:
            return Response(possible_sheet_payload())
        except PossibleSheetError as exc:
            return Response({"detail": str(exc)}, status=500)


class WritebackStatusView(APIView):
    """GET writeback gate + provenance for Fix (PRD-WB-04 / WB-06)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _WRITEBACK_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view writeback status."},
                status=403,
            )
        company, error = _company_response(request)
        if error is not None:
            return error

        check_id = request.query_params.get("check_id")
        if not isinstance(check_id, str) or not check_id.strip():
            return Response({"detail": "check_id is required."}, status=400)
        if not is_valid_writeback_status_check_id(check_id):
            return Response(
                {"detail": "Invalid check_id format."},
                status=404,
            )

        data_run_id = request.query_params.get("data_run_id")
        parsed_run_id = None
        if data_run_id is not None and str(data_run_id).strip():
            try:
                parsed_run_id = int(str(data_run_id).strip())
            except (TypeError, ValueError):
                return Response({"detail": "data_run_id must be an integer."}, status=400)

        try:
            payload = writeback_status_payload(
                company=company,
                check_id=check_id.strip(),
                data_run_id=parsed_run_id,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(payload)


class WritebackPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return _handle_preview(request)


class WritebackExecuteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return _handle_execute(request)


class WritebackRollbackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return _handle_rollback(request)


class WritebackRunView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        body = _json_body(request)
        action = body.get("action")
        if not isinstance(action, str) or action.strip().lower() not in _RUN_REQUIRED_KEYS:
            return Response(
                {
                    "detail": "action must be preview, execute, or rollback.",
                    "required_keys": ["action"],
                },
                status=400,
            )
        action = action.strip().lower()
        missing = _missing_run_keys(action, body)
        if missing:
            return Response(
                {
                    "detail": f"Missing required keys for action={action}.",
                    "action": action,
                    "required_keys": missing,
                },
                status=400,
            )
        if action == "preview":
            return _handle_preview(request)
        if action == "execute":
            return _handle_execute(request)
        return _handle_rollback(request)
