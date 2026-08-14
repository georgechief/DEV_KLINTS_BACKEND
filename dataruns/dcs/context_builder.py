"""Build FoundationGateContext from connector / bootstrap payloads.

Keeps Django optional so unit tests can pass plain dicts. Live credential
revalidation is opt-in via callables (sheet 02 signed Manago call / shop.json).
"""

from __future__ import annotations

from typing import Any, Callable

from dataruns.dcs.executors.foundation import (
    ConnectorGateInput,
    FoundationGateContext,
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def connector_gate_from_payload(
    *,
    platform: str,
    payload: dict[str, Any] | None,
) -> ConnectorGateInput | None:
    """Map a connector-shaped dict into ConnectorGateInput."""
    if not payload:
        return None
    connected = bool(payload.get("connected", True))
    status = payload.get("status") or payload.get("connector_status")
    if isinstance(status, str) and status.lower() in {"disconnected", "not_connected"}:
        connected = False

    health = payload.get("health_report")
    if health is None:
        health = payload.get("bootstrap_health")
    health = health if isinstance(health, dict) else None

    preflight = _as_dict((health or {}).get("preflight"))
    scopes = payload.get("scopes_granted")
    if scopes is None:
        scopes = preflight.get("scopes_granted")
    if scopes is not None and not isinstance(scopes, list):
        scopes = [str(scopes)]

    return ConnectorGateInput(
        platform=platform,
        connected=connected,
        connector_status=str(status) if status is not None else None,
        data_run_id=payload.get("data_run_id"),
        health_report=health,
        live_auth_ok=payload.get("live_auth_ok"),
        live_auth_message=payload.get("live_auth_message"),
        scopes_granted=[str(s) for s in scopes] if isinstance(scopes, list) else None,
        topology_ok=payload.get("topology_ok"),
        topology_accounts=payload.get("topology_accounts"),
        tracking_measurable=payload.get("tracking_measurable"),
        tracking_active=payload.get("tracking_active"),
        visit_events_recent=payload.get("visit_events_recent"),
        smclient_cookie_seen=payload.get("smclient_cookie_seen"),
        storefront_domains=payload.get("storefront_domains"),
        history_earliest=payload.get("history_earliest"),
        rate_budget=payload.get("rate_budget"),
    )


def apply_live_manago_auth(
    gate: ConnectorGateInput,
    *,
    verify: Callable[..., Any],
    client_id: str,
    api_secret: str,
    endpoint: str | None = None,
) -> ConnectorGateInput:
    """Run Manago verify_credentials and stamp live_auth_* on the gate input."""
    result = verify(
        client_id=client_id,
        api_secret=api_secret,
        endpoint=endpoint,
    )
    valid = bool(getattr(result, "valid", False))
    message = str(getattr(result, "message", "") or "")
    gate.live_auth_ok = valid
    gate.live_auth_message = message
    return gate


def apply_live_shopify_auth(
    gate: ConnectorGateInput,
    *,
    fetch_shop: Callable[..., Any],
    shop: str,
    access_token: str,
) -> ConnectorGateInput:
    """Run Shopify shop.json probe and stamp live_auth_* on the gate input."""
    try:
        fetch_shop(shop=shop, access_token=access_token)
        gate.live_auth_ok = True
        gate.live_auth_message = "shop.json ok"
    except Exception as exc:  # noqa: BLE001 — surface as auth fail for gate
        gate.live_auth_ok = False
        gate.live_auth_message = str(exc)
    return gate


def build_foundation_gate_context(
    *,
    manago: dict[str, Any] | None = None,
    shopify: dict[str, Any] | None = None,
    erp: dict[str, Any] | None = None,
    tenant_id: str = "",
    run_id: str = "",
    bootstrap_days_required: int = 30,
    evaluated_at: str | None = None,
    company_website_domain: str | None = None,
    storefront_scrape_hosts: list[str] | None = None,
    skip_website_scrape: bool = False,
) -> FoundationGateContext:
    """Pure builder from dict payloads (no ORM)."""
    from dataruns.dcs.scrapers.company_website import normalize_company_domain

    erp_payload = erp or {}
    erp_in_scope = bool(erp_payload.get("in_scope", False))
    host = normalize_company_domain(company_website_domain)
    extra_hosts: list[str] = []
    for raw in storefront_scrape_hosts or []:
        normalized = normalize_company_domain(raw)
        if normalized and normalized != host and normalized not in extra_hosts:
            extra_hosts.append(normalized)
    # Prefer Shopify shop_domain from payload when not already listed.
    shopify_payload = shopify or {}
    shop_cfg = shopify_payload.get("_config") if isinstance(shopify_payload, dict) else None
    if not isinstance(shop_cfg, dict):
        shop_cfg = {}
    for key in ("shop_domain", "shop"):
        normalized = normalize_company_domain(shop_cfg.get(key) if shop_cfg else None)
        if not normalized:
            # Also accept top-level shopify payload fields.
            normalized = normalize_company_domain(
                shopify_payload.get(key) if isinstance(shopify_payload, dict) else None
            )
        if normalized and normalized != host and normalized not in extra_hosts:
            extra_hosts.append(normalized)
            break
    return FoundationGateContext(
        manago=connector_gate_from_payload(platform="manago_ai", payload=manago),
        shopify=connector_gate_from_payload(platform="shopify", payload=shopify),
        erp_in_scope=erp_in_scope,
        erp_connected=bool(erp_payload.get("connected", False)),
        erp_reachable=erp_payload.get("reachable"),
        erp_row_count=erp_payload.get("row_count"),
        erp_schema_ok=erp_payload.get("schema_ok"),
        erp_encoding_ok=erp_payload.get("encoding_ok"),
        company_website_domain=host,
        storefront_scrape_hosts=extra_hosts,
        skip_website_scrape=skip_website_scrape,
        tenant_id=tenant_id,
        run_id=run_id,
        evaluated_at=evaluated_at,
        bootstrap_days_required=bootstrap_days_required,
    )
