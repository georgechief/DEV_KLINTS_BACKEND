"""PRD-HO-01 Step 4 — handoff HTTP APIs (GET/POST)."""

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
from dataruns.use_cases.handoff_package import (
    AUDIT_ACTION_HANDOFF_STAGED,
    HANDOFF_PACKAGE_REQUIRED_FIELDS,
    HANDOFF_STATUS_STAGED,
)
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import (
    HandoffPackage,
    UseCasePilot,
    WorkflowBuildPackage,
    WorkflowQaResult,
)
from dataruns.use_cases.qa_result import QA_STATUS_FAIL, QA_STATUS_PASS
from dataruns.use_cases.recommend import (
    RecommendationContext,
    _gates_from_blueprint,
    build_gates_snapshot,
)
from dataruns.use_cases.views import (
    BuildPackageHandoffView,
    HandoffDetailView,
    HandoffListView,
)
from tenants.models import Company, Tenant, User

_SCHEMA_KEYS = tuple(sorted(HANDOFF_PACKAGE_REQUIRED_FIELDS))
_FE_SIBLINGS = (
    "use_case_id",
    "package_id",
    "qa_run_id",
)


class HandoffApiStep4Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="HO API", slug="ho-api")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="HO API Co",
            domain="ho-api.example.com",
        )
        cls.other_tenant = Tenant.objects.create(name="HO Other", slug="ho-other")
        cls.other_company = Company.objects.create(
            tenant=cls.other_tenant,
            name="HO Other Co",
            domain="ho-other.example.com",
        )
        cls.analyst = User.objects.create_user(
            email="ho-api-analyst@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ANALYST,
        )
        cls.viewer = User.objects.create_user(
            email="ho-api-viewer@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.VIEWER,
        )
        cls.outsider = User.objects.create_user(
            email="ho-api-outsider@example.com",
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
            package_id="00000000-0000-0000-0000-000000000004",
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
                "package_content_hash", "e" * 64
            ),
            generated_by=self.analyst,
        )
        body["package_id"] = str(record.id)
        record.payload = body
        record.save(update_fields=["payload"])
        return record

    def _qa(
        self,
        package: WorkflowBuildPackage,
        *,
        status: str = QA_STATUS_PASS,
    ) -> WorkflowQaResult:
        return WorkflowQaResult.objects.create(
            company=self.company,
            package=package,
            use_case_id="UC-02",
            score=100.0 if status == QA_STATUS_PASS else 40.0,
            status=status,
            payload={"status": status, "score": 100.0 if status == QA_STATUS_PASS else 40.0},
            created_by=self.analyst,
        )

    def _assert_handoff_shape(self, data: dict, *, package_id: str, qa_run_id: str):
        for key in _SCHEMA_KEYS:
            self.assertIn(key, data)
        for key in _FE_SIBLINGS:
            self.assertIn(key, data)
        self.assertEqual(data["status"], HANDOFF_STATUS_STAGED)
        self.assertEqual(data["package_id"], package_id)
        self.assertEqual(data["qa_run_id"], qa_run_id)
        self.assertEqual(data["qa_ref"], qa_run_id)
        self.assertEqual(data["use_case_id"], "UC-02")
        self.assertEqual(data["tenant_id"], str(self.company.id))

    def test_post_stages_201_then_idempotent_200(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        path = f"/api/v1/build-packages/{package.id}/handoff/"

        create_req = self.factory.post(path, {}, format="json")
        force_authenticate(create_req, user=self.analyst)
        created = BuildPackageHandoffView.as_view()(
            create_req, package_id=str(package.id)
        )
        self.assertEqual(created.status_code, 201)
        self._assert_handoff_shape(
            created.data,
            package_id=str(package.id),
            qa_run_id=str(qa.id),
        )
        self.assertEqual(HandoffPackage.objects.filter(package=package).count(), 1)
        audit = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_HANDOFF_STAGED,
        ).latest("created_at")
        self.assertEqual(audit.metadata["handoff_id"], created.data["handoff_id"])

        again_req = self.factory.post(path, {}, format="json")
        force_authenticate(again_req, user=self.analyst)
        again = BuildPackageHandoffView.as_view()(
            again_req, package_id=str(package.id)
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data["handoff_id"], created.data["handoff_id"])
        self.assertEqual(HandoffPackage.objects.filter(package=package).count(), 1)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_STAGED,
            ).count(),
            1,
        )

    def test_post_fail_qa_returns_409(self):
        package = self._persist_package()
        self._qa(package, status=QA_STATUS_FAIL)
        request = self.factory.post(
            f"/api/v1/build-packages/{package.id}/handoff/", {}, format="json"
        )
        force_authenticate(request, user=self.analyst)
        response = BuildPackageHandoffView.as_view()(
            request, package_id=str(package.id)
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "qa_not_pass")
        self.assertEqual(HandoffPackage.objects.filter(package=package).count(), 0)

    def test_post_missing_qa_returns_409(self):
        package = self._persist_package()
        request = self.factory.post(
            f"/api/v1/build-packages/{package.id}/handoff/", {}, format="json"
        )
        force_authenticate(request, user=self.analyst)
        response = BuildPackageHandoffView.as_view()(
            request, package_id=str(package.id)
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "qa_missing")

    def test_viewer_forbidden_on_post_allowed_on_get(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        path = f"/api/v1/build-packages/{package.id}/handoff/"

        post_req = self.factory.post(path, {}, format="json")
        force_authenticate(post_req, user=self.viewer)
        blocked = BuildPackageHandoffView.as_view()(
            post_req, package_id=str(package.id)
        )
        self.assertEqual(blocked.status_code, 403)

        # Stage as analyst, then viewer may read.
        stage_req = self.factory.post(path, {}, format="json")
        force_authenticate(stage_req, user=self.analyst)
        staged = BuildPackageHandoffView.as_view()(
            stage_req, package_id=str(package.id)
        )
        self.assertEqual(staged.status_code, 201)

        get_req = self.factory.get(path)
        force_authenticate(get_req, user=self.viewer)
        latest = BuildPackageHandoffView.as_view()(
            get_req, package_id=str(package.id)
        )
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.data["qa_run_id"], str(qa.id))

    def test_get_latest_404_then_200(self):
        package = self._persist_package()
        path = f"/api/v1/build-packages/{package.id}/handoff/"

        empty_req = self.factory.get(path)
        force_authenticate(empty_req, user=self.analyst)
        empty = BuildPackageHandoffView.as_view()(
            empty_req, package_id=str(package.id)
        )
        self.assertEqual(empty.status_code, 404)

        self._qa(package, status=QA_STATUS_PASS)
        post_req = self.factory.post(path, {}, format="json")
        force_authenticate(post_req, user=self.analyst)
        created = BuildPackageHandoffView.as_view()(
            post_req, package_id=str(package.id)
        )
        self.assertEqual(created.status_code, 201)

        get_req = self.factory.get(path)
        force_authenticate(get_req, user=self.analyst)
        latest = BuildPackageHandoffView.as_view()(
            get_req, package_id=str(package.id)
        )
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.data["handoff_id"], created.data["handoff_id"])

    def test_detail_and_list_filters(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        path = f"/api/v1/build-packages/{package.id}/handoff/"
        post_req = self.factory.post(path, {}, format="json")
        force_authenticate(post_req, user=self.analyst)
        created = BuildPackageHandoffView.as_view()(
            post_req, package_id=str(package.id)
        )
        handoff_id = created.data["handoff_id"]

        detail_req = self.factory.get(f"/api/v1/handoffs/{handoff_id}/")
        force_authenticate(detail_req, user=self.viewer)
        detail = HandoffDetailView.as_view()(detail_req, handoff_id=handoff_id)
        self.assertEqual(detail.status_code, 200)
        self._assert_handoff_shape(
            detail.data,
            package_id=str(package.id),
            qa_run_id=str(qa.id),
        )

        list_req = self.factory.get(
            f"/api/v1/handoffs/?package_id={package.id}&qa_run_id={qa.id}"
        )
        force_authenticate(list_req, user=self.analyst)
        listed = HandoffListView.as_view()(list_req)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 1)
        self.assertEqual(listed.data["results"][0]["handoff_id"], handoff_id)

        miss_req = self.factory.get(f"/api/v1/handoffs/?qa_run_id={uuid4()}")
        force_authenticate(miss_req, user=self.analyst)
        miss = HandoffListView.as_view()(miss_req)
        self.assertEqual(miss.status_code, 200)
        self.assertEqual(miss.data["count"], 0)

    def test_routed_client_urls(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        url = reverse("build-package-handoff", kwargs={"package_id": package.id})
        self.client.force_authenticate(user=self.analyst)

        created = self.client.post(url, {}, format="json")
        self.assertEqual(created.status_code, 201)
        handoff_id = created.data["handoff_id"]

        latest = self.client.get(url)
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.data["handoff_id"], handoff_id)

        detail = self.client.get(
            reverse("handoff-detail", kwargs={"handoff_id": handoff_id})
        )
        self.assertEqual(detail.status_code, 200)

        listed = self.client.get(
            reverse("handoff-list"),
            {"package_id": str(package.id), "qa_run_id": str(qa.id)},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 1)

    def test_wrong_company_404(self):
        package = self._persist_package()
        self._qa(package, status=QA_STATUS_PASS)
        path = f"/api/v1/build-packages/{package.id}/handoff/"

        post_req = self.factory.post(path, {}, format="json")
        force_authenticate(post_req, user=self.outsider)
        blocked_post = BuildPackageHandoffView.as_view()(
            post_req, package_id=str(package.id)
        )
        self.assertEqual(blocked_post.status_code, 404)

        # Stage for real company, then outsider cannot read.
        stage_req = self.factory.post(path, {}, format="json")
        force_authenticate(stage_req, user=self.analyst)
        staged = BuildPackageHandoffView.as_view()(
            stage_req, package_id=str(package.id)
        )
        handoff_id = staged.data["handoff_id"]

        get_req = self.factory.get(path)
        force_authenticate(get_req, user=self.outsider)
        blocked_get = BuildPackageHandoffView.as_view()(
            get_req, package_id=str(package.id)
        )
        self.assertEqual(blocked_get.status_code, 404)

        detail_req = self.factory.get(f"/api/v1/handoffs/{handoff_id}/")
        force_authenticate(detail_req, user=self.outsider)
        blocked_detail = HandoffDetailView.as_view()(
            detail_req, handoff_id=handoff_id
        )
        self.assertEqual(blocked_detail.status_code, 404)

    def test_unknown_package_404(self):
        missing = str(uuid4())
        request = self.factory.post(
            f"/api/v1/build-packages/{missing}/handoff/", {}, format="json"
        )
        force_authenticate(request, user=self.analyst)
        response = BuildPackageHandoffView.as_view()(request, package_id=missing)
        self.assertEqual(response.status_code, 404)

    def test_post_explicit_qa_run_id(self):
        package = self._persist_package()
        older = self._qa(package, status=QA_STATUS_PASS)
        newer_fail = self._qa(package, status=QA_STATUS_FAIL)
        path = f"/api/v1/build-packages/{package.id}/handoff/"

        # Latest is FAIL → default POST 409
        fail_req = self.factory.post(path, {}, format="json")
        force_authenticate(fail_req, user=self.analyst)
        failed = BuildPackageHandoffView.as_view()(
            fail_req, package_id=str(package.id)
        )
        self.assertEqual(failed.status_code, 409)
        self.assertEqual(failed.data["code"], "qa_not_pass")

        # Explicit older PASS qa_run_id → 201
        ok_req = self.factory.post(
            path, {"qa_run_id": str(older.id)}, format="json"
        )
        force_authenticate(ok_req, user=self.analyst)
        created = BuildPackageHandoffView.as_view()(
            ok_req, package_id=str(package.id)
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["qa_run_id"], str(older.id))
        self.assertNotEqual(created.data["qa_run_id"], str(newer_fail.id))

    def test_invalid_uuid_filters_and_body_return_400(self):
        package = self._persist_package()
        self._qa(package, status=QA_STATUS_PASS)

        list_req = self.factory.get("/api/v1/handoffs/?package_id=not-a-uuid")
        force_authenticate(list_req, user=self.analyst)
        listed = HandoffListView.as_view()(list_req)
        self.assertEqual(listed.status_code, 400)
        self.assertEqual(listed.data["code"], "invalid_package_id")

        list_qa = self.factory.get("/api/v1/handoffs/?qa_run_id=also-bad")
        force_authenticate(list_qa, user=self.analyst)
        listed_qa = HandoffListView.as_view()(list_qa)
        self.assertEqual(listed_qa.status_code, 400)
        self.assertEqual(listed_qa.data["code"], "invalid_qa_run_id")

        post_req = self.factory.post(
            f"/api/v1/build-packages/{package.id}/handoff/",
            {"qa_run_id": "not-a-uuid"},
            format="json",
        )
        force_authenticate(post_req, user=self.analyst)
        bad_post = BuildPackageHandoffView.as_view()(
            post_req, package_id=str(package.id)
        )
        self.assertEqual(bad_post.status_code, 400)
        self.assertEqual(bad_post.data["code"], "invalid_qa_run_id")

    def test_serialize_forces_identity_from_columns(self):
        from dataruns.use_cases.handoff_package import serialize_handoff
        from dataruns.use_cases.handoff_stage import create_or_get_staged_handoff

        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        outcome = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=self.analyst,
        )
        record = (
            HandoffPackage.objects.select_related(
                "package", "package__pilot", "qa_result"
            ).get(pk=outcome.record.id)
        )
        # Corrupt stored payload identity — API must still reflect columns.
        record.payload = {
            **(record.payload if isinstance(record.payload, dict) else {}),
            "handoff_id": "00000000-0000-0000-0000-000000000099",
            "tenant_id": "00000000-0000-0000-0000-000000000088",
            "qa_ref": "00000000-0000-0000-0000-000000000077",
            "status": "ACTIVATED",
        }
        record.save(update_fields=["payload"])
        record.refresh_from_db()
        record = (
            HandoffPackage.objects.select_related(
                "package", "package__pilot", "qa_result"
            ).get(pk=record.id)
        )

        data = serialize_handoff(record)
        self.assertEqual(data["handoff_id"], str(record.id))
        self.assertEqual(data["tenant_id"], str(self.company.id))
        self.assertEqual(data["qa_ref"], str(qa.id))
        self.assertEqual(data["status"], HANDOFF_STATUS_STAGED)
        self.assertEqual(data["package_id"], str(package.id))
        self.assertIn("title", data)
        self.assertEqual(data["qa_status"], QA_STATUS_PASS)