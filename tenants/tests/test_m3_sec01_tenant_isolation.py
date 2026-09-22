"""M3-SEC-01 Phase 2/3 — cross-tenant isolation (tenants surfaces).

Team member + connector + invite object IDs must not cross companies.
TenantViewSet / DataRunViewSet scoped in Phase 3 (tests below).
"""

from __future__ import annotations

from django.test import TestCase

from dataruns.models import DataRun
from dataruns.tests.helpers_m3_sec01 import make_sec01_tenant_pair
from tenants.models import Connector, Invite, Tenant, User


class M3Sec01TeamIsolationTests(TestCase):
    def setUp(self):
        self.pair = make_sec01_tenant_pair(slug_prefix="sec01-team")
        self.member_a = User.objects.create_user(
            email="analyst-a@sec01-team.test",
            password="TestPass123!",
            name="Analyst A",
            tenant=self.pair.tenant_a,
            role=User.Role.ANALYST,
            email_verified=True,
            is_active=True,
        )
        self.invite_a = Invite.objects.create(
            tenant=self.pair.tenant_a,
            email="invitee-a@sec01-team.test",
            role=User.Role.VIEWER,
            invited_by=self.pair.admin_a,
        )

    def test_b_member_list_excludes_a(self):
        response = self.pair.client_b.get("/api/v1/team/members/")
        self.assertEqual(response.status_code, 200)
        emails = {m.get("email") for m in response.data.get("members") or []}
        self.assertNotIn(self.pair.admin_a.email, emails)
        self.assertNotIn(self.member_a.email, emails)
        self.assertIn(self.pair.admin_b.email, emails)

    def test_b_cannot_patch_a_member(self):
        response = self.pair.client_b.patch(
            f"/api/v1/team/members/{self.member_a.id}/",
            {"role": "viewer"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.member_a.refresh_from_db()
        self.assertEqual(self.member_a.role, User.Role.ANALYST)

    def test_b_invite_list_excludes_a(self):
        response = self.pair.client_b.get("/api/v1/team/invites/")
        self.assertEqual(response.status_code, 200)
        ids = {str(i.get("id")) for i in response.data.get("invites") or []}
        self.assertNotIn(str(self.invite_a.id), ids)

    def test_b_cannot_revoke_a_invite(self):
        response = self.pair.client_b.post(
            f"/api/v1/team/invites/{self.invite_a.id}/revoke/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.invite_a.refresh_from_db()
        self.assertEqual(self.invite_a.status, Invite.Status.PENDING)

    def test_b_cannot_resend_a_invite(self):
        response = self.pair.client_b.post(
            f"/api/v1/team/invites/{self.invite_a.id}/resend/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 404)


class M3Sec01ConnectorIsolationTests(TestCase):
    def setUp(self):
        self.pair = make_sec01_tenant_pair(slug_prefix="sec01-conn")
        self.connector_a = Connector.objects.create(
            company=self.pair.company_a,
            name="shopify",
            type="ecommerce",
            config={"shop_domain": "a.myshopify.com"},
            status="connected",
        )
        self.connector_b = Connector.objects.create(
            company=self.pair.company_b,
            name="shopify",
            type="ecommerce",
            config={"shop_domain": "b.myshopify.com"},
            status="connected",
        )

    def test_b_list_excludes_a_connector(self):
        response = self.pair.client_b.get("/api/v1/connectors/")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results") or []
        ids = {str(row.get("id")) for row in results if isinstance(row, dict)}
        self.assertIn(str(self.connector_b.id), ids)
        self.assertNotIn(str(self.connector_a.id), ids)

    def test_b_cannot_disconnect_a_connector(self):
        response = self.pair.client_b.delete(
            f"/api/v1/connectors/{self.connector_a.id}/"
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            Connector.objects.filter(pk=self.connector_a.id).exists()
        )

    def test_b_cannot_view_a_bootstrap(self):
        response = self.pair.client_b.get(
            f"/api/v1/connectors/{self.connector_a.id}/bootstrap/"
        )
        self.assertEqual(response.status_code, 404)


class M3Sec01TenantViewSetIsolationTests(TestCase):
    """PRD §8 — TenantViewSet must not list/leak other tenants."""

    def setUp(self):
        from rest_framework.test import APIClient

        self.pair = make_sec01_tenant_pair(slug_prefix="sec01-tv")
        self.viewer_a = User.objects.create_user(
            email="viewer-a@sec01-tv.test",
            password="TestPass123!",
            name="Viewer A",
            tenant=self.pair.tenant_a,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )
        self.client_viewer_a = APIClient()
        self.client_viewer_a.force_authenticate(user=self.viewer_a)

    def test_a_list_only_own_tenant(self):
        response = self.pair.client_a.get("/api/v1/tenants/")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results") or response.data
        if isinstance(results, dict):
            results = results.get("results") or []
        slugs = {row.get("slug") for row in results if isinstance(row, dict)}
        self.assertEqual(slugs, {self.pair.tenant_a.slug})

    def test_b_cannot_retrieve_a_tenant(self):
        response = self.pair.client_b.get(
            f"/api/v1/tenants/{self.pair.tenant_a.slug}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_a_can_retrieve_own_tenant(self):
        response = self.pair.client_a.get(
            f"/api/v1/tenants/{self.pair.tenant_a.slug}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("slug"), self.pair.tenant_a.slug)

    def test_create_tenant_forbidden(self):
        response = self.pair.client_a.post(
            "/api/v1/tenants/",
            {"name": "Evil", "slug": "evil-tenant"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Tenant.objects.filter(slug="evil-tenant").exists())

    def test_destroy_own_tenant_forbidden(self):
        response = self.pair.client_a.delete(
            f"/api/v1/tenants/{self.pair.tenant_a.slug}/"
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            Tenant.objects.filter(pk=self.pair.tenant_a.id).exists()
        )

    def test_destroy_foreign_tenant_forbidden_no_leak(self):
        # Always 403 — must not reveal whether foreign slug exists (404 vs 403).
        response = self.pair.client_b.delete(
            f"/api/v1/tenants/{self.pair.tenant_a.slug}/"
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            Tenant.objects.filter(pk=self.pair.tenant_a.id).exists()
        )

    def test_b_cannot_patch_a_tenant(self):
        response = self.pair.client_b.patch(
            f"/api/v1/tenants/{self.pair.tenant_a.slug}/",
            {"name": "Hijacked"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.pair.tenant_a.refresh_from_db()
        self.assertEqual(self.pair.tenant_a.name, "sec01-tv-A")

    def test_viewer_cannot_patch_own_tenant(self):
        response = self.client_viewer_a.patch(
            f"/api/v1/tenants/{self.pair.tenant_a.slug}/",
            {"name": "Viewer Rename"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.pair.tenant_a.refresh_from_db()
        self.assertEqual(self.pair.tenant_a.name, "sec01-tv-A")

    def test_admin_can_patch_own_name_but_slug_and_active_readonly(self):
        response = self.pair.client_a.patch(
            f"/api/v1/tenants/{self.pair.tenant_a.slug}/",
            {
                "name": "Renamed A",
                "slug": "stolen-slug",
                "is_active": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.pair.tenant_a.refresh_from_db()
        self.assertEqual(self.pair.tenant_a.name, "Renamed A")
        self.assertEqual(self.pair.tenant_a.slug, "sec01-tv-a")
        self.assertTrue(self.pair.tenant_a.is_active)

    def test_unauthenticated_tenants_401(self):
        from rest_framework.test import APIClient

        response = APIClient().get("/api/v1/tenants/")
        self.assertEqual(response.status_code, 401)


class M3Sec01DataRunViewSetIsolationTests(TestCase):
    """PRD §8 — DataRunViewSet scoped; foreign ?tenant= must not leak."""

    def setUp(self):
        self.pair = make_sec01_tenant_pair(slug_prefix="sec01-dr")
        self.run_a = DataRun.objects.create(
            tenant=self.pair.tenant_a,
            name="A run",
            status=DataRun.Status.SUCCEEDED,
            metadata={"owner": "a"},
        )
        self.run_b = DataRun.objects.create(
            tenant=self.pair.tenant_b,
            name="B run",
            status=DataRun.Status.SUCCEEDED,
            metadata={"owner": "b"},
        )

    def test_a_list_only_own_runs(self):
        response = self.pair.client_a.get("/api/v1/dataruns/")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results") or response.data
        if isinstance(results, dict):
            results = results.get("results") or []
        ids = {row.get("id") for row in results if isinstance(row, dict)}
        self.assertIn(self.run_a.id, ids)
        self.assertNotIn(self.run_b.id, ids)

    def test_b_foreign_tenant_query_param_does_not_leak_a(self):
        response = self.pair.client_b.get(
            f"/api/v1/dataruns/?tenant={self.pair.tenant_a.slug}"
        )
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results") or response.data
        if isinstance(results, dict):
            results = results.get("results") or []
        ids = {row.get("id") for row in results if isinstance(row, dict)}
        self.assertNotIn(self.run_a.id, ids)
        self.assertIn(self.run_b.id, ids)

    def test_b_foreign_tenant_uuid_query_param_does_not_leak_a(self):
        # Ignore ?tenant=<uuid> the same as ?tenant=<slug>.
        response = self.pair.client_b.get(
            f"/api/v1/dataruns/?tenant={self.pair.tenant_a.id}"
        )
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results") or response.data
        if isinstance(results, dict):
            results = results.get("results") or []
        ids = {row.get("id") for row in results if isinstance(row, dict)}
        self.assertNotIn(self.run_a.id, ids)
        self.assertIn(self.run_b.id, ids)
        self.assertEqual(response.data.get("count"), 1)

    def test_b_status_filter_stays_tenant_scoped(self):
        pending_a = DataRun.objects.create(
            tenant=self.pair.tenant_a,
            name="A pending",
            status=DataRun.Status.PENDING,
        )
        pending_b = DataRun.objects.create(
            tenant=self.pair.tenant_b,
            name="B pending",
            status=DataRun.Status.PENDING,
        )
        response = self.pair.client_b.get("/api/v1/dataruns/?status=pending")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results") or response.data
        if isinstance(results, dict):
            results = results.get("results") or []
        ids = {row.get("id") for row in results if isinstance(row, dict)}
        self.assertIn(pending_b.id, ids)
        self.assertNotIn(pending_a.id, ids)
        self.assertNotIn(self.run_a.id, ids)

    def test_b_cannot_retrieve_a_run(self):
        response = self.pair.client_b.get(f"/api/v1/dataruns/{self.run_a.id}/")
        self.assertEqual(response.status_code, 404)

    def test_b_cannot_patch_a_run(self):
        response = self.pair.client_b.patch(
            f"/api/v1/dataruns/{self.run_a.id}/",
            {"name": "hijacked"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.run_a.refresh_from_db()
        self.assertEqual(self.run_a.name, "A run")
        self.assertEqual(self.run_a.tenant_id, self.pair.tenant_a.id)

    def test_b_cannot_delete_a_run(self):
        response = self.pair.client_b.delete(f"/api/v1/dataruns/{self.run_a.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(DataRun.objects.filter(pk=self.run_a.id).exists())

    def test_create_forces_caller_tenant(self):
        response = self.pair.client_b.post(
            "/api/v1/dataruns/",
            {"name": "forced", "status": DataRun.Status.PENDING},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        created = DataRun.objects.get(pk=response.data["id"])
        self.assertEqual(created.tenant_id, self.pair.tenant_b.id)
        self.assertEqual(response.data.get("tenant_slug"), self.pair.tenant_b.slug)

    def test_create_ignores_foreign_tenant_slug_in_body(self):
        response = self.pair.client_b.post(
            "/api/v1/dataruns/",
            {
                "name": "inject",
                "status": DataRun.Status.PENDING,
                "tenant_slug": self.pair.tenant_a.slug,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        created = DataRun.objects.get(pk=response.data["id"])
        self.assertEqual(created.tenant_id, self.pair.tenant_b.id)
        self.assertEqual(response.data.get("tenant_slug"), self.pair.tenant_b.slug)

    def test_patch_own_run_cannot_move_to_foreign_tenant(self):
        response = self.pair.client_b.patch(
            f"/api/v1/dataruns/{self.run_b.id}/",
            {
                "name": "still-b",
                "tenant_slug": self.pair.tenant_a.slug,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.run_b.refresh_from_db()
        self.assertEqual(self.run_b.name, "still-b")
        self.assertEqual(self.run_b.tenant_id, self.pair.tenant_b.id)

    def test_put_own_run_cannot_move_to_foreign_tenant(self):
        response = self.pair.client_b.put(
            f"/api/v1/dataruns/{self.run_b.id}/",
            {
                "name": "put-still-b",
                "status": DataRun.Status.SUCCEEDED,
                "tenant_slug": self.pair.tenant_a.slug,
                "tenant": str(self.pair.tenant_a.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.run_b.refresh_from_db()
        self.assertEqual(self.run_b.name, "put-still-b")
        self.assertEqual(self.run_b.tenant_id, self.pair.tenant_b.id)
        self.assertEqual(response.data.get("tenant_slug"), self.pair.tenant_b.slug)

    def test_create_ignores_raw_tenant_id_in_body(self):
        response = self.pair.client_b.post(
            "/api/v1/dataruns/",
            {
                "name": "raw-tenant",
                "status": DataRun.Status.PENDING,
                "tenant": str(self.pair.tenant_a.id),
                "tenant_id": str(self.pair.tenant_a.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        created = DataRun.objects.get(pk=response.data["id"])
        self.assertEqual(created.tenant_id, self.pair.tenant_b.id)

    def test_unauthenticated_dataruns_401(self):
        from rest_framework.test import APIClient

        response = APIClient().get("/api/v1/dataruns/")
        self.assertEqual(response.status_code, 401)
