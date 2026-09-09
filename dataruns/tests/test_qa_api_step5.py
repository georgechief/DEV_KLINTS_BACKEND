"""PRD-QA-01 Step 5 — build-package QA HTTP API."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from dataruns.models import AuditLog
from dataruns.use_cases.build_package import assemble_build_package_payload
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot, WorkflowBuildPackage, WorkflowQaResult
from dataruns.use_cases.qa_run import AUDIT_ACTION_QA_RUN_COMPLETED
from dataruns.use_cases.recommend import (
    RecommendationContext,
    _gates_from_blueprint,
    build_gates_snapshot,
)
from dataruns.use_cases.views import BuildPackageQaView, QaRunDetailView
from tenants.models import Company, Tenant, User

_SCHEMA_KEYS = (
    "schema_version",
    "qa_run_id",
    "tenant_id",
    "object_id",
    "package_id",
    "use_case_id",
    "score",
    "minimum_score",
    "hard_tests",
    "status",
    "evidence",
    "created_at",
)

class BuildPackageQaApiStep5Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="QA API", slug="qa-api")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="QA API Co",
            domain="qa-api.example.com",
        )
        cls.other_tenant = Tenant.objects.create(name="QA Other", slug="qa-other")
        cls.other_company = Company.objects.create(
            tenant=cls.other_tenant,
            name="QA Other Co",
            domain="qa-other.example.com",
        )
        cls.analyst = User.objects.create_user(
            email="qa-api-analyst@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ANALYST,
        )
        cls.viewer = User.objects.create_user(
            email="qa-api-viewer@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.VIEWER,
        )
        cls.outsider = User.objects.create_user(
            email="qa-api-outsider@example.com",
            password="pass",
            tenant=cls.other_tenant,
            role=User.Role.ADMIN,
        )
        cls.pilot = (
            UseCasePilot.objects.select_related("blueprint").get(use_case_id="UC-02")
        )
        cls.blueprint = cls.pilot.blueprint
        body = cls.blueprint.body if isinstance(cls.blueprint.body, dict) else {}
        gates = _gates_from_blueprint(body)
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
        gates_snapshot = build_gates_snapshot(
            gates=gates,
            ctx=ctx,
            provisional_supplemental=True,
        )
        cls.golden_payload = assemble_build_package_payload(
            package_id="00000000-0000-0000-0000-000000000005",
            pilot=cls.pilot,
            blueprint=cls.blueprint,
            company=cls.company,
            ctx_snapshot={
                "dcs_data_run_id": 1,
                "af_assessment_id": None,
                "af_mode": "AUGMENT",
                "headline_score": 85.0,
            },
            gates=gates,
            gates_snapshot=gates_snapshot,
            provisional_supplemental=True,
            generated_by=cls.analyst,
        )
        cls.factory = APIRequestFactory()

    def setUp(self):
        # Fresh client per test so force_authenticate does not leak.
        self.client = APIClient()

    def _persist_package(self, payload: dict | None = None) -> WorkflowBuildPackage:
        body = deepcopy(payload or self.golden_payload)
        record = WorkflowBuildPackage.objects.create(
            company=self.company,
            pilot=self.pilot,
            payload=body,
            provisional_supplemental=bool(body.get("provisional_supplemental")),
            blueprint_content_hash=self.blueprint.content_hash,
            package_content_hash=(body.get("hashes") or {}).get(
                "package_content_hash", "d" * 64
            ),
            generated_by=self.analyst,
        )
        body["package_id"] = str(record.id)
        record.payload = body
        record.save(update_fields=["payload"])
        return record

    def test_post_qa_returns_201_schema_and_audits(self):
        package = self._persist_package()
        request = self.factory.post(f"/api/v1/build-packages/{package.id}/qa/", {}, format="json")
        force_authenticate(request, user=self.analyst)
        response = BuildPackageQaView.as_view()(request, package_id=str(package.id))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "PASS")
        self.assertEqual(response.data["score"], 100.0)
        self.assertEqual(response.data["package_id"], str(package.id))
        self.assertEqual(response.data["object_id"], str(package.id))
        self.assertEqual(response.data["tenant_id"], str(self.company.id))
        self.assertEqual(response.data["use_case_id"], "UC-02")
        self.assertEqual(response.data["minimum_score"], 80.0)
        self.assertEqual(response.data["schema_version"], "1.0.0")
        for key in _SCHEMA_KEYS:
            self.assertIn(key, response.data)
        self.assertEqual(len(response.data["hard_tests"]), 7)
        self.assertTrue(WorkflowQaResult.objects.filter(package=package).exists())
        audit = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_QA_RUN_COMPLETED,
        ).latest("created_at")
        self.assertEqual(audit.metadata["package_id"], str(package.id))
        self.assertEqual(audit.metadata["qa_run_id"], response.data["qa_run_id"])
        self.assertEqual(audit.metadata["status"], "PASS")
        self.assertEqual(audit.metadata["hard_fail_ids"], [])

    def test_viewer_may_run_qa(self):
        package = self._persist_package()
        request = self.factory.post(f"/api/v1/build-packages/{package.id}/qa/", {}, format="json")
        force_authenticate(request, user=self.viewer)
        response = BuildPackageQaView.as_view()(request, package_id=str(package.id))
        self.assertEqual(response.status_code, 201)

    def test_get_latest_404_before_run_then_200(self):
        package = self._persist_package()
        get_empty = self.factory.get(f"/api/v1/build-packages/{package.id}/qa/")
        force_authenticate(get_empty, user=self.analyst)
        empty = BuildPackageQaView.as_view()(get_empty, package_id=str(package.id))
        self.assertEqual(empty.status_code, 404)

        post_req = self.factory.post(
            f"/api/v1/build-packages/{package.id}/qa/", {}, format="json"
        )
        force_authenticate(post_req, user=self.analyst)
        created = BuildPackageQaView.as_view()(post_req, package_id=str(package.id))
        self.assertEqual(created.status_code, 201)

        get_latest = self.factory.get(f"/api/v1/build-packages/{package.id}/qa/")
        force_authenticate(get_latest, user=self.analyst)
        latest = BuildPackageQaView.as_view()(get_latest, package_id=str(package.id))
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.data["qa_run_id"], created.data["qa_run_id"])
        self.assertEqual(latest.data["status"], "PASS")

    def test_routed_client_post_get_and_fail_still_201(self):
        """Hit real URLConf (uuid path kwargs) — not just the view callable."""
        package = self._persist_package()
        url = reverse("build-package-qa", kwargs={"package_id": package.id})
        self.client.force_authenticate(user=self.analyst)

        created = self.client.post(url, {}, format="json")
        self.assertEqual(created.status_code, 201)
        for key in _SCHEMA_KEYS:
            self.assertIn(key, created.data)

        latest = self.client.get(url)
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.data["qa_run_id"], created.data["qa_run_id"])

        detail = self.client.get(
            reverse("qa-run-detail", kwargs={"qa_run_id": created.data["qa_run_id"]})
        )
        self.assertEqual(detail.status_code, 200)

        # Overall FAIL is still HTTP 201 — status lives in the body (PRD §7.2).
        bad_payload = deepcopy(self.golden_payload)
        bad_payload["gates_snapshot"] = {
            "checks": {"CC-03": "FAIL", "CC-06": "not_evaluated"},
            "provisional_supplemental": True,
        }
        bad_package = self._persist_package(bad_payload)
        bad_url = reverse("build-package-qa", kwargs={"package_id": bad_package.id})
        failed = self.client.post(bad_url, {}, format="json")
        self.assertEqual(failed.status_code, 201)
        self.assertEqual(failed.data["status"], "FAIL")
        self.assertGreaterEqual(failed.data["score"], 80)

    def test_get_wrong_company_404(self):
        package = self._persist_package()
        request = self.factory.get(f"/api/v1/build-packages/{package.id}/qa/")
        force_authenticate(request, user=self.outsider)
        response = BuildPackageQaView.as_view()(request, package_id=str(package.id))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "Build package not found.")
    def test_rerun_appends_and_get_returns_newest(self):
        package = self._persist_package()
        view = BuildPackageQaView.as_view()
        first_req = self.factory.post(
            f"/api/v1/build-packages/{package.id}/qa/", {}, format="json"
        )
        force_authenticate(first_req, user=self.analyst)
        first = view(first_req, package_id=str(package.id))

        second_req = self.factory.post(
            f"/api/v1/build-packages/{package.id}/qa/", {}, format="json"
        )
        force_authenticate(second_req, user=self.analyst)
        second = view(second_req, package_id=str(package.id))

        self.assertNotEqual(first.data["qa_run_id"], second.data["qa_run_id"])
        self.assertEqual(WorkflowQaResult.objects.filter(package=package).count(), 2)

        get_req = self.factory.get(f"/api/v1/build-packages/{package.id}/qa/")
        force_authenticate(get_req, user=self.viewer)
        latest = view(get_req, package_id=str(package.id))
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.data["qa_run_id"], second.data["qa_run_id"])

    def test_missing_qa_requirements_returns_409(self):
        package = self._persist_package({"use_case_id": "UC-02", "title": "broken"})
        request = self.factory.post(f"/api/v1/build-packages/{package.id}/qa/", {}, format="json")
        force_authenticate(request, user=self.analyst)
        response = BuildPackageQaView.as_view()(request, package_id=str(package.id))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "qa_requirements_missing")
        self.assertEqual(WorkflowQaResult.objects.filter(package=package).count(), 0)

    def test_unknown_package_404(self):
        missing = str(uuid4())
        request = self.factory.post(f"/api/v1/build-packages/{missing}/qa/", {}, format="json")
        force_authenticate(request, user=self.analyst)
        response = BuildPackageQaView.as_view()(request, package_id=missing)
        self.assertEqual(response.status_code, 404)

    def test_wrong_company_package_404(self):
        package = self._persist_package()
        request = self.factory.post(f"/api/v1/build-packages/{package.id}/qa/", {}, format="json")
        force_authenticate(request, user=self.outsider)
        response = BuildPackageQaView.as_view()(request, package_id=str(package.id))
        self.assertEqual(response.status_code, 404)

    def test_qa_run_detail_get(self):
        package = self._persist_package()
        post_req = self.factory.post(
            f"/api/v1/build-packages/{package.id}/qa/", {}, format="json"
        )
        force_authenticate(post_req, user=self.analyst)
        created = BuildPackageQaView.as_view()(post_req, package_id=str(package.id))
        qa_run_id = created.data["qa_run_id"]

        get_req = self.factory.get(f"/api/v1/qa-runs/{qa_run_id}/")
        force_authenticate(get_req, user=self.viewer)
        detail = QaRunDetailView.as_view()(get_req, qa_run_id=qa_run_id)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["qa_run_id"], qa_run_id)
        self.assertEqual(detail.data["package_id"], str(package.id))

        outsider_req = self.factory.get(f"/api/v1/qa-runs/{qa_run_id}/")
        force_authenticate(outsider_req, user=self.outsider)
        blocked = QaRunDetailView.as_view()(outsider_req, qa_run_id=qa_run_id)
        self.assertEqual(blocked.status_code, 404)
