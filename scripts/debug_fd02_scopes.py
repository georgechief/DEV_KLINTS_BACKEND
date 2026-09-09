"""Debug FD-02 scope mismatch: bootstrap vs foundation gate."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.connectors.base import CONNECTOR_BOOTSTRAP_KIND, decrypt_connector_config
from dataruns.connectors.bootstrap_health import missing_shopify_scopes, parse_shopify_scopes
from dataruns.dcs.executors.foundation import (
    ConnectorGateInput,
    FoundationGateContext,
    evaluate_fd_02,
)
from dataruns.models import DataRun
from tenants.models import Connector


def fd02_for_scopes(granted_list: list[str]):
    ctx = FoundationGateContext(
        shopify=ConnectorGateInput(
            platform="shopify",
            connected=True,
            connector_status="connected",
            scopes_granted=granted_list,
            health_report={
                "preflight": {
                    "auth_ok": True,
                    "scopes_granted": granted_list,
                    "issues": [],
                },
            },
        ),
    )
    return evaluate_fd_02(ctx)


def main() -> None:
    print("=== REPRO: modern Shopify OAuth scope bundle ===")
    scopes_str = (
        "read_analytics,write_assigned_fulfillment_orders,read_customer_events,"
        "write_cart_transforms,read_all_cart_transforms,write_validations,"
        "write_checkouts,write_companies,write_customers,write_customer_merge,"
        "write_orders,customer_write_companies,customer_write_customers,"
        "customer_write_orders"
    )
    granted = parse_shopify_scopes(scopes_str)
    missing_req, _ = missing_shopify_scopes(granted)
    granted_list = sorted(granted)
    result = fd02_for_scopes(granted_list)
    print("Bootstrap missing_required:", missing_req)
    print("FD-02 status:", result.status)
    print("FD-02 message:", getattr(result, "failure_message", None) or getattr(result, "detail", None))
    if result.evidence:
        print("FD-02 evidence:", json.dumps(result.evidence[0].value, indent=2))

    print("\n=== LIVE DB: Shopify connectors ===")
    connectors = Connector.objects.filter(name="shopify").order_by("-updated_at")[:5]
    if not connectors:
        print("No shopify connectors found.")
        return

    for connector in connectors:
        config = decrypt_connector_config(connector.config or {})
        scopes_raw = config.get("scopes", "")
        granted = parse_shopify_scopes(scopes_raw)
        missing_req, _ = missing_shopify_scopes(granted)
        granted_list = sorted(granted)
        result = fd02_for_scopes(granted_list)

        print(f"\ncompany={connector.company_id} status={connector.status}")
        print(f"  config.scopes: {scopes_raw!r}")
        print(f"  bootstrap missing_required: {missing_req}")
        print(f"  FD-02 would be: {result.status} — {getattr(result, 'failure_message', None) or getattr(result, 'detail', None)}")

        bootstrap = (
            DataRun.objects.filter(
                name="connector-bootstrap:shopify",
                metadata__company_id=str(connector.company_id),
                metadata__kind=CONNECTOR_BOOTSTRAP_KIND,
            )
            .order_by("-created_at")
            .first()
        )
        if bootstrap is None:
            print("  latest bootstrap: none")
            continue
        preflight = (bootstrap.metadata or {}).get("health_report", {}).get("preflight", {})
        print(f"  latest bootstrap run={bootstrap.id} status={bootstrap.status}")
        print(f"  health_report scopes_granted: {preflight.get('scopes_granted')}")
        print(f"  health_report scopes_missing: {preflight.get('scopes_missing')}")


if __name__ == "__main__":
    main()
