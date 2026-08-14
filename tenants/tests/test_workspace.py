from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from tenants.auth.views import MeView
from tenants.models import Company, Tenant, User
from tenants.workspace.views import WorkspaceView


class WorkspacePatchTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = WorkspaceView.as_view()
        self.me_view = MeView.as_view()
        self.tenant = Tenant.objects.create(name="Lumera Skin", slug="workspace-test")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Lumera Skin",
            domain="lumera.skin",
        )
        self.admin = User.objects.create_user(
            email="workspace-admin@example.com",
            password="TestPass123!",
            name="Workspace Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.analyst = User.objects.create_user(
            email="workspace-analyst@example.com",
            password="TestPass123!",
            name="Workspace Analyst",
            tenant=self.tenant,
            role=User.Role.ANALYST,
            email_verified=True,
            is_active=True,
        )

    def _patch_workspace(self, data, user=None):
        request = self.factory.patch(
            "/api/v1/auth/workspace/",
            data,
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return self.view(request)

    def _get_me(self, user=None):
        request = self.factory.get("/api/v1/auth/me/")
        if user is not None:
            force_authenticate(request, user=user)
        return self.me_view(request)

    def test_workspace_patch_reflected_in_get_me(self):
        patch_response = self._patch_workspace(
            {
                "tenant_name": "Renamed Tenant",
                "company_name": "Renamed Company",
                "company_domain": "renamed.example",
            },
            user=self.admin,
        )
        self.assertEqual(patch_response.status_code, 200)

        fresh_admin = User.objects.select_related("tenant").get(pk=self.admin.pk)
        me_response = self._get_me(user=fresh_admin)

        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.data["tenant"]["name"], "Renamed Tenant")
        self.assertEqual(me_response.data["tenant"]["slug"], "workspace-test")
        self.assertEqual(me_response.data["company"]["name"], "Renamed Company")
        self.assertEqual(me_response.data["company"]["domain"], "renamed.example")

    def test_admin_updates_tenant_name(self):
        response = self._patch_workspace(
            {"tenant_name": "Lumera Updated"},
            user=self.admin,
        )

        self.assertEqual(response.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.name, "Lumera Updated")
        self.assertEqual(response.data["tenant"]["name"], "Lumera Updated")

    def test_admin_updates_company_name(self):
        response = self._patch_workspace(
            {"company_name": "Lumera Co"},
            user=self.admin,
        )

        self.assertEqual(response.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Lumera Co")
        self.assertEqual(response.data["company"]["name"], "Lumera Co")

    def test_admin_updates_company_domain(self):
        response = self._patch_workspace(
            {"company_domain": "updated.lumera.skin"},
            user=self.admin,
        )

        self.assertEqual(response.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.domain, "updated.lumera.skin")
        self.assertEqual(response.data["company"]["domain"], "updated.lumera.skin")

    def test_partial_patch_updates_only_provided_fields(self):
        self.tenant.name = "Before Tenant"
        self.tenant.save(update_fields=["name", "updated_at"])
        self.company.name = "Before Company"
        self.company.domain = "before.example"
        self.company.save(update_fields=["name", "domain"])

        response = self._patch_workspace(
            {"company_name": "After Company"},
            user=self.admin,
        )

        self.assertEqual(response.status_code, 200)
        self.tenant.refresh_from_db()
        self.company.refresh_from_db()
        self.assertEqual(self.tenant.name, "Before Tenant")
        self.assertEqual(self.company.name, "After Company")
        self.assertEqual(self.company.domain, "before.example")

    def test_tenant_slug_never_changes(self):
        response = self._patch_workspace(
            {"tenant_name": "Renamed Workspace"},
            user=self.admin,
        )

        self.assertEqual(response.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.slug, "workspace-test")
        self.assertEqual(response.data["tenant"]["slug"], "workspace-test")

    def test_company_domain_normalization(self):
        response = self._patch_workspace(
            {"company_domain": "https://NEW.DOMAIN.COM/"},
            user=self.admin,
        )

        self.assertEqual(response.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.domain, "new.domain.com")
        self.assertEqual(response.data["company"]["domain"], "new.domain.com")

    def test_non_admin_returns_403(self):
        response = self._patch_workspace(
            {"tenant_name": "Blocked Update"},
            user=self.analyst,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data, {"detail": "Admin only."})
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.name, "Lumera Skin")

    def test_tenant_without_company_returns_400(self):
        tenant = Tenant.objects.create(name="No Company Co", slug="no-company-workspace")
        admin = User.objects.create_user(
            email="no-company-admin@example.com",
            password="TestPass123!",
            name="No Company Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )

        response = self._patch_workspace(
            {"tenant_name": "Should Fail"},
            user=admin,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"detail": "No company on this workspace."},
        )
