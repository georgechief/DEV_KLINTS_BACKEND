"""Persist connector fetch results into runs, snapshots, contacts, and orders."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from dataruns.models import Contact, ContactMetric, Order, Run, RunConnector, RunJob
from tenants.models import Company, Connector, ConnectorSnapshot
from tenants.shopify_fetch import _format_shopify_datetime

_SUCCESS_FINANCIAL_STATUSES = frozenset({"authorized", "pending"})


_SHOPIFY_FETCH_TRIGGER = "shopify_fetch"
_DEFAULT_RUN_JOB_PRIORITY = 0
_DEFAULT_RUN_JOB_MAX_ATTEMPTS = 1


def create_run_job(*, run: Run) -> RunJob:
    now = timezone.now()
    return RunJob.objects.create(
        run=run,
        trigger_type=_SHOPIFY_FETCH_TRIGGER,
        status="running",
        priority=_DEFAULT_RUN_JOB_PRIORITY,
        attempts=0,
        max_attempts=_DEFAULT_RUN_JOB_MAX_ATTEMPTS,
        queued_at=now,
        started_at=now,
        finished_at=None,
        error="",
    )


def mark_run_job_completed(*, run_job: RunJob) -> None:
    run_job.status = "completed"
    run_job.attempts = 1
    run_job.finished_at = timezone.now()
    run_job.error = ""
    run_job.save(update_fields=["status", "attempts", "finished_at", "error"])


def mark_run_job_failed(*, run_job: RunJob, error: str) -> None:
    run_job.status = "failed"
    run_job.attempts += 1
    run_job.finished_at = timezone.now()
    run_job.error = error
    run_job.save(update_fields=["status", "attempts", "finished_at", "error"])


def persist_shopify_fetch(
    *,
    run: Run,
    company: Company,
    connector: Connector,
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    transactions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    PRD §5 steps 8–12 for Shopify: snapshot, upserts, metrics, complete run.
    """
    transactions = transactions or []
    fetched_at = timezone.now()
    touched_contacts: dict[str, Contact] = {}

    with transaction.atomic():
        snapshot_data = {
            "ok": True,
            "connector": "shopify",
            "fetched_at": _format_shopify_datetime(fetched_at),
            "window_start": _format_shopify_datetime(window_start),
            "window_end": _format_shopify_datetime(window_end),
            "counts": {
                "customers": len(customers),
                "orders": len(orders),
                "transactions": len(transactions),
            },
            "notes": [],
            "customers": customers,
            "orders": orders,
            "transactions": transactions,
            "events": [],
        }
        last_version = (
            ConnectorSnapshot.objects.filter(connector=connector)
            .aggregate(Max("version"))["version__max"]
            or 0
        )
        snapshot = ConnectorSnapshot.objects.create(
            connector=connector,
            version=last_version + 1,
            snapshot_data=snapshot_data,
        )
        RunConnector.objects.create(run=run, connector_snapshot=snapshot)

        for customer in customers:
            contact = _upsert_shopify_customer(company, customer)
            if contact is not None:
                touched_contacts[contact.external_id] = contact

        orders_upserted = 0
        for order in orders:
            contact = _upsert_shopify_order_contact(company, order)
            if contact is None:
                continue
            touched_contacts[contact.external_id] = contact
            order_id = order.get("id")
            if order_id is None:
                continue
            amount = _decimal_or_zero(order.get("total_price"))
            currency = str(order.get("currency") or "")
            order_status = _map_shopify_order_status(
                str(order.get("financial_status") or "")
            )
            db_order, created = Order.objects.update_or_create(
                company=company,
                source="shopify",
                external_id=str(order_id),
                defaults={
                    "contact": contact,
                    "amount": amount,
                    "currency": currency,
                    "status": order_status,
                },
            )
            if created:
                source_created_at = _parse_api_datetime(order.get("created_at"))
                if source_created_at is not None:
                    Order.objects.filter(pk=db_order.pk).update(
                        created_at=source_created_at
                    )
            orders_upserted += 1

        metrics_written = 0
        for contact in touched_contacts.values():
            _upsert_contact_metric(run=run, company=company, contact=contact)
            metrics_written += 1

        run.status = Run.Status.COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])

    return {
        "run_id": str(run.id),
        "snapshot_id": str(snapshot.id),
        "connector": "shopify",
        "window_start": _format_shopify_datetime(window_start),
        "window_end": _format_shopify_datetime(window_end),
        "status": run.status,
        "counts": {
            "contacts": len(touched_contacts),
            "orders": orders_upserted,
            "contact_metrics": metrics_written,
        },
    }


def _upsert_shopify_customer(
    company: Company, customer: dict[str, Any]
) -> Contact | None:
    customer_id = customer.get("id")
    if customer_id is None:
        return None
    contact, _created = Contact.objects.update_or_create(
        company=company,
        source="shopify",
        external_id=str(customer_id),
        defaults={
            "email": str(customer.get("email") or ""),
            "phone": str(customer.get("phone") or ""),
        },
    )
    return contact


def _upsert_shopify_order_contact(
    company: Company,
    order: dict[str, Any],
) -> Contact | None:
    customer = order.get("customer") or {}
    customer_id = customer.get("id")
    email = str(customer.get("email") or order.get("email") or "").strip()
    phone = str(customer.get("phone") or "").strip()

    if customer_id is not None:
        contact, _created = Contact.objects.update_or_create(
            company=company,
            source="shopify",
            external_id=str(customer_id),
            defaults={"email": email, "phone": phone},
        )
        return contact

    if not email:
        return None

    contact, _created = Contact.objects.update_or_create(
        company=company,
        source="shopify",
        external_id=f"email:{email.lower()}",
        defaults={"email": email, "phone": phone},
    )
    return contact


def _map_shopify_order_status(financial_status: str) -> str:
    status = financial_status.lower()
    if status in ("paid", "partially_paid"):
        return Order.Status.PAID
    if status in ("refunded", "partially_refunded"):
        return Order.Status.REFUNDED
    if status in ("voided", "failed"):
        return Order.Status.FAILED
    if status in _SUCCESS_FINANCIAL_STATUSES:
        return Order.Status.PAID
    return Order.Status.FAILED


def _upsert_contact_metric(
    *, run: Run, company: Company, contact: Contact
) -> ContactMetric:
    orders_qs = Order.objects.filter(company=company, contact=contact)
    total_orders = orders_qs.count()
    total_revenue = orders_qs.filter(status=Order.Status.PAID).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")
    last_order_at = orders_qs.aggregate(last=Max("created_at"))["last"]
    if total_orders > 0:
        avg_order_value = total_revenue / total_orders
    else:
        avg_order_value = Decimal("0")
    if total_orders == 0:
        lifecycle_stage = ""
    elif total_orders == 1:
        lifecycle_stage = "new"
    else:
        lifecycle_stage = "repeat"

    metric, _created = ContactMetric.objects.update_or_create(
        run=run,
        contact=contact,
        defaults={
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "last_order_at": last_order_at,
            "avg_order_value": avg_order_value,
            "ltv": total_revenue,
            "lifecycle_stage": lifecycle_stage,
        },
    )
    return metric


def _decimal_or_zero(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _parse_api_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)

