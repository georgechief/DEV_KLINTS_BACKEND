"""Shared Company A / Company B fixtures for M3-SEC-01 isolation tests."""

from __future__ import annotations

from dataclasses import dataclass

from rest_framework.test import APIClient

from tenants.models import Company, Tenant, User


@dataclass(frozen=True)
class Sec01TenantPair:
    tenant_a: Tenant
    company_a: Company
    admin_a: User
    client_a: APIClient
    tenant_b: Tenant
    company_b: Company
    admin_b: User
    client_b: APIClient


@dataclass(frozen=True)
class Sec01RoleClients:
    """Single-tenant Admin / Analyst / Viewer clients for RBAC negatives."""

    tenant: Tenant
    company: Company
    admin: User
    analyst: User
    viewer: User
    client_admin: APIClient
    client_analyst: APIClient
    client_viewer: APIClient
    client_anon: APIClient


def make_sec01_tenant_pair(*, slug_prefix: str = "sec01") -> Sec01TenantPair:
    """Two separate tenants/companies with admin API clients."""
    tenant_a = Tenant.objects.create(
        name=f"{slug_prefix}-A",
        slug=f"{slug_prefix}-a",
        is_active=True,
    )
    tenant_b = Tenant.objects.create(
        name=f"{slug_prefix}-B",
        slug=f"{slug_prefix}-b",
        is_active=True,
    )
    company_a = Company.objects.create(
        tenant=tenant_a,
        name=f"{slug_prefix} Co A",
        domain=f"{slug_prefix}-a.example.com",
    )
    company_b = Company.objects.create(
        tenant=tenant_b,
        name=f"{slug_prefix} Co B",
        domain=f"{slug_prefix}-b.example.com",
    )
    admin_a = User.objects.create_user(
        email=f"admin-a@{slug_prefix}.test",
        password="TestPass123!",
        name="Admin A",
        tenant=tenant_a,
        role=User.Role.ADMIN,
        email_verified=True,
        is_active=True,
    )
    admin_b = User.objects.create_user(
        email=f"admin-b@{slug_prefix}.test",
        password="TestPass123!",
        name="Admin B",
        tenant=tenant_b,
        role=User.Role.ADMIN,
        email_verified=True,
        is_active=True,
    )
    client_a = APIClient()
    client_a.force_authenticate(user=admin_a)
    client_b = APIClient()
    client_b.force_authenticate(user=admin_b)
    return Sec01TenantPair(
        tenant_a=tenant_a,
        company_a=company_a,
        admin_a=admin_a,
        client_a=client_a,
        tenant_b=tenant_b,
        company_b=company_b,
        admin_b=admin_b,
        client_b=client_b,
    )


def make_sec01_role_clients(*, slug_prefix: str = "sec01-rbac") -> Sec01RoleClients:
    """One company with Admin / Analyst / Viewer API clients (+ anonymous)."""
    tenant = Tenant.objects.create(
        name=f"{slug_prefix}-T",
        slug=f"{slug_prefix}-t",
        is_active=True,
    )
    company = Company.objects.create(
        tenant=tenant,
        name=f"{slug_prefix} Co",
        domain=f"{slug_prefix}.example.com",
    )
    admin = User.objects.create_user(
        email=f"admin@{slug_prefix}.test",
        password="TestPass123!",
        name="Admin",
        tenant=tenant,
        role=User.Role.ADMIN,
        email_verified=True,
        is_active=True,
    )
    analyst = User.objects.create_user(
        email=f"analyst@{slug_prefix}.test",
        password="TestPass123!",
        name="Analyst",
        tenant=tenant,
        role=User.Role.ANALYST,
        email_verified=True,
        is_active=True,
    )
    viewer = User.objects.create_user(
        email=f"viewer@{slug_prefix}.test",
        password="TestPass123!",
        name="Viewer",
        tenant=tenant,
        role=User.Role.VIEWER,
        email_verified=True,
        is_active=True,
    )
    client_admin = APIClient()
    client_admin.force_authenticate(user=admin)
    client_analyst = APIClient()
    client_analyst.force_authenticate(user=analyst)
    client_viewer = APIClient()
    client_viewer.force_authenticate(user=viewer)
    return Sec01RoleClients(
        tenant=tenant,
        company=company,
        admin=admin,
        analyst=analyst,
        viewer=viewer,
        client_admin=client_admin,
        client_analyst=client_analyst,
        client_viewer=client_viewer,
        client_anon=APIClient(),
    )
