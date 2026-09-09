"""Tests for GET /api/v1/connectors/ latest_bootstrap (PRD-CONN-04)."""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.connectors.base import CONNECTOR_BOOTSTRAP_KIND, CONNECTOR_FETCH_KIND
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

    def test_last_data_refresh_null_when_missing(self):
        request = self.factory.get("/api/v1/connectors/")
        force_authenticate(request, user=self.admin)
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["results"][0]["last_data_refresh"])

    def test_last_data_refresh_matches_bootstrap_when_only_bootstrap(self):
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
                "run_id": "bootstrap-run",
                "counts": {"contacts": 10, "orders": 20},
                "health_report": {
                    "summary_status": "ok",
                    "preflight": {"issues": []},
                    "fetch": {"contacts_upserted": 10, "orders_upserted": 20},
                    "postflight": {"issues": []},
                },
            },
        )

        request = self.factory.get("/api/v1/connectors/")
        force_authenticate(request, user=self.admin)
        response = self.view(request)

        refresh = response.data["results"][0]["last_data_refresh"]
        self.assertIsNotNone(refresh)
        self.assertEqual(refresh["source"], "bootstrap")
        self.assertEqual(refresh["contacts"], 10)
        self.assertEqual(refresh["orders"], 20)

    def test_last_data_refresh_prefers_newer_dcs_fresh_import(self):
        older = timezone.now() - timezone.timedelta(hours=2)
        newer = timezone.now() - timezone.timedelta(minutes=5)
        DataRun.objects.create(
            tenant=self.tenant,
            name="connector-bootstrap:shopify",
            status=DataRun.Status.SUCCEEDED,
            finished_at=older,
            metadata={
                "kind": CONNECTOR_BOOTSTRAP_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "run_id": "bootstrap-run",
                "counts": {"contacts": 49, "orders": 80},
                "health_report": {
                    "summary_status": "ok",
                    "preflight": {"issues": []},
                    "fetch": {"contacts_upserted": 49, "orders_upserted": 80},
                    "postflight": {"issues": []},
                },
            },
        )
        fresh_run_id = "fresh-run"
        DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-fresh-import:shopify",
            status=DataRun.Status.SUCCEEDED,
            finished_at=newer,
            metadata={
                "kind": CONNECTOR_FETCH_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "triggered_by": "dcs_score",
                "run_id": fresh_run_id,
                "counts": {"contacts": 59, "orders": 100},
                "health_report": {
                    "summary_status": "ok",
                    "preflight": {"issues": []},
                    "fetch": {"contacts_upserted": 59, "orders_upserted": 100},
                    "postflight": {"issues": []},
                },
            },
        )

        request = self.factory.get("/api/v1/connectors/")
        force_authenticate(request, user=self.admin)
        response = self.view(request)

        connector = response.data["results"][0]
        self.assertEqual(connector["latest_bootstrap"]["orders"], 80)
        refresh = connector["last_data_refresh"]
        self.assertIsNotNone(refresh)
        self.assertEqual(refresh["source"], "dcs_fresh_import")
        self.assertEqual(refresh["run_id"], fresh_run_id)
        self.assertEqual(refresh["contacts"], 59)
        self.assertEqual(refresh["orders"], 100)

    def test_last_data_refresh_falls_back_to_bootstrap_when_fresh_import_failed(self):
        bootstrap_finished = timezone.now() - timezone.timedelta(hours=1)
        failed_finished = timezone.now() - timezone.timedelta(minutes=5)
        DataRun.objects.create(
            tenant=self.tenant,
            name="connector-bootstrap:shopify",
            status=DataRun.Status.SUCCEEDED,
            finished_at=bootstrap_finished,
            metadata={
                "kind": CONNECTOR_BOOTSTRAP_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "run_id": "bootstrap-run",
                "counts": {"contacts": 49, "orders": 80},
                "health_report": {
                    "summary_status": "ok",
                    "preflight": {"issues": []},
                    "fetch": {"contacts_upserted": 49, "orders_upserted": 80},
                    "postflight": {"issues": []},
                },
            },
        )
        DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-fresh-import:shopify",
            status=DataRun.Status.FAILED,
            finished_at=failed_finished,
            metadata={
                "kind": CONNECTOR_FETCH_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "triggered_by": "dcs_score",
                "error": "Shopify token refresh failed",
            },
        )

        request = self.factory.get("/api/v1/connectors/")
        force_authenticate(request, user=self.admin)
        response = self.view(request)

        refresh = response.data["results"][0]["last_data_refresh"]
        self.assertIsNotNone(refresh)
        self.assertEqual(refresh["source"], "bootstrap")
        self.assertEqual(refresh["orders"], 80)
        self.assertEqual(refresh["data_run_status"], "succeeded")
