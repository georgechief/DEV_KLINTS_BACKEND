"""AI suggestion API (PRD-AI-01 §9.1)."""

from __future__ import annotations

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
from dataruns.ai.service import get_or_create_fix_suggestion, serialize_fix_suggestion_result
from tenants.auth.services import get_user_company
from tenants.models import User

_AI_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)


class FixSuggestionView(APIView):
    """POST /api/v1/ai/suggestions/fix/ — get or create Fix AI suggestion."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in _AI_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view AI suggestions."},
                status=403,
            )

        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )

        body = request.data if isinstance(request.data, dict) else {}
        check_id_raw = body.get("check_id")
        if isinstance(check_id_raw, str):
            check_id = check_id_raw.strip()
        elif check_id_raw is not None:
            check_id = str(check_id_raw).strip()
        else:
            check_id = ""
        if not check_id:
            return Response({"detail": "check_id is required."}, status=400)

        dcs_run_id_raw = body.get("dcs_run_id")
        dcs_run_id: int | None = None
        if dcs_run_id_raw is not None and dcs_run_id_raw != "":
            try:
                dcs_run_id = int(dcs_run_id_raw)
            except (TypeError, ValueError):
                return Response({"detail": "dcs_run_id must be an integer."}, status=400)

        try:
            result = get_or_create_fix_suggestion(
                company=company,
                check_id=check_id,
                dcs_run_id=dcs_run_id,
            )
        except AiNotFoundError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=404)
        except AiGateDeniedError as exc:
            return Response(
                {
                    "detail": exc.message,
                    "code": exc.code,
                    "reason": exc.reason,
                },
                status=422,
            )
        except AiDisabledError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=503)
        except AiJsonRetryExhaustedError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=503)
        except AiProviderError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=503)

        return Response(serialize_fix_suggestion_result(result), status=200)
