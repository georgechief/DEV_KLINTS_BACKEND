"""Tests for governance audit log (PRD-AUDIT-01)."""

from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.audit import (
    GENESIS_HASH,
    append_audit_event,
    extract_audit_link_fields,
    resolve_audit_href,
    sanitize_audit_metadata,
    verify_audit_chain_for_company,
)
from dataruns.audit_views import AuditEventsListView
from dataruns.models import AuditLog
from tenants.models import Company, Tenant, User


class AuditLogServiceTests(TestCase):
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

    def test_genesis_hash_on_first_entry(self):
        entry = append_audit_event(
            company=self.company_a,
            action="connector.connected",
            summary="Shopify connected",
            performed_by=self.user_a.email,
            actor_user_id=str(self.user_a.id),
            metadata={"platform": "shopify"},
        )
        self.assertEqual(entry.prev_hash, GENESIS_HASH)

    def test_second_entry_links_prev_hash(self):
        first = append_audit_event(
            company=self.company_a,
            action="connector.connected",
            summary="Manago connected",
            performed_by=self.user_a.email,
            metadata={"platform": "manago_ai"},
        )
        second = append_audit_event(
            company=self.company_a,
            action="connector.bootstrap_succeeded",
            summary="Manago bootstrap succeeded · 1 contacts · 2 orders",
            performed_by="system",
            metadata={"platform": "manago_ai"},
        )
        self.assertEqual(second.prev_hash, first.entry_hash)

    def test_sanitize_metadata_strips_secrets(self):
        sanitized = sanitize_audit_metadata(
            {
                "platform": "shopify",
                "api_key": "secret",
                "access_token": "shpat_secret",
            }
        )
        self.assertEqual(sanitized, {"platform": "shopify"})

    def test_verify_audit_chain_passes(self):
        append_audit_event(
            company=self.company_a,
            action="workspace.updated",
            summary="Workspace updated",
            performed_by=self.user_a.email,
            metadata={"fields": ["company_name"]},
        )
        call_command("verify_audit_chain", company_id=str(self.company_a.id))

    def test_verify_audit_chain_survives_entry_hash_tamper_attempt(self):
        entry = append_audit_event(
            company=self.company_a,
            action="connector.connected",
            summary="Shopify connected",
            performed_by=self.user_a.email,
            metadata={"platform": "shopify"},
        )
        before_hash = entry.entry_hash
        AuditLog.objects.filter(pk=entry.id).update(entry_hash="0" * 64)
        entry.refresh_from_db()
        # POLISH-01: Postgres trigger reverts protected-column updates.
        self.assertEqual(entry.entry_hash, before_hash)
        call_command("verify_audit_chain", company_id=str(self.company_a.id))


class AuditEventsApiTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = AuditEventsListView.as_view()
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
            email="viewer@acme.com",
            password="TestPass123!",
            name="Viewer",
            tenant=self.tenant_a,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )
        self.user_b = User.objects.create_user(
            email="viewer@beta.com",
            password="TestPass123!",
            name="Viewer B",
            tenant=self.tenant_b,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )
        append_audit_event(
            company=self.company_a,
            action="connector.connected",
            summary="Shopify connected",
            performed_by=self.user_a.email,
            metadata={"platform": "shopify"},
        )
        append_audit_event(
            company=self.company_b,
            action="connector.connected",
            summary="Manago connected",
            performed_by=self.user_b.email,
            metadata={"platform": "manago_ai"},
        )

    def test_list_events_scoped_to_user_company(self):
        request = self.factory.get("/api/v1/audit/events/")
        force_authenticate(request, user=self.user_a)
        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["action"], "connector.connected")
        self.assertEqual(response.data["results"][0]["meta"], "shopify")
        self.assertEqual(response.data["results"][0]["summary"], "Shopify connected")
        self.assertFalse(response.data["results"][0]["audit_read"])

    def test_company_b_does_not_see_company_a_events(self):
        request = self.factory.get("/api/v1/audit/events/")
        force_authenticate(request, user=self.user_b)
        response = self.view(request)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["meta"], "manago_ai")


class AuditNotificationsApiTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
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
            name="Admin B",
            tenant=self.tenant_b,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.events = []
        for index in range(6):
            self.events.append(
                append_audit_event(
                    company=self.company_a,
                    action="connector.connected",
                    summary=f"Event {index}",
                    performed_by=self.user_a.email,
                    metadata={"platform": "shopify"},
                )
            )

    def test_notifications_returns_unread_count_and_limit_five(self):
        from dataruns.audit_views import AuditNotificationsListView

        request = self.factory.get("/api/v1/audit/notifications/?limit=5")
        force_authenticate(request, user=self.user_a)
        response = AuditNotificationsListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["unread_count"], 6)
        self.assertEqual(len(response.data["results"]), 5)
        self.assertFalse(response.data["results"][0]["audit_read"])

    def test_mark_all_read_clears_unread_count(self):
        from dataruns.audit_views import (
            AuditNotificationsListView,
            AuditNotificationsMarkAllReadView,
        )

        mark_request = self.factory.post(
            "/api/v1/audit/notifications/mark-all-read/",
            {},
            format="json",
        )
        force_authenticate(mark_request, user=self.user_a)
        mark_response = AuditNotificationsMarkAllReadView.as_view()(mark_request)

        self.assertEqual(mark_response.status_code, 200)
        self.assertEqual(mark_response.data["updated"], 6)
        self.assertEqual(mark_response.data["unread_count"], 0)

        list_request = self.factory.get("/api/v1/audit/notifications/")
        force_authenticate(list_request, user=self.user_a)
        list_response = AuditNotificationsListView.as_view()(list_request)
        self.assertEqual(list_response.data["unread_count"], 0)
        self.assertEqual(list_response.data["results"], [])

    def test_mark_one_read_decrements_count(self):
        from dataruns.audit_views import AuditEventMarkReadView

        target = self.events[0]
        request = self.factory.post(
            f"/api/v1/audit/events/{target.id}/mark-read/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.user_a)
        response = AuditEventMarkReadView.as_view()(request, event_id=target.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["audit_read"])
        self.assertEqual(response.data["unread_count"], 5)

    def test_company_b_cannot_mark_company_a_event(self):
        from dataruns.audit_views import AuditEventMarkReadView

        target = self.events[0]
        request = self.factory.post(
            f"/api/v1/audit/events/{target.id}/mark-read/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.user_b)
        response = AuditEventMarkReadView.as_view()(request, event_id=target.id)
        self.assertEqual(response.status_code, 404)

    def test_mark_read_does_not_break_hash_chain(self):
        from dataruns.audit_views import AuditNotificationsMarkAllReadView

        before_hash = self.events[-1].entry_hash
        request = self.factory.post(
            "/api/v1/audit/notifications/mark-all-read/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.user_a)
        AuditNotificationsMarkAllReadView.as_view()(request)
        self.events[-1].refresh_from_db()
        self.assertEqual(self.events[-1].entry_hash, before_hash)
        errors = verify_audit_chain_for_company(company=self.company_a)
        self.assertEqual(errors, [])

    def test_unread_only_filter_on_events_list(self):
        from dataruns.audit_views import (
            AuditEventsListView,
            AuditNotificationsMarkAllReadView,
        )

        mark_request = self.factory.post(
            "/api/v1/audit/notifications/mark-all-read/",
            {},
            format="json",
        )
        force_authenticate(mark_request, user=self.user_a)
        AuditNotificationsMarkAllReadView.as_view()(mark_request)

        append_audit_event(
            company=self.company_a,
            action="connector.disconnected",
            summary="Shopify disconnected",
            performed_by=self.user_a.email,
            metadata={"platform": "shopify"},
        )

        request = self.factory.get("/api/v1/audit/events/?unread_only=true")
        force_authenticate(request, user=self.user_a)
        response = AuditEventsListView.as_view()(request)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["action"], "connector.disconnected")


class AuditDeepLinkTests(TestCase):
    def test_resolve_writeback_check_id_to_fix(self):
        href = resolve_audit_href(
            action="writeback.executed",
            metadata={"check_id": "cc-03", "job_id": "abc"},
        )
        self.assertEqual(href, "/fix?issue=CC-03")

    def test_resolve_handoff_approved_for_activation(self):
        href = resolve_audit_href(
            action="workflow.handoff_approved_for_activation",
            metadata={
                "handoff_id": "ho-1",
                "package_id": "pkg-1",
                "qa_run_id": "qa-1",
                "use_case_id": "UC-02",
            },
        )
        self.assertEqual(
            href,
            "/handoff?uc=UC-02&package_id=pkg-1&handoff_id=ho-1&qa_run_id=qa-1",
        )

    def test_resolve_handoff_activated(self):
        href = resolve_audit_href(
            action="workflow.handoff_activated",
            metadata={
                "handoff_id": "ho-2",
                "package_id": "pkg-2",
                "use_case_id": "UC-02",
            },
        )
        self.assertEqual(
            href,
            "/handoff?uc=UC-02&package_id=pkg-2&handoff_id=ho-2",
        )

    def test_resolve_handoff_staged(self):
        href = resolve_audit_href(
            action="workflow.handoff_staged",
            metadata={
                "handoff_id": "ho-3",
                "package_id": "pkg-3",
                "qa_run_id": "qa-3",
                "use_case_id": "UC-02",
            },
        )
        self.assertEqual(
            href,
            "/handoff?uc=UC-02&package_id=pkg-3&handoff_id=ho-3&qa_run_id=qa-3",
        )

    def test_resolve_handoff_rejected(self):
        href = resolve_audit_href(
            action="workflow.handoff_rejected",
            metadata={
                "handoff_id": "ho-4",
                "package_id": "pkg-4",
                "qa_run_id": "qa-4",
                "use_case_id": "UC-02",
            },
        )
        self.assertEqual(
            href,
            "/handoff?uc=UC-02&package_id=pkg-4&handoff_id=ho-4&qa_run_id=qa-4",
        )

    def test_resolve_workflow_package(self):
        href = resolve_audit_href(
            action="workflow.build_package_generated",
            metadata={
                "package_id": "pkg-1",
                "use_case_id": "UC-01",
            },
        )
        self.assertEqual(href, "/workflow?uc=UC-01&package_id=pkg-1")

    def test_resolve_qa_package(self):
        href = resolve_audit_href(
            action="qa.gate_failed",
            metadata={
                "package_id": "pkg-1",
                "use_case_id": "UC-02",
            },
        )
        self.assertEqual(href, "/qa?uc=UC-02&package_id=pkg-1")

    def test_resolve_report_to_activity(self):
        href = resolve_audit_href(
            action="report.downloaded",
            metadata={"report_id": "rpt-1"},
        )
        self.assertEqual(href, "/activity")

    def test_resolve_dcs_run_to_data_consistency(self):
        href = resolve_audit_href(
            action="dcs.score_completed",
            metadata={"run_state": "ready"},
            run_id="run-123",
        )
        self.assertEqual(href, "/data-consistency#dcs-score")

    def test_resolve_connector_to_integrations(self):
        href = resolve_audit_href(
            action="connector.connected",
            metadata={"platform": "shopify"},
        )
        self.assertEqual(href, "/integrations")

    def test_explicit_same_origin_href_wins(self):
        href = resolve_audit_href(
            action="writeback.executed",
            metadata={
                "check_id": "CI-01",
                "href": "/data-consistency?check=CI-01",
            },
        )
        self.assertEqual(href, "/data-consistency?check=CI-01")

    def test_external_href_ignored(self):
        href = resolve_audit_href(
            action="writeback.executed",
            metadata={
                "check_id": "CI-01",
                "href": "https://evil.example/fix",
            },
        )
        self.assertEqual(href, "/fix?issue=CI-01")

    def test_extract_link_fields_from_object_id(self):
        fields = extract_audit_link_fields({"object_id": "le-04"})
        self.assertEqual(fields["check_id"], "LE-04")

    def test_extract_link_fields_includes_handoff_ids(self):
        fields = extract_audit_link_fields(
            {
                "handoff_id": "ho-99",
                "qa_run_id": "qa-99",
                "package_id": "pkg-99",
                "use_case_id": "UC-02",
            }
        )
        self.assertEqual(fields["handoff_id"], "ho-99")
        self.assertEqual(fields["qa_run_id"], "qa-99")
        self.assertEqual(fields["package_id"], "pkg-99")
        self.assertEqual(fields["use_case_id"], "UC-02")

    def test_serialized_event_includes_href_and_check_id(self):
        tenant = Tenant.objects.create(name="Acme", slug="acme")
        company = Company.objects.create(
            tenant=tenant,
            name="Acme",
            domain="acme.com",
        )
        user = User.objects.create_user(
            email="admin@acme.com",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        entry = append_audit_event(
            company=company,
            action="writeback.previewed",
            summary="Writeback preview for CC-03",
            performed_by=user.email,
            metadata={"check_id": "CC-03", "job_id": "job-1"},
        )

        from dataruns.audit_views import AuditEventsListView

        factory = APIRequestFactory()
        request = factory.get("/api/v1/audit/events/")
        force_authenticate(request, user=user)
        response = AuditEventsListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.data["results"] if item["id"] == str(entry.id))
        self.assertEqual(row["check_id"], "CC-03")
        self.assertEqual(row["href"], "/fix?issue=CC-03")
        self.assertIsNone(row["package_id"])
        self.assertIsNone(row["report_id"])

    def test_serialized_handoff_audit_event_includes_handoff_href(self):
        tenant = Tenant.objects.create(name="Acme", slug="acme-handoff")
        company = Company.objects.create(
            tenant=tenant,
            name="Acme",
            domain="acme-handoff.com",
        )
        user = User.objects.create_user(
            email="admin-handoff@acme.com",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        entry = append_audit_event(
            company=company,
            action="workflow.handoff_approved_for_activation",
            summary="Handoff approved for activation",
            performed_by=user.email,
            metadata={
                "handoff_id": "11111111-1111-1111-1111-111111111111",
                "package_id": "22222222-2222-2222-2222-222222222222",
                "qa_run_id": "33333333-3333-3333-3333-333333333333",
                "use_case_id": "UC-02",
                "status": "APPROVED_FOR_ACTIVATION",
                "manifest_hash": "a" * 64,
                "path": "HUMAN_MANAGO_UI",
            },
        )

        factory = APIRequestFactory()
        request = factory.get("/api/v1/audit/events/")
        force_authenticate(request, user=user)
        response = AuditEventsListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.data["results"] if item["id"] == str(entry.id))
        self.assertEqual(row["handoff_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(row["qa_run_id"], "33333333-3333-3333-3333-333333333333")
        self.assertEqual(row["package_id"], "22222222-2222-2222-2222-222222222222")
        self.assertEqual(row["use_case_id"], "UC-02")
        self.assertEqual(
            row["href"],
            "/handoff?uc=UC-02&package_id=22222222-2222-2222-2222-222222222222"
            "&handoff_id=11111111-1111-1111-1111-111111111111"
            "&qa_run_id=33333333-3333-3333-3333-333333333333",
        )
