from rest_framework import serializers

from tenants.connector_types import resolve_connector_type
from tenants.models import (
    Company,
    Connector,
    ConnectorSnapshot,
    EmailVerificationToken,
    Tenant,
    User,
)


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = (
            "id",
            "name",
            "slug",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "name",
            "password",
            "tenant_id",
            "role",
            "email_verified",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "email_verified",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "password": {"write_only": True},
        }

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = (
            "id",
            "tenant_id",
            "name",
            "domain",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class EmailVerificationTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailVerificationToken
        fields = (
            "id",
            "user_id",
            "email",
            "token",
            "expires_at",
            "used_at",
            "created_at",
        )
        read_only_fields = ("id", "created_at")
        extra_kwargs = {
            # Never expose verification tokens in API responses.
            "token": {"write_only": True},
        }


class ConnectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Connector
        fields = (
            "id",
            "company_id",
            "name",
            "type",
            "config",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "type", "status", "created_at", "updated_at")

    def create(self, validated_data):
        name = validated_data.get("name")
        if isinstance(name, str) and name:
            validated_data["type"] = resolve_connector_type(name)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        name = validated_data.get("name", instance.name)
        if isinstance(name, str) and name in ("manago_ai", "shopify"):
            validated_data["type"] = resolve_connector_type(name)
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        config = data.get("config")
        if isinstance(config, dict) and "api_key" in config:
            data["config"] = {**config, "api_key": self._mask_api_key(config["api_key"])}
        return data

    @staticmethod
    def _mask_api_key(api_key):
        if not isinstance(api_key, str) or not api_key:
            return "****"
        if "_" in api_key:
            prefix, _sep, _rest = api_key.rpartition("_")
            return f"{prefix}_****"
        return "****"


class ConnectorSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConnectorSnapshot
        fields = (
            "id",
            "connector_id",
            "version",
            "snapshot_data",
            "created_at",
        )
        read_only_fields = ("id", "created_at")
