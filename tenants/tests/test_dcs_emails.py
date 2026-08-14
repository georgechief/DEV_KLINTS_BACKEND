"""Tests for DCS completed / blocked / failed notification emails."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from tenants.emails import (
    send_dcs_completed_email,
    send_dcs_failed_email,
)


@override_settings(
    MAILER_API_URL="https://mailer.test/send",
    MAILER_API_TOKEN="token",
    FRONTEND_DCS_URL="https://app.test/dashboard",
    FRONTEND_APP_ORIGIN="https://app.test",
    EMAIL_LOGO_URL="https://app.test/klints-mark.png",
)
class DcsEmailContentTests(SimpleTestCase):
    @patch("tenants.emails.send_email")
    @patch("tenants.emails._dcs_recipient_emails", return_value=["admin@acme.com"])
    def test_blocked_email_uses_friendly_fix_text(self, _recipients, mock_send):
        company = SimpleNamespace(name="Acme", tenant_id="t1")
        send_dcs_completed_email(
            company=company,
            run_state="BLOCKED",
            headline_score=None,
            data_run_id=9,
            blocking_gates_failed=1,
            fail_checks=[
                {
                    "check_id": "FD-07",
                    "check_name": "Website tracking is working",
                    "message": (
                        "We couldn't confirm Manago tracking on your live storefront."
                    ),
                    "suggested_fix": (
                        "Install or repair the Manago tracking code on your live "
                        "Shopify storefront, then visit the site once so we can "
                        "confirm visits are arriving."
                    ),
                    "fix_in_klints": False,
                }
            ],
        )
        self.assertEqual(mock_send.call_count, 1)
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["to"], "admin@acme.com")
        self.assertIn("fixes needed", kwargs["subject"].lower())
        self.assertIn("Website tracking is working", kwargs["text"])
        self.assertIn("Install or repair the Manago tracking code", kwargs["text"])
        self.assertNotIn("DataRun id", kwargs["text"])
        self.assertNotIn("Blocking gates", kwargs["text"])
        self.assertNotIn("RC-12", kwargs["text"])
        self.assertNotIn("FD-07", kwargs["text"])
        self.assertIn("https://app.test/dashboard", kwargs["text"])
        self.assertIn("https://app.test/klints-mark.png", kwargs["html"])
        self.assertIn("#1f3a5f", kwargs["html"])
        self.assertIn("#f5f2eb", kwargs["html"])

    @patch("tenants.emails.send_email")
    @patch("tenants.emails._dcs_recipient_emails", return_value=["admin@acme.com"])
    def test_technical_excel_fix_is_replaced(self, _recipients, mock_send):
        company = SimpleNamespace(name="Acme", tenant_id="t1")
        send_dcs_completed_email(
            company=company,
            run_state="INCOMPLETE",
            headline_score=70.516,
            data_run_id=9,
            fail_checks=[
                {
                    "check_id": "CI-01",
                    "check_name": "Contact count reconciliation",
                    "message": "CI-01 failed: RC-01 Integration gap — Detail: pipe missing",
                    "suggested_fix": (
                        "Build the missing pipe; backfill common window with approval."
                    ),
                    "fix_in_klints": True,
                }
            ],
        )
        kwargs = mock_send.call_args.kwargs
        self.assertIn("Contact count reconciliation", kwargs["text"])
        self.assertIn("Klints can help with this", kwargs["text"])
        self.assertNotIn("RC-01", kwargs["text"])
        self.assertNotIn("missing pipe", kwargs["text"])
        self.assertIn("Score: 70.5", kwargs["text"])
        self.assertIn("Still finishing", kwargs["text"])

    @patch("tenants.emails.send_email")
    @patch("tenants.emails._dcs_recipient_emails", return_value=["admin@acme.com"])
    def test_failed_pipeline_email(self, _recipients, mock_send):
        company = SimpleNamespace(name="Acme", tenant_id="t1")
        send_dcs_failed_email(
            company=company,
            error_message="Shopify refresh token is inactive; reconnect required.",
            data_run_id=12,
        )
        kwargs = mock_send.call_args.kwargs
        self.assertIn("couldn't finish", kwargs["subject"].lower())
        self.assertIn("try again from the dashboard", kwargs["text"].lower())
        self.assertNotIn("refresh token", kwargs["text"].lower())
        self.assertNotIn("DataRun id", kwargs["text"])
        self.assertNotIn("Support reference", kwargs["html"])
    @patch("tenants.emails.send_email")
    @patch("tenants.emails._bootstrap_admin_recipient_emails", return_value=["admin@co.test"])
    @patch("tenants.emails.User.objects")
    def test_includes_actor_and_admin(self, mock_users, _admins, mock_send):
        actor = SimpleNamespace(email="actor@co.test")
        mock_users.filter.return_value.only.return_value.first.return_value = actor
        company = SimpleNamespace(name="Co", tenant_id="t1")
        send_dcs_completed_email(
            company=company,
            run_state="BLOCKED",
            headline_score=None,
            data_run_id=1,
            actor_user_id="actor-id",
            fail_checks=[],
        )
        recipients = sorted(c.kwargs["to"] for c in mock_send.call_args_list)
        self.assertEqual(recipients, ["actor@co.test", "admin@co.test"])
