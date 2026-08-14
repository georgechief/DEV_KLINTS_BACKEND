from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from tenants.auth_views import VerifyEmailView, _create_verification_token
from tenants.models import Company, Tenant, User


class VerifyEmailViewTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.user = User.objects.create_user(
            email="verify-test@example.com",
            password="TestPass123!",
            name="Verify Test",
            tenant=self.tenant,
            email_verified=False,
            is_active=False,
        )
        Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="example.com",
        )
        self.token = _create_verification_token(self.user)
        self.factory = APIRequestFactory()
        self.view = VerifyEmailView.as_view()

    def _post_verify(self):
        request = self.factory.post(
            "/api/v1/auth/verify-email/",
            {"token": self.token.token, "email": self.token.email},
            format="json",
        )
        return self.view(request)

    def test_verify_email_success(self):
        response = self._post_verify()
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.token.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertTrue(self.user.is_active)
        self.assertIsNotNone(self.token.used_at)

    def test_verify_email_idempotent_for_duplicate_requests(self):
        first = self._post_verify()
        second = self._post_verify()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["email_verified"], True)

    def test_verify_email_rejects_expired_token(self):
        self.token.expires_at = timezone.now() - timedelta(hours=1)
        self.token.save(update_fields=["expires_at"])
        response = self._post_verify()
        self.assertEqual(response.status_code, 400)
