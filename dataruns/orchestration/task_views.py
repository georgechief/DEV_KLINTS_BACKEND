"""Orchestration task HTTP API (PRD-GAP-01 Slice A1 Phase 3)."""

from __future__ import annotations

import uuid
from typing import Any

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.orchestration.models import OrchestrationTask
from dataruns.orchestration.task_constants import (
    ORCH_ERROR_VALIDATION,
    normalize_orch_status,
    normalize_orch_task_type,
    serialize_orch_task,
)
from dataruns.orchestration.task_transitions import (
    OrchTransitionError,
    create_orchestration_task,
    get_orchestration_task,
    transition_orchestration_task,
)
from tenants.auth.services import get_user_company
from tenants.models import Company, User

_ORCH_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)
_ORCH_MUTATE_ROLES = (User.Role.ADMIN, User.Role.ANALYST)


def _request_dict(request) -> dict[str, Any]:
    data = request.data if hasattr(request, "data") else {}
    return data if isinstance(data, dict) else {}


def _company_for_orch_read(
    request,
) -> tuple[Company | None, Response | None]:
    if request.user.role not in _ORCH_READ_ROLES:
        return None, Response(
            {
                "detail": "You do not have permission to view orchestration tasks.",
                "code": "forbidden",
            },
            status=403,
        )
    company = get_user_company(request.user)
    if company is None:
        return None, Response(
            {"detail": "No company is associated with this account."},
            status=400,
        )
    return company, None


def _company_for_orch_mutate(
    request,
) -> tuple[Company | None, Response | None]:
    if request.user.role not in _ORCH_MUTATE_ROLES:
        return None, Response(
            {
                "detail": "You do not have permission to modify orchestration tasks.",
                "code": "forbidden",
            },
            status=403,
        )
    company = get_user_company(request.user)
    if company is None:
        return None, Response(
            {"detail": "No company is associated with this account."},
            status=400,
        )
    return company, None


def _parse_task_uuid(value) -> uuid.UUID | None | bool:
    if value is None or str(value).strip() == "":
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False


def _normalize_filter_status(raw: str | None) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return normalize_orch_status(raw)
    except ValueError as exc:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=str(exc),
            status=400,
        ) from exc


def _normalize_filter_task_type(raw: str | None) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return normalize_orch_task_type(raw)
    except ValueError as exc:
        raise OrchTransitionError(
            code=ORCH_ERROR_VALIDATION,
            detail=str(exc),
            status=400,
        ) from exc


class OrchestrationTaskListCreateView(APIView):
    """GET/POST /api/v1/orchestration/tasks/ (PRD-GAP-01 §8)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        company, err = _company_for_orch_read(request)
        if err is not None:
            return err

        try:
            status_filter = _normalize_filter_status(request.query_params.get("status"))
            task_type_filter = _normalize_filter_task_type(
                request.query_params.get("task_type")
            )
        except OrchTransitionError as exc:
            return Response(
                {"detail": exc.detail, "code": exc.code},
                status=exc.status,
            )

        qs = OrchestrationTask.objects.filter(company=company).order_by(
            "-created_at",
            "-id",
        )
        if status_filter is not None:
            qs = qs.filter(status=status_filter)
        if task_type_filter is not None:
            qs = qs.filter(task_type=task_type_filter)

        check_id = request.query_params.get("check_id")
        if check_id is not None and str(check_id).strip():
            qs = qs.filter(check_id=str(check_id).strip().upper())

        rows = list(qs[:100])
        results = [serialize_orch_task(row) for row in rows]
        return Response({"count": len(results), "results": results})

    def post(self, request):
        company, err = _company_for_orch_mutate(request)
        if err is not None:
            return err

        body = _request_dict(request)
        priority_inputs = body.get("priority_inputs")
        if not isinstance(priority_inputs, dict):
            return Response(
                {
                    "detail": "priority_inputs must be an object.",
                    "code": ORCH_ERROR_VALIDATION,
                },
                status=400,
            )

        try:
            outcome = create_orchestration_task(
                company=company,
                actor=request.user,
                task_id=str(body.get("task_id") or ""),
                task_type=str(body.get("task_type") or ""),
                idempotency_key=str(body.get("idempotency_key") or ""),
                priority_inputs=priority_inputs,
                status=body.get("status"),
                title=str(body.get("title") or ""),
                check_id=body.get("check_id"),
                priority_score=body.get("priority_score"),
                priority_class=body.get("priority_class"),
                depends_on=body.get("depends_on"),
                wave=body.get("wave", 0),
                capability_dependencies=body.get("capability_dependencies"),
                approval=body.get("approval"),
                provenance=body.get("provenance"),
                source_refs=body.get("source_refs"),
                metadata=body.get("metadata"),
            )
        except OrchTransitionError as exc:
            return Response(
                {"detail": exc.detail, "code": exc.code},
                status=exc.status,
            )

        status_code = 201 if not outcome.idempotent else 200
        payload = serialize_orch_task(outcome.record)
        payload["idempotent"] = outcome.idempotent
        return Response(payload, status=status_code)


class OrchestrationTaskDetailView(APIView):
    """GET /api/v1/orchestration/tasks/{id}/ (PRD-GAP-01 §8)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        company, err = _company_for_orch_read(request)
        if err is not None:
            return err

        parsed = _parse_task_uuid(task_id)
        if parsed is False:
            return Response(
                {
                    "detail": "task id must be a valid UUID.",
                    "code": ORCH_ERROR_VALIDATION,
                },
                status=400,
            )

        record = get_orchestration_task(company=company, task_id=parsed)
        if record is None:
            return Response(
                {"detail": "Orchestration task not found."},
                status=404,
            )
        return Response(serialize_orch_task(record))


class OrchestrationTaskTransitionView(APIView):
    """POST /api/v1/orchestration/tasks/{id}/transition/ (PRD-GAP-01 §8)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        company, err = _company_for_orch_mutate(request)
        if err is not None:
            return err

        parsed = _parse_task_uuid(task_id)
        if parsed is False:
            return Response(
                {
                    "detail": "task id must be a valid UUID.",
                    "code": ORCH_ERROR_VALIDATION,
                },
                status=400,
            )

        record = get_orchestration_task(company=company, task_id=parsed)
        if record is None:
            return Response(
                {"detail": "Orchestration task not found."},
                status=404,
            )

        body = _request_dict(request)
        to_status = body.get("to_status")
        if to_status is None or not str(to_status).strip():
            return Response(
                {
                    "detail": "to_status is required.",
                    "code": ORCH_ERROR_VALIDATION,
                },
                status=400,
            )

        reason = body.get("reason")
        try:
            outcome = transition_orchestration_task(
                record=record,
                company=company,
                actor=request.user,
                to_status=str(to_status),
                reason=str(reason).strip() if reason is not None else None,
            )
        except OrchTransitionError as exc:
            return Response(
                {"detail": exc.detail, "code": exc.code},
                status=exc.status,
            )

        payload = serialize_orch_task(outcome.record)
        payload["idempotent"] = outcome.idempotent
        return Response(payload, status=200)
