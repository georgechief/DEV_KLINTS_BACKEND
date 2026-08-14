"""Tests for POST /api/v1/dcs/runs/ (manual re-run / start score)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.enqueue import DcsAlreadyRunningError, DcsEnqueueResult
from dataruns.dcs.views import DcsRunsView
from tenants.models import Company, Connector, Tenant, User


class DcsRunsApiTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.tenant = Tenant.objects.create(name="Acme", slug="acme-runs")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme-runs.com",
        )
        self.admin = User.objects.create_user(
            email="admin-runs@acme.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.viewer = User.objects.create_user(
            email="viewer-runs@acme.com",
            password="TestPass123!",
            name="Viewer",
            tenant=self.tenant,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )

    def _connect(self, name: str) -> Connector:
        return Connector.objects.create(
            company=self.company,
            name=name,
            type="ecommerce" if name == "shopify" else "cdp",
            status="connected",
            config={},
        )

    def _post(self, user: User, body: dict | None = None):
        request = self.factory.post(
            "/api/v1/dcs/runs/",
            data=body or {},
            format="json",
        )
        force_authenticate(request, user=user)
        return DcsRunsView.as_view()(request)

    def test_viewer_cannot_start_run(self):
        response = self._post(self.viewer)
        self.assertEqual(response.status_code, 403)

    def test_422_without_eligible_connector(self):
        response = self._post(self.admin)
        self.assertEqual(response.status_code, 422)
        self.assertIn("Connect", response.data["detail"])

    @patch("dataruns.dcs.views.enqueue_dcs_score")
    def test_admin_starts_run_202(self, mock_enqueue):
        self._connect("shopify")

        data_run = SimpleNamespace(id=55, status="pending")
        domain_run = SimpleNamespace(id=uuid4())
        mock_enqueue.return_value = DcsEnqueueResult(
            data_run=data_run,
            domain_run=domain_run,
            task_queued=True,
        )

        response = self._post(self.admin, {"erp_in_scope": False})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["data_run_id"], 55)
        self.assertEqual(response.data["dcs_run_id"], str(domain_run.id))
        self.assertEqual(response.data["status"], "pending")
        self.assertIn("scoring_model_version", response.data)

        kwargs = mock_enqueue.call_args.kwargs
        self.assertEqual(kwargs.get("triggered_by"), "manual")
        self.assertTrue(kwargs.get("queue"))
        self.assertTrue(kwargs.get("live_revalidate"))
        self.assertEqual(kwargs.get("actor_user_id"), str(self.admin.id))

    @patch(
        "dataruns.dcs.views.enqueue_dcs_score",
        side_effect=DcsAlreadyRunningError("already running"),
    )
    def test_409_when_already_running(self, _mock_enqueue):
        self._connect("shopify")
        response = self._post(self.admin)
        self.assertEqual(response.status_code, 409)
