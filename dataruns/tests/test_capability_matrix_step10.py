"""CAP-01 Step 10 — writeback safety (option B; CI-01 / CC-03 / WB-SHOP-01).

Deep non-regression: Matrix registry must not replace Maheep writeback execute map.
"""

from __future__ import annotations

import ast
from pathlib import Path

from django.test import SimpleTestCase

from dataruns.capabilities.registry import get_capability, matrix_seed_path
from dataruns.writebacks.capabilities import (
    capability_allows_execute,
    capability_status,
)
from dataruns.writebacks.registry import get_check_mapping, list_mapping_entries

_WB_ROOT = Path(__file__).resolve().parents[1] / "writebacks"
_PILOT_CHECKS = ("CI-01", "CC-03", "WB-SHOP-01")
_EXPECTED_CAPS = {
    "CI-01": "RESTV2.CONTACT.UPSERT",
    "CC-03": "RESTV2.CONTACT.UPSERT",
    "WB-SHOP-01": "SHOPIFY.CUSTOMER.UPDATE",
}


def _mapping_capability_ids(mapping: dict) -> set[str]:
    return {
        str(op.get("capability_id") or "").strip()
        for op in (mapping.get("operations") or [])
        if isinstance(op, dict) and str(op.get("capability_id") or "").strip()
    }


def _module_imports_matrix_registry(py_path: Path) -> bool:
    """True if source imports dataruns.capabilities (Matrix) as a module dependency."""
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "dataruns.capabilities" or alias.name.startswith(
                    "dataruns.capabilities."
                ):
                    return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "dataruns.capabilities" or mod.startswith("dataruns.capabilities."):
                return True
    return False


class Cap01WritebackSafetyStep10Tests(SimpleTestCase):
    """PRD §3.3 option B + execute-critical check mappings stay green."""

    def test_option_b_documented_on_writeback_capabilities(self):
        wb_caps = _WB_ROOT / "capabilities.py"
        text = wb_caps.read_text(encoding="utf-8")
        self.assertIn("option B", text)
        self.assertIn("TODO(CAP-unify)", text)
        self.assertIn("matrix_seed.json", text)
        self.assertIn("CI-01", text)
        self.assertIn("CC-03", text)
        self.assertIn("WB-SHOP-01", text)

    def test_writeback_and_matrix_seed_paths_are_distinct(self):
        wb_json = (_WB_ROOT / "capabilities.json").resolve()
        matrix_json = matrix_seed_path().resolve()
        self.assertTrue(wb_json.is_file())
        self.assertTrue(matrix_json.is_file())
        self.assertNotEqual(wb_json, matrix_json)

    def test_writeback_adapters_do_not_import_matrix_registry(self):
        """Execute adapters must gate on writebacks.capabilities only."""
        for rel in (
            "capabilities.py",
            "adapters/manago.py",
            "adapters/shopify.py",
        ):
            path = _WB_ROOT / rel
            with self.subTest(rel=rel):
                self.assertTrue(path.is_file(), msg=str(path))
                self.assertFalse(
                    _module_imports_matrix_registry(path),
                    msg=f"{rel} must not import dataruns.capabilities Matrix registry",
                )

    def test_pilot_checks_enabled_in_mapping_registry(self):
        by_id = {
            str(row.get("check_id") or ""): row for row in list_mapping_entries()
        }
        for check_id in _PILOT_CHECKS:
            with self.subTest(check_id=check_id):
                row = by_id.get(check_id)
                self.assertIsNotNone(row, msg=f"{check_id} missing from registry")
                assert row is not None
                self.assertTrue(row.get("enabled"), msg=f"{check_id} must stay enabled")

    def test_pilot_mappings_capability_ids_execute_eligible(self):
        for check_id, expected_cap in _EXPECTED_CAPS.items():
            with self.subTest(check_id=check_id):
                mapping = get_check_mapping(check_id)
                caps = _mapping_capability_ids(mapping)
                self.assertIn(expected_cap, caps)
                self.assertEqual(capability_status(expected_cap), "CONFIRMED_LIVE")
                self.assertTrue(
                    capability_allows_execute(expected_cap),
                    msg=f"{expected_cap} must remain execute-eligible for {check_id}",
                )

    def test_matrix_loader_does_not_replace_writeback_execute_gate(self):
        """
        Even when Matrix knows the same id (e.g. RESTV2.CONTACT.UPSERT),
        writeback execute still reads writebacks/capabilities.json.
        Shopify proof may be writeback-only (absent from Matrix seed).
        """
        matrix_rest = get_capability("RESTV2.CONTACT.UPSERT")
        self.assertIsNotNone(matrix_rest)
        # Writeback status SoT remains CONFIRMED_LIVE regardless of Matrix fields.
        self.assertEqual(
            capability_status("RESTV2.CONTACT.UPSERT"),
            "CONFIRMED_LIVE",
        )
        self.assertTrue(capability_allows_execute("RESTV2.CONTACT.UPSERT"))

        # Independence: WB-SHOP-01 cap need not exist in Matrix at all.
        self.assertIsNone(get_capability("SHOPIFY.CUSTOMER.UPDATE"))
        self.assertEqual(
            capability_status("SHOPIFY.CUSTOMER.UPDATE"),
            "CONFIRMED_LIVE",
        )
        self.assertTrue(capability_allows_execute("SHOPIFY.CUSTOMER.UPDATE"))
