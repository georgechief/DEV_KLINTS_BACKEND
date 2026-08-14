"""Audit timeline API (PRD-AUDIT-01 §6, PRD-AUDIT-02 notifications)."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.audit import (
    audit_meta_short_string,
    count_unread_audit_events,
    mark_all_audit_events_read,
    mark_audit_event_read,
)
from dataruns.models import AuditLog
from tenants.auth.services import get_user_company
from tenants.models import User

_AUDIT_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)


def _parse_limit(value: str | None, *, default: int, max_value: int) -> int:
    try:
        limit = int(value) if value is not None else default
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, max_value))


def _parse_before_cursor(value: str) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=timezone.utc)
    return parsed


def _serialize_audit_event(entry: AuditLog) -> dict:
    metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
    actor = entry.performed_by or "system"
    return {
        "id": str(entry.id),
        "action": entry.action,
        "tone": entry.tone,
        "summary": entry.summary,
        "performed_by": entry.performed_by,
        "actor": actor,
        "meta": audit_meta_short_string(metadata),
        "created_at": entry.created_at.isoformat().replace("+00:00", "Z"),
        "run_id": str(entry.run_id) if entry.run_id else None,
        "audit_read": entry.audit_read,
    }


def _audit_access_or_response(request):
    if request.user.role not in _AUDIT_ROLES:
        return None, Response(
            {"detail": "You do not have permission to view audit events."},
            status=status.HTTP_403_FORBIDDEN,
        )
    company = get_user_company(request.user)
    return company, None


class AuditEventsListView(APIView):
    """GET /api/v1/audit/events/ — company-scoped governance timeline."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        company, denied = _audit_access_or_response(request)
        if denied is not None:
            return denied

        if company is None:
            return Response({"results": [], "next_cursor": None})

        limit = _parse_limit(request.query_params.get("limit"), default=50, max_value=100)

        before_raw = request.query_params.get("before") or request.query_params.get("cursor")
        queryset = AuditLog.objects.filter(company=company).order_by("-created_at", "-id")

        unread_only = request.query_params.get("unread_only", "").lower() in {
            "1",
            "true",
            "yes",
        }
        if unread_only:
            queryset = queryset.filter(audit_read=False)

        if before_raw:
            before_dt = _parse_before_cursor(before_raw)
            if before_dt is not None:
                queryset = queryset.filter(created_at__lt=before_dt)

        rows = list(queryset[: limit + 1])
        has_more = len(rows) > limit
        page = rows[:limit]

        next_cursor = None
        if has_more and page:
            next_cursor = page[-1].created_at.isoformat().replace("+00:00", "Z")

        return Response(
            {
                "results": [_serialize_audit_event(row) for row in page],
                "next_cursor": next_cursor,
            }
        )


class AuditNotificationsListView(APIView):
    """GET /api/v1/audit/notifications/ — unread bell feed (PRD-AUDIT-02 §6.2)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        company, denied = _audit_access_or_response(request)
        if denied is not None:
            return denied

        if company is None:
            return Response({"unread_count": 0, "results": []})

        limit = _parse_limit(request.query_params.get("limit"), default=5, max_value=10)
        unread_count = count_unread_audit_events(company=company)
        rows = list(
            AuditLog.objects.filter(company=company, audit_read=False)
            .order_by("-created_at", "-id")[:limit]
        )

        return Response(
            {
                "unread_count": unread_count,
                "results": [_serialize_audit_event(row) for row in rows],
            }
        )


class AuditNotificationsMarkAllReadView(APIView):
    """POST /api/v1/audit/notifications/mark-all-read/ (PRD-AUDIT-02 §6.3)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        company, denied = _audit_access_or_response(request)
        if denied is not None:
            return denied

        if company is None:
            return Response({"updated": 0, "unread_count": 0})

        updated = mark_all_audit_events_read(company=company)
        return Response(
            {
                "updated": updated,
                "unread_count": count_unread_audit_events(company=company),
            }
        )


class AuditEventMarkReadView(APIView):
    """POST /api/v1/audit/events/{id}/mark-read/ (PRD-AUDIT-02 §6.4)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, event_id):
        company, denied = _audit_access_or_response(request)
        if denied is not None:
            return denied

        if company is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            parsed_id = uuid.UUID(str(event_id))
        except (ValueError, TypeError):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        entry = mark_audit_event_read(company=company, event_id=parsed_id)
        if entry is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "id": str(entry.id),
                "audit_read": True,
                "unread_count": count_unread_audit_events(company=company),
            }
        )
