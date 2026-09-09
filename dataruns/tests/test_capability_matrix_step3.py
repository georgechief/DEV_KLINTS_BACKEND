"""CAP-01 Step 3 — Matrix registry loader (get / list)."""

from __future__ import annotations

from django.test import SimpleTestCase

from dataruns.capabilities.contract import (
    CAP_ID_HUMAN_WORKFLOW_BUILD,
    CAP_ID_MCP_WORKFLOW_UPSERT,
    CAP_STATUS_CONFIRMED_LIVE,
    CAP_STATUS_DISCOVERY_REQUIRED,
    MATRIX_PACK_SOURCE,
)
from dataruns.capabilities.registry import (
    clear_matrix_registry_cache,
    get_capability,
    get_matrix_source,
    list_capabilities,
    matrix_seed_path,
)


class Cap01RegistryStep3Tests(SimpleTestCase):
    def setUp(self):
        clear_matrix_registry_cache()

    def tearDown(self):
        clear_matrix_registry_cache()

    def test_seed_path_points_at_committed_json(self):
        path = matrix_seed_path()
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "matrix_seed.json")

    def test_get_capability_human_build(self):
        row = get_capability(CAP_ID_HUMAN_WORKFLOW_BUILD)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], CAP_STATUS_CONFIRMED_LIVE)
        self.assertEqual(row["channel"], "HUMAN_OPERATOR")

    def test_get_capability_upsert_discovery(self):
        row = get_capability(CAP_ID_MCP_WORKFLOW_UPSERT)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], CAP_STATUS_DISCOVERY_REQUIRED)
        self.assertEqual(row["evidence"], [])
        self.assertEqual(row["fallback"], CAP_ID_HUMAN_WORKFLOW_BUILD)

    def test_get_capability_unknown_returns_none(self):
        self.assertIsNone(get_capability("MCP.DOES.NOT.EXIST"))
        self.assertIsNone(get_capability(""))
        self.assertIsNone(get_capability(None))

    def test_get_capability_strips_whitespace(self):
        row = get_capability(f"  {CAP_ID_MCP_WORKFLOW_UPSERT}  ")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["capability_id"], CAP_ID_MCP_WORKFLOW_UPSERT)

    def test_get_capability_case_insensitive(self):
        row = get_capability(CAP_ID_MCP_WORKFLOW_UPSERT.lower())
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["capability_id"], CAP_ID_MCP_WORKFLOW_UPSERT)

    def test_seed_rejects_count_mismatch(self):
        from unittest.mock import mock_open, patch

        from dataruns.capabilities.registry import MatrixSeedError, _load_seed_envelope

        bad = (
            '{"schema_version":"1.0.0","source":"x","count":99,'
            '"capabilities":[{'
            '"schema_version":"1.0.0","capability_id":"X.TEST",'
            '"channel":"REST_V2","mode":"READ","status":"CONFIRMED_LIVE",'
            '"input_contract":"","output_contract":"","fallback":null,'
            '"evidence":[]'
            "}]}"
        )
        clear_matrix_registry_cache()
        with patch("dataruns.capabilities.registry.matrix_seed_path") as path_mock:
            fake = path_mock.return_value
            fake.is_file.return_value = True
            fake.open = mock_open(read_data=bad)
            with self.assertRaises(MatrixSeedError) as ctx:
                _load_seed_envelope()
            self.assertIn("count", str(ctx.exception).lower())
        clear_matrix_registry_cache()

    def test_get_capability_returns_copy(self):
        a = get_capability(CAP_ID_MCP_WORKFLOW_UPSERT)
        b = get_capability(CAP_ID_MCP_WORKFLOW_UPSERT)
        assert a is not None and b is not None
        a["status"] = "CONFIRMED_LIVE"
        self.assertEqual(b["status"], CAP_STATUS_DISCOVERY_REQUIRED)

    def test_list_capabilities_envelope(self):
        listed = list_capabilities()
        self.assertEqual(listed["schema_version"], "1.0.0")
        self.assertEqual(listed["source"], MATRIX_PACK_SOURCE)
        self.assertEqual(listed["count"], 40)
        self.assertEqual(len(listed["results"]), 40)
        self.assertEqual(get_matrix_source(), MATRIX_PACK_SOURCE)

    def test_list_filter_channel(self):
        listed = list_capabilities(channel="MANAGO_MCP")
        self.assertGreater(listed["count"], 0)
        for row in listed["results"]:
            self.assertEqual(row["channel"], "MANAGO_MCP")
            self.assertEqual(row["status"], CAP_STATUS_DISCOVERY_REQUIRED)

    def test_list_filter_status(self):
        listed = list_capabilities(status="DISCOVERY_REQUIRED")
        self.assertGreaterEqual(listed["count"], 15)
        for row in listed["results"]:
            self.assertEqual(row["status"], CAP_STATUS_DISCOVERY_REQUIRED)

    def test_list_filter_q(self):
        listed = list_capabilities(q="WORKFLOW")
        self.assertGreater(listed["count"], 0)
        for row in listed["results"]:
            self.assertIn("WORKFLOW", row["capability_id"].upper())

    def test_list_filter_combined(self):
        listed = list_capabilities(channel="MANAGO_MCP", q="WORKFLOW.UPSERT")
        self.assertEqual(listed["count"], 1)
        self.assertEqual(
            listed["results"][0]["capability_id"],
            CAP_ID_MCP_WORKFLOW_UPSERT,
        )
