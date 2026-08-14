"""Tests for GET /api/v1/connectors/ latest_bootstrap (PRD-CONN-04)."""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.connectors.base import CONNECTOR_BOOTSTRAP_KIND
from dataruns.models import DataRun
from tenants.connector_views import ConnectorListCreateView
from tenants.models import Company, Connector, Tenant, User


class ConnectorListLatestBootstrapTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ConnectorListCreateView.as_view()
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme.com",
        )
        self.admin = User.objects.create_user(
            email="admin@acme.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config={"shop_domain": "acme.myshopify.com"},
            status="connected",
        )

    def test_list_includes_latest_bootstrap_payload(self):
        run_id = "a680e914-1111-2222-3333-444455556666"
        finished_at = timezone.now()
        DataRun.objects.create(
            tenant=self.tenant,
            name="connector-bootstrap:shopify",
            status=DataRun.Status.SUCCEEDED,
            finished_at=finished_at,
            metadata={
                "kind": CONNECTOR_BOOTSTRAP_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "run_id": run_id,
                "counts": {"contacts": 13, "orders": 20},
                "health_report": {
                    "summary_status": "ok",
                    "preflight": {"issues": []},
                    "fetch": {
                        "contacts_upserted": 13,
                        "orders_upserted": 20,
                    },
                    "postflight": {"issues": []},
                },
            },
        )

        request = self.factory.get("/api/v1/connectors/")
        force_authenticate(request, user=self.admin)
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        connector = response.data["results"][0]
        latest = connector["latest_bootstrap"]
        self.assertIsNotNone(latest)
        self.assertEqual(latest["run_id"], run_id)
        self.assertEqual(latest["contacts"], 13)
        self.assertEqual(latest["orders"], 20)
        self.assertEqual(latest["issue_count"], 0)
        self.assertEqual(latest["summary_status"], "ok")
        self.assertEqual(latest["data_run_status"], "succeeded")

    def test_list_latest_bootstrap_null_when_missing(self):
        request = self.factory.get("/api/v1/connectors/")
        force_authenticate(request, user=self.admin)
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["results"][0]["latest_bootstrap"])

    def test_issue_count_counts_all_health_issues(self):
        DataRun.objects.create(
            tenant=self.tenant,
            name="connector-bootstrap:shopify",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": CONNECTOR_BOOTSTRAP_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "run_id": "run-1",
                "health_report": {
                    "summary_status": "degraded",
                    "preflight": {
                        "issues": [
                            {"code": "SCOPES_MISSING", "severity": "warn"},
                        ]
                    },
                    "fetch": {"contacts_upserted": 1, "orders_upserted": 2},
                    "postflight": {
                        "issues": [
                            {"code": "EMPTY_CONTACTS_WINDOW", "severity": "warn"},
                        ]
                    },
                },
            },
        )

        request = self.factory.get("/api/v1/connectors/")
        force_authenticate(request, user=self.admin)
        response = self.view(request)

        self.assertEqual(response.data["results"][0]["latest_bootstrap"]["issue_count"], 2)
