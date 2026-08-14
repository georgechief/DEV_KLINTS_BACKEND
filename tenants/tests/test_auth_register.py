from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from tenants.auth_views import RegisterView
from tenants.models import Company, Tenant, User


class RegisterCompanyDomainTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = RegisterView.as_view()

    def _register(self, **overrides):
        payload = {
            "email": "signup@lumera.skin",
            "password": "Str0ngPass!word",
            "name": "George L.",
            "company_name": "Lumera Skin",
            "company_domain": "https://Lumera.skin/",
            "tenant_name": "Lumera Skin",
        }
        payload.update(overrides)
        request = self.factory.post("/api/v1/auth/register/", payload, format="json")
        with patch("tenants.auth_views.send_verification_email"):
            return self.view(request)

    def test_register_stores_normalized_company_domain(self):
        response = self._register()

        self.assertEqual(response.status_code, 201)
        company = Company.objects.get(name="Lumera Skin")
        self.assertEqual(company.domain, "lumera.skin")
        self.assertEqual(response.data["company"]["domain"], "lumera.skin")

    def test_register_rejects_empty_company_domain(self):
        response = self._register(company_domain="   ")

        self.assertEqual(response.status_code, 400)
        self.assertIn("company_domain", response.data)

    def test_register_rejects_localhost_company_domain(self):
        response = self._register(company_domain="localhost")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["company_domain"],
            ["Enter a valid website or domain."],
        )

    def test_register_rejects_duplicate_email(self):
        tenant = Tenant.objects.create(name="Existing", slug="existing")
        User.objects.create_user(
            email="signup@lumera.skin",
            password="Str0ngPass123!",
            name="Existing",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )

        response = self._register()

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)
