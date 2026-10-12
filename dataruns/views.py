from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from dataruns.models import DataRun
from dataruns.serializers import DataRunSerializer


class DataRunViewSet(viewsets.ReadOnlyModelViewSet):
    """DataRun list/retrieve scoped to the caller's tenant (M3-SEC-01 / B1).

    Read-only for ALL roles including Admin — DCS evidence is produced only by
    the scoring pipeline (``POST /api/v1/dcs/runs/`` + Celery), never via this
    HTTP surface. Foreign ``?tenant=`` overrides are ignored.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = DataRunSerializer
    # Base queryset is unused; get_queryset always scopes. Keep empty-safe default.
    queryset = DataRun.objects.none()
    http_method_names = ["get", "head", "options"]

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
