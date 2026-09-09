"""Read-only FE-11 backend verification — evidence element enrichment."""

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


def main() -> int:
    print("=== FE-11 BACKEND VERIFICATION ===")

    ci13: dict[str, Any] = _require(
        _normalize_evidence_item(
            {"side": "dead_state", "bucket": "blocked", "count": 3},
            truncate=False,
            check_id="CI-13",
        ),
        "CI-13 normalize returned None",
    )
    print("CI-13 mismatch:")
    print(f"  source={ci13.get('source')}")
    print(f"  element={ci13.get('element')}")
    print(f"  element_label={ci13.get('element_label')}")
    print(f"  locator={ci13.get('locator')!r}")
    _assert(ci13.get("source") == "manago_ai", "CI-13 source must be manago_ai")
    _assert(bool(ci13.get("element")), "CI-13 element must be non-empty")
    _assert(
        bool(ci13.get("element_label")),
        "CI-13 element_label must be non-empty",
    )
    _assert(ci13.get("locator") != "—", "CI-13 locator must not be em-dash placeholder")
    print("CI-13 bare mismatch enrichment: OK")

    field_row: dict[str, Any] = _require(
        _normalize_evidence_item(
            {
                "source": "shopify",
                "entity": "contact",
                "db_key": "email",
                "value": {"email": "test@example.com"},
            },
            truncate=False,
            check_id="CI-01",
        ),
        "field-level normalize returned None",
    )
    print("Field-level row:")
    print(f"  api_key={field_row.get('api_key')}")
    print(f"  db_key={field_row.get('db_key')}")
    _assert(field_row.get("api_key") == "email", "shopify email api_key expected")
    print("Field-level api_key from map: OK")

    ci01_side: dict[str, Any] = _require(
        _normalize_evidence_item(
            {"side": "shopify_only", "shopify_customer_id": "1"},
            truncate=False,
            check_id="CI-01",
        ),
        "CI-01 side normalize returned None",
    )
    _assert(
        ci01_side.get("source") == "shopify",
        "shopify_only side must infer shopify source",
    )
    print("CI-01 side source inference: OK")

    le04: dict[str, Any] = _require(
        _normalize_evidence_item(
            {"side": "duplicate_purchase", "count": 2},
            truncate=False,
            check_id="LE-04",
        ),
        "LE-04 normalize returned None",
    )
    _assert(le04.get("source") == "snapshot", "LE-04 source must be snapshot")
    _assert(
        bool(le04.get("element_label")),
        "LE-04 element_label must be non-empty",
    )
    print("LE-04 duplicate purchase enrichment: OK")

    print("\nFE-11 backend verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
