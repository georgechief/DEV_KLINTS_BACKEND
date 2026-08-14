from __future__ import annotations

from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from dataruns.models import CheckMaster, DimensionMaster, RootCauseMaster

WORKBOOK_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/dcs_scoring/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx"
)


class SeedDcsMasterCommandTests(TestCase):
    def setUp(self):
        if not WORKBOOK_PATH.exists():
            self.skipTest(f"Workbook not found: {WORKBOOK_PATH}")
        call_command("seed_dcs_master")

    def test_dimension_masters_include_workbook_fields(self):
        dimension = DimensionMaster.objects.get(dimension_id="01")
        self.assertEqual(dimension.key, "01 Customer Identity")
        self.assertEqual(
            dimension.purpose,
            "Identity match, duplicates, customer-universe integrity",
        )
        self.assertEqual(dimension.percent_needed, 80)
        self.assertEqual(dimension.weight_percent, 18)

        result_status = dimension.result_status_json
        self.assertEqual(result_status["PASS"]["score_factor"], 1)
        self.assertEqual(result_status["WARN"]["score_factor"], 0.5)
        self.assertEqual(result_status["FAIL"]["score_factor"], 0)
        self.assertIsNone(result_status["NOT_APPLICABLE"]["score_factor"])
        self.assertIsNone(result_status["NOT_CONNECTED"]["score_factor"])
        self.assertIsNone(result_status["UNKNOWN"]["score_factor"])

        confidence = dimension.confidence_json
        self.assertEqual(confidence["HIGH"]["numeric_factor"], 1)
        self.assertEqual(confidence["MEDIUM"]["numeric_factor"], 0.7)
        self.assertEqual(confidence["LOW"]["numeric_factor"], 0.4)

        final_states = dimension.final_state_json
        self.assertEqual(len(final_states), 6)
        blocked_states = [
            item for item in final_states if item["final_state"] == "BLOCKED"
        ]
        self.assertEqual(len(blocked_states), 2)

    def test_foundation_gate_dimension_not_in_scoring_sheet(self):
        dimension = DimensionMaster.objects.get(dimension_id="00")
        self.assertEqual(dimension.key, "00 Foundation Gate")
        self.assertEqual(dimension.purpose, "")
        self.assertIsNone(dimension.percent_needed)

    def test_root_cause_masters_table_and_remediation_pattern(self):
        root_cause = RootCauseMaster.objects.get(code="RC-01")
        self.assertEqual(root_cause.name, "Integration gap")
        self.assertIn("missing pipe", root_cause.standard_remediation_pattern.lower())
        self.assertEqual(RootCauseMaster._meta.db_table, "root_cause_masters")

    def test_check_masters_store_root_cause_ids_json(self):
        check = CheckMaster.objects.get(check_id="CI-01")
        self.assertEqual(check.root_cause_ids, ["RC-01", "RC-03", "RC-09"])

    def test_check_masters_store_excel_fix_ownership(self):
        klints = CheckMaster.objects.get(check_id="CI-01")
        self.assertEqual(klints.fix_owner, "Klints (automated)")
        self.assertEqual(klints.fix_type, "Automated writeback (approved)")
        self.assertTrue(klints.suggested_fix)

        data_lead = CheckMaster.objects.get(check_id="FD-06")
        self.assertEqual(data_lead.fix_owner, "Data lead")
        self.assertEqual(data_lead.fix_type, "Configuration")

        external = CheckMaster.objects.get(check_id="FD-07")
        self.assertEqual(external.fix_owner, "External integrator")

        self.assertEqual(
            CheckMaster.objects.filter(fix_owner="Klints (automated)").count(),
            18,
        )
        self.assertEqual(
            CheckMaster.objects.filter(fix_owner="Data lead").count(),
            10,
        )
        self.assertEqual(
            CheckMaster.objects.filter(fix_owner="External integrator").count(),
            10,
        )
        self.assertEqual(
            CheckMaster.objects.filter(fix_owner="CRM manager").count(),
            4,
        )
    def test_seed_is_idempotent(self):
        call_command("seed_dcs_master")
        self.assertEqual(DimensionMaster.objects.count(), 8)
        self.assertEqual(RootCauseMaster.objects.count(), 15)
        self.assertEqual(CheckMaster.objects.count(), 42)

    def test_seed_is_optional_flags(self):
        fd03 = CheckMaster.objects.get(check_id="FD-03")
        self.assertTrue(fd03.is_optional)
        self.assertFalse(CheckMaster.objects.exclude(check_id="FD-03").filter(is_optional=True).exists())

    def test_workbook_result_status_values_match_prd(self):
        dimension = DimensionMaster.objects.first()
        expected_statuses = {
            "PASS",
            "WARN",
            "FAIL",
            "NOT_APPLICABLE",
            "NOT_CONNECTED",
            "UNKNOWN",
        }
        self.assertEqual(set(dimension.result_status_json.keys()), expected_statuses)
