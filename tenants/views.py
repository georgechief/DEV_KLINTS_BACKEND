from rest_framework import viewsets

from tenants.models import Tenant
from tenants.serializers import TenantSerializer


class TenantViewSet(viewsets.ModelViewSet):
    queryset = Tenant.objects.all()
    serializer_class = TenantSerializer
    lookup_field = "slug"
