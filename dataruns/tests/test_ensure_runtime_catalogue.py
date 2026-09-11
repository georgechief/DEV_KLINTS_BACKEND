"""ensure_runtime_catalogue — empty DB recovery for deploy CMD."""

from __future__ import annotations

from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from dataruns.models import CheckMaster
from dataruns.use_cases.models import UseCasePilot

WORKBOOK_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/dcs_scoring/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx"
)


class EnsureRuntimeCatalogueTests(TestCase):
    def setUp(self):
        if not WORKBOOK_PATH.exists():
            self.skipTest(f"Workbook not found: {WORKBOOK_PATH}")

    def test_seeds_when_empty_and_idempotent_second_run(self):
        self.assertEqual(CheckMaster.objects.count(), 0)

        call_command("ensure_runtime_catalogue", verbosity=0)
        first = CheckMaster.objects.count()
        self.assertGreaterEqual(first, 42)
        self.assertGreaterEqual(UseCasePilot.objects.count(), 16)

        call_command("ensure_runtime_catalogue", verbosity=0)
        self.assertEqual(CheckMaster.objects.count(), first)
        self.assertGreaterEqual(UseCasePilot.objects.count(), 16)
