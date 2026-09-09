"""CAP-01 Step 5 — build package uses Matrix resolver (no hardcode)."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from dataruns.capabilities.contract import (
    CAP_ID_HUMAN_WORKFLOW_BUILD,
    CAP_ID_MCP_WORKFLOW_UPSERT,
    CAP_STATUS_CONFIRMED_LIVE,
    CAP_STATUS_DISCOVERY_REQUIRED,
    PACKAGE_ROUTE_HUMAN_FALLBACK,
    RESOLVED_HUMAN_FALLBACK,
)
from dataruns.use_cases.build_package import (
    _resolve_capabilities,
    assemble_build_package_payload,
)
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot
from dataruns.use_cases.recommend import (
    RecommendationContext,
    _gates_from_blueprint,
    build_gates_snapshot,
)
from tenants.models import Company, Tenant


class Cap01BuildPackageStep5Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="CAP-01 BP", slug="cap01-bp")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="CAP-01 BP Co",
            domain="cap01-bp.example.com",
        )
        cls.pilot = (
            UseCasePilot.objects.select_related("blueprint").get(use_case_id="UC-02")
        )
        cls.blueprint = cls.pilot.blueprint
        cls.body = cls.blueprint.body if isinstance(cls.blueprint.body, dict) else {}
        gates = _gates_from_blueprint(cls.body)
        ctx = RecommendationContext(
            headline_score=85.0,
            score_ready=True,
            dcs_data_run_id=1,
            check_results={"CC-03": "PASS"},
            af_mode="AUGMENT",
            af_assessment_id=None,
            gap_stage_ids=[],
            as_of=timezone.now(),
        )
        cls.gates = gates
        cls.gates_snapshot = build_gates_snapshot(
            gates=gates,
            ctx=ctx,
            provisional_supplemental=True,
        )

    def _assemble(self) -> dict:
        return assemble_build_package_payload(
            package_id="00000000-0000-4000-8000-0000000000c5",
            pilot=self.pilot,
            blueprint=self.blueprint,
            company=self.company,
            ctx_snapshot={
                "dcs_data_run_id": 1,
                "af_assessment_id": None,
                "af_mode": "AUGMENT",
                "headline_score": 85.0,
            },
            gates=self.gates,
            gates_snapshot=self.gates_snapshot,
            provisional_supplemental=True,
            generated_by=None,
        )

    def test_uc02_package_route_human_fallback(self):
        payload = self._assemble()
        self.assertEqual(payload["route"], PACKAGE_ROUTE_HUMAN_FALLBACK)

    def test_uc02_capability_resolution_matrix_backed(self):
        payload = self._assemble()
        rows = payload["capability_resolution"]
        self.assertIsInstance(rows, list)
        self.assertGreaterEqual(len(rows), 3)
        by_id = {r["capability_id"]: r for r in rows}

        upsert = by_id[CAP_ID_MCP_WORKFLOW_UPSERT]
        self.assertEqual(upsert["resolved_status"], RESOLVED_HUMAN_FALLBACK)
        self.assertEqual(upsert["fallback_used"], CAP_ID_HUMAN_WORKFLOW_BUILD)
        self.assertEqual(upsert["matrix_status"], CAP_STATUS_DISCOVERY_REQUIRED)
        self.assertEqual(upsert["channel"], "MANAGO_MCP")
        self.assertEqual(
            upsert["required_status"],
            "CONFIRMED_LIVE_OR_APPROVED_FALLBACK",
        )

        for cap_id in ("AGENT.SEGMENT.CREATE", "AGENT.EMAIL.DRAFT"):
            self.assertEqual(by_id[cap_id]["resolved_status"], CAP_STATUS_CONFIRMED_LIVE)
            self.assertEqual(by_id[cap_id]["matrix_status"], CAP_STATUS_CONFIRMED_LIVE)
            self.assertIsNone(by_id[cap_id]["fallback_used"])

    def test_resolve_capabilities_helper_matches_assemble(self):
        via_helper = _resolve_capabilities(
            self.body,
            fallback=self.pilot.fallback or CAP_ID_HUMAN_WORKFLOW_BUILD,
        )
        payload = self._assemble()
        self.assertEqual(
            [r["capability_id"] for r in via_helper],
            [r["capability_id"] for r in payload["capability_resolution"]],
        )
        self.assertEqual(
            via_helper[-1]["resolved_status"],
            payload["capability_resolution"][-1]["resolved_status"],
        )

    def test_no_hardcoded_not_confirmed_for_agent_deps(self):
        """Pre-CAP hardcode marked non-UPSERT as NOT_CONFIRMED — must not regress."""
        payload = self._assemble()
        for row in payload["capability_resolution"]:
            if row["capability_id"].startswith("AGENT."):
                self.assertNotEqual(row["resolved_status"], "NOT_CONFIRMED")
