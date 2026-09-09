"""CAP-01 Step 2 — committed matrix_seed.json asserts (no xlsx at runtime)."""

from __future__ import annotations

import json
from pathlib import Path

from django.test import SimpleTestCase

from dataruns.capabilities.contract import (
    CAP_ID_HUMAN_WORKFLOW_BUILD,
    CAP_ID_MCP_WORKFLOW_PUBLISH,
    CAP_ID_MCP_WORKFLOW_UPSERT,
    CAP_ID_RESTV2_WORKFLOW_LIST,
    CAP_STATUS_CONFIRMED_LIVE,
    CAP_STATUS_DISCOVERY_REQUIRED,
    CAP_STATUS_ENUM,
    CAP_MODE_ENUM,
    MATRIX_PACK_SOURCE,
    SEED_ROW_REQUIRED_FIELDS,
)

SEED_PATH = (
    Path(__file__).resolve().parents[1] / "capabilities" / "matrix_seed.json"
)


class Cap01MatrixSeedStep2Tests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with SEED_PATH.open(encoding="utf-8") as handle:
            cls.seed = json.load(handle)
        caps = cls.seed.get("capabilities")
        assert isinstance(caps, list)
        cls.by_id = {row["capability_id"]: row for row in caps}

    def test_seed_file_exists(self):
        self.assertTrue(SEED_PATH.is_file())

    def test_envelope(self):
        self.assertEqual(self.seed.get("schema_version"), "1.0.0")
        self.assertEqual(self.seed.get("source"), MATRIX_PACK_SOURCE)
        self.assertEqual(self.seed.get("count"), len(self.seed["capabilities"]))
        self.assertEqual(self.seed.get("count"), 40)

    def test_all_rows_have_required_fields(self):
        for row in self.seed["capabilities"]:
            missing = SEED_ROW_REQUIRED_FIELDS - set(row.keys())
            self.assertFalse(missing, msg=f"{row.get('capability_id')}: {missing}")
            self.assertEqual(row["schema_version"], "1.0.0")
            self.assertIn(row["status"], CAP_STATUS_ENUM)
            self.assertIn(row["mode"], CAP_MODE_ENUM)
            self.assertIsInstance(row["evidence"], list)

    def test_unique_capability_ids(self):
        ids = [r["capability_id"] for r in self.seed["capabilities"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_must_seed_statuses(self):
        self.assertEqual(
            self.by_id[CAP_ID_HUMAN_WORKFLOW_BUILD]["status"],
            CAP_STATUS_CONFIRMED_LIVE,
        )
        self.assertEqual(
            self.by_id[CAP_ID_MCP_WORKFLOW_UPSERT]["status"],
            CAP_STATUS_DISCOVERY_REQUIRED,
        )
        self.assertEqual(
            self.by_id[CAP_ID_MCP_WORKFLOW_PUBLISH]["status"],
            CAP_STATUS_DISCOVERY_REQUIRED,
        )
        self.assertEqual(
            self.by_id[CAP_ID_RESTV2_WORKFLOW_LIST]["status"],
            CAP_STATUS_CONFIRMED_LIVE,
        )

    def test_mcp_rows_have_empty_evidence(self):
        for row in self.seed["capabilities"]:
            if not str(row["capability_id"]).startswith("MCP."):
                continue
            self.assertEqual(
                row["evidence"],
                [],
                msg=f"{row['capability_id']} must not invent evidence",
            )
            self.assertEqual(row["status"], CAP_STATUS_DISCOVERY_REQUIRED)
            self.assertIsNone(row.get("verified_at"))

    def test_no_fabricated_mcp_confirmed(self):
        for row in self.seed["capabilities"]:
            if str(row["capability_id"]).startswith("MCP."):
                self.assertNotIn(
                    row["status"],
                    {"CONFIRMED_LIVE", "CONFIRMED_LIMITED"},
                )

    def test_upsert_fallback_is_human_build_id(self):
        upsert = self.by_id[CAP_ID_MCP_WORKFLOW_UPSERT]
        self.assertEqual(upsert["fallback"], CAP_ID_HUMAN_WORKFLOW_BUILD)
        self.assertEqual(upsert["channel"], "MANAGO_MCP")
        self.assertEqual(upsert["mode"], "WRITE")
