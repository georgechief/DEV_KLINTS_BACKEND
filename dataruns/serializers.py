from rest_framework import serializers

from dataruns.models import DataRun


class DataRunSerializer(serializers.ModelSerializer):
    tenant_slug = serializers.SlugRelatedField(
        source="tenant",
        slug_field="slug",
        read_only=True,
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
        read_only_fields = ("id", "tenant_slug", "created_at", "updated_at")
