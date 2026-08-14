"""Generic connector import orchestration (fetch → map → persist)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from dataruns.connectors.mapping import (
    load_connector_map,
    map_api_to_db,
)
from dataruns.connectors.base import (
    attach_run_to_data_run,
    bootstrap_data_run_may_persist,
    complete_import_run,
    create_connector_data_run,
    create_import_run,
    create_run_connector_snapshot,
    decrypt_connector_config,
    finalize_import_run_on_failure,
    get_connector,
    mark_data_run_failed,
    mark_data_run_succeeded,
    resolve_company_from_data_run,
    resolve_company_from_user,
    resolve_tenant_from_user,
)
from dataruns.connectors.manago_ai.client import FetchWindow as ManagoFetchWindow
from dataruns.connectors.manago_ai.client import ManagoClient
from dataruns.connectors.shopify.client import FetchWindow as ShopifyFetchWindow
from dataruns.connectors.shopify.client import ShopifyClient
from dataruns.models import Contact, ContactMetric, DataRun, Order, Run
from tenants.crypto import SECRET_CONFIG_FIELDS
from tenants.models import Company, User

_SUPPORTED_PLATFORMS = frozenset({"shopify", "manago_ai"})


class ImportFailedError(Exception):
    """Raised when import fails after a DataRun has been created (PRD §6b, §7)."""

    def __init__(self, message: str, *, data_run_id: int) -> None:
        super().__init__(message)
        self.data_run_id = data_run_id


class BootstrapSupersededError(Exception):
    """Raised when a bootstrap import must stop because credentials were refreshed."""

    def __init__(self, *, data_run_id: int) -> None:
        super().__init__(f"Bootstrap DataRun {data_run_id} was superseded.")
        self.data_run_id = data_run_id


def _assert_bootstrap_may_persist(data_run: DataRun) -> None:
    if not bootstrap_data_run_may_persist(data_run):
        raise BootstrapSupersededError(data_run_id=data_run.id)


def run_import(
    platform: str,
    user: User | None = None,
    days: int | None = None,
    *,
    company: Company | None = None,
    data_run: DataRun | None = None,
) -> dict[str, Any]:
    """
    Import pipeline entry point (PRD §6, PRD-CONN-01 §4 E4).

    Orchestrates workspace resolution, connector load, fetch, and (later)
    mapping + persistence.

    Callers must provide either ``user`` or ``company`` (or a ``data_run``
    whose metadata includes ``company_id``). When ``data_run`` is omitted,
    ``user`` is required (manual fetch path).
    """
    if platform not in _SUPPORTED_PLATFORMS:
        raise ValueError(f"Unknown platform: {platform}")
    if days is None:
        days = settings.BOOTSTRAP_DAYS
    if days < 1 or days > 31:
        raise ValueError("days must be between 1 and 31")

    if company is None:
        if user is not None:
            company = resolve_company_from_user(user)
        elif data_run is not None:
            company = resolve_company_from_data_run(data_run)
    if company is None:
        raise ValueError("Company not found for this import.")

    if user is not None:
        resolve_tenant_from_user(user)

    connector = get_connector(company=company, platform=platform)
    config = decrypt_connector_config(connector.config)
    connector_map = load_connector_map(platform)
    client = _build_client(platform, config)

    window_end = timezone.now()
    window_start = window_end - timedelta(days=days)
    window = _build_fetch_window(platform, window_start, window_end)

    if data_run is None:
        if user is None:
            raise ValueError("user is required when data_run is not provided.")
        data_run = create_connector_data_run(
            user=user,
            platform=platform,
            days=days,
            company=company,
        )
    raw: dict[str, Any] = {}
    normalized: dict[str, Any] = {"contacts": [], "orders": []}
    run: Run | None = None

    try:
        raw = client.fetch(window)
        rate_budget = getattr(client, "last_rate_budget", None)
        normalized = map_raw_payload(
            raw=raw,
            connector_map=connector_map,
            config=config,
        )

        _assert_bootstrap_may_persist(data_run)

        run = create_import_run(company=company)
        attach_run_to_data_run(data_run=data_run, run=run)

        with transaction.atomic():
            counts = persist_normalized_records(
                company=company,
                normalized=normalized,
                platform=platform,
            )
            contact_metrics_written = _persist_contact_metrics(
                run=run,
                company=company,
            )
            snapshot_data = _build_snapshot_data(
                platform=platform,
                raw=raw,
                normalized=normalized,
                connector_config=connector.config,
                window_start=window_start,
                window_end=window_end,
            )
            snapshot = create_run_connector_snapshot(
                run=run,
                connector=connector,
                snapshot_data=snapshot_data,
            )
            complete_import_run(run=run)

        _assert_bootstrap_may_persist(data_run)

        success_counts = {
            **counts,
            "contact_metrics": contact_metrics_written,
        }
        mark_data_run_succeeded(
            data_run=data_run,
            counts=success_counts,
            snapshot=snapshot,
        )

        return {
            "data_run_id": data_run.id,
            "run_id": str(run.id),
            "snapshot_id": str(snapshot.id),
            "connector": platform,
            "window_start": _format_timestamp(window_start),
            "window_end": _format_timestamp(window_end),
            "status": "succeeded",
            "counts": success_counts,
            "rate_budget": rate_budget,
        }
    except BootstrapSupersededError:
        raise
    except Exception as exc:
        if not bootstrap_data_run_may_persist(data_run):
            raise BootstrapSupersededError(data_run_id=data_run.id) from exc

        if run is None:
            run = create_import_run(company=company)
            attach_run_to_data_run(data_run=data_run, run=run)

        failure_snapshot_data = _build_failure_snapshot_data(
            platform=platform,
            raw=raw,
            normalized=normalized,
            connector_config=connector.config,
            window_start=window_start,
            window_end=window_end,
            exc=exc,
        )
        create_run_connector_snapshot(
            run=run,
            connector=connector,
            snapshot_data=failure_snapshot_data,
        )
        mark_data_run_failed(data_run=data_run, exc=exc)
        finalize_import_run_on_failure(run=run)
        raise ImportFailedError(str(exc), data_run_id=data_run.id) from exc


def map_raw_payload(
    *,
    raw: dict[str, Any],
    connector_map: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Map raw platform payloads to shared-key normalized records (PRD §4, §6 step 7).

    Uses map.json key_mapping (api_key -> db_key) and status_map only.
    """
    key_mapping = connector_map.get("key_mapping")
    if not isinstance(key_mapping, list):
        raise ValueError("connector map is missing key_mapping.")

    status_map = connector_map.get("status_map")
    if status_map is not None and not isinstance(status_map, dict):
        raise ValueError("connector map status_map must be a JSON object.")

    mappings_by_entity = _group_mappings_by_entity(key_mapping)
    contacts_by_id: dict[str, dict[str, Any]] = {}
    orders_by_id: dict[str, dict[str, Any]] = {}

    for source in _raw_sources(connector_map):
        collection = source["collection"]
        entity = source["entity"]
        mappings = mappings_by_entity.get(entity, [])
        if not mappings:
            continue

        items = raw.get(collection)
        if not isinstance(items, list):
            continue

        target = _normalized_target(entity, contacts_by_id, orders_by_id)
        if target is None:
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            record = map_api_to_db(item, mappings, status_map)
            external_id = record.get("external_id")
            if external_id is not None and str(external_id).strip():
                target[str(external_id)] = record

    normalized_config: dict[str, Any] = {}
    config_mappings = mappings_by_entity.get("config", [])
    if config is not None and config_mappings:
        normalized_config = map_api_to_db(config, config_mappings, status_map)

    return {
        "contacts": list(contacts_by_id.values()),
        "orders": list(orders_by_id.values()),
        "config": normalized_config,
    }


def persist_normalized_records(
    *,
    company: Company,
    normalized: dict[str, Any],
    platform: str,
) -> dict[str, int]:
    """
    Upsert normalized contacts and orders (PRD §8).

    Uniqueness is (company, source=platform, external_id) so Shopify and Manago
    never overwrite each other when raw IDs collide.
    """
    if platform not in _SUPPORTED_PLATFORMS:
        raise ValueError(f"Unknown platform: {platform}")

    contacts_upserted = 0
    orders_upserted = 0

    contact_records = list(normalized.get("contacts") or [])
    if not isinstance(contact_records, list):
        contact_records = []

    # Shopify guest checkouts: order has email but no customer.id → synthesize contact.
    if platform == "shopify":
        contact_records = _with_shopify_guest_contacts(
            contact_records=contact_records,
            order_records=normalized.get("orders") or [],
            raw_orders_hint=normalized,
        )

    for record in contact_records:
        if not isinstance(record, dict):
            continue
        external_id = record.get("external_id")
        if external_id is None or not str(external_id).strip():
            continue
        Contact.objects.update_or_create(
            company=company,
            source=platform,
            external_id=str(external_id),
            defaults={
                "email": str(record.get("email") or ""),
                "phone": str(record.get("phone") or ""),
                "link_key": str(record.get("link_key") or "").strip(),
            },
        )
        contacts_upserted += 1
        source_created_at = _parse_order_created_at(record.get("created_at"))
        if source_created_at is not None:
            Contact.objects.filter(
                company=company,
                source=platform,
                external_id=str(external_id),
            ).update(created_at=source_created_at)

    order_records = normalized.get("orders")
    if not isinstance(order_records, list):
        order_records = []

    for record in order_records:
        if not isinstance(record, dict):
            continue
        external_id = record.get("external_id")
        contact_external_id = record.get("contact_external_id")
        email = str(record.get("email") or "").strip()
        if external_id is None or not str(external_id).strip():
            continue
        # Guest Shopify orders: bind via email:{normalized} contact.
        if (
            (contact_external_id is None or not str(contact_external_id).strip())
            and platform == "shopify"
            and email
        ):
            contact_external_id = f"email:{email.lower()}"

        if contact_external_id is None or not str(contact_external_id).strip():
            continue

        # Same-platform contact only — never attach a Shopify order to a Manago contact.
        contact = Contact.objects.filter(
            company=company,
            source=platform,
            external_id=str(contact_external_id),
        ).first()
        if contact is None:
            contact = Contact.objects.filter(
                company=company,
                source=platform,
                email__iexact=str(contact_external_id),
            ).first()
        if contact is None and email:
            contact = Contact.objects.filter(
                company=company,
                source=platform,
                email__iexact=email,
            ).first()
        if contact is None:
            continue

        db_order, created = Order.objects.update_or_create(
            company=company,
            source=platform,
            external_id=str(external_id),
            defaults={
                "contact": contact,
                "amount": _decimal_or_zero(record.get("amount")),
                "currency": str(record.get("currency") or ""),
                "status": str(record.get("status") or ""),
            },
        )
        source_created_at = _parse_order_created_at(record.get("created_at"))
        if source_created_at is not None:
            Order.objects.filter(pk=db_order.pk).update(created_at=source_created_at)
        orders_upserted += 1

    return {
        "contacts": contacts_upserted,
        "orders": orders_upserted,
    }


def _with_shopify_guest_contacts(
    *,
    contact_records: list[Any],
    order_records: Any,
    raw_orders_hint: dict[str, Any],
) -> list[Any]:
    """Ensure guest Shopify orders get an email:{addr} contact row."""
    del raw_orders_hint  # reserved for future raw-path enrichment
    existing_ids = {
        str(r.get("external_id"))
        for r in contact_records
        if isinstance(r, dict) and r.get("external_id") is not None
    }
    enriched = list(contact_records)
    if not isinstance(order_records, list):
        return enriched

    for order in order_records:
        if not isinstance(order, dict):
            continue
        if order.get("contact_external_id"):
            continue
        email = str(order.get("email") or "").strip()
        if not email:
            continue
        guest_id = f"email:{email.lower()}"
        if guest_id in existing_ids:
            continue
        enriched.append(
            {
                "external_id": guest_id,
                "email": email,
                "phone": "",
            }
        )
        existing_ids.add(guest_id)
        # Mutate order so persist can link without a second pass.
        order["contact_external_id"] = guest_id
    return enriched



def _persist_contact_metrics(*, run: Run, company: Company) -> int:
    metrics_written = 0
    for contact in Contact.objects.filter(company=company):
        _upsert_contact_metric(run=run, company=company, contact=contact)
        metrics_written += 1
    return metrics_written


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


def _build_snapshot_data(
    *,
    platform: str,
    raw: dict[str, Any],
    normalized: dict[str, Any],
    connector_config: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    fetched_at = timezone.now()
    return {
        "ok": True,
        "platform": platform,
        "fetched_at": _format_timestamp(fetched_at),
        "window_start": _format_timestamp(window_start),
        "window_end": _format_timestamp(window_end),
        "raw": raw,
        "normalized": {
            "contacts": normalized.get("contacts", []),
            "orders": normalized.get("orders", []),
        },
        "config": _snapshot_config(connector_config),
        "notes": [],
    }


def _build_failure_snapshot_data(
    *,
    platform: str,
    raw: dict[str, Any],
    normalized: dict[str, Any],
    connector_config: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    exc: BaseException,
) -> dict[str, Any]:
    fetched_at = timezone.now()
    return {
        "ok": False,
        "platform": platform,
        "fetched_at": _format_timestamp(fetched_at),
        "window_start": _format_timestamp(window_start),
        "window_end": _format_timestamp(window_end),
        "raw": raw,
        "normalized": {
            "contacts": normalized.get("contacts", []),
            "orders": normalized.get("orders", []),
        },
        "config": _snapshot_config(connector_config),
        "notes": [str(exc)],
    }


def _snapshot_config(config: dict[str, Any]) -> dict[str, Any]:
    safe_config = dict(config or {})
    for field in SECRET_CONFIG_FIELDS:
        safe_config.pop(field, None)
    return safe_config


def _format_timestamp(value: datetime) -> str:
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone=dt_timezone.utc)
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decimal_or_zero(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _parse_order_created_at(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=dt_timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


def _group_mappings_by_entity(
    key_mapping: list[Any],
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for entry in key_mapping:
        if not isinstance(entry, dict):
            continue
        entity = entry.get("entity")
        api_key = entry.get("api_key")
        db_key = entry.get("db_key")
        if not isinstance(entity, str) or not entity.strip():
            continue
        if not isinstance(api_key, str) or not api_key.strip():
            continue
        if not isinstance(db_key, str) or not db_key.strip():
            continue
        grouped.setdefault(entity, []).append(
            {"api_key": api_key, "db_key": db_key}
        )
    return grouped


def _raw_sources(connector_map: dict[str, Any]) -> list[dict[str, str]]:
    raw_sources = connector_map.get("raw_sources")
    if not isinstance(raw_sources, list):
        raise ValueError("connector map is missing raw_sources.")

    sources: list[dict[str, str]] = []
    for source in raw_sources:
        if not isinstance(source, dict):
            continue
        collection = source.get("collection")
        entity = source.get("entity")
        if not isinstance(collection, str) or not collection.strip():
            continue
        if not isinstance(entity, str) or not entity.strip():
            continue
        sources.append({"collection": collection.strip(), "entity": entity.strip()})
    if not sources:
        raise ValueError("connector map raw_sources is empty.")
    return sources


def _normalized_target(
    entity: str,
    contacts_by_id: dict[str, dict[str, Any]],
    orders_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]] | None:
    if entity == "contact":
        return contacts_by_id
    if entity == "order":
        return orders_by_id
    return None


# Backward-compatible alias for tests / helpers that import from import_data.
_load_connector_map = load_connector_map


def _build_client(platform: str, config: dict[str, Any]) -> ShopifyClient | ManagoClient:
    if platform == "shopify":
        return ShopifyClient(config)
    if platform == "manago_ai":
        return ManagoClient(config)
    raise ValueError(f"Unknown platform: {platform}")


def _build_fetch_window(
    platform: str,
    window_start: Any,
    window_end: Any,
) -> ShopifyFetchWindow | ManagoFetchWindow:
    if platform == "shopify":
        return ShopifyFetchWindow(
            window_start=window_start,
            window_end=window_end,
        )
    if platform == "manago_ai":
        return ManagoFetchWindow(
            window_start=window_start,
            window_end=window_end,
        )
    raise ValueError(f"Unknown platform: {platform}")
