from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError

from tenants.auth.services import get_user_company
from tenants.models import Company, Tenant, User

_NO_COMPANY_DETAIL = "No company on this workspace."
_INVALID_DOMAIN_MESSAGE = "Enter a valid website or domain."
_RESERVED_COMPANY_DOMAINS = frozenset({"localhost", "127.0.0.1"})


def normalize_company_domain(domain: str) -> str:
    value = domain.strip().lower()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value.rstrip("/")


def validate_company_domain(domain: str) -> str:
    """Normalize and validate a company website/domain (PRD-AUTH-01 §5)."""
    normalized = normalize_company_domain(domain or "")
    if not normalized:
        raise ValidationError({"company_domain": [_INVALID_DOMAIN_MESSAGE]})
    if len(normalized) > 255:
        raise ValidationError({"company_domain": [_INVALID_DOMAIN_MESSAGE]})
    if any(character.isspace() for character in normalized):
        raise ValidationError({"company_domain": [_INVALID_DOMAIN_MESSAGE]})
    if normalized in _RESERVED_COMPANY_DOMAINS:
        raise ValidationError({"company_domain": [_INVALID_DOMAIN_MESSAGE]})
    return normalized


def serialize_workspace_response(*, tenant: Tenant, company: Company) -> dict:
    return {
        "tenant": {
            "id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
        },
        "company": {
            "id": str(company.id),
            "name": company.name,
            "domain": company.domain,
        },
    }


def update_workspace(
    *,
    user: User,
    tenant_name: str | None = None,
    company_name: str | None = None,
    company_domain: str | None = None,
) -> dict:
    tenant = Tenant.objects.filter(pk=user.tenant_id).first()
    if tenant is None:
        raise NotFound()

    company = get_user_company(user)
    if company is None:
        raise ValidationError(_NO_COMPANY_DETAIL)

    company_update_fields: list[str] = []
    changed_fields: list[str] = []

    with transaction.atomic():
        if tenant_name is not None:
            tenant.name = tenant_name
            tenant.save(update_fields=["name", "updated_at"])
            changed_fields.append("tenant_name")

        if company_name is not None:
            company.name = company_name
            company_update_fields.append("name")
            changed_fields.append("company_name")

        if company_domain is not None:
            company.domain = company_domain
            company_update_fields.append("domain")
            changed_fields.append("company_domain")

        if company_update_fields:
            company.save(update_fields=company_update_fields)

    if changed_fields:
        from dataruns.audit import append_audit_event

        append_audit_event(
            company=company,
            action="workspace.updated",
            summary="Workspace updated",
            performed_by=user.email,
            actor_user_id=str(user.id),
            metadata={"fields": changed_fields},
        )

    return serialize_workspace_response(tenant=tenant, company=company)
