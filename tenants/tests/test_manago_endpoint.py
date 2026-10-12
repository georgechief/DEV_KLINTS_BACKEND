"""Gate B P1 — Manago verify endpoint SSRF hardening."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from tenants.connector_views import ConnectorVerifyView
from tenants.manago import ManagoVerifyResult
from tenants.manago_endpoint import (
    ManagoEndpointError,
    allowed_manago_api_hosts,
    normalize_and_validate_manago_endpoint,
)
from tenants.models import Tenant, User

_PUBLIC_ADDRINFO = [
    (None, None, None, None, ("93.184.216.34", 443)),
]


@override_settings(MANAGO_API_BASE_URL="https://app2.manago.ai")
class ManagoEndpointValidationTests(SimpleTestCase):
    @patch(
        "tenants.manago_endpoint.socket.getaddrinfo",
        return_value=_PUBLIC_ADDRINFO,
    )
    def test_allows_official_https_host(self, _mock_dns):
        self.assertEqual(
            normalize_and_validate_manago_endpoint("https://app3.manago.ai"),
            "https://app3.manago.ai",
        )
        self.assertEqual(
            normalize_and_validate_manago_endpoint("app.manago.ai"),
            "https://app.manago.ai",
        )

    @patch(
        "tenants.manago_endpoint.socket.getaddrinfo",
        return_value=_PUBLIC_ADDRINFO,
    )
    def test_strips_path_and_trailing_slash(self, _mock_dns):
        self.assertEqual(
            normalize_and_validate_manago_endpoint(
                "https://app2.manago.ai/api/extra/"
            ),
            "https://app2.manago.ai",
        )

    def test_rejects_http(self):
        with self.assertRaises(ManagoEndpointError) as ctx:
            normalize_and_validate_manago_endpoint("http://app2.manago.ai")
        self.assertIn("HTTPS", str(ctx.exception))

    def test_rejects_non_manago_host(self):
        with self.assertRaises(ManagoEndpointError) as ctx:
            normalize_and_validate_manago_endpoint("https://evil.example.com")
        self.assertIn("official Manago host", str(ctx.exception))

    def test_rejects_manago_lookalike(self):
        with self.assertRaises(ManagoEndpointError):
            normalize_and_validate_manago_endpoint(
                "https://app2.manago.ai.evil.com"
            )

    def test_rejects_ip_literal(self):
        with self.assertRaises(ManagoEndpointError) as ctx:
            normalize_and_validate_manago_endpoint("https://127.0.0.1")
        self.assertIn("not an IP address", str(ctx.exception))

    def test_rejects_userinfo(self):
        with self.assertRaises(ManagoEndpointError):
            normalize_and_validate_manago_endpoint(
                "https://user:pass@app2.manago.ai"
            )

    def test_rejects_non_default_port(self):
        with self.assertRaises(ManagoEndpointError):
            normalize_and_validate_manago_endpoint(
                "https://app2.manago.ai:8443"
            )

    @patch(
        "tenants.manago_endpoint.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("127.0.0.1", 443))],
    )
    def test_rejects_private_dns_resolution(self, _mock_dns):
        with self.assertRaises(ManagoEndpointError) as ctx:
            normalize_and_validate_manago_endpoint("https://app2.manago.ai")
        self.assertIn("private or internal", str(ctx.exception))

    @patch(
        "tenants.manago_endpoint.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("169.254.169.254", 443))],
    )
    def test_rejects_link_local_metadata(self, _mock_dns):
        with self.assertRaises(ManagoEndpointError):
            normalize_and_validate_manago_endpoint("https://app2.manago.ai")

    def test_allowed_hosts_include_settings_base(self):
        hosts = allowed_manago_api_hosts()
        self.assertIn("app2.manago.ai", hosts)
        self.assertIn("app.manago.ai", hosts)

    def test_no_redirect_handler_raises(self):
        from tenants.manago_endpoint import _NoRedirectHandler

        request = MagicMock()
        request.full_url = "https://app2.manago.ai/api/user/listByClient"
        handler = _NoRedirectHandler()
        with self.assertRaises(ManagoEndpointError) as ctx:
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "http://127.0.0.1/",
            )
        self.assertIn("redirect", str(ctx.exception).lower())


@override_settings(
    MANAGO_API_BASE_URL="https://app2.manago.ai",
    MANAGO_ALLOWED_API_HOSTS=["custom.manago.ai"],
)
class ManagoEndpointExtraHostsTests(SimpleTestCase):
    @patch(
        "tenants.manago_endpoint.socket.getaddrinfo",
        return_value=_PUBLIC_ADDRINFO,
    )
    def test_settings_extra_host_allowed(self, _mock_dns):
        self.assertEqual(
            normalize_and_validate_manago_endpoint("https://custom.manago.ai"),
            "https://custom.manago.ai",
        )


@override_settings(MANAGO_API_BASE_URL="https://app2.manago.ai")
class ConnectorVerifySsrfViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ConnectorVerifyView.as_view()
        self.tenant = Tenant(name="Acme", slug="acme")
        self.user = User(
            email="admin@example.com",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )

    def _post(self, body: dict):
        request = self.factory.post(
            "/api/v1/connectors/verify/",
            body,
            format="json",
        )
        force_authenticate(request, user=self.user)
        return self.view(request)

    @patch(
        "tenants.manago_endpoint.socket.getaddrinfo",
        return_value=_PUBLIC_ADDRINFO,
    )
    @patch("tenants.connector_views.verify_credentials")
    def test_verify_rejects_http_before_fetch(self, mock_verify, _mock_dns):
        response = self._post(
            {
                "client_id": "c1",
                "api_secret": "s1",
                "endpoint": "http://app2.manago.ai",
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("valid", True))
        mock_verify.assert_not_called()

    @patch(
        "tenants.manago_endpoint.socket.getaddrinfo",
        return_value=_PUBLIC_ADDRINFO,
    )
    @patch("tenants.connector_views.verify_credentials")
    def test_verify_rejects_external_host(self, mock_verify, _mock_dns):
        response = self._post(
            {
                "client_id": "c1",
                "api_secret": "s1",
                "endpoint": "https://169.254.169.254",
            }
        )
        self.assertEqual(response.status_code, 400)
        mock_verify.assert_not_called()

    @patch("tenants.connector_views._user_company", return_value=None)
    @patch(
        "tenants.manago_endpoint.socket.getaddrinfo",
        return_value=_PUBLIC_ADDRINFO,
    )
    @patch("tenants.connector_views.verify_credentials")
    def test_verify_success_uses_safe_endpoint(
        self, mock_verify, _mock_dns, _mock_company
    ):
        mock_verify.return_value = ManagoVerifyResult(
            valid=True,
            message="Credentials verified",
        )
        response = self._post(
            {
                "client_id": "c1",
                "api_secret": "s1",
                "endpoint": "https://app3.manago.ai",
            }
        )
        self.assertEqual(response.status_code, 200)
        mock_verify.assert_called_once_with(
            client_id="c1",
            api_secret="s1",
            endpoint="https://app3.manago.ai",
        )

    @patch("tenants.connector_views._user_company", return_value=None)
    @patch(
        "tenants.manago_endpoint.socket.getaddrinfo",
        return_value=_PUBLIC_ADDRINFO,
    )
    @patch("tenants.connector_views.verify_credentials")
    def test_verify_does_not_print_email_or_client_id(
        self,
        mock_verify,
        _mock_dns,
        _mock_company,
    ):
        import inspect

        mock_verify.return_value = ManagoVerifyResult(
            valid=True,
            message="Credentials verified",
        )
        with patch("builtins.print") as mock_print:
            self._post(
                {
                    "client_id": "secret-client-id",
                    "api_secret": "s1",
                    "endpoint": "https://app2.manago.ai",
                }
            )
        mock_print.assert_not_called()
        source = inspect.getsource(ConnectorVerifyView)
        self.assertNotIn("print(", source)
        # Must not interpolate raw secrets into log format strings.
        self.assertNotIn("client_id={", source)
        self.assertNotIn("client_id=%r", source)
        self.assertNotIn("user=", source)
        self.assertNotIn("email=", source)
        self.assertIn("has_client_id=%s", source)
