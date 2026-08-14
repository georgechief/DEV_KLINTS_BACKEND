"""Generic connector export (DB → shared-key or API-shaped JSON per PRD §6 / WB-01 §2.2)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from dataruns.connectors.base import resolve_company_from_user, resolve_tenant_from_user
from dataruns.connectors.mapping import reverse_map_record
from dataruns.models import Contact, Order, Run
from tenants.models import User

_SUPPORTED_PLATFORMS = frozenset({"shopify", "manago_ai"})
ExportShape = Literal["db", "api"]


def run_export(
    platform: str,
    user: User,
    run_id: Any,
    *,
    shape: ExportShape = "db",
) -> dict[str, Any]:
    """
    Export pipeline entry point (PRD §6).

    Loads the requested run for the user's company, reads normalized contacts
    and orders, and returns shared-key JSON (db_key field names).
    """
    if platform not in _SUPPORTED_PLATFORMS:
        raise ValueError(f"Unknown platform: {platform}")

    company = resolve_company_from_user(user)
    if company is None:
        raise ValueError("Company not found for this user.")

    resolve_tenant_from_user(user)

    run = Run.objects.filter(pk=run_id, company=company).first()
    if run is None:
        raise ValueError("Run not found for this company.")

    exported_contacts = [
        _contact_export_record(contact, platform=platform, shape=shape)
        for contact in Contact.objects.filter(company=company)
    ]
    exported_orders = [
        _order_export_record(order, platform=platform, shape=shape)
        for order in Order.objects.filter(company=company).select_related("contact")
    ]

    return {
        "platform": platform,
        "shape": shape,
        "run_id": str(run.id),
        "contacts": exported_contacts,
        "orders": exported_orders,
    }


def _contact_export_record(
    contact: Contact,
    *,
    platform: str,
    shape: ExportShape,
) -> dict[str, Any]:
    record = {
        "external_id": contact.external_id,
        "email": contact.email,
        "phone": contact.phone,
        "link_key": contact.link_key,
    }
    if shape == "api":
        return reverse_map_record(
            {k: v for k, v in record.items() if v not in (None, "")},
            platform=platform,
            entity="contact",
        )
    return {k: v for k, v in record.items() if v not in (None, "")}


def _order_export_record(
    order: Order,
    *,
    platform: str,
    shape: ExportShape,
) -> dict[str, Any]:
    record = {
        "external_id": order.external_id,
        "amount": _serialize_amount(order.amount),
        "currency": order.currency,
        "status": order.status,
        "contact_external_id": order.contact.external_id,
    }
    if shape == "api":
        return reverse_map_record(
            {k: v for k, v in record.items() if v not in (None, "")},
            platform=platform,
            entity="order",
        )
    return {k: v for k, v in record.items() if v not in (None, "")}


def _serialize_amount(value: Decimal) -> str:
    return str(value)
