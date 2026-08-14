"""DB-backed check master loader tests."""

from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase

from dataruns.dcs.master import (
    CheckMasterNotSeededError,
    clear_check_master_cache,
    load_check_master,
    load_check_master_from_json,
)
from dataruns.models import CheckMaster as CheckMasterRow


class DbCheckMasterLoaderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_dcs_master")

    def setUp(self):
        clear_check_master_cache()

    def test_db_master_has_42_checks(self):
        master = load_check_master()
        self.assertEqual(len(master.checks), 42)
        self.assertTrue(master.by_id()["FD-03"].is_optional)

    def test_db_master_parity_with_json_ids_and_weights(self):
        db_master = load_check_master()
        json_master = load_check_master_from_json()
        self.assertEqual(db_master.check_ids(), json_master.check_ids())
        self.assertEqual(
            set(db_master.dimension_weights.keys()),
            set(json_master.dimension_weights.keys()),
        )
        for key, weight in json_master.dimension_weights.items():
            self.assertEqual(db_master.dimension_weights[key], weight)
        for check_id, definition in json_master.by_id().items():
            db_def = db_master.by_id()[check_id]
            self.assertEqual(db_def.numeric_weight, definition.numeric_weight)
            self.assertEqual(db_def.role, definition.role)
            self.assertEqual(db_def.is_optional, definition.is_optional)
            self.assertEqual(db_def.dimension, definition.dimension)

    def test_empty_masters_raise(self):
        CheckMasterRow.objects.all().delete()
        clear_check_master_cache()
        with self.assertRaises(CheckMasterNotSeededError):
            load_check_master()
