"""Tests for Spotlight global search API (PRD-FE-05)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import AuditLog, CheckMaster, DataRun, DimensionMaster, Run, RunIssue
from dataruns.search import search_company
from dataruns.search_views import GlobalSearchView
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant, User


class GlobalSearchServiceTests(TestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(name="Acme", slug="acme")
        self.tenant_b = Tenant.objects.create(name="Beta", slug="beta")
        self.company_a = Company.objects.create(
            tenant=self.tenant_a,
            name="Acme",
            domain="acme.com",
        )
        self.company_b = Company.objects.create(
            tenant=self.tenant_b,
            name="Beta",
            domain="beta.com",
        )
        self.user_a = User.objects.create_user(
            email="admin@acme.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant_a,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.user_b = User.objects.create_user(
            email="admin@beta.com",
            password="TestPass123!",
            name="Beta Admin",
            tenant=self.tenant_b,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.dimension = DimensionMaster.objects.create(
            dimension_id="01",
            name="Customer Identity",
            weight_percent=10,
        )
        CheckMaster.objects.create(
            sequence=1,
            check_id="CI-02",
            check_name="Guest checkout identity share",
            dimension=self.dimension,
            check_class="RULE_BASED",
            check_type="identity",
            role="GATE",
            cadence="daily",
            phase="1",
            systems_compared="shopify,manago",
            severity="High",
        )
        self.domain_run = Run.objects.create(
            company=self.company_a,
            run_type="full",
            status="completed",
        )
        self.latest_dcs_run = DataRun.objects.create(
            tenant=self.tenant_a,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company_a.id),
                "run_id": str(self.domain_run.id),
                "dcs_run": {"run_id": str(self.domain_run.id)},
                "check_results": [
                    {
                        "check_id": "CI-02",
                        "status": "FAIL",
                        "message": "Guest checkout identity share",
                    }
                ],
            },
        )
        RunIssue.objects.create(
            run=self.domain_run,
            entity_type="dcs_check",
            entity_id=self.company_a.id,
            issue_type="CI-02",
            severity="High",
            detected_at=timezone.now(),
            details={
                "check_id": "CI-02",
                "status": "FAIL",
                "message": "Guest checkout identity share",
            },
        )
        self.shopify_connector = Connector.objects.create(
            company=self.company_a,
            name="shopify",
            type="ecommerce",
            status="connected",
            external_account_key="klints-dev.myshopify.com",
            config=encrypt_config({"shop_domain": "klints-dev.myshopify.com"}),
        )
        ConnectorSnapshot.objects.create(
            connector=self.shopify_connector,
            version=1,
            snapshot_data={"shop_domain": "klints-dev.myshopify.com"},
        )
        AuditLog.objects.create(
            company=self.company_a,
            action="connector.connected",
            tone=AuditLog.Tone.INFO,
            summary="Shopify connector connected",
            performed_by="admin@acme.com",
            prev_hash="0" * 64,
            entry_hash="a" * 64,
            created_at=timezone.now() - timedelta(hours=2),
        )

    def test_short_query_returns_empty_results(self):
        self.assertEqual(search_company(company=self.company_a, q="a"), [])
        self.assertEqual(search_company(company=self.company_a, q=""), [])

    def test_issue_search_matches_check_id(self):
        hits = search_company(company=self.company_a, q="CI-02", types={"issue"})
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].type, "issue")
        self.assertEqual(hits[0].href, "/data-consistency?check=CI-02")
        self.assertEqual(hits[0].meta["check_id"], "CI-02")
        self.assertEqual(hits[0].meta["status"], "FAIL")

    def test_connector_search_matches_name_and_domain(self):
        by_name = search_company(company=self.company_a, q="shopify", types={"connector"})
        self.assertEqual(len(by_name), 1)
        self.assertEqual(by_name[0].type, "connector")
        self.assertEqual(by_name[0].href, "/integrations")

        by_domain = search_company(
            company=self.company_a,
            q="klints-dev",
            types={"connector"},
        )
        self.assertEqual(len(by_domain), 1)

    def test_audit_search_matches_summary(self):
        hits = search_company(company=self.company_a, q="connected", types={"audit"})
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].type, "audit")
        self.assertEqual(hits[0].href, "/activity")

    def test_run_search_matches_status_and_id(self):
        hits = search_company(
            company=self.company_a,
            q=str(self.latest_dcs_run.id),
            types={"run"},
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].type, "run")
        self.assertEqual(hits[0].meta["data_run_id"], self.latest_dcs_run.id)

    def test_limit_applies_per_type(self):
        for index in range(3):
            AuditLog.objects.create(
                company=self.company_a,
                action=f"test.action.{index}",
                tone=AuditLog.Tone.INFO,
                summary=f"Audit match {index}",
                performed_by="system",
                prev_hash="0" * 64,
                entry_hash=f"{index:064d}",
                created_at=timezone.now() - timedelta(minutes=index),
            )
        hits = search_company(
            company=self.company_a,
            q="Audit match",
            types={"audit"},
            limit=2,
        )
        self.assertEqual(len(hits), 2)

    def test_unknown_types_are_ignored(self):
        hits = search_company(
            company=self.company_a,
            q="CI-02",
            types={"issue", "workflow", "unknown"},
        )
        self.assertTrue(all(hit.type != "workflow" for hit in hits))
        self.assertTrue(any(hit.type == "issue" for hit in hits))

    def test_issue_search_falls_back_to_check_results_metadata(self):
        RunIssue.objects.filter(run=self.domain_run).delete()
        hits = search_company(company=self.company_a, q="CI-02", types={"issue"})
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].id, "CI-02")
        self.assertEqual(hits[0].href, "/data-consistency?check=CI-02")

    def test_company_isolation(self):
        other_run = Run.objects.create(
            company=self.company_b,
            run_type="full",
            status="completed",
        )
        RunIssue.objects.create(
            run=other_run,
            entity_type="dcs_check",
            entity_id=self.company_b.id,
            issue_type="CI-99",
            severity="High",
            detected_at=timezone.now(),
            details={"check_id": "CI-99", "status": "FAIL"},
        )
        hits = search_company(company=self.company_a, q="CI-99", types={"issue"})
        self.assertEqual(hits, [])

    def test_result_order_is_issue_run_connector_audit(self):
        hits = search_company(company=self.company_a, q="shop")
        types = [hit.type for hit in hits]
        issue_index = types.index("issue") if "issue" in types else -1
        run_index = types.index("run") if "run" in types else -1
        connector_index = types.index("connector") if "connector" in types else -1
        audit_index = types.index("audit") if "audit" in types else -1
        if issue_index >= 0 and run_index >= 0:
            self.assertLess(issue_index, run_index)
        if run_index >= 0 and connector_index >= 0:
            self.assertLess(run_index, connector_index)
        if connector_index >= 0 and audit_index >= 0:
            self.assertLess(connector_index, audit_index)


class GlobalSearchApiTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme.com",
        )
        self.user = User.objects.create_user(
            email="admin@acme.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.dimension = DimensionMaster.objects.create(
            dimension_id="01",
            name="Customer Identity",
            weight_percent=10,
        )
        CheckMaster.objects.create(
            sequence=1,
            check_id="CI-02",
            check_name="Guest checkout identity share",
            dimension=self.dimension,
            check_class="RULE_BASED",
            check_type="identity",
            role="GATE",
            cadence="daily",
            phase="1",
            systems_compared="shopify,manago",
            severity="High",
        )
        domain_run = Run.objects.create(
            company=self.company,
            run_type="full",
            status="completed",
        )
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "run_id": str(domain_run.id),
                "dcs_run": {"run_id": str(domain_run.id)},
                "check_results": [{"check_id": "CI-02", "status": "FAIL"}],
            },
        )
        RunIssue.objects.create(
            run=domain_run,
            entity_type="dcs_check",
            entity_id=self.company.id,
            issue_type="CI-02",
            severity="High",
            detected_at=timezone.now(),
            details={"check_id": "CI-02", "status": "FAIL"},
        )

    def _get(self, path: str, user=None):
        request = self.factory.get(path)
        if user is not None:
            force_authenticate(request, user=user)
        return GlobalSearchView.as_view()(request)

    def test_unauthenticated_returns_401(self):
        response = self._get("/api/v1/search/?q=CI-02")
        self.assertEqual(response.status_code, 401)

    def test_short_query_returns_empty_results(self):
        response = self._get("/api/v1/search/?q=a", user=self.user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["q"], "a")
        self.assertEqual(response.data["results"], [])

    def test_issue_search_via_api(self):
        response = self._get("/api/v1/search/?q=CI-02&types=issue", user=self.user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["q"], "CI-02")
        self.assertEqual(len(response.data["results"]), 1)
        result = response.data["results"][0]
        self.assertEqual(result["type"], "issue")
        self.assertEqual(result["href"], "/data-consistency?check=CI-02")
        self.assertEqual(result["meta"]["check_id"], "CI-02")

    def test_no_company_returns_empty_results(self):
        orphan_tenant = Tenant.objects.create(name="Orphan", slug="orphan")
        orphan_user = User.objects.create_user(
            email="orphan@example.com",
            password="TestPass123!",
            name="Orphan",
            tenant=orphan_tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        response = self._get("/api/v1/search/?q=CI-02", user=orphan_user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_limit_clamped_to_ten(self):
        from dataruns.search import parse_search_limit

        self.assertEqual(parse_search_limit("0"), 1)
        self.assertEqual(parse_search_limit("99"), 10)
        self.assertEqual(parse_search_limit(None), 6)

    def test_workflow_type_returns_empty(self):
        response = self._get(
            "/api/v1/search/?q=CI-02&types=workflow",
            user=self.user,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])
