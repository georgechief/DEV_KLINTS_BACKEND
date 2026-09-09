"""DCS-09 Step 7 — HTTP APIs for pilot supplemental gates.

Mounted under ``/api/v1/dcs/`` (see ``dataruns.dcs_urls``).
Does not touch headline 42 / DCS worklist.
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.dcs.pilot_gates.contract import (
    GATE_CATALOG_VERSION,
    PILOT_SUPPLEMENTAL_SCOPE,
)
from dataruns.dcs.pilot_gates.evaluate import (
    PilotGateEvaluateError,
    evaluate_pilot_gates,
    supplemental_readiness_for_use_case,
)
from dataruns.dcs.pilot_gates.master import master_as_api_payload
from dataruns.dcs.pilot_gates.store import get_latest_pilot_gate_eval
from dataruns.use_cases.models import UseCasePilot
from tenants.auth.services import get_user_company
from tenants.models import User

_DCS_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)
_PILOT_GATE_WRITE_ROLES = (User.Role.ADMIN, User.Role.ANALYST)


def _company_or_error(request) -> tuple[Any, Response | None]:
    company = get_user_company(request.user)
    if company is None:
        return None, Response(
            {"detail": "No company is associated with this account."},
            status=400,
        )
    return company, None


def _forbid_read() -> Response:
    return Response(
        {"detail": "You do not have permission to view pilot supplemental gates."},
        status=403,
    )


def _forbid_write() -> Response:
    return Response(
        {
            "detail": (
                "Only admins and analysts can evaluate pilot supplemental gates."
            ),
        },
        status=403,
    )


def _parse_optional_str_list(
    body: dict[str, Any], key: str
) -> tuple[list[str] | None, Response | None]:
    """
    Omit / null → None (caller uses default semantics).
    List → cleaned list (may be empty).
    """
    if key not in body or body.get(key) is None:
        return None, None
    raw = body.get(key)
    if not isinstance(raw, list):
        return None, Response(
            {"detail": f"{key} must be a list of strings when provided."},
            status=400,
        )
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out, None


def _parse_optional_int(
    body: dict[str, Any], key: str
) -> tuple[int | None, Response | None]:
    if key not in body or body.get(key) is None:
        return None, None
    raw = body.get(key)
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, Response(
            {"detail": f"{key} must be an integer when provided."},
            status=400,
        )


def _parse_bool(
    body: dict[str, Any], key: str, *, default: bool = False
) -> tuple[bool, Response | None]:
    """
    Parse JSON boolean safely.

    ``bool("false")`` is True in Python — reject / coerce string forms explicitly.
    """
    if key not in body or body.get(key) is None:
        return default, None
    raw = body.get(key)
    if isinstance(raw, bool):
        return raw, None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw in (0, 1):
        return bool(raw), None
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True, None
        if lowered in {"false", "0", "no", ""}:
            return False, None
    return False, Response(
        {"detail": f"{key} must be a boolean when provided."},
        status=400,
    )


def _empty_latest_payload(*, company_id: str) -> dict[str, Any]:
    """Stable shape matching ``PilotGateEvalBundle.to_dict`` + ``evaluated``."""
    return {
        "evaluated": False,
        "data_run_id": None,
        "company_id": company_id,
        "scope": PILOT_SUPPLEMENTAL_SCOPE,
        "gate_catalog_version": GATE_CATALOG_VERSION,
        "data_run_id_score": None,
        "erp_in_scope": False,
        "results": [],
        "evaluated_at": None,
        "status_by_check_id": {},
        "count": 0,
    }


class PilotGatesMasterView(APIView):
    """GET /api/v1/dcs/pilot-gates/master/ — 12 defs + UC map."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _DCS_READ_ROLES:
            return _forbid_read()
        return Response(master_as_api_payload())


class PilotGatesLatestView(APIView):
    """GET /api/v1/dcs/pilot-gates/latest/ — latest company supplemental eval."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _DCS_READ_ROLES:
            return _forbid_read()
        company, error = _company_or_error(request)
        if error is not None:
            return error
        bundle = get_latest_pilot_gate_eval(company=company)
        if bundle is None:
            return Response(_empty_latest_payload(company_id=str(company.id)))
        payload = bundle.to_dict()
        payload["evaluated"] = True
        return Response(payload)


class PilotGatesEvaluateView(APIView):
    """POST /api/v1/dcs/pilot-gates/evaluate/ — on-demand supplemental eval."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in _PILOT_GATE_WRITE_ROLES:
            return _forbid_write()
        company, error = _company_or_error(request)
        if error is not None:
            return error

        body = request.data if isinstance(request.data, dict) else {}
        use_case_ids, err = _parse_optional_str_list(body, "use_case_ids")
        if err is not None:
            return err
        check_ids, err = _parse_optional_str_list(body, "check_ids")
        if err is not None:
            return err
        data_run_id, err = _parse_optional_int(body, "data_run_id")
        if err is not None:
            return err
        erp_in_scope, err = _parse_bool(body, "erp_in_scope", default=False)
        if err is not None:
            return err

        try:
            result = evaluate_pilot_gates(
                company=company,
                use_case_ids=use_case_ids,
                check_ids=check_ids,
                data_run_id=data_run_id,
                erp_in_scope=erp_in_scope,
                triggered_by="manual",
                actor_user_id=str(request.user.id),
            )
        except PilotGateEvaluateError as exc:
            return Response({"detail": str(exc)}, status=422)

        return Response(result.to_dict(), status=200)


class PilotSupplementalReadinessView(APIView):
    """GET /api/v1/dcs/pilots/{use_case_id}/readiness/ — supplemental readiness."""

    permission_classes = [IsAuthenticated]

    def get(self, request, use_case_id: str):
        if request.user.role not in _DCS_READ_ROLES:
            return _forbid_read()
        company, error = _company_or_error(request)
        if error is not None:
            return error

        uc = str(use_case_id or "").strip().upper()
        if not uc:
            return Response({"detail": "use_case_id is required."}, status=400)
        if not UseCasePilot.objects.filter(use_case_id=uc).exists():
            return Response({"detail": "Pilot not found."}, status=404)

        row = supplemental_readiness_for_use_case(
            use_case_id=uc,
            status_by_check_id=None,
            company=company,
        )
        return Response(row)
