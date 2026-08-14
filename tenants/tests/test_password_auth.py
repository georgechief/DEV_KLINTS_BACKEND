from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from tenants.auth.services import create_password_reset_token
from tenants.auth.views import (
    ChangePasswordView,
    ForgotPasswordView,
    ResetPasswordView,
)
from tenants.auth_views import LoginView
from tenants.models import PasswordResetToken, Tenant, User


class PasswordAuthTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.user = User.objects.create_user(
            email="password-test@example.com",
            password="OldPass123!",
            name="Password Test",
            tenant=self.tenant,
            email_verified=True,
            is_active=True,
        )
        self.factory = APIRequestFactory()
        self.forgot_view = ForgotPasswordView.as_view()
        self.reset_view = ResetPasswordView.as_view()
        self.change_view = ChangePasswordView.as_view()
        self.login_view = LoginView.as_view()

    def _login(self, email, password):
        return self.login_view(
            self.factory.post(
                "/api/v1/auth/login/",
                {"email": email, "password": password},
                format="json",
            )
        )

    def test_forgot_password_unknown_email_returns_opaque_success(self):
        with patch("tenants.auth.views.send_password_reset_email") as send_email:
            response = self.forgot_view(
                self.factory.post(
                    "/api/v1/auth/forgot-password/",
                    {"email": "missing@example.com"},
                    format="json",
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"detail": "If an account exists, a reset link has been sent."},
        )
        send_email.assert_not_called()
        self.assertEqual(PasswordResetToken.objects.count(), 0)

    def test_forgot_password_valid_email_creates_token_and_sends_email(self):
        with patch("tenants.auth.views.send_password_reset_email") as send_email:
            response = self.forgot_view(
                self.factory.post(
                    "/api/v1/auth/forgot-password/",
                    {"email": self.user.email},
                    format="json",
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"detail": "If an account exists, a reset link has been sent."},
        )
        reset_token = PasswordResetToken.objects.get(user=self.user)
        send_email.assert_called_once_with(
            email=self.user.email,
            token=reset_token.token,
        )

    def test_reset_password_success_updates_password(self):
        reset_token = create_password_reset_token(self.user)

        response = self.reset_view(
            self.factory.post(
                "/api/v1/auth/reset-password/",
                {
                    "token": reset_token.token,
                    "email": self.user.email,
                    "password": "NewSecurePass456!",
                },
                format="json",
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"detail": "Password updated. You can sign in."},
        )
        self.user.refresh_from_db()
        reset_token.refresh_from_db()
        self.assertTrue(self.user.check_password("NewSecurePass456!"))
        self.assertIsNotNone(reset_token.used_at)

    def test_reset_password_rejects_expired_token(self):
        reset_token = create_password_reset_token(self.user)
        reset_token.expires_at = timezone.now() - timedelta(hours=1)
        reset_token.save(update_fields=["expires_at"])

        response = self.reset_view(
            self.factory.post(
                "/api/v1/auth/reset-password/",
                {
                    "token": reset_token.token,
                    "email": self.user.email,
                    "password": "NewSecurePass456!",
                },
                format="json",
            )
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"detail": "Invalid or expired reset link."},
        )

    def test_reset_password_rejects_used_token(self):
        reset_token = create_password_reset_token(self.user)
        reset_token.used_at = timezone.now()
        reset_token.save(update_fields=["used_at"])

        response = self.reset_view(
            self.factory.post(
                "/api/v1/auth/reset-password/",
                {
                    "token": reset_token.token,
                    "email": self.user.email,
                    "password": "NewSecurePass456!",
                },
                format="json",
            )
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"detail": "Invalid or expired reset link."},
        )

    def test_change_password_success(self):
        request = self.factory.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": "OldPass123!",
                "new_password": "NewSecurePass456!",
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = self.change_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"detail": "Password updated."})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewSecurePass456!"))

    def test_change_password_rejects_wrong_current_password(self):
        request = self.factory.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": "WrongPass123!",
                "new_password": "NewSecurePass456!",
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = self.change_view(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"current_password": ["Incorrect password."]},
        )

    def test_forgot_reset_then_login_with_new_password(self):
        new_password = "NewSecurePass456!"

        with patch("tenants.auth.views.send_password_reset_email"):
            forgot_response = self.forgot_view(
                self.factory.post(
                    "/api/v1/auth/forgot-password/",
                    {"email": self.user.email},
                    format="json",
                )
            )

        self.assertEqual(forgot_response.status_code, 200)
        reset_token = PasswordResetToken.objects.get(user=self.user)

        reset_response = self.reset_view(
            self.factory.post(
                "/api/v1/auth/reset-password/",
                {
                    "token": reset_token.token,
                    "email": self.user.email,
                    "password": new_password,
                },
                format="json",
            )
        )
        self.assertEqual(reset_response.status_code, 200)

        old_login = self._login(self.user.email, "OldPass123!")
        self.assertEqual(old_login.status_code, 401)

        new_login = self._login(self.user.email, new_password)
        self.assertEqual(new_login.status_code, 200)
        self.assertIn("access", new_login.data)

    def test_change_password_then_login_with_new_password(self):
        new_password = "NewSecurePass456!"

        request = self.factory.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": "OldPass123!",
                "new_password": new_password,
            },
            format="json",
        )
        force_authenticate(request, user=self.user)
        change_response = self.change_view(request)
        self.assertEqual(change_response.status_code, 200)

        old_login = self._login(self.user.email, "OldPass123!")
        self.assertEqual(old_login.status_code, 401)

        new_login = self._login(self.user.email, new_password)
        self.assertEqual(new_login.status_code, 200)
        self.assertIn("access", new_login.data)
