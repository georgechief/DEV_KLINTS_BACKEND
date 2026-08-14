"""Shared helpers for PRD-CONN-01 bootstrap acceptance tests."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from dataruns.connectors.base import (
    attach_run_to_data_run,
    complete_import_run,
    create_import_run,
    create_run_connector_snapshot,
    decrypt_connector_config,
    get_connector,
    mark_data_run_succeeded,
)
from dataruns.connectors.import_data import (
    _build_snapshot_data,
    _load_connector_map,
    _persist_contact_metrics,
    map_raw_payload,
    persist_normalized_records,
)
from dataruns.models import DataRun
from tenants.models import Company


def shopify_raw_payload() -> dict[str, list[dict[str, Any]]]:
    return {
        "customers": [
            {
                "id": 101,
                "email": "alice@example.com",
                "phone": "+111",
            }
        ],
        "orders": [
            {
                "id": 501,
                "email": "alice@example.com",
                "customer": {"id": 101, "email": "alice@example.com"},
                "total_price": "25.50",
                "currency": "USD",
                "financial_status": "paid",
                "created_at": "2026-07-15T10:00:00Z",
            }
        ],
        "transactions": [],
    }


def manago_raw_payload() -> dict[str, list[dict[str, Any]]]:
    return {
        "contacts": [
            {
                "contactId": "c-1",
                "email": "alice@example.com",
                "phone": "+111",
            }
        ],
        "transactions": [
            {
                "transactionId": "t-1",
                "value": 25.5,
                "currency": "USD",
                "email": "alice@example.com",
                "date": 1_752_500_400_000,
                "contactExtEventType": "PURCHASE",
            }
        ],
        "events": [],
    }


def successful_run_import_side_effect(
    *,
    platform: str,
    company: Company | None = None,
    data_run: DataRun | None = None,
    days: int | None = None,
    user=None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Simulate a successful import while persisting run/snapshot metadata."""
    if company is None or data_run is None:
        raise ValueError("company and data_run are required for bootstrap tests.")

    raw = shopify_raw_payload() if platform == "shopify" else manago_raw_payload()
    window_end = timezone.now()
    window_start = window_end - timedelta(days=days or 30)
    connector = get_connector(company=company, platform=platform)
    config = decrypt_connector_config(connector.config)
    connector_map = _load_connector_map(platform)
    run = create_import_run(company=company)
    attach_run_to_data_run(data_run=data_run, run=run)
    normalized = map_raw_payload(raw=raw, connector_map=connector_map, config=config)
    with transaction.atomic():
        counts = persist_normalized_records(company=company, normalized=normalized)
        contact_metrics_written = _persist_contact_metrics(run=run, company=company)
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
    success_counts = {**counts, "contact_metrics": contact_metrics_written}
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
        "window_start": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_end": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "succeeded",
        "counts": success_counts,
    }


def assert_health_report_shape(health_report: dict[str, Any]) -> None:
    """Assert PRD §5 top-level health_report fields are populated."""
    for key in (
        "platform",
        "days",
        "window_start",
        "window_end",
        "preflight",
        "fetch",
        "postflight",
        "blocking",
        "summary_status",
    ):
        assert key in health_report, f"missing health_report.{key}"

    assert health_report["window_start"] is not None
    assert health_report["window_end"] is not None
    assert isinstance(health_report["preflight"], dict)
    assert isinstance(health_report["fetch"], dict)
    assert isinstance(health_report["postflight"], dict)
    assert isinstance(health_report["postflight"].get("issues"), list)
    assert health_report["summary_status"] in {"ok", "degraded", "error"}
    assert isinstance(health_report["blocking"], bool)


def assert_connector_status_matches_summary(
    *,
    connector_status: str,
    summary_status: str,
) -> None:
    expected = {
        "ok": "connected",
        "degraded": "degraded",
        "error": "error",
    }[summary_status]
    assert connector_status == expected
