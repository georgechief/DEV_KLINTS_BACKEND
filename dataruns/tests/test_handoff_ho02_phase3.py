"""PRD-HO-02 Phase 3 — handoff activation HTTP APIs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from dataruns.capabilities.contract import CAP_STATUS_DISCOVERY_REQUIRED
from dataruns.models import AuditLog
from dataruns.use_cases.build_package import assemble_build_package_payload
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.handoff_package import (
    ACTIVATION_PATH_HUMAN_MANAGO_UI,
    AUDIT_ACTION_HANDOFF_ACTIVATED,
    AUDIT_ACTION_HANDOFF_APPROVED,
    AUDIT_ACTION_HANDOFF_REJECTED,
    HANDOFF_STATUS_ACTIVATED,
    HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
    HANDOFF_STATUS_REJECTED,
    HANDOFF_STATUS_STAGED,
)
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import (
    HandoffPackage,
    UseCasePilot,
    WorkflowBuildPackage,
)
from dataruns.use_cases.qa_result import QA_STATUS_FAIL, QA_STATUS_PASS
from dataruns.use_cases.qa_run import run_qa_for_package
from dataruns.use_cases.recommend import (
    RecommendationContext,
    _gates_from_blueprint,
    build_gates_snapshot,
)
from tenants.models import Company, Tenant, User


class HandoffHo02Phase3ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="HO02 P3", slug="ho02-p3")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="HO02 P3 Co",
            domain="ho02-p3.example.com",
        )
        cls.other_tenant = Tenant.objects.create(name="HO02 P3 Other", slug="ho02-p3-other")
        cls.other_company = Company.objects.create(
            tenant=cls.other_tenant,
            name="HO02 P3 Other Co",
            domain="ho02-p3-other.example.com",
        )
        cls.admin = User.objects.create_user(
            email="ho02-p3-admin@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ADMIN,
        )
        cls.analyst = User.objects.create_user(
            email="ho02-p3-analyst@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ANALYST,
        )
        cls.viewer = User.objects.create_user(
            email="ho02-p3-viewer@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.VIEWER,
        )
        cls.outsider = User.objects.create_user(
            email="ho02-p3-outsider@example.com",
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
            package_id="00000000-0000-0000-0000-000000000006",
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

    def setUp(self):
        self.client = APIClient()

    def _persist_package(self) -> WorkflowBuildPackage:
        body = deepcopy(self.golden_payload)
        record = WorkflowBuildPackage.objects.create(
            company=self.company,
            pilot=self.pilot,
            payload=body,
            provisional_supplemental=True,
            blueprint_content_hash=self.blueprint.content_hash,
            package_content_hash=(body.get("hashes") or {}).get(
                "package_content_hash", "f" * 64
            ),
            generated_by=self.analyst,
        )
        body["package_id"] = str(record.id)
        record.payload = body
        record.save(update_fields=["payload"])
        return record

    def _stage_handoff_via_api(self) -> tuple[str, str]:
        package = self._persist_package()
        run_qa_for_package(package=package, created_by=self.analyst)
        self.client.force_authenticate(user=self.analyst)
        staged = self.client.post(
            reverse("build-package-handoff", kwargs={"package_id": package.id}),
            {},
            format="json",
        )
        self.assertIn(staged.status_code, (200, 201))
        return staged.data["handoff_id"], staged.data["manifest_hash"]

    def test_approve_returns_prd_shape(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash, "notes": "go"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["handoff_id"], handoff_id)
        self.assertEqual(response.data["status"], HANDOFF_STATUS_APPROVED_FOR_ACTIVATION)
        self.assertEqual(response.data["activation_meta"]["path"], ACTIVATION_PATH_HUMAN_MANAGO_UI)
        self.assertIn("activation_guide", response.data)
        self.assertIn("human_guide", response.data["activation_guide"])
        self.assertEqual(response.data["activation_guide"]["use_case_id"], "UC-02")
        self.assertEqual(
            response.data["activation_guide"]["summary"],
            "Build/activate this workflow in Manago UI using the package guide.",
        )
        self.assertIn("manago_hint", response.data["activation_guide"])
        self.assertEqual(
            response.data["capability"]["mcp_publish_status"],
            CAP_STATUS_DISCOVERY_REQUIRED,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_APPROVED,
            ).count(),
            1,
        )

    def test_approve_idempotent_200(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        url = reverse("handoff-approve", kwargs={"handoff_id": handoff_id})
        body = {"manifest_hash": manifest_hash}
        self.assertEqual(self.client.post(url, body, format="json").status_code, 200)
        second = self.client.post(url, body, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["status"], HANDOFF_STATUS_APPROVED_FOR_ACTIVATION)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_APPROVED,
            ).count(),
            1,
        )

    def test_approve_manifest_mismatch_409(self):
        handoff_id, _manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": "a" * 64},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "manifest_mismatch")

    def test_approve_missing_manifest_400(self):
        handoff_id, _manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "manifest_required")

    def test_analyst_and_viewer_forbidden_on_activate(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        body = {"manifest_hash": manifest_hash}
        for user in (self.analyst, self.viewer):
            self.client.force_authenticate(user=user)
            for name in ("handoff-approve", "handoff-reject", "handoff-confirm-activated"):
                response = self.client.post(
                    reverse(name, kwargs={"handoff_id": handoff_id}),
                    body,
                    format="json",
                )
                self.assertEqual(response.status_code, 403, msg=f"{user.role} {name}")
                self.assertEqual(response.data["code"], "forbidden")

    def test_reject_and_confirm_flow(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)

        reject = self.client.post(
            reverse("handoff-reject", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash, "reason": "not yet"},
            format="json",
        )
        self.assertEqual(reject.status_code, 200)
        self.assertEqual(reject.data["status"], HANDOFF_STATUS_REJECTED)
        self.assertEqual(reject.data["activation_meta"]["rejection_reason"], "not yet")

        handoff_id2, manifest_hash2 = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        approved = self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id2}),
            {"manifest_hash": manifest_hash2},
            format="json",
        )
        self.assertEqual(approved.status_code, 200)

        confirmed = self.client.post(
            reverse(
                "handoff-confirm-activated",
                kwargs={"handoff_id": handoff_id2},
            ),
            {
                "manifest_hash": manifest_hash2,
                "manago_workflow_external_id": "wf-42",
            },
            format="json",
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.data["status"], HANDOFF_STATUS_ACTIVATED)
        self.assertEqual(
            confirmed.data["activation_meta"]["manago_workflow_external_id"],
            "wf-42",
        )
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_ACTIVATED,
            ).count(),
            1,
        )

    def test_confirm_from_staged_409(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse(
                "handoff-confirm-activated",
                kwargs={"handoff_id": handoff_id},
            ),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "handoff_not_staged")

    def test_handoff_not_found_404(self):
        self.client.force_authenticate(user=self.admin)
        missing = str(uuid4())
        response = self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": missing}),
            {"manifest_hash": "b" * 64},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_cross_company_handoff_not_found(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.outsider)
        response = self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_get_detail_includes_activation_meta_after_approve(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        self.client.force_authenticate(user=self.viewer)
        detail = self.client.get(
            reverse("handoff-detail", kwargs={"handoff_id": handoff_id})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["status"], HANDOFF_STATUS_APPROVED_FOR_ACTIVATION)
        self.assertIn("activation_meta", detail.data)
        self.assertEqual(
            detail.data["activation_meta"]["path"],
            ACTIVATION_PATH_HUMAN_MANAGO_UI,
        )
        self.assertIn("activation_guide", detail.data)
        self.assertIn("human_guide", detail.data["activation_guide"])
        self.assertEqual(
            detail.data["capability"]["mcp_publish_status"],
            CAP_STATUS_DISCOVERY_REQUIRED,
        )

    def test_approve_on_activated_returns_handoff_not_staged(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        self.client.post(
            reverse(
                "handoff-confirm-activated",
                kwargs={"handoff_id": handoff_id},
            ),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        response = self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "handoff_not_staged")

    def test_approve_qa_not_pass_409(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        record = HandoffPackage.objects.select_related("qa_result").get(pk=handoff_id)
        record.qa_result.status = "FAIL"
        record.qa_result.save(update_fields=["status"])
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "qa_not_pass")

    def test_confirm_idempotent_200(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        url = reverse(
            "handoff-confirm-activated",
            kwargs={"handoff_id": handoff_id},
        )
        body = {"manifest_hash": manifest_hash}
        self.assertEqual(self.client.post(url, body, format="json").status_code, 200)
        second = self.client.post(url, body, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["status"], HANDOFF_STATUS_ACTIVATED)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_ACTIVATED,
            ).count(),
            1,
        )

    def test_reject_idempotent_200(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        url = reverse("handoff-reject", kwargs={"handoff_id": handoff_id})
        body = {"manifest_hash": manifest_hash, "reason": "once"}
        self.assertEqual(self.client.post(url, body, format="json").status_code, 200)
        second = self.client.post(url, body, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["status"], HANDOFF_STATUS_REJECTED)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_REJECTED,
            ).count(),
            1,
        )

    def test_unauthenticated_returns_401(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=None)
        for name in ("handoff-approve", "handoff-reject", "handoff-confirm-activated"):
            response = self.client.post(
                reverse(name, kwargs={"handoff_id": handoff_id}),
                {"manifest_hash": manifest_hash},
                format="json",
            )
            self.assertEqual(response.status_code, 401, msg=name)

    def test_uc02_journey_stage_approve_confirm(self):
        """PRD §10 manual path — BE: STAGED → APPROVED → ACTIVATED via APIs."""
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        record = HandoffPackage.objects.get(pk=handoff_id)
        self.assertEqual(record.status, HANDOFF_STATUS_STAGED)

        self.client.force_authenticate(user=self.admin)
        approved = self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        self.assertEqual(approved.status_code, 200)
        self.assertIn("activation_guide", approved.data)

        confirmed = self.client.post(
            reverse(
                "handoff-confirm-activated",
                kwargs={"handoff_id": handoff_id},
            ),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.data["status"], HANDOFF_STATUS_ACTIVATED)

        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_REJECTED,
            ).count(),
            0,
        )

    def test_confirm_qa_not_pass_409(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        record = HandoffPackage.objects.select_related("qa_result").get(pk=handoff_id)
        record.qa_result.status = QA_STATUS_FAIL
        record.qa_result.save(update_fields=["status"])

        response = self.client.post(
            reverse(
                "handoff-confirm-activated",
                kwargs={"handoff_id": handoff_id},
            ),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "qa_not_pass")

    def test_approve_with_approval_id_body(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        approval_id = str(uuid4())
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash, "approval_id": approval_id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["activation_meta"]["approval_token_id"],
            approval_id,
        )

    def test_rejected_get_excludes_activation_guide(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            reverse("handoff-reject", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash, "reason": "hold"},
            format="json",
        )
        self.client.force_authenticate(user=self.viewer)
        detail = self.client.get(
            reverse("handoff-detail", kwargs={"handoff_id": handoff_id})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["status"], HANDOFF_STATUS_REJECTED)
        self.assertNotIn("activation_guide", detail.data)
        self.assertNotIn("capability", detail.data)

    def test_list_includes_activation_guide_after_approve(self):
        handoff_id, manifest_hash = self._stage_handoff_via_api()
        package_id = HandoffPackage.objects.get(pk=handoff_id).package_id
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            reverse("handoff-approve", kwargs={"handoff_id": handoff_id}),
            {"manifest_hash": manifest_hash},
            format="json",
        )
        self.client.force_authenticate(user=self.viewer)
        listed = self.client.get(
            reverse("handoff-list"),
            {"package_id": str(package_id)},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 1)
        row = listed.data["results"][0]
        self.assertEqual(row["handoff_id"], handoff_id)
        self.assertIn("activation_guide", row)
        self.assertIn("capability", row)
