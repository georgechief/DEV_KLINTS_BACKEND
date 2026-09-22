"""PRD-WB-12 — PT-04 PASS when klints_net_ltv matches Shopify net."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.dcs.product_truth import klints_net_ltv_matches_shopify_net
from dataruns.writebacks.registry import _load_registry, get_check_mapping


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 1


def main() -> int:
    print("=== WB-12 VERIFICATION (PT-04 PASS on klints_net_ltv) ===\n")

    _load_registry.cache_clear()
    pt04 = get_check_mapping("PT-04")
    disclosure = str(pt04.get("operator_disclosure") or "")
    if "may not make PT-04 PASS" in disclosure:
        return _fail("disclosure still says may not make PT-04 PASS")
    if "re-run DCS" not in disclosure:
        return _fail("disclosure must mention re-run DCS")
    if "PASS" not in disclosure:
        return _fail("disclosure must mention PASS")
    print("Mapping disclosure WB-12: OK")

    if not klints_net_ltv_matches_shopify_net(stamped=60.0, shopify_net=60.0):
        return _fail("exact stamp must match")
    if not klints_net_ltv_matches_shopify_net(stamped=60.005, shopify_net=60.0):
        return _fail("absolute 0.01 match failed")
    if klints_net_ltv_matches_shopify_net(stamped=10.0, shopify_net=60.0):
        return _fail("wrong stamp must not match")
    if klints_net_ltv_matches_shopify_net(stamped=None, shopify_net=60.0):
        return _fail("missing stamp must not match")
    print("Governed match helper: OK")

    product_truth_path = os.path.join(ROOT, "dataruns", "dcs", "product_truth.py")
    with open(product_truth_path, encoding="utf-8") as fh:
        src = fh.read()
    if "dataruns.writebacks" in src or "from dataruns.writebacks" in src:
        return _fail("product_truth must not import dataruns.writebacks")
    print("No writebacks import in product_truth: OK")

    print("\nWB-12 verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
