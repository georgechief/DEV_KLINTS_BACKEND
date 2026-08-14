import secrets
import uuid
from datetime import timedelta

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


def _default_invite_expires_at():
    return timezone.now() + timedelta(days=7)


def _generate_invite_token():
    return secrets.token_urlsafe(32)


class Tenant(models.Model):
    """Organization / workspace that owns data and runs."""
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )


    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="companies",
    )
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "companies"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("email_verified", True)
        extra_fields.setdefault("role", User.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        ANALYST = "analyst", "Analyst"
        VIEWER = "viewer", "Viewer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
    )
    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.VIEWER,
    )
    email_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name", "tenant"]

    class Meta:
        db_table = "users"
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email


class EmailVerificationToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="email_verification_tokens",
    )
    email = models.EmailField()
    token = models.CharField(max_length=255, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "email_verification_tokens"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.email} ({self.token[:8]}…)"


class PasswordResetToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="password_reset_tokens",
    )
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "password_reset_tokens"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.email} ({self.token[:8]}…)"


class Invite(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="invites",
    )
    email = models.EmailField()
    role = models.CharField(max_length=32, choices=User.Role.choices)
    invited_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="invites_sent",
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        default=_generate_invite_token,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    expires_at = models.DateTimeField(default=_default_invite_expires_at)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_invites",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "invites"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "email"],
                condition=models.Q(status="pending"),
                name="uniq_invites_tenant_email_pending",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.email} ({self.status})"


class Connector(models.Model):
    class Type(models.TextChoices):
        CDP = "cdp", "CDP"
        ECOMMERCE = "ecommerce", "Ecommerce"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="connectors",
    )
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=64, choices=Type.choices)
    config = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=64)
    external_account_key = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "connectors"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="uniq_connectors_company_name",
            ),
            models.UniqueConstraint(
                fields=["external_account_key"],
                condition=models.Q(
                    status__in=("connected", "degraded"),
                    external_account_key__isnull=False,
                ),
                name="uniq_connectors_external_account_key_owner",
            ),
        ]

    def save(self, *args, **kwargs):
        from tenants.connector_types import resolve_connector_type

        if self.name in ("manago_ai", "shopify"):
            self.type = resolve_connector_type(self.name)
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = list(dict.fromkeys([*update_fields, "type"]))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"


class ConnectorSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connector = models.ForeignKey(
        Connector,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    version = models.PositiveIntegerField()
    snapshot_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "connector_snapshots"
        ordering = ["-version"]

    def __str__(self) -> str:
        return f"{self.connector_id} v{self.version}"
