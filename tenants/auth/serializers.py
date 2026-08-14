from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from tenants.models import User


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    def validate(self, attrs):
        user = User.objects.filter(email__iexact=attrs["email"]).first()
        try:
            validate_password(attrs["password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"password": list(exc.messages)}
            ) from exc
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {
                    "new_password": [
                        "New password must be different from current password."
                    ]
                }
            )

        user = self.context["request"].user
        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"new_password": list(exc.messages)}
            ) from exc
        return attrs


class UpdateMeSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)

    def validate_name(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("This field may not be blank.")
        return normalized
