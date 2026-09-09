"""Build frozen DCS scoring snapshot (PRD-DCS-03 v1)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from django.conf import settings

from dataruns.dcs.catalog_join import build_catalog_snapshot
from dataruns.dcs.consent_join import build_consent_snapshot
from dataruns.dcs.drift_join import build_drift_snapshot
from dataruns.dcs.identity_join import build_identity_snapshot
from dataruns.dcs.lifecycle_join import build_lifecycle_snapshot
from dataruns.dcs.product_truth import build_product_truth_snapshot
from dataruns.dcs.segment_join import build_segment_snapshot
from dataruns.dcs.workflow_join import build_workflow_snapshot
from dataruns.models import Contact, DataRun, Order
from tenants.models import Company, Connector


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _connector_status(*, company: Company, platform: str) -> dict[str, Any]:
    try:
        connector = Connector.objects.get(company=company, name=platform)
    except Connector.DoesNotExist:
        return {"status": "not_connected", "scopes": []}
    scopes: list[str] = []
    if platform == "shopify":
        from dataruns.connectors.bootstrap_health import parse_shopify_scopes

        scopes = sorted(parse_shopify_scopes((connector.config or {}).get("scopes")))
    return {
        "status": connector.status,
        "scopes": scopes,
    }


def _source_run_payload(
    *,
    data_run_id: int | None,
    fresh_imports: dict[str, Any],
    platform: str,
) -> dict[str, Any] | None:
    if data_run_id is None:
        return None
    fresh = fresh_imports.get(platform) or {}
    return {
        "data_run_id": data_run_id,
        "run_id": fresh.get("run_id"),
        "window_start": fresh.get("window_start"),
        "window_end": fresh.get("window_end"),
        "counts": fresh.get("counts") or {},
    }


def _gate_inputs_from_import(data_run_id: int | None) -> dict[str, Any]:
    if data_run_id is None:
        return {}
    try:
        data_run = DataRun.objects.get(pk=data_run_id)
    except DataRun.DoesNotExist:
        return {}
    health = (data_run.metadata or {}).get("health_report")
    if not isinstance(health, dict):
        return {}
    preflight = health.get("preflight") if isinstance(health.get("preflight"), dict) else {}
    fetch = health.get("fetch") if isinstance(health.get("fetch"), dict) else {}
    return {
        "summary_status": health.get("summary_status"),
        "days": health.get("days"),
        "window_start": health.get("window_start"),
        "window_end": health.get("window_end"),
        "auth_ok": preflight.get("auth_ok"),
        "scopes_granted": preflight.get("scopes_granted") or [],
        "scopes_missing": preflight.get("scopes_missing") or [],
        "rate_budget": fetch.get("rate_budget"),
        "counts": fetch.get("counts") or (data_run.metadata or {}).get("counts") or {},
        "issues": {
            "preflight": preflight.get("issues") or [],
            "fetch": fetch.get("issues") or [],
            "postflight": (
                (health.get("postflight") or {}).get("issues")
                if isinstance(health.get("postflight"), dict)
                else []
            ),
        },
    }


def _normalize_source_run_ids(source_runs: dict[str, Any]) -> dict[str, int | None]:
    out: dict[str, int | None] = {"shopify": None, "manago_ai": None}
    for platform in ("shopify", "manago_ai"):
        value = source_runs.get(platform)
        if value is None:
            continue
        try:
            out[platform] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def _pinned_snapshot_ids(fresh_imports: dict[str, Any]) -> dict[str, str | None]:
    """Optional direct snapshot ids from ``fresh_imports`` (Slice E fast path)."""
    out: dict[str, str | None] = {"shopify": None, "manago_ai": None}
    for platform in ("shopify", "manago_ai"):
        block = fresh_imports.get(platform)
        if not isinstance(block, dict):
            continue
        snapshot_id = block.get("snapshot_id")
        if snapshot_id is not None and str(snapshot_id).strip():
            out[platform] = str(snapshot_id)
    return out


def build_dcs_run_snapshot(
    *,
    company: Company,
    source_runs: dict[str, Any],
    fresh_imports: dict[str, Any] | None = None,
    window_days: int | None = None,
) -> dict[str, Any]:
    """
    Freeze scoring inputs after fresh import.

    v1 practical shape from PRD-DCS-03: counts + connector status + gate_inputs
    from the fresh import health_reports. Entity arrays stay empty until RULE
    executors need row-level evidence (listed in missing_inputs).
    """
    fresh_imports = fresh_imports or {}
    days = window_days if window_days is not None else settings.BOOTSTRAP_DAYS
    pinned_source_run_ids = _normalize_source_run_ids(source_runs)
    pinned_snapshot_ids = _pinned_snapshot_ids(fresh_imports)

    shopify_id = source_runs.get("shopify")
    manago_id = source_runs.get("manago_ai")
    if shopify_id is not None:
        try:
            shopify_id = int(shopify_id)
        except (TypeError, ValueError):
            shopify_id = None
    if manago_id is not None:
        try:
            manago_id = int(manago_id)
        except (TypeError, ValueError):
            manago_id = None

    shopify_fresh = fresh_imports.get("shopify") or {}
    manago_fresh = fresh_imports.get("manago_ai") or {}
    shopify_counts = shopify_fresh.get("counts") or {}
    manago_counts = manago_fresh.get("counts") or {}

    identity = build_identity_snapshot(company=company)
    identity_summary = identity.get("identity") or {}
    lifecycle = build_lifecycle_snapshot(
        company=company,
        source_run_ids=pinned_source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    lifecycle_summary = lifecycle.get("lifecycle") or {}
    consent = build_consent_snapshot(
        company=company,
        source_run_ids=pinned_source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    consent_summary = consent.get("consent") or {}
    product_truth = build_product_truth_snapshot(
        company=company,
        source_run_ids=pinned_source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    product_truth_summary = product_truth.get("product_truth") or {}
    catalog = build_catalog_snapshot(
        company=company,
        source_run_ids=pinned_source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    catalog_summary = catalog.get("catalog") or {}
    segment = build_segment_snapshot(
        company=company,
        source_run_ids=pinned_source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    segment_summary = segment.get("segment") or {}
    workflow = build_workflow_snapshot(
        company=company,
        source_run_ids=pinned_source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    measurement_summary = workflow.get("measurement") or {}
    drift = build_drift_snapshot(
        company=company,
        source_run_ids=pinned_source_run_ids,
        pinned_snapshot_ids=pinned_snapshot_ids,
    )
    drift_summary = drift.get("drift") or {}

    contact_total = Contact.objects.filter(company=company).count()
    order_total = Order.objects.filter(company=company).count()

    # RULE MVP1-A batch 4c: declare truly missing ingest surfaces only.
    missing_inputs: list[str] = []
    cat_raw = catalog_summary.get("raw_enrichment") or {}
    if not cat_raw.get("manago_catalog_present"):
        missing_inputs.append("manago_product_catalog")
    if not cat_raw.get("manago_catalog_meta_present"):
        missing_inputs.append("manago_catalog_list")
    if not (
        cat_raw.get("shopify_products_api_present")
        or cat_raw.get("shopify_line_items_present")
    ):
        missing_inputs.append("shopify_products")
    seg_raw = segment_summary.get("raw_enrichment") or {}
    if not seg_raw.get("details_present"):
        missing_inputs.append("details")
    if not seg_raw.get("tags_present"):
        missing_inputs.append("segments")
    meas_raw = measurement_summary.get("raw_enrichment") or {}
    if not meas_raw.get("workflow_definitions_present"):
        missing_inputs.append("workflows")
    raw_enrichment = lifecycle_summary.get("raw_enrichment") or {}
    if not raw_enrichment.get("return_events_from_raw"):
        missing_inputs.append("manago_return_events_raw")
    if not raw_enrichment.get("external_id_from_raw"):
        missing_inputs.append("manago_raw_external_id")
    if not raw_enrichment.get("test_filter_applied"):
        missing_inputs.append("shopify_test_order_filter")
    consent_raw = consent_summary.get("raw_enrichment") or {}
    if not consent_raw.get("consent_fields_present"):
        missing_inputs.append("consent_raw")
    if not consent_summary.get("hard_bounce_complaint_available"):
        missing_inputs.append("suppression_events")
    # Provenance fields exist on Manago consents[]; empty arrays still "present".
    if consent_raw.get("manago_contacts_from_raw") and int(
        consent_summary.get("opted_in_weak_or_missing_provenance") or 0
    ) == int(consent_summary.get("opted_in_manago_email") or 0) and int(
        consent_summary.get("opted_in_manago_email") or 0
    ) > 0:
        missing_inputs.append("consent_provenance")

    as_of = _utcnow_iso()
    return {
        "schema_version": "1.0.0",
        "company_id": str(company.id),
        "as_of": as_of,
        "window_days": days,
        "source_runs": {
            "shopify": _source_run_payload(
                data_run_id=shopify_id,
                fresh_imports=fresh_imports,
                platform="shopify",
            ),
            "manago_ai": _source_run_payload(
                data_run_id=manago_id,
                fresh_imports=fresh_imports,
                platform="manago_ai",
            ),
        },
        "connectors": {
            "shopify": _connector_status(company=company, platform="shopify"),
            "manago_ai": _connector_status(company=company, platform="manago_ai"),
            "erp": {"status": "not_connected"},
        },
        "counts": {
            "shopify_customers": int(
                shopify_counts.get("contacts")
                or identity_summary.get("shopify_customers")
                or 0
            ),
            "shopify_orders": int(
                shopify_counts.get("orders")
                or identity_summary.get("shopify_orders")
                or 0
            ),
            "shopify_paid_orders": int(
                lifecycle_summary.get("shopify_paid_orders") or 0
            ),
            "manago_contacts": int(
                manago_counts.get("contacts")
                or identity_summary.get("manago_contacts")
                or 0
            ),
            "manago_purchase_events": int(
                lifecycle_summary.get("manago_purchase_events") or 0
            ),
            "manago_cart_events": int(drift_summary.get("le08_cart_events") or 0),
            "manago_return_events": int(
                lifecycle_summary.get("manago_return_cancel_events") or 0
            ),
            "contacts_total": contact_total,
            "orders_total": order_total,
            "identity_in_both": int(identity_summary.get("in_both") or 0),
            "identity_manago_only": int(identity_summary.get("manago_only") or 0),
            "identity_shopify_only": int(identity_summary.get("shopify_only") or 0),
        },
        "contacts": identity.get("contacts") or [],
        # CI-02 needs all Shopify orders (incl. guests); LE-* use lifecycle summary.
        "orders": identity.get("orders") or [],
        "events": lifecycle.get("events") or [],
        "products": catalog.get("products") or [],
        "segments": segment.get("segments") or [],
        "details": segment.get("details") or [],
        "workflows": workflow.get("workflows") or [],
        "identity": identity_summary,
        "lifecycle": lifecycle_summary,
        "consent": consent_summary,
        "consent_rows": consent.get("consent_rows") or [],
        "product_truth": product_truth_summary,
        "product_truth_rows": product_truth.get("product_truth_rows") or [],
        "catalog": catalog_summary,
        "segment": segment_summary,
        "measurement": measurement_summary,
        "drift": drift_summary,
        "missing_inputs": missing_inputs,
        "gate_inputs": {
            "shopify": _gate_inputs_from_import(shopify_id),
            "manago_ai": _gate_inputs_from_import(manago_id),
        },
    }
