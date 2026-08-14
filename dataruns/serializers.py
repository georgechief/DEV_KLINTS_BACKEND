from rest_framework import serializers

from dataruns.models import DataRun
from tenants.models import Tenant


class DataRunSerializer(serializers.ModelSerializer):
    tenant_slug = serializers.SlugRelatedField(
        source="tenant",
        slug_field="slug",
        queryset=Tenant.objects.all(),
    )

    class Meta:
        model = DataRun
        fields = (
            "id",
            "tenant_slug",
            "name",
            "status",
            "started_at",
            "finished_at",
            "metadata",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
