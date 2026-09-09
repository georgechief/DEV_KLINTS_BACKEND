"""Tests for PRD-WF-01 Phase 1 — build package + provisional gates."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.architecture.constants import ARCHITECTURE_ASSESSMENT_KIND
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.pilot_gates.store import save_pilot_gate_eval
from dataruns.models import AuditLog, DataRun
from dataruns.use_cases.constants import (
    DEFAULT_MANIFEST_REL,
    HANDOFF_PACKAGE_SPEC,
    MCP_ACTION_OBJECT_THEATER_FORMAT,
    MVP1_PILOT_IDS,
    SUPPLEMENTAL_PREFLIGHT_CHECKS,
)
from dataruns.use_cases.build_package import (
    _handoff_stub_from_blueprint,
    normalize_handoff_stub_format,
    serialize_build_package,
)
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot, WorkflowBuildPackage
from dataruns.use_cases.recommend import STATUS_READY, STATUS_READY_PROVISIONAL
from dataruns.use_cases.views import BuildPackageDetailView, UseCaseBuildPackageView
from tenants.models import Company, Tenant, User


class WorkflowBuildPackageTests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="WF-01", slug="wf-01")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="WF-01 Co",
            domain="wf-01.example.com",
        )
        self.analyst = User.objects.create_user(
            email="wf-analyst@example.com",
            password="pass",
            tenant=self.tenant,
            role=User.Role.ANALYST,
        )
        self.viewer = User.objects.create_user(
            email="wf-viewer@example.com",
            password="pass",
            tenant=self.tenant,
            role=User.Role.VIEWER,
        )
        self.factory = APIRequestFactory()

    def _dcs(self, *, score: float, checks: list[dict]) -> DataRun:
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": score,
                "check_results": checks,
            },
        )

    def _af(self, mode=ArchitectureAssessment.Mode.AUGMENT) -> ArchitectureAssessment:
        af_run = DataRun.objects.create(
            tenant=self.tenant,
            name="Architecture Assessment",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": ARCHITECTURE_ASSESSMENT_KIND,
                "company_id": str(self.company.id),
            },
        )
        return ArchitectureAssessment.objects.create(
            company=self.company,
            tenant=self.tenant,
            data_run=af_run,
            status=ArchitectureAssessment.Status.SUCCEEDED,
            mode=mode,
            probe_coverage={"lifecycle_gaps": []},
        )

    def _seed_pilot_buildable(self, use_case_id: str) -> None:
        pilot = (
            UseCasePilot.objects.select_related("blueprint")
            .prefetch_related("stage_maps")
            .get(use_case_id=use_case_id)
        )
        body = pilot.blueprint.body if pilot.blueprint else {}
        gates = body.get("gates") if isinstance(body.get("gates"), dict) else {}
        min_dcs = float(gates.get("min_dcs") or 70)
        check_ids = [str(c).strip().upper() for c in (gates.get("gating_check_ids") or [])]
        hard = [
            {"check_id": cid, "status": "PASS"}
            for cid in check_ids
            if cid not in SUPPLEMENTAL_PREFLIGHT_CHECKS
        ]
        supplemental = [
            {"check_id": cid, "status": "PASS"}
            for cid in check_ids
            if cid in SUPPLEMENTAL_PREFLIGHT_CHECKS
        ]
        self._dcs(score=max(min_dcs, 75), checks=hard)
        if supplemental:
            save_pilot_gate_eval(
                company=self.company,
                results=supplemental,
                erp_in_scope=False,
                merge_with_previous=True,
            )
        allowed = gates.get("architecture_modes") or ["AUGMENT"]
        mode_key = str(allowed[0]).upper() if allowed else "AUGMENT"
        mode = getattr(
            ArchitectureAssessment.Mode,
            mode_key,
            ArchitectureAssessment.Mode.AUGMENT,
        )
        self._af(mode=mode)

    def _seed_uc02_provisional(self) -> None:
        self._dcs(
            score=80,
            checks=[{"check_id": "CC-03", "status": "PASS"}],
        )
        self._af()

    def _seed_uc06b_provisional(self) -> None:
        checks = [
            {"check_id": "LE-01", "status": "PASS"},
            {"check_id": "LE-05", "status": "PASS"},
            {"check_id": "PT-04", "status": "PASS"},
            {"check_id": "CC-01", "status": "PASS"},
            {"check_id": "CC-02", "status": "PASS"},
        ]
        self._dcs(score=80, checks=checks)
        self._af()

    def test_uc02_build_package_provisional(self):
        self._seed_uc02_provisional()
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["provisional_supplemental"])
        self.assertEqual(response.data["route"], "HUMAN_FALLBACK")
        self.assertEqual(response.data["use_case_id"], "UC-02")
        self.assertIn("human_guide", response.data)
        self.assertIn("agent_spec", response.data)
        self.assertIn("qa_requirements", response.data)
        self.assertIn("approval_requirements", response.data)
        self.assertIn("rollback", response.data)
        self.assertIn("handoff_stub", response.data)
        self.assertEqual(
            response.data["handoff_stub"]["activation_state"],
            "STAGED_NOT_LIVE",
        )
        # GAP-01 Slice D: runtime honesty — not pack MCP_ACTION theater
        self.assertEqual(
            response.data["handoff_stub"]["format"],
            HANDOFF_PACKAGE_SPEC,
        )
        self.assertNotEqual(
            response.data["handoff_stub"]["format"],
            MCP_ACTION_OBJECT_THEATER_FORMAT,
        )
        self.assertEqual(response.data["content_state"]["agent_output_state"], "DRAFT")
        gates = response.data["gates_snapshot"]
        self.assertTrue(gates["provisional_supplemental"])
        self.assertEqual(gates["checks"]["CC-06"], "not_evaluated")
        self.assertGreater(len(response.data["human_guide"]["steps"]), 1)
        first_step = response.data["human_guide"]["steps"][0]
        self.assertIn("fields", first_step)
        self.assertTrue(first_step["fields"])
        self.assertGreater(len(response.data["agent_spec"]["nodes"]), 1)

        package_id = response.data["package_id"]
        self.assertTrue(
            WorkflowBuildPackage.objects.filter(pk=package_id, company=self.company).exists()
        )

        audit = AuditLog.objects.filter(
            company=self.company,
            action="workflow.build_package_generated",
        ).first()
        self.assertIsNotNone(audit)
        self.assertTrue(audit.metadata.get("provisional_supplemental"))

    def test_uc06b_build_package_provisional_when_sp10_missing(self):
        self._seed_uc06b_provisional()
        request = self.factory.post("/api/v1/use-cases/UC-06B/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-06B")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["provisional_supplemental"])
        self.assertEqual(
            response.data["gates_snapshot"]["checks"]["SP-10"],
            "not_evaluated",
        )

    def test_build_package_blocked_when_cc03_fail(self):
        self._dcs(
            score=80,
            checks=[
                {"check_id": "CC-03", "status": "FAIL"},
                {"check_id": "CC-06", "status": "PASS"},
                {"check_id": "CI-08", "status": "PASS"},
            ],
        )
        self._af()
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "blocked_checks")
        self.assertTrue(response.data["blockers"])

    def test_build_package_blocked_when_supplemental_fail(self):
        # DCS-09 Step 9: store supplemental FAIL → Generate locked (blocked_checks).
        self._seed_uc02_provisional()
        save_pilot_gate_eval(
            company=self.company,
            results=[
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "FAIL"},
            ],
            erp_in_scope=False,
            merge_with_previous=False,
        )
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "blocked_checks")
        self.assertTrue(
            any(b.get("check_id") == "CC-06" for b in response.data["blockers"])
        )

    def test_build_package_blocked_when_score_low(self):
        self._dcs(
            score=65,
            checks=[{"check_id": "CC-03", "status": "PASS"}],
        )
        self._af()
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "blocked_dcs_score")

    def test_get_build_package(self):
        self._seed_uc02_provisional()
        post = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(post, user=self.analyst)
        created = UseCaseBuildPackageView.as_view()(post, use_case_id="UC-02")
        package_id = created.data["package_id"]

        get = self.factory.get(f"/api/v1/build-packages/{package_id}/")
        force_authenticate(get, user=self.viewer)
        response = BuildPackageDetailView.as_view()(get, package_id=package_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["package_id"], str(package_id))
        self.assertEqual(response.data["use_case_id"], "UC-02")
        self.assertEqual(
            response.data["handoff_stub"]["format"],
            HANDOFF_PACKAGE_SPEC,
        )

    def test_viewer_cannot_generate(self):
        self._seed_uc02_provisional()
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.viewer)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 403)

    def test_uc06b_recommendation_provisional(self):
        self._seed_uc06b_provisional()
        pilot = UseCasePilot.objects.get(use_case_id="UC-06B")
        from dataruns.use_cases.recommend import (
            evaluate_pilot,
            resolve_recommendation_context,
        )

        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(pilot, ctx)
        self.assertEqual(row["status"], STATUS_READY_PROVISIONAL)
        self.assertEqual(row["supplemental_status"]["SP-10"], "not_evaluated")

    def test_uc02_build_package_ready_when_store_pass(self):
        self._seed_pilot_buildable("UC-02")
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["provisional_supplemental"])
        self.assertEqual(
            response.data["gates_snapshot"]["checks"]["CI-08"],
            "PASS",
        )
        self.assertEqual(
            response.data["gates_snapshot"]["checks"]["CC-06"],
            "PASS",
        )
        pilot = UseCasePilot.objects.get(use_case_id="UC-02")
        from dataruns.use_cases.recommend import (
            evaluate_pilot,
            resolve_recommendation_context,
        )

        row = evaluate_pilot(
            pilot, resolve_recommendation_context(company=self.company)
        )
        self.assertEqual(row["status"], STATUS_READY)

    def test_all_sixteen_pilots_generate_build_package(self):
        """PRD-WF-01 §13 slice 4 — generic generator for full MVP1 library."""
        for use_case_id in sorted(MVP1_PILOT_IDS):
            with self.subTest(use_case_id=use_case_id):
                self._seed_pilot_buildable(use_case_id)
                request = self.factory.post(
                    f"/api/v1/use-cases/{use_case_id}/build-package/",
                )
                force_authenticate(request, user=self.analyst)
                response = UseCaseBuildPackageView.as_view()(
                    request,
                    use_case_id=use_case_id,
                )
                self.assertEqual(
                    response.status_code,
                    201,
                    msg=response.data if hasattr(response, "data") else response,
                )
                self.assertEqual(response.data["use_case_id"], use_case_id)
                self.assertEqual(response.data["route"], "HUMAN_FALLBACK")
                self.assertIn("human_guide", response.data)
                self.assertIn("agent_spec", response.data)
                self.assertIn("qa_requirements", response.data)
                self.assertIn("handoff_stub", response.data)
                self.assertEqual(
                    response.data["handoff_stub"]["format"],
                    HANDOFF_PACKAGE_SPEC,
                )
                self.assertGreater(len(response.data["human_guide"]["steps"]), 0)

    def test_handoff_stub_overrides_pack_mcp_action_theater(self):
        """GAP-01 Slice D: pack MCP_ACTION label must not leak into API payload."""
        stub = _handoff_stub_from_blueprint(
            {
                "handoff": {
                    "format": MCP_ACTION_OBJECT_THEATER_FORMAT,
                    "activation_state": "STAGED_NOT_LIVE",
                    "idempotency_key_template": "uc:{use_case_id}:{hash}",
                }
            }
        )
        self.assertEqual(stub["format"], HANDOFF_PACKAGE_SPEC)
        self.assertNotEqual(stub["format"], MCP_ACTION_OBJECT_THEATER_FORMAT)
        self.assertEqual(stub["activation_state"], "STAGED_NOT_LIVE")
        self.assertEqual(stub["idempotency_key_template"], "uc:{use_case_id}:{hash}")

        empty = _handoff_stub_from_blueprint({})
        self.assertEqual(empty["format"], HANDOFF_PACKAGE_SPEC)
        self.assertEqual(empty["activation_state"], "STAGED_NOT_LIVE")

    def test_serialize_normalizes_stored_mcp_action_theater(self):
        """GAP-01 Slice D: GET/Download must not leak stored MCP_ACTION theater."""
        self._seed_pilot_buildable("UC-02")
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 201)
        package_id = response.data["package_id"]
        record = WorkflowBuildPackage.objects.get(pk=package_id)

        # Simulate a pre-Slice-D stored row (immutable DB still has theater).
        dirty = dict(record.payload)
        stub = dict(dirty.get("handoff_stub") or {})
        stub["format"] = MCP_ACTION_OBJECT_THEATER_FORMAT
        dirty["handoff_stub"] = stub
        record.payload = dirty
        record.save(update_fields=["payload"])

        stored = WorkflowBuildPackage.objects.get(pk=package_id)
        self.assertEqual(
            stored.payload["handoff_stub"]["format"],
            MCP_ACTION_OBJECT_THEATER_FORMAT,
        )

        api = serialize_build_package(stored)
        self.assertEqual(api["handoff_stub"]["format"], HANDOFF_PACKAGE_SPEC)
        # DB unchanged
        stored.refresh_from_db()
        self.assertEqual(
            stored.payload["handoff_stub"]["format"],
            MCP_ACTION_OBJECT_THEATER_FORMAT,
        )

        normalized = normalize_handoff_stub_format(stored.payload)
        self.assertEqual(normalized["handoff_stub"]["format"], HANDOFF_PACKAGE_SPEC)

        # Case / future labels also forced honest until Track B (D0.1).
        for raw in (
            MCP_ACTION_OBJECT_THEATER_FORMAT.lower(),
            "  " + MCP_ACTION_OBJECT_THEATER_FORMAT + "  ",
            "FUTURE_MCP_SIGNED_V1",
            "",
        ):
            forced = normalize_handoff_stub_format(
                {"handoff_stub": {"format": raw}}
            )
            self.assertEqual(forced["handoff_stub"]["format"], HANDOFF_PACKAGE_SPEC)

        # Must not mutate caller payload.
        src = {
            "handoff_stub": {
                "format": MCP_ACTION_OBJECT_THEATER_FORMAT,
                "keep": True,
            }
        }
        normalize_handoff_stub_format(src)
        self.assertEqual(src["handoff_stub"]["format"], MCP_ACTION_OBJECT_THEATER_FORMAT)
        self.assertTrue(src["handoff_stub"]["keep"])
