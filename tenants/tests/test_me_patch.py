from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from tenants.auth.views import MeView
from tenants.models import Company, Connector, Tenant, User


class MePatchTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = MeView.as_view()
        self.tenant = Tenant.objects.create(name="Acme Corp", slug="me-patch-acme")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme Corp",
            domain="acme.example",
        )
        self.user = User.objects.create_user(
            email="me-patch@example.com",
            password="TestPass123!",
            name="Original Name",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )

    def _get_me(self, user=None):
        request = self.factory.get("/api/v1/auth/me/")
        if user is not None:
            force_authenticate(request, user=user)
        return self.view(request)

    def _patch_me(self, data, user=None):
        request = self.factory.patch("/api/v1/auth/me/", data, format="json")
        if user is not None:
            force_authenticate(request, user=user)
        return self.view(request)

    def test_authenticated_user_can_update_name(self):
        response = self._patch_me({"name": "George L."}, user=self.user)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "George L.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "George L.")

    def test_patch_response_matches_get_me_shape(self):
        get_response = self._get_me(user=self.user)
        patch_response = self._patch_me({"name": "George L."}, user=self.user)

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(set(patch_response.data.keys()), set(get_response.data.keys()))
        self.assertEqual(
            set(patch_response.data["tenant"].keys()),
            set(get_response.data["tenant"].keys()),
        )
        self.assertEqual(
            set(patch_response.data["company"].keys()),
            set(get_response.data["company"].keys()),
        )

    def test_patch_cannot_change_email(self):
        response = self._patch_me(
            {"name": "George L.", "email": "hacker@example.com"},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "me-patch@example.com")
        self.assertEqual(response.data["email"], "me-patch@example.com")

    def test_patch_cannot_change_role(self):
        response = self._patch_me(
            {"name": "George L.", "role": "viewer"},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.ADMIN)
        self.assertEqual(response.data["role"], User.Role.ADMIN)

    def test_patch_leaves_tenant_and_company_unchanged(self):
        response = self._patch_me(
            {
                "name": "George L.",
                "tenant": {"name": "Hacked Tenant", "slug": "hacked"},
                "company": {"name": "Hacked Co", "domain": "hacked.example"},
            },
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        self.tenant.refresh_from_db()
        self.company.refresh_from_db()
        self.assertEqual(self.tenant.name, "Acme Corp")
        self.assertEqual(self.tenant.slug, "me-patch-acme")
        self.assertEqual(self.company.name, "Acme Corp")
        self.assertEqual(self.company.domain, "acme.example")
        self.assertEqual(response.data["tenant"]["name"], "Acme Corp")
        self.assertEqual(response.data["company"]["domain"], "acme.example")

    def test_unauthenticated_patch_returns_401(self):
        response = self._patch_me({"name": "George L."})

        self.assertEqual(response.status_code, 401)

    def test_get_me_includes_needs_connector_true_without_connected_connector(self):
        response = self._get_me(user=self.user)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["needs_connector"])

    def test_get_me_includes_needs_connector_false_with_connected_connector(self):
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config={},
            status="connected",
        )

        response = self._get_me(user=self.user)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["needs_connector"])
