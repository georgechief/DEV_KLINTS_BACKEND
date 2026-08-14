from rest_framework import serializers

from tenants.workspace.services import validate_company_domain


class UpdateWorkspaceSerializer(serializers.Serializer):
    tenant_name = serializers.CharField(max_length=255, required=False)
    company_name = serializers.CharField(max_length=255, required=False)
    company_domain = serializers.CharField(max_length=255, required=False)

    def validate_tenant_name(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("This field may not be blank.")
        return normalized

    def validate_company_name(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("This field may not be blank.")
        return normalized

    def validate_company_domain(self, value: str) -> str:
        return validate_company_domain(value)
