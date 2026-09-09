"""Identity + stub connector scaffolding for ``seed_demo_tenant`` (W9-05 Phase 1)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import transaction

from dataruns.demo_seed.constants import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_NAME,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_COMPANY_DOMAIN,
    DEFAULT_COMPANY_NAME,
    DEFAULT_TENANT_NAME,
    DEFAULT_TENANT_SLUG,
    DEMO_SEED_CONFIG_MARKER,
)
from tenants.connector_types import resolve_connector_type
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


@dataclass(frozen=True)
class DemoTenantIdentity:
    tenant: Tenant
    company: Company
    user: User


def demo_tenant_slug(vertical: str) -> str:
    if vertical == "skincare":
        return DEFAULT_TENANT_SLUG
    return f"klints-demo-{vertical}"


def assert_email_available_for_slug(*, email: str, slug: str) -> None:
    """
    Refuse emails owned by a *different* tenant.

    Must run **before** ``--reset`` so we never retire the demo tenant and then
    fail create, leaving no active demo row.
    """
    existing = (
        User.objects.filter(email__iexact=email.strip())
        .select_related("tenant")
        .first()
    )
    if existing is None:
        return
    if existing.tenant.slug == slug:
        # Same demo tenant — ``--reset`` will retire this user email.
        return
    raise ValueError(
        f"User email already exists on tenant {existing.tenant.slug!r}: {email}. "
        f"Choose a different --email ( --reset only retires slug {slug!r})."
    )


def reset_demo_tenant(*, slug: str) -> bool:
    """
    Retire existing demo tenant so ``slug`` + demo email can be reused.

    Hard-delete is **not** used: Postgres append-only triggers forbid deleting
    ``audit_logs`` (CASCADE from Company would raise). Retire = rename slug,
    free emails, deactivate. Returns True if a row was retired.
    """
    existing = Tenant.objects.filter(slug=slug).first()
    if existing is None:
        return False

    token = uuid.uuid4().hex[:10]
    retired_slug = f"{slug}-retired-{token}"
    with transaction.atomic():
        for user in User.objects.filter(tenant=existing):
            local = (user.email or "user").split("@", 1)[0]
            # Keep unique + HTML5-safe domain.
            user.email = f"retired+{local}+{token}@example.com"
            user.is_active = False
            user.save(update_fields=["email", "is_active", "updated_at"])
        for company in Company.objects.filter(tenant=existing):
            # Free globally-unique connector external_account_key for the new seed.
            for connector in Connector.objects.filter(company=company):
                key = connector.external_account_key or connector.name
                connector.external_account_key = f"retired:{token}:{key}"[:255]
                connector.status = "disconnected"
                connector.save(
                    update_fields=["external_account_key", "status", "updated_at"]
                )
            company.domain = f"retired-{token}.{company.domain}"[:255]
            company.save(update_fields=["domain"])
        existing.slug = retired_slug
        existing.name = f"[retired] {existing.name}"[:255]
        existing.is_active = False
        existing.save(update_fields=["slug", "name", "is_active", "updated_at"])
    return True


def create_demo_identity(
    *,
    vertical: str,
    slug: str | None = None,
    email: str | None = None,
    password: str | None = None,
    tenant_name: str | None = None,
    company_name: str | None = None,
    company_domain: str | None = None,
) -> DemoTenantIdentity:
    """
    Create Tenant + Company + admin User for the demo seed.

    Caller must have already applied ``--reset`` if the slug exists, and
    ``assert_email_available_for_slug`` before any destructive reset.
    """
    resolved_slug = (slug or demo_tenant_slug(vertical)).strip()
    resolved_email = (email or DEFAULT_ADMIN_EMAIL).strip().lower()
    resolved_password = password or DEFAULT_ADMIN_PASSWORD
    resolved_tenant_name = tenant_name or DEFAULT_TENANT_NAME
    resolved_company_name = company_name or DEFAULT_COMPANY_NAME
    resolved_domain = company_domain or DEFAULT_COMPANY_DOMAIN

    if Tenant.objects.filter(slug=resolved_slug).exists():
        raise ValueError(
            f"Tenant slug already exists: {resolved_slug}. Re-run with --reset."
        )
    if User.objects.filter(email__iexact=resolved_email).exists():
        raise ValueError(
            f"User email already exists: {resolved_email}. "
            "Use a different --email, or --reset if that user is on this demo slug."
        )

    with transaction.atomic():
        tenant = Tenant.objects.create(
            name=resolved_tenant_name,
            slug=resolved_slug,
            is_active=True,
        )
        company = Company.objects.create(
            tenant=tenant,
            name=resolved_company_name,
            domain=resolved_domain,
        )
        user = User.objects.create_user(
            email=resolved_email,
            password=resolved_password,
            name=DEFAULT_ADMIN_NAME,
            tenant=tenant,
            role=User.Role.ADMIN,
        )
        user.email_verified = True
        user.is_active = True
        user.is_staff = True
        user.save(
            update_fields=[
                "email_verified",
                "is_active",
                "is_staff",
                "updated_at",
            ]
        )

    return DemoTenantIdentity(
        tenant=tenant,
        company=company,
        user=user,
    )


def ensure_stub_connectors(*, company: Company, vertical: str) -> list[Connector]:
    """
    Upsert connected Shopify + Manago stubs with honest demo markers (no live tokens).
    """
    shopify_config = encrypt_config(
        {
            DEMO_SEED_CONFIG_MARKER: True,
            "vertical": vertical,
            "shop_domain": f"{company.tenant.slug}.myshopify.com",
            "access_token": "demo-stub-not-a-live-token",
            # FD-02 scopes for offline demo (not live OAuth grants).
            "scopes": "read_customers,read_orders,write_customers,write_orders",
        }
    )
    manago_config = encrypt_config(
        {
            DEMO_SEED_CONFIG_MARKER: True,
            "vertical": vertical,
            "base_url": "https://app.manago.ai",
            "client_id": "demo-stub-client-id",
            "api_secret": "demo-stub-not-a-live-secret",
        }
    )

    shopify, _ = Connector.objects.update_or_create(
        company=company,
        name="shopify",
        defaults={
            "type": resolve_connector_type("shopify"),
            "status": "connected",
            "config": shopify_config,
            "external_account_key": f"demo:shopify:{company.tenant.slug}",
        },
    )
    manago, _ = Connector.objects.update_or_create(
        company=company,
        name="manago_ai",
        defaults={
            "type": resolve_connector_type("manago_ai"),
            "status": "connected",
            "config": manago_config,
            "external_account_key": f"demo:manago_ai:{company.tenant.slug}",
        },
    )
    return [shopify, manago]
