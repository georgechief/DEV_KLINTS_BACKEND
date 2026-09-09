"""PRD-GAP-01 Slice A1 Phase 3 — orchestration task HTTP APIs."""

from __future__ import annotations

from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from dataruns.orchestration.models import OrchestrationTask
from dataruns.orchestration.task_constants import (
    ORCH_ERROR_FORBIDDEN,
    ORCH_ERROR_INVALID_TRANSITION,
    ORCH_ERROR_VALIDATION,
    ORCH_STATUS_AWAITING_APPROVAL,
    ORCH_STATUS_DONE,
    ORCH_STATUS_IN_PROGRESS,
    ORCH_STATUS_READY,
    ORCH_TASK_SCHEMA_VERSION,
    ORCH_TASK_TYPE_FIX,
)
from tenants.models import Company, Tenant, User


class OrchSmPhase3ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name="Orch SM P3", slug="orch-sm-p3")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="Orch SM P3 Co",
            domain="orch-sm-p3.example.com",
        )
        cls.other_tenant = Tenant.objects.create(name="Orch SM P3 Other", slug="orch-sm-p3-other")
        cls.other_company = Company.objects.create(
            tenant=cls.other_tenant,
            name="Orch SM P3 Other Co",
            domain="orch-sm-p3-other.example.com",
        )
        cls.admin = User.objects.create_user(
            email="orch-p3-admin@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ADMIN,
        )
        cls.analyst = User.objects.create_user(
            email="orch-p3-analyst@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ANALYST,
        )
        cls.viewer = User.objects.create_user(
            email="orch-p3-viewer@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.VIEWER,
        )
        cls.outsider = User.objects.create_user(
            email="orch-p3-outsider@example.com",
            password="pass",
            tenant=cls.other_tenant,
            role=User.Role.ADMIN,
        )

    def setUp(self):
        self.client = APIClient()

    def _priority_inputs(self) -> dict[str, int]:
        return {
            "blocker_status": 2,
            "severity_risk": 1,
            "dependency_readiness": 3,
            "effort_impact": 2,
        }

    def _create_body(self, *, suffix: str = "1") -> dict:
        return {
            "task_type": ORCH_TASK_TYPE_FIX,
            "task_id": "FIX-CC-03",
            "title": "Fix CC-03",
            "check_id": "CC-03",
            "status": ORCH_STATUS_READY,
            "priority_inputs": self._priority_inputs(),
            "priority_score": 2.1,
            "idempotency_key": f"{self.company.id}:FIX-CC-03:dcs:{suffix}",
        }

    def _create_via_api(self, *, user=None, suffix: str = "1") -> dict:
        self.client.force_authenticate(user=user or self.analyst)
        response = self.client.post(
            reverse("orchestration-task-list-create"),
            self._create_body(suffix=suffix),
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        return response.data

    def test_post_create_returns_201_and_pack_shape(self):
        self.client.force_authenticate(user=self.analyst)
        response = self.client.post(
            reverse("orchestration-task-list-create"),
            self._create_body(),
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        for key in (
            "schema_version",
            "id",
            "task_id",
            "tenant_id",
            "task_type",
            "status",
            "priority_inputs",
            "priority_score",
            "idempotency_key",
            "provenance",
        ):
            self.assertIn(key, response.data)
        self.assertEqual(response.data["schema_version"], ORCH_TASK_SCHEMA_VERSION)
        self.assertEqual(response.data["task_id"], "FIX-CC-03")
        self.assertEqual(response.data["tenant_id"], str(self.company.id))

    def test_get_list_and_filters(self):
        created = self._create_via_api(suffix="list-a")
        self._create_via_api(suffix="list-b")
        OrchestrationTask.objects.filter(id=created["id"]).update(
            status=ORCH_STATUS_IN_PROGRESS
        )

        self.client.force_authenticate(user=self.viewer)
        list_url = reverse("orchestration-task-list-create")

        all_response = self.client.get(list_url)
        self.assertEqual(all_response.status_code, 200)
        self.assertEqual(all_response.data["count"], 2)

        ready_response = self.client.get(list_url, {"status": ORCH_STATUS_READY})
        self.assertEqual(ready_response.status_code, 200)
        self.assertEqual(ready_response.data["count"], 1)
        self.assertEqual(ready_response.data["results"][0]["status"], ORCH_STATUS_READY)

        type_response = self.client.get(list_url, {"task_type": ORCH_TASK_TYPE_FIX})
        self.assertEqual(type_response.status_code, 200)
        self.assertEqual(type_response.data["count"], 2)

        check_response = self.client.get(list_url, {"check_id": "CC-03"})
        self.assertEqual(check_response.status_code, 200)
        self.assertEqual(check_response.data["count"], 2)

    def test_get_detail(self):
        created = self._create_via_api()
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(
            reverse(
                "orchestration-task-detail",
                kwargs={"task_id": created["id"]},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], created["id"])
        self.assertEqual(response.data["task_id"], "FIX-CC-03")

    def test_post_transition_success(self):
        created = self._create_via_api()
        self.client.force_authenticate(user=self.analyst)
        response = self.client.post(
            reverse(
                "orchestration-task-transition",
                kwargs={"task_id": created["id"]},
            ),
            {"to_status": ORCH_STATUS_IN_PROGRESS, "reason": "Started"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], ORCH_STATUS_IN_PROGRESS)
        self.assertFalse(response.data["idempotent"])

    def test_invalid_transition_returns_409(self):
        created = self._create_via_api()
        self.client.force_authenticate(user=self.analyst)
        response = self.client.post(
            reverse(
                "orchestration-task-transition",
                kwargs={"task_id": created["id"]},
            ),
            {"to_status": ORCH_STATUS_DONE},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], ORCH_ERROR_INVALID_TRANSITION)

    def test_viewer_post_create_and_transition_forbidden(self):
        self.client.force_authenticate(user=self.viewer)
        create_response = self.client.post(
            reverse("orchestration-task-list-create"),
            self._create_body(suffix="viewer-block"),
            format="json",
        )
        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(create_response.data["code"], ORCH_ERROR_FORBIDDEN)

        created = self._create_via_api(suffix="viewer-transition")
        self.client.force_authenticate(user=self.viewer)
        transition_response = self.client.post(
            reverse(
                "orchestration-task-transition",
                kwargs={"task_id": created["id"]},
            ),
            {"to_status": ORCH_STATUS_IN_PROGRESS},
            format="json",
        )
        self.assertEqual(transition_response.status_code, 403)
        self.assertEqual(transition_response.data["code"], ORCH_ERROR_FORBIDDEN)

    def test_cross_company_detail_returns_404(self):
        created = self._create_via_api()
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(
            reverse(
                "orchestration-task-detail",
                kwargs={"task_id": created["id"]},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_cross_company_transition_returns_404(self):
        created = self._create_via_api()
        self.client.force_authenticate(user=self.outsider)
        response = self.client.post(
            reverse(
                "orchestration-task-transition",
                kwargs={"task_id": created["id"]},
            ),
            {"to_status": ORCH_STATUS_IN_PROGRESS},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_orchestration_plan_regression_still_200(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(reverse("orchestration-plan"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("tasks", response.data)
        self.assertIn("summary", response.data)

    def test_analyst_cannot_approve_to_done_via_api(self):
        created = self._create_via_api(suffix="analyst-approve-block")
        task_id = created["id"]
        self.client.force_authenticate(user=self.analyst)

        self.client.post(
            reverse("orchestration-task-transition", kwargs={"task_id": task_id}),
            {"to_status": ORCH_STATUS_IN_PROGRESS},
            format="json",
        )
        self.client.post(
            reverse("orchestration-task-transition", kwargs={"task_id": task_id}),
            {"to_status": ORCH_STATUS_AWAITING_APPROVAL},
            format="json",
        )

        response = self.client.post(
            reverse("orchestration-task-transition", kwargs={"task_id": task_id}),
            {"to_status": ORCH_STATUS_DONE},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], ORCH_ERROR_FORBIDDEN)

    def test_invalid_status_filter_returns_400(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(
            reverse("orchestration-task-list-create"),
            {"status": "NOT_A_STATUS"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], ORCH_ERROR_VALIDATION)

    def test_transition_missing_to_status_returns_400(self):
        created = self._create_via_api(suffix="missing-to-status")
        self.client.force_authenticate(user=self.analyst)
        response = self.client.post(
            reverse(
                "orchestration-task-transition",
                kwargs={"task_id": created["id"]},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], ORCH_ERROR_VALIDATION)

    def test_transition_idempotent_flag(self):
        created = self._create_via_api(suffix="transition-idem")
        task_id = created["id"]
        self.client.force_authenticate(user=self.analyst)

        self.client.post(
            reverse("orchestration-task-transition", kwargs={"task_id": task_id}),
            {"to_status": ORCH_STATUS_IN_PROGRESS},
            format="json",
        )
        self.client.post(
            reverse("orchestration-task-transition", kwargs={"task_id": task_id}),
            {"to_status": ORCH_STATUS_AWAITING_APPROVAL},
            format="json",
        )

        repeat = self.client.post(
            reverse("orchestration-task-transition", kwargs={"task_id": task_id}),
            {"to_status": ORCH_STATUS_AWAITING_APPROVAL},
            format="json",
        )
        self.assertEqual(repeat.status_code, 200)
        self.assertTrue(repeat.data["idempotent"])

    def test_admin_approval_transition_via_api(self):
        created = self._create_via_api(suffix="approve")
        task_id = created["id"]
        self.client.force_authenticate(user=self.analyst)

        self.client.post(
            reverse("orchestration-task-transition", kwargs={"task_id": task_id}),
            {"to_status": ORCH_STATUS_IN_PROGRESS},
            format="json",
        )
        self.client.post(
            reverse("orchestration-task-transition", kwargs={"task_id": task_id}),
            {"to_status": ORCH_STATUS_AWAITING_APPROVAL},
            format="json",
        )

        self.client.force_authenticate(user=self.admin)
        done = self.client.post(
            reverse("orchestration-task-transition", kwargs={"task_id": task_id}),
            {"to_status": ORCH_STATUS_DONE, "reason": "Approved"},
            format="json",
        )
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.data["status"], ORCH_STATUS_DONE)

    def test_idempotent_create_returns_200(self):
        self.client.force_authenticate(user=self.analyst)
        url = reverse("orchestration-task-list-create")
        body = self._create_body(suffix="idem")
        first = self.client.post(url, body, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertFalse(first.data["idempotent"])
        second = self.client.post(url, body, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["idempotent"])
        self.assertEqual(
            OrchestrationTask.objects.filter(company=self.company).count(),
            1,
        )

    def test_urls_resolve(self):
        task_id = uuid4()
        self.assertEqual(
            reverse("orchestration-task-list-create"),
            "/api/v1/orchestration/tasks/",
        )
        self.assertEqual(
            reverse("orchestration-task-detail", kwargs={"task_id": task_id}),
            f"/api/v1/orchestration/tasks/{task_id}/",
        )
        self.assertEqual(
            reverse("orchestration-task-transition", kwargs={"task_id": task_id}),
            f"/api/v1/orchestration/tasks/{task_id}/transition/",
        )
