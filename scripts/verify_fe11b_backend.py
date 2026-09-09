"""Read-only FE-11B backend verification — Elements = {entity}.{api_key}."""

from __future__ import annotations

import os
import sys
from typing import Any, TypeVar

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.dcs.worklist import _normalize_evidence_item

T = TypeVar("T")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _require(value: T | None, message: str) -> T:
    if value is None:
        raise AssertionError(message)
    return value


def _normalize(item: dict[str, Any], check_id: str) -> dict[str, Any]:
    return _require(
        _normalize_evidence_item(item, truncate=False, check_id=check_id),
        f"{check_id} normalize returned None",
    )


def main() -> int:
    print("=== FE-11B BACKEND VERIFICATION ===")
    print("Bar: Elements identity = {entity}.{api_key} from map.json")
    print("element_label is What-we-found copy only - not the Elements id\n")

    shopify_email = _normalize(
        {
            "side": "shopify_only",
            "email": "buyer@example.com",
            "locator": "—",
        },
        "CI-01",
    )
    print("CI-01 Shopify email:")
    print(f"  element={shopify_email.get('element')}")
    print(f"  api_key={shopify_email.get('api_key')}")
    print(f"  element_label={shopify_email.get('element_label')}")
    _assert(shopify_email.get("source") == "shopify", "CI-01 shopify source")
    _assert(shopify_email.get("api_key") == "email", "CI-01 shopify api_key=email")
    _assert(shopify_email.get("element") == "contact.email", "CI-01 shopify element")
    _assert(
        shopify_email.get("element") != shopify_email.get("element_label"),
        "Elements must not equal element_label prose",
    )
    _assert(shopify_email.get("locator") == "", "placeholder locator must clear")
    print("CI-01 Shopify -> contact.email: OK")

    manago_email = _normalize(
        {"side": "manago_only", "email": "buyer@example.com"},
        "CI-01",
    )
    print("CI-01 Manago email:")
    print(f"  element={manago_email.get('element')}")
    print(f"  api_key={manago_email.get('api_key')}")
    _assert(manago_email.get("source") == "manago_ai", "CI-01 manago source")
    _assert(manago_email.get("api_key") == "email", "CI-01 manago api_key=email")
    _assert(manago_email.get("element") == "contact.email", "CI-01 manago element")
    print("CI-01 Manago -> contact.email: OK")

    shopify_amount = _normalize(
        {
            "source": "shopify",
            "entity": "order",
            "db_key": "amount",
            "value": {"total_price": "42.00"},
        },
        "LE-02",
    )
    print("LE-02 Shopify amount:")
    print(f"  element={shopify_amount.get('element')}")
    print(f"  api_key={shopify_amount.get('api_key')}")
    print(f"  element_label={shopify_amount.get('element_label')}")
    _assert(shopify_amount.get("api_key") == "total_price", "Shopify amount api_key")
    _assert(shopify_amount.get("element") == "order.total_price", "Shopify amount element")
    _assert(
        shopify_amount.get("element") != shopify_amount.get("element_label"),
        "api_key must win over purchase-value label",
    )
    print("Shopify amount -> order.total_price: OK")

    manago_amount = _normalize(
        {
            "source": "manago_ai",
            "entity": "order",
            "db_key": "amount",
            "value": {"value": 42.0},
        },
        "LE-02",
    )
    print("LE-02 Manago amount:")
    print(f"  element={manago_amount.get('element')}")
    print(f"  api_key={manago_amount.get('api_key')}")
    _assert(manago_amount.get("api_key") == "value", "Manago amount api_key")
    _assert(manago_amount.get("element") == "order.value", "Manago amount element")
    print("Manago amount -> order.value: OK")

    _assert(
        shopify_amount.get("api_key") != manago_amount.get("api_key"),
        "same db_key=amount must map to different platform api_keys",
    )
    print("Shopify total_price != Manago value: OK")

    txn = _normalize(
        {"source": "manago_ai", "value": {"transactionId": "txn_9"}},
        "LE-02",
    )
    print("Manago transaction id:")
    print(f"  element={txn.get('element')}")
    _assert(txn.get("api_key") == "transactionId", "transactionId api_key")
    _assert(txn.get("element") == "order.transactionId", "transactionId element")
    print("Manago transaction -> order.transactionId: OK")

    ci13 = _normalize(
        {"side": "dead_state", "bucket": "blocked", "count": 3},
        "CI-13",
    )
    print("CI-13 dead_state aggregate:")
    print(f"  element={ci13.get('element')}")
    print(f"  api_key={ci13.get('api_key')!r}")
    print(f"  element_label={ci13.get('element_label')}")
    _assert(ci13.get("element") == "contact.state", "CI-13 element is contact.state")
    _assert(not ci13.get("api_key"), "CI-13 must not invent a Shopify/Manago api_key")
    _assert(
        ci13.get("element") != ci13.get("element_label"),
        "CI-13 Elements id must not be the side prose",
    )
    print("CI-13 -> contact.state, no invented api_key: OK")

    print("\nFE-11B backend verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
