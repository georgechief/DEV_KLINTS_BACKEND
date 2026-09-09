"""CAP-01 Step 6 — GET /api/v1/capabilities/ (+ by id)."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from dataruns.capabilities.contract import (
    CAP_ID_HUMAN_WORKFLOW_BUILD,
    CAP_ID_MCP_WORKFLOW_UPSERT,
    CAP_STATUS_DISCOVERY_REQUIRED,
    MATRIX_PACK_SOURCE,
)
from tenants.models import Company, Tenant, User


class Cap01CapabilitiesApiStep6Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name="CAP-01 API", slug="cap01-api")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="CAP-01 API Co",
            domain="cap01-api.example.com",
        )
        cls.admin = User.objects.create_user(
            email="cap01-admin@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ADMIN,
        )
        cls.analyst = User.objects.create_user(
            email="cap01-analyst@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ANALYST,
        )
        cls.viewer = User.objects.create_user(
            email="cap01-viewer@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.VIEWER,
        )

    def setUp(self):
        self.client = APIClient()

    def test_list_requires_auth(self):
        response = self.client.get("/api/v1/capabilities/")
        self.assertEqual(response.status_code, 401)

    def test_list_viewer_ok_includes_mcp_and_human(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get("/api/v1/capabilities/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["schema_version"], "1.0.0")
        self.assertEqual(body["source"], MATRIX_PACK_SOURCE)
        self.assertEqual(body["count"], 40)
        self.assertEqual(len(body["results"]), 40)
        ids = {row["capability_id"] for row in body["results"]}
        self.assertIn(CAP_ID_MCP_WORKFLOW_UPSERT, ids)
        self.assertIn(CAP_ID_HUMAN_WORKFLOW_BUILD, ids)

    def test_list_analyst_and_admin_ok(self):
        for user in (self.analyst, self.admin):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user=user)
                response = self.client.get("/api/v1/capabilities/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["count"], 40)

    def test_list_filter_channel_status_q(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(
            "/api/v1/capabilities/",
            {
                "channel": "MANAGO_MCP",
                "status": "DISCOVERY_REQUIRED",
                "q": "WORKFLOW.UPSERT",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        row = body["results"][0]
        self.assertEqual(row["capability_id"], CAP_ID_MCP_WORKFLOW_UPSERT)
        self.assertEqual(row["status"], CAP_STATUS_DISCOVERY_REQUIRED)
        self.assertEqual(row["channel"], "MANAGO_MCP")

    def test_detail_known_capability(self):
        self.client.force_authenticate(user=self.viewer)
        url = reverse(
            "capability-detail",
            kwargs={"capability_id": CAP_ID_HUMAN_WORKFLOW_BUILD},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["capability_id"], CAP_ID_HUMAN_WORKFLOW_BUILD)
        self.assertEqual(body["status"], "CONFIRMED_LIVE")
        self.assertEqual(body["channel"], "HUMAN_OPERATOR")

    def test_detail_dotted_mcp_id(self):
        self.client.force_authenticate(user=self.analyst)
        response = self.client.get(
            f"/api/v1/capabilities/{CAP_ID_MCP_WORKFLOW_UPSERT}/"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["capability_id"], CAP_ID_MCP_WORKFLOW_UPSERT)
        self.assertEqual(body["status"], CAP_STATUS_DISCOVERY_REQUIRED)
        self.assertEqual(body["evidence"], [])

    def test_detail_case_insensitive(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(
            f"/api/v1/capabilities/{CAP_ID_MCP_WORKFLOW_UPSERT.lower()}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["capability_id"],
            CAP_ID_MCP_WORKFLOW_UPSERT,
        )

    def test_detail_unknown_404(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get("/api/v1/capabilities/MCP.DOES.NOT.EXIST/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())

    def test_put_and_delete_not_allowed(self):
        self.client.force_authenticate(user=self.admin)
        for method in ("put", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    f"/api/v1/capabilities/{CAP_ID_HUMAN_WORKFLOW_BUILD}/",
                    {"status": "CONFIRMED_LIVE"},
                    format="json",
                )
                self.assertEqual(response.status_code, 405)

    def test_post_not_allowed(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/v1/capabilities/",
            {"capability_id": "X", "status": "CONFIRMED_LIVE"},
            format="json",
        )
        self.assertEqual(response.status_code, 405)

    def test_patch_detail_not_allowed(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            f"/api/v1/capabilities/{CAP_ID_MCP_WORKFLOW_UPSERT}/",
            {"status": "CONFIRMED_LIVE"},
            format="json",
        )
        self.assertEqual(response.status_code, 405)

    def test_non_reader_role_gets_403(self):
        """PRD §6: _forbid_if_not_reader guard fires for any role not in (Admin/Analyst/Viewer).
        All current User.Role values ARE reader-eligible, making this guard future-proofing.
        Tested by forcing a non-existent role string via DB-level update.
        """
        from tenants.models import User as _User

        # Create a viewer then demote to a hypothetical future "operator" role (DB bypass).
        operator = _User.objects.create_user(
            email="cap01-s6-operator@example.com",
            password="pass",
            tenant=self.tenant,
            role=_User.Role.VIEWER,
        )
        _User.objects.filter(pk=operator.pk).update(role="operator")
        operator.refresh_from_db()
        self.client.force_authenticate(user=operator)
        response = self.client.get("/api/v1/capabilities/")
        self.assertEqual(response.status_code, 403)
        response_detail = self.client.get(
            f"/api/v1/capabilities/{CAP_ID_HUMAN_WORKFLOW_BUILD}/"
        )
        self.assertEqual(response_detail.status_code, 403)
