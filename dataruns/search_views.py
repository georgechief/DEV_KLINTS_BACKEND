"""Spotlight global search API (PRD-FE-05 §5)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.search import (
    parse_search_limit,
    parse_search_types,
    search_company,
    serialize_search_hit,
)
from tenants.auth.services import get_user_company
from tenants.models import User

_SEARCH_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)


class GlobalSearchView(APIView):
    """GET /api/v1/search/ — company-scoped Spotlight search."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _SEARCH_ROLES:
            return Response(
                {"detail": "You do not have permission to search."},
                status=403,
            )

        q = request.query_params.get("q", "")
        if q is None:
            q = ""
        q = str(q).strip()

        if len(q) < 2:
            return Response({"q": q, "results": []})

        company = get_user_company(request.user)
        if company is None:
            return Response({"q": q, "results": []})

        types = parse_search_types(request.query_params.get("types"))
        limit = parse_search_limit(request.query_params.get("limit"))
        if request.query_params.get("types") is not None and not types:
            hits = []
        else:
            hits = search_company(company=company, q=q, types=types, limit=limit)

        return Response(
            {
                "q": q,
                "results": [serialize_search_hit(hit) for hit in hits],
            }
        )
