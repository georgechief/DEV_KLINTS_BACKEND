"""CAP-01 Step 7 — BE case matrix sign-off (PRD §8 backend rows).

Authoritative BE gate before FE Steps 8–9. Writeback deep execute stays Step 10;
§8 still requires a CI-01 capability non-regression check here.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from dataruns.architecture.constants import ARCHITECTURE_ASSESSMENT_KIND
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.capabilities.contract import (
    CAP_ID_HUMAN_WORKFLOW_BUILD,
    CAP_ID_MCP_WORKFLOW_UPSERT,
    CAP_STATUS_CONFIRMED_LIVE,
    CAP_STATUS_DISCOVERY_REQUIRED,
    MATRIX_PACK_SOURCE,
    PACKAGE_ROUTE_HUMAN_FALLBACK,
    PACKAGE_ROUTE_MCP,
    RESOLVED_HUMAN_FALLBACK,
    RESOLVED_MCP,
)
from dataruns.capabilities.registry import (
    clear_matrix_registry_cache,
    get_capability,
    list_capabilities,
    matrix_seed_path,
)
from dataruns.capabilities.resolver import resolve_blueprint_capabilities
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import DataRun
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.views import UseCaseBuildPackageView
from dataruns.writebacks.capabilities import (
    capability_allows_execute,
    capability_status,
)
from tenants.models import Company, Tenant, User

_UC02_DEPS = [
    {
        "capability_id": "AGENT.SEGMENT.CREATE",
        "required_status": "CONFIRMED_LIVE",
        "fallback": None,
    },
    {
        "capability_id": "AGENT.EMAIL.DRAFT",
        "required_status": "CONFIRMED_LIVE",
        "fallback": None,
    },
    {
        "capability_id": CAP_ID_MCP_WORKFLOW_UPSERT,
        "required_status": "CONFIRMED_LIVE_OR_APPROVED_FALLBACK",
        "fallback": CAP_ID_HUMAN_WORKFLOW_BUILD,
    },
]


class Cap01BeMatrixStep7SeedTests(SimpleTestCase):
    """§8 seed rows — no DB."""

    def setUp(self):
        clear_matrix_registry_cache()

    def tearDown(self):
        clear_matrix_registry_cache()

    def test_seed_human_workflow_build_confirmed_live(self):
        row = get_capability(CAP_ID_HUMAN_WORKFLOW_BUILD)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], CAP_STATUS_CONFIRMED_LIVE)
        self.assertTrue(matrix_seed_path().is_file())

    def test_stock_seed_upsert_discovery_required(self):
        row = get_capability(CAP_ID_MCP_WORKFLOW_UPSERT)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], CAP_STATUS_DISCOVERY_REQUIRED)
        self.assertEqual(row["evidence"], [])

    def test_no_fabricated_mcp_confirmed_in_committed_seed(self):
        listed = list_capabilities()
        mcp_rows = [
            r
            for r in listed["results"]
            if str(r.get("capability_id") or "").startswith("MCP.")
        ]
        self.assertGreaterEqual(len(mcp_rows), 1)
        for row in mcp_rows:
            self.assertEqual(
                row["status"],
                CAP_STATUS_DISCOVERY_REQUIRED,
                msg=row["capability_id"],
            )
            self.assertEqual(row["evidence"], [], msg=row["capability_id"])

    def test_restv2_workflow_list_confirmed_live_does_not_unlock_mcp_route(self):
        """PRD §3.2: RESTV2.WORKFLOW.LIST = CONFIRMED_LIVE (READ) must NOT set route=MCP.
        Only UPSERT execute-eligible unlocks MCP route; REST LIST is READ-only and
        does not satisfy the UPSERT check in resolve_package_route.
        """
        from dataruns.capabilities.contract import CAP_ID_RESTV2_WORKFLOW_LIST

        rest_list = get_capability(CAP_ID_RESTV2_WORKFLOW_LIST)
        self.assertIsNotNone(rest_list)
        assert rest_list is not None
        self.assertEqual(rest_list["status"], CAP_STATUS_CONFIRMED_LIVE)
        self.assertEqual(rest_list["channel"], "REST_V2")
        # Route with only REST LIST in deps stays HUMAN_FALLBACK.
        outcome = resolve_blueprint_capabilities(
            {
                "capability_dependencies": [
                    {
                        "capability_id": CAP_ID_RESTV2_WORKFLOW_LIST,
                        "required_status": "CONFIRMED_LIVE",
                        "fallback": None,
                    }
                ]
            }
        )
        self.assertEqual(outcome.route, PACKAGE_ROUTE_HUMAN_FALLBACK)

    def test_stock_seed_uc02_route_human_fallback(self):
        """§8 generate expects HUMAN_FALLBACK — assert resolver stock path too."""
        outcome = resolve_blueprint_capabilities(
            {"capability_dependencies": _UC02_DEPS}
        )
        self.assertEqual(outcome.route, PACKAGE_ROUTE_HUMAN_FALLBACK)
        upsert = next(
            r
            for r in outcome.capability_resolution
            if r["capability_id"] == CAP_ID_MCP_WORKFLOW_UPSERT
        )
        self.assertEqual(upsert["resolved_status"], RESOLVED_HUMAN_FALLBACK)
        self.assertEqual(upsert["fallback_used"], CAP_ID_HUMAN_WORKFLOW_BUILD)

    def test_in_memory_upsert_override_sets_route_mcp(self):
        stock = get_capability(CAP_ID_MCP_WORKFLOW_UPSERT)
        assert stock is not None
        fake = deepcopy(stock)
        fake["status"] = CAP_STATUS_CONFIRMED_LIVE
        fake["evidence"] = [
            {
                "source": "unit-test",
                "locator": "step7",
                "observed_at": "2026-08-26T00:00:00Z",
            }
        ]
        outcome = resolve_blueprint_capabilities(
            {"capability_dependencies": _UC02_DEPS},
            overrides={CAP_ID_MCP_WORKFLOW_UPSERT: fake},
        )
        self.assertEqual(outcome.route, PACKAGE_ROUTE_MCP)
        upsert = next(
            r
            for r in outcome.capability_resolution
            if r["capability_id"] == CAP_ID_MCP_WORKFLOW_UPSERT
        )
        self.assertEqual(upsert["resolved_status"], RESOLVED_MCP)


class Cap01BeMatrixStep7WritebackSafetyTests(SimpleTestCase):
    """§8 writeback row — option B registry must still allow CI-01 capability."""

    def test_writeback_ci01_capability_still_execute_eligible(self):
        # CI-01 mapping uses RESTV2.CONTACT.UPSERT (Maheep writeback JSON — not Matrix).
        mapping_path = (
            Path(__file__).resolve().parents[1]
            / "writebacks"
            / "mappings"
            / "CI-01.identity_backfill.v1.json"
        )
        self.assertTrue(mapping_path.is_file(), msg=str(mapping_path))
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        cap_ids = {
            str(op.get("capability_id") or "")
            for op in (mapping.get("operations") or [])
            if isinstance(op, dict)
        }
        self.assertIn("RESTV2.CONTACT.UPSERT", cap_ids)
        self.assertEqual(
            capability_status("RESTV2.CONTACT.UPSERT"),
            "CONFIRMED_LIVE",
        )
        self.assertTrue(capability_allows_execute("RESTV2.CONTACT.UPSERT"))

    def test_writeback_registry_stays_separate_from_matrix(self):
        import dataruns.writebacks.capabilities as wb_caps

        wb_src = Path(wb_caps.__file__).resolve()
        text = wb_src.read_text(encoding="utf-8")
        self.assertIn("option B", text)
        self.assertIn("TODO(CAP-unify)", text)
        self.assertIn("matrix_seed.json", text)
        # Matrix file must not be the writeback loader path.
        self.assertNotEqual(
            matrix_seed_path().resolve(),
            wb_src.with_name("capabilities.json").resolve(),
        )


class Cap01BeMatrixStep7HttpAndPackageTests(TestCase):
    """§8 generate + GET capabilities rows."""

    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="CAP-01 S7", slug="cap01-s7")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="CAP-01 S7 Co",
            domain="cap01-s7.example.com",
        )
        cls.analyst = User.objects.create_user(
            email="cap01-s7-analyst@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ANALYST,
        )
        cls.viewer = User.objects.create_user(
            email="cap01-s7-viewer@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.VIEWER,
        )

    def setUp(self):
        self.client = APIClient()
        self.factory = APIRequestFactory()

    def _seed_uc02_provisional(self) -> None:
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 80,
                "check_results": [{"check_id": "CC-03", "status": "PASS"}],
            },
        )
        af_run = DataRun.objects.create(
            tenant=self.tenant,
            name="Architecture Assessment",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": ARCHITECTURE_ASSESSMENT_KIND,
                "company_id": str(self.company.id),
            },
        )
        ArchitectureAssessment.objects.create(
            company=self.company,
            tenant=self.tenant,
            data_run=af_run,
            status=ArchitectureAssessment.Status.SUCCEEDED,
            mode=ArchitectureAssessment.Mode.AUGMENT,
            probe_coverage={"lifecycle_gaps": []},
        )

    def test_generate_uc02_package_human_fallback_resolution(self):
        self._seed_uc02_provisional()
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["route"], PACKAGE_ROUTE_HUMAN_FALLBACK)
        by_id = {
            r["capability_id"]: r for r in response.data["capability_resolution"]
        }
        upsert = by_id[CAP_ID_MCP_WORKFLOW_UPSERT]
        self.assertEqual(upsert["resolved_status"], RESOLVED_HUMAN_FALLBACK)
        self.assertEqual(upsert["fallback_used"], CAP_ID_HUMAN_WORKFLOW_BUILD)
        self.assertEqual(upsert["matrix_status"], CAP_STATUS_DISCOVERY_REQUIRED)

    def test_get_capabilities_includes_mcp_and_human(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get("/api/v1/capabilities/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["schema_version"], "1.0.0")
        self.assertEqual(body["source"], MATRIX_PACK_SOURCE)
        ids = {row["capability_id"] for row in body["results"]}
        self.assertIn(CAP_ID_MCP_WORKFLOW_UPSERT, ids)
        self.assertIn(CAP_ID_HUMAN_WORKFLOW_BUILD, ids)

    def test_get_unknown_capability_404(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get("/api/v1/capabilities/MCP.DOES.NOT.EXIST/")
        self.assertEqual(response.status_code, 404)
