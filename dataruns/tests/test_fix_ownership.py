"""Tests for Excel Fix Type / Fix Owner helpers."""

from __future__ import annotations

from django.test import TestCase

from dataruns.dcs.fix_ownership import (
    KLINTS_AUTOMATED_OWNER,
    enrich_check_results_from_master,
    fix_ownership_fields,
    is_klints_automated_fix,
)
from dataruns.dcs.types import CheckResult
from dataruns.models import CheckMaster, DimensionMaster


class FixOwnershipHelperTests(TestCase):
    def test_klints_automated_owner_detection(self):
        self.assertTrue(is_klints_automated_fix(KLINTS_AUTOMATED_OWNER))
        self.assertTrue(is_klints_automated_fix(" klints (automated) "))
        self.assertFalse(is_klints_automated_fix("Data lead"))
        self.assertFalse(is_klints_automated_fix(""))

    def test_fix_ownership_fields_shape(self):
        row = fix_ownership_fields(
            fix_type="Configuration",
            fix_owner=KLINTS_AUTOMATED_OWNER,
            suggested_fix="Reconnect",
        )
        self.assertEqual(
            row,
            {
                "fix_type": "Configuration",
                "fix_owner": KLINTS_AUTOMATED_OWNER,
                "fix_in_klints": True,
                "suggested_fix": "Reconnect",
            },
        )


class EnrichCheckResultsFromMasterTests(TestCase):
    def setUp(self):
        self.dimension = DimensionMaster.objects.create(
            dimension_id="00",
            key="00 Foundation Gate",
            name="Foundation Gate",
            purpose="",
        )
        CheckMaster.objects.create(
            sequence=1,
            check_id="FD-02",
            check_name="Shopify API authentication and scopes",
            dimension=self.dimension,
            check_class=CheckMaster.CheckClass.RULE_BASED,
            check_type="Connectivity",
            role=CheckMaster.Role.GATE,
            cadence="Initial",
            phase="MVP1-A",
            systems_compared="Shopify",
            numeric_weight=0,
            severity=CheckMaster.Severity.CRITICAL,
            root_cause_ids=["RC-12"],
            suggested_fix="Re-run OAuth with full read scope set.",
            fix_type="Configuration",
            fix_owner=KLINTS_AUTOMATED_OWNER,
        )
        CheckMaster.objects.create(
            sequence=6,
            check_id="FD-06",
            check_name="Manago account/sub-account topology mapped",
            dimension=self.dimension,
            check_class=CheckMaster.CheckClass.RULE_BASED,
            check_type="Connectivity",
            role=CheckMaster.Role.GATE,
            cadence="Initial",
            phase="MVP1-A",
            systems_compared="Manago",
            numeric_weight=0,
            severity=CheckMaster.Severity.HIGH,
            root_cause_ids=["RC-11"],
            suggested_fix="Capture account relationship classification.",
            fix_type="Configuration",
            fix_owner="Data lead",
        )

    def test_enrich_sets_klints_flag_from_master(self):
        results = [
            CheckResult(check_id="FD-02", status="FAIL", confidence="HIGH"),
            CheckResult(check_id="FD-06", status="FAIL", confidence="HIGH"),
        ]
        enrich_check_results_from_master(results)
        self.assertEqual(results[0].fix_owner, KLINTS_AUTOMATED_OWNER)
        self.assertTrue(results[0].fix_in_klints)
        self.assertEqual(results[0].fix_type, "Configuration")
        self.assertEqual(results[1].fix_owner, "Data lead")
        self.assertFalse(results[1].fix_in_klints)
