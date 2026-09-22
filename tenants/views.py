from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tenants.models import Tenant, User
from tenants.serializers import TenantSerializer


class TenantViewSet(viewsets.ModelViewSet):
    """Tenant CRUD scoped to the caller's tenant (M3-SEC-01 Phase 3).

    Mutations align with workspace: create/destroy forbidden; update Admin-only.
    Slug / is_active are read-only on the serializer.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TenantSerializer
    lookup_field = "slug"
    # Base unused; get_queryset always scopes. Empty-safe for schema/router.
    queryset = Tenant.objects.none()

    def get_queryset(self):
        user = self.request.user
        tenant_id = getattr(user, "tenant_id", None)
        if not user.is_authenticated or tenant_id is None:
            return Tenant.objects.none()
        return Tenant.objects.filter(pk=tenant_id)

    def create(self, request, *args, **kwargs):
        # Workspace creation is via auth/register — not an open multi-tenant create.
        # Always 403 (do not call get_object) so responses do not leak existence.
        return Response(
            {"detail": "Creating tenants via this API is not allowed."},
            status=status.HTTP_403_FORBIDDEN,
        )

    def destroy(self, request, *args, **kwargs):
        # Always 403 — same for own/foreign/missing slug (no existence leak).
        return Response(
            {"detail": "Deleting tenants via this API is not allowed."},
            status=status.HTTP_403_FORBIDDEN,
        )

    def update(self, request, *args, **kwargs):
        if request.user.role != User.Role.ADMIN:
            return Response(
                {"detail": "Admin only."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if request.user.role != User.Role.ADMIN:
            return Response(
                {"detail": "Admin only."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().partial_update(request, *args, **kwargs)
