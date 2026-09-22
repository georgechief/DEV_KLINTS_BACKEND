from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from dataruns.models import DataRun
from dataruns.serializers import DataRunSerializer


class DataRunViewSet(viewsets.ModelViewSet):
    """DataRun CRUD scoped to the caller's tenant (M3-SEC-01 Phase 3).

    Foreign ``?tenant=`` overrides are ignored — never widen beyond caller tenant.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = DataRunSerializer
    # Base queryset is unused; get_queryset always scopes. Keep empty-safe default.
    queryset = DataRun.objects.none()

    def get_queryset(self):
        user = self.request.user
        tenant_id = getattr(user, "tenant_id", None)
        if not user.is_authenticated or tenant_id is None:
            return DataRun.objects.none()

        queryset = DataRun.objects.select_related("tenant").filter(
            tenant_id=tenant_id
        )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        # Intentionally ignore ?tenant= — do not allow cross-tenant override.
        return queryset

    def _caller_tenant(self):
        tenant = getattr(self.request.user, "tenant", None)
        if tenant is None:
            raise PermissionDenied("User has no tenant.")
        return tenant

    def perform_create(self, serializer):
        serializer.save(tenant=self._caller_tenant())

    def perform_update(self, serializer):
        # Force caller tenant even if a client tries to reassign via payload.
        serializer.save(tenant=self._caller_tenant())
