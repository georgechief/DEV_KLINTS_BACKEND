"""DCS-09 Step 1 — static supplemental master + UC↔gate map + contract."""

from __future__ import annotations

import json
from pathlib import Path

from django.test import SimpleTestCase

from dataruns.dcs.master import load_check_master_from_json
from dataruns.dcs.pilot_gates.contract import (
    ERP_SENSITIVE_CHECK_IDS,
    EXPECTED_SUPPLEMENTAL_CHECK_COUNT,
    GATE_CATALOG_VERSION,
    SLICE_A_CHECK_IDS,
    STATUS_FAIL,
    STATUS_NOT_CONNECTED,
    STATUS_PASS,
    STATUS_WARN,
    is_erp_sensitive,
    is_supplemental_check_id,
    supplemental_status_blocks_pilot,
    supplemental_status_is_ready,
)
from dataruns.dcs.pilot_gates.master import (
    clear_supplemental_master_cache,
    get_supplemental_check,
    get_supplemental_checks_for_use_case,
    list_supplemental_checks,
    load_supplemental_check_master,
    resolve_check_ids_for_evaluate,
    supplemental_gate_map_path,
    supplemental_master_path,
)
from dataruns.use_cases.constants import SUPPLEMENTAL_PREFLIGHT_CHECKS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = (
    _REPO_ROOT
    / "Klints_MVP1_Rohan_Build_Pack_v1.2_20260718"
    / "04_MVP1_Pilot_Blueprints"
    / "pilot_manifest.json"
)

_PRD_UC_SUPPLEMENTAL: dict[str, list[str]] = {
    "UC-02": ["CI-08", "CC-06"],
    "UC-04": ["PT-13"],
    "UC-05": ["CC-06"],
    "UC-06B": ["SP-10"],
    "UC-08": ["BR-09"],
    "UC-09": ["LE-10"],
    "UC-11": ["BR-09", "SP-04"],
    "UC-12": ["PT-06"],
    "UC-13": ["PT-05"],
    "UC-21": ["LE-07", "PT-06"],
    "UC-28": ["BR-03", "PT-11"],
}


class PilotGatesStep1MasterTests(SimpleTestCase):
    def setUp(self):
        clear_supplemental_master_cache()

    def tearDown(self):
        clear_supplemental_master_cache()

    def test_master_and_gate_map_files_committed(self):
        self.assertTrue(supplemental_master_path().is_file())
        self.assertTrue(supplemental_gate_map_path().is_file())

    def test_load_master_count_and_catalog(self):
        master = load_supplemental_check_master()
        self.assertEqual(master.count, EXPECTED_SUPPLEMENTAL_CHECK_COUNT)
        self.assertEqual(master.gate_catalog_version, GATE_CATALOG_VERSION)
        self.assertEqual(master.check_ids(), set(SUPPLEMENTAL_PREFLIGHT_CHECKS))

    def test_master_matches_manifest_and_constants(self):
        manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        listed = set(manifest["supplemental_preflight_checks"])
        master = load_supplemental_check_master()
        self.assertEqual(master.check_ids(), listed)
        self.assertEqual(listed, set(SUPPLEMENTAL_PREFLIGHT_CHECKS))

    def test_master_ids_match_constants_and_zero_overlap_with_42(self):
        master = load_supplemental_check_master()
        headline = load_check_master_from_json().check_ids()
        self.assertEqual(len(headline), 42)
        self.assertEqual(master.check_ids() & headline, set())

    def test_every_row_in_headline_score_false(self):
        for row in load_supplemental_check_master().checks:
            self.assertFalse(row.in_headline_score, msg=row.check_id)
            self.assertEqual(row.role, "PILOT_SUPPLEMENTAL")

    def test_erp_sensitive_flags(self):
        self.assertEqual(ERP_SENSITIVE_CHECK_IDS, frozenset({"BR-09", "PT-06"}))
        for check_id in ("BR-09", "PT-06"):
            row = get_supplemental_check(check_id)
            self.assertIsNotNone(row)
            assert row is not None
            self.assertTrue(row.erp_sensitive)
            self.assertTrue(is_erp_sensitive(check_id))
            self.assertTrue(is_erp_sensitive(check_id.lower()))
        ci08 = get_supplemental_check("CI-08")
        self.assertIsNotNone(ci08)
        assert ci08 is not None
        self.assertFalse(ci08.erp_sensitive)
        self.assertFalse(is_erp_sensitive("CI-08"))

    def test_slice_a_ids(self):
        self.assertEqual(SLICE_A_CHECK_IDS, frozenset({"CI-08", "CC-06"}))
        self.assertTrue(SLICE_A_CHECK_IDS <= set(SUPPLEMENTAL_PREFLIGHT_CHECKS))

    def test_id_helpers_case_insensitive(self):
        self.assertTrue(is_supplemental_check_id("ci-08"))
        self.assertTrue(is_supplemental_check_id("CI-08"))
        self.assertFalse(is_supplemental_check_id("CC-03"))
        self.assertFalse(is_supplemental_check_id(""))

    def test_get_supplemental_check_case_insensitive(self):
        row = get_supplemental_check("ci-08")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.check_id, "CI-08")
        self.assertIsNone(get_supplemental_check("NOT-A-CHECK"))

    def test_gate_map_matches_prd(self):
        for uc, expected in _PRD_UC_SUPPLEMENTAL.items():
            self.assertEqual(
                list(get_supplemental_checks_for_use_case(uc)),
                sorted(expected),
                msg=uc,
            )
        self.assertEqual(get_supplemental_checks_for_use_case("UC-10"), ())
        self.assertEqual(get_supplemental_checks_for_use_case(None), ())
        self.assertEqual(
            list(get_supplemental_checks_for_use_case("uc-02")),
            ["CC-06", "CI-08"],
        )

    def test_list_envelope_includes_use_case_map(self):
        body = list_supplemental_checks()
        self.assertEqual(body["count"], 12)
        self.assertEqual(body["gate_catalog_version"], GATE_CATALOG_VERSION)
        self.assertEqual(len(body["checks"]), 12)
        self.assertEqual(
            set(body["use_case_map"]),
            set(_PRD_UC_SUPPLEMENTAL),
        )

    def test_resolve_check_ids_for_evaluate(self):
        self.assertEqual(
            resolve_check_ids_for_evaluate(),
            sorted(SUPPLEMENTAL_PREFLIGHT_CHECKS),
        )
        self.assertEqual(
            resolve_check_ids_for_evaluate(use_case_ids=["UC-02"]),
            ["CC-06", "CI-08"],
        )
        self.assertEqual(
            resolve_check_ids_for_evaluate(use_case_ids=["UC-02", "UC-05"]),
            ["CC-06", "CI-08"],
        )
        self.assertEqual(
            resolve_check_ids_for_evaluate(check_ids=["CI-08", "bogus", "CC-06"]),
            ["CC-06", "CI-08"],
        )
        self.assertEqual(
            resolve_check_ids_for_evaluate(check_ids=["ci-08"]),
            ["CI-08"],
        )
        self.assertEqual(
            resolve_check_ids_for_evaluate(
                use_case_ids=["UC-28"],
                check_ids=["SP-10"],
            ),
            ["SP-10"],
        )

    def test_resolve_empty_list_is_not_all_twelve(self):
        """PRD: only both null → all 12. Empty list must not expand to all."""
        self.assertEqual(resolve_check_ids_for_evaluate(check_ids=[]), [])
        self.assertEqual(resolve_check_ids_for_evaluate(use_case_ids=[]), [])
        self.assertEqual(
            resolve_check_ids_for_evaluate(use_case_ids=["UC-10"]),
            [],
        )
        self.assertEqual(
            resolve_check_ids_for_evaluate(check_ids=[], use_case_ids=["UC-02"]),
            [],
        )

    def test_strict_readiness_helpers(self):
        self.assertTrue(supplemental_status_is_ready(STATUS_PASS))
        self.assertTrue(supplemental_status_is_ready("pass"))
        self.assertFalse(supplemental_status_is_ready(STATUS_WARN))
        self.assertFalse(supplemental_status_is_ready(STATUS_FAIL))
        self.assertFalse(supplemental_status_is_ready(STATUS_NOT_CONNECTED))
        self.assertFalse(supplemental_status_is_ready(None))
        self.assertTrue(supplemental_status_blocks_pilot(STATUS_FAIL))
        self.assertTrue(supplemental_status_blocks_pilot(STATUS_WARN))
        self.assertFalse(supplemental_status_blocks_pilot(STATUS_PASS))
        self.assertFalse(supplemental_status_blocks_pilot(None))
        self.assertFalse(supplemental_status_blocks_pilot("not_evaluated"))

    def test_json_envelope_count_field(self):
        raw = json.loads(supplemental_master_path().read_text(encoding="utf-8"))
        self.assertEqual(raw["count"], 12)
        self.assertEqual(raw["gate_catalog_version"], GATE_CATALOG_VERSION)
        self.assertEqual(len(raw["checks"]), 12)
        erp = {c["check_id"] for c in raw["checks"] if c.get("erp_sensitive")}
        self.assertEqual(erp, set(ERP_SENSITIVE_CHECK_IDS))


class PilotGatesStep1IsolationTests(SimpleTestCase):
    def test_headline_master_unchanged_by_supplemental_package(self):
        headline = load_check_master_from_json()
        self.assertEqual(len(headline.checks), 42)
        from dataruns.dcs.executors.registry import registered_check_ids

        registered = registered_check_ids()
        overlap = registered & set(SUPPLEMENTAL_PREFLIGHT_CHECKS)
        self.assertEqual(overlap, set(), msg=f"registry bleed: {sorted(overlap)}")
