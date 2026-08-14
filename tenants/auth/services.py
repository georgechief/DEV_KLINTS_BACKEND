from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from tenants.models import Company, Connector, PasswordResetToken, User

_INVALID_RESET_LINK = "Invalid or expired reset link."


def user_needs_connector(user: User) -> bool:
    """Match login `needs_connector` semantics (PRD-FE-01 §3 / auth_views login)."""
    company = get_user_company(user)
    if company is None:
        return True
    return not Connector.objects.filter(
        company=company,
        status="connected",
    ).exists()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_user_for_password_reset(email: str) -> User | None:
    return User.objects.filter(email__iexact=email, is_active=True).first()


def create_password_reset_token(user: User) -> PasswordResetToken:
    with transaction.atomic():
        PasswordResetToken.objects.filter(
            user=user,
            used_at__isnull=True,
        ).update(used_at=timezone.now())
        return PasswordResetToken.objects.create(
            user=user,
            email=user.email,
            token=secrets.token_urlsafe(32),
            expires_at=timezone.now()
            + timedelta(hours=settings.PASSWORD_RESET_TTL_HOURS),
        )


def consume_password_reset_token(token: str, email: str) -> PasswordResetToken:
    normalized_email = normalize_email(email)
    reset_token = (
        PasswordResetToken.objects.select_related("user")
        .filter(token=token, email__iexact=normalized_email)
        .first()
    )
    if reset_token is None:
        raise ValidationError(_INVALID_RESET_LINK)
    if reset_token.used_at is not None:
        raise ValidationError(_INVALID_RESET_LINK)
    if reset_token.expires_at <= timezone.now():
        raise ValidationError(_INVALID_RESET_LINK)
    return reset_token


def reset_user_password(reset_token: PasswordResetToken, password: str) -> User:
    with transaction.atomic():
        user = reset_token.user
        user.set_password(password)
        user.save()

        now = timezone.now()
        reset_token.used_at = now
        reset_token.save(update_fields=["used_at"])

        PasswordResetToken.objects.filter(
            user=user,
            used_at__isnull=True,
        ).update(used_at=now)

        return user


def change_user_password(
    *,
    user: User,
    current_password: str,
    new_password: str,
) -> User:
    """Verify the current password, validate the new one, and persist the change."""
    if not user.check_password(current_password):
        raise ValidationError(
            {"current_password": ["Incorrect password."]}
        )
    if current_password == new_password:
        raise ValidationError(
            {
                "new_password": [
                    "New password must be different from current password."
                ]
            }
        )
    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        raise ValidationError({"new_password": list(exc.messages)}) from exc

    user.set_password(new_password)
    user.save(update_fields=["password"])
    return user


def get_user_company(user: User) -> Company | None:
    return (
        Company.objects.filter(tenant_id=user.tenant_id)
        .order_by("created_at")
        .first()
    )


def serialize_me_response(user: User) -> dict:
    company = get_user_company(user)
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "email_verified": user.email_verified,
        "needs_connector": user_needs_connector(user),
        "tenant": {
            "id": str(user.tenant_id),
            "name": user.tenant.name,
            "slug": user.tenant.slug,
        },
        "company": (
            {
                "id": str(company.id),
                "name": company.name,
                "domain": company.domain,
            }
            if company
            else None
        ),
    }


def update_user_display_name(*, user: User, name: str) -> User:
    user.name = name
    user.save(update_fields=["name", "updated_at"])
    return user
