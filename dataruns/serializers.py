from rest_framework import serializers

from dataruns.models import DataRun


class DataRunSerializer(serializers.ModelSerializer):
    """Read-only DataRun projection (B1 — no HTTP forge of status/metadata)."""

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
        # Explicit list (not `= fields`) so verify/static review cannot miss locks.
        read_only_fields = (
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
