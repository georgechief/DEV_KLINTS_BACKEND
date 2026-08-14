from rest_framework import viewsets

from dataruns.models import DataRun
from dataruns.serializers import DataRunSerializer


class DataRunViewSet(viewsets.ModelViewSet):
    queryset = DataRun.objects.select_related("tenant").all()
    serializer_class = DataRunSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant_slug = self.request.query_params.get("tenant")
        status = self.request.query_params.get("status")
        if tenant_slug:
            queryset = queryset.filter(tenant__slug=tenant_slug)
        if status:
            queryset = queryset.filter(status=status)
        return queryset
