"""Load FoundationGateContext from company connectors + bootstrap health (DB)."""

from __future__ import annotations

from typing import Any

from dataruns.connectors.base import (
    CONNECTOR_BOOTSTRAP_KIND,
    CONNECTOR_FETCH_KIND,
    decrypt_connector_config,
    find_latest_bootstrap_data_run,
)
from dataruns.dcs.context_builder import (
    apply_live_manago_auth,
    apply_live_shopify_auth,
    build_foundation_gate_context,
)
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.manago_tracking import load_manago_tracking_evidence
from dataruns.models import DataRun
from tenants.models import Company, Connector

_CONNECTED_STATUSES = frozenset({"connected", "degraded"})
_FD07_TRACKING_LOOKBACK_DAYS = 30
_SOURCE_RUN_KINDS = frozenset({CONNECTOR_BOOTSTRAP_KIND, CONNECTOR_FETCH_KIND})
_VISIT_TYPES = frozenset({"VISIT", "PAGE_VIEW", "PAGEVIEW", "VIEW"})


def find_latest_succeeded_bootstrap_data_run(
    *,
    company: Company,
    platform: str,
) -> DataRun | None:
    """Prefer the latest succeeded bootstrap DataRun for a platform."""
    return (
        DataRun.objects.filter(
            name=f"connector-bootstrap:{platform}",
            status=DataRun.Status.SUCCEEDED,
            metadata__kind=CONNECTOR_BOOTSTRAP_KIND,
            metadata__company_id=str(company.id),
            metadata__platform=platform,
        )
        .order_by("-created_at")
        .first()
    )


def _resolve_bootstrap_run(
    *,
    company: Company,
    platform: str,
    source_run_id: str | int | None,
) -> DataRun | None:
    if source_run_id is not None and str(source_run_id).strip():
        try:
            data_run = DataRun.objects.get(pk=source_run_id)
        except (DataRun.DoesNotExist, ValueError, TypeError):
            return None
        meta = data_run.metadata or {}
        # Accept bootstrap or DCS fresh-import (connector_fetch) source runs.
        if meta.get("kind") not in _SOURCE_RUN_KINDS:
            return None
        if meta.get("platform") != platform:
            return None
        if str(meta.get("company_id") or "") != str(company.id):
            return None
        return data_run

    succeeded = find_latest_succeeded_bootstrap_data_run(
        company=company, platform=platform
    )
    if succeeded is not None:
        return succeeded

    try:
        connector = Connector.objects.get(company=company, name=platform)
    except Connector.DoesNotExist:
        return None
    return find_latest_bootstrap_data_run(company=company, connector=connector)


def _connector_payload(
    *,
    company: Company,
    platform: str,
    source_run_id: str | int | None = None,
) -> dict[str, Any]:
    try:
        connector = Connector.objects.get(company=company, name=platform)
    except Connector.DoesNotExist:
        return {
            "connected": False,
            "status": "not_connected",
            "data_run_id": None,
            "health_report": None,
        }

    bootstrap = _resolve_bootstrap_run(
        company=company,
        platform=platform,
        source_run_id=source_run_id,
    )
    health = None
    data_run_id = None
    if bootstrap is not None:
        data_run_id = bootstrap.id
        raw_health = (bootstrap.metadata or {}).get("health_report")
        health = raw_health if isinstance(raw_health, dict) else None

    scopes = None
    if isinstance(health, dict):
        preflight = health.get("preflight")
        if isinstance(preflight, dict) and isinstance(
            preflight.get("scopes_granted"), list
        ):
            scopes = preflight["scopes_granted"]

    connected = connector.status in _CONNECTED_STATUSES
    return {
        "connected": connected,
        "status": connector.status,
        "data_run_id": data_run_id,
        "health_report": health,
        "scopes_granted": scopes,
        # Tracking filled later via Manago recentActivity (FD-07).
        "topology_ok": None,
        "tracking_measurable": None,
        "tracking_active": None,
        "visit_events_recent": None,
        "smclient_cookie_seen": None,
        "_connector_id": str(connector.id),
        "_config": connector.config or {},
    }


def _apply_manago_tracking_evidence(
    payload: dict[str, Any],
    *,
    company: Company | None = None,
) -> None:
    """Populate FD-07 VISIT/smclient proxies when Manago is connected."""
    if not payload.get("connected"):
        return
    config = payload.get("_config")
    if not isinstance(config, dict) or not config:
        payload["tracking_measurable"] = False
        return

    evidence = load_manago_tracking_evidence(
        config=config,
        lookback_days=_FD07_TRACKING_LOOKBACK_DAYS,
    )
    payload.update(evidence.as_payload())
    # Keep raw counts for debugging / evidence enrichment on the gate context.
    payload["_tracking_detail"] = evidence.detail

    # Fallback: if recentActivity is empty, use ingested Manago VISIT events.
    if evidence.tracking_measurable and not evidence.tracking_active and company is not None:
        _enrich_tracking_from_ingested_events(payload, company=company)


def _enrich_tracking_from_ingested_events(
    payload: dict[str, Any],
    *,
    company: Company,
) -> None:
    """Flip FD-07 visit signals from ingested Manago events when API is quiet."""
    try:
        from dataruns.dcs.lifecycle_join import _latest_connector_raw

        raw = _latest_connector_raw(company=company, platform="manago_ai")
    except Exception:
        return
    if not isinstance(raw, dict):
        return

    events = [
        e
        for e in (raw.get("events") or [])
        if isinstance(e, dict)
        and str(e.get("contactExtEventType") or e.get("eventType") or "").upper()
        in _VISIT_TYPES
    ]
    if not events:
        return

    identified = sum(
        1
        for e in events
        if e.get("contactId") or e.get("cid") or e.get("email") or e.get("contactEmail")
    )
    payload["visit_events_recent"] = True
    if identified > 0:
        payload["smclient_cookie_seen"] = True
    payload["tracking_active"] = True
    detail = payload.get("_tracking_detail")
    if not isinstance(detail, dict):
        detail = {}
    payload["_tracking_detail"] = {
        **detail,
        "ingested_visit_events": len(events),
        "ingested_identified_visits": identified,
        "source": "ingested_events_fallback",
    }


def _apply_manago_topology(
    payload: dict[str, Any],
    *,
    shopify_shop_domain: str | None = None,
) -> None:
    """Enumerate Manago owners/sub-accounts and classify for FD-06."""
    if not payload.get("connected"):
        return
    config = payload.get("_config")
    if not isinstance(config, dict) or not config:
        payload["topology_ok"] = False
        payload["topology_accounts"] = []
        payload["_topology_error"] = "Manago connector config missing."
        return

    from dataruns.dcs.topology import load_manago_topology

    # Pass connector config as stored (api_key still encrypted); loader decrypts.
    result = load_manago_topology(
        config=dict(config),
        shopify_shop_domain=shopify_shop_domain,
    )
    payload["topology_ok"] = result.topology_ok
    payload["topology_accounts"] = result.topology_accounts
    payload["_topology_registry"] = result.registry
    if result.error:
        payload["_topology_error"] = result.error


def _shopify_shop_domain(payload: dict[str, Any]) -> str | None:
    config = payload.get("_config")
    if not isinstance(config, dict):
        return None
    for key in ("shop_domain", "shop"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _apply_rate_budget(payload: dict[str, Any], *, platform: str) -> None:
    """FD-04: reuse import-measured budget, else controlled probe."""
    if not payload.get("connected"):
        return

    from dataruns.dcs.rate_budget import (
        measure_manago_rate_budget,
        measure_shopify_rate_budget,
        rate_budget_from_health,
    )

    existing = rate_budget_from_health(payload.get("health_report"))
    if isinstance(existing, dict) and existing:
        payload["rate_budget"] = existing
        return

    config = decrypt_connector_config(dict(payload.get("_config") or {}))
    try:
        if platform == "shopify":
            shop = str(config.get("shop") or config.get("shop_domain") or "")
            token = str(config.get("access_token") or "")
            if shop and token:
                payload["rate_budget"] = measure_shopify_rate_budget(
                    shop=shop,
                    access_token=token,
                )
        elif platform == "manago_ai":
            client_id = str(
                config.get("client_id") or config.get("workspace_id") or ""
            )
            api_secret = str(
                config.get("api_secret") or config.get("api_key") or ""
            )
            if client_id and api_secret:
                payload["rate_budget"] = measure_manago_rate_budget(
                    client_id=client_id,
                    api_secret=api_secret,
                    endpoint=config.get("base_url") or config.get("endpoint"),
                )
    except Exception as exc:  # noqa: BLE001 — surface as missing/failed measure
        payload["rate_budget"] = {
            "platform": platform,
            "hit_rate_limit": "429" in str(exc) or "rate limit" in str(exc).lower(),
            "headroom_ok": False,
            "source": "probe",
            "error": str(exc),
        }


def _apply_history_depth(
    payload: dict[str, Any],
    *,
    company: Company,
    platform: str,
    required_days: int,
) -> dict[str, Any] | None:
    """FD-05: earliest timestamps per entity from ingested rows."""
    if not payload.get("connected"):
        return None

    from dataruns.dcs.history_depth import (
        compute_history_depth,
        history_earliest_payload,
    )

    depth = compute_history_depth(
        company=company,
        platform=platform,
        required_days=required_days,
    )
    earliest = history_earliest_payload(depth)
    if earliest:
        payload["history_earliest"] = earliest
    payload["_history_depth"] = depth
    return depth


def _maybe_live_revalidate(
    *,
    platform: str,
    payload: dict[str, Any],
    gate_context: FoundationGateContext,
) -> None:
    """Optional cheap live auth probe (PRD-DCS-02)."""
    if not payload.get("connected"):
        return
    config = decrypt_connector_config(dict(payload.get("_config") or {}))

    if platform == "manago_ai" and gate_context.manago is not None:
        from tenants.manago import verify_credentials

        client_id = str(config.get("client_id") or "")
        api_secret = str(
            config.get("api_secret") or config.get("api_key") or ""
        )
        if client_id and api_secret:
            apply_live_manago_auth(
                gate_context.manago,
                verify=verify_credentials,
                client_id=client_id,
                api_secret=api_secret,
                endpoint=config.get("base_url") or config.get("endpoint"),
            )
        return

    if platform == "shopify" and gate_context.shopify is not None:
        from tenants.shopify import fetch_shop

        shop = str(config.get("shop") or config.get("shop_domain") or "")
        token = str(config.get("access_token") or "")
        if shop and token:
            apply_live_shopify_auth(
                gate_context.shopify,
                fetch_shop=fetch_shop,
                shop=shop,
                access_token=token,
            )


def build_foundation_context_for_company(
    *,
    company: Company,
    tenant_id: str,
    run_id: str,
    erp_in_scope: bool = False,
    source_run_ids: dict[str, Any] | None = None,
    live_revalidate: bool = False,
    bootstrap_days_required: int = 30,
) -> tuple[FoundationGateContext, dict[str, Any]]:
    """
    Build gate context from DB connectors + bootstrap health_report.

    Returns (context, resolved_source_runs) where resolved_source_runs maps
    platform → bootstrap data_run id (or None).
    """
    source_run_ids = source_run_ids or {}
    manago_src = source_run_ids.get("manago_ai")
    shopify_src = source_run_ids.get("shopify")

    manago_payload = _connector_payload(
        company=company, platform="manago_ai", source_run_id=manago_src
    )
    shopify_payload = _connector_payload(
        company=company, platform="shopify", source_run_id=shopify_src
    )

    resolved = {
        "manago_ai": manago_payload.get("data_run_id"),
        "shopify": shopify_payload.get("data_run_id"),
    }

    _apply_manago_tracking_evidence(manago_payload, company=company)
    _apply_manago_topology(
        manago_payload,
        shopify_shop_domain=_shopify_shop_domain(shopify_payload),
    )
    _apply_rate_budget(manago_payload, platform="manago_ai")
    _apply_rate_budget(shopify_payload, platform="shopify")
    manago_depth = _apply_history_depth(
        manago_payload,
        company=company,
        platform="manago_ai",
        required_days=bootstrap_days_required,
    )
    shopify_depth = _apply_history_depth(
        shopify_payload,
        company=company,
        platform="shopify",
        required_days=bootstrap_days_required,
    )

    ctx = build_foundation_gate_context(
        manago=manago_payload,
        shopify=shopify_payload,
        erp={"in_scope": erp_in_scope, "connected": False},
        tenant_id=tenant_id,
        run_id=run_id,
        bootstrap_days_required=bootstrap_days_required,
        company_website_domain=getattr(company, "domain", None),
    )
    if ctx.manago is not None and manago_payload.get("_tracking_detail"):
        ctx.extra["manago_tracking_detail"] = manago_payload["_tracking_detail"]
    if manago_payload.get("_topology_registry"):
        ctx.extra["manago_topology"] = manago_payload["_topology_registry"]
    if manago_payload.get("_topology_error"):
        ctx.extra["manago_topology_error"] = manago_payload["_topology_error"]

    from dataruns.dcs.history_depth import shortest_common_window_days

    history_depths = [
        d for d in (manago_depth, shopify_depth) if isinstance(d, dict)
    ]
    if history_depths:
        ctx.extra["history_depth"] = {
            "platforms": {
                d["platform"]: d for d in history_depths if d.get("platform")
            },
            "common_window_days": shortest_common_window_days(history_depths),
        }

    if live_revalidate:
        _maybe_live_revalidate(
            platform="manago_ai", payload=manago_payload, gate_context=ctx
        )
        _maybe_live_revalidate(
            platform="shopify", payload=shopify_payload, gate_context=ctx
        )

    return ctx, resolved
