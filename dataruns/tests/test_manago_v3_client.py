"""Manago API v3 client header tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase

from dataruns.connectors.manago_ai.client import (
    _MANAGO_V3_USER_AGENT,
    _fetch_product_catalogs_v3,
    _manago_v3_headers,
    _manago_v3_url,
)


class ManagoV3ClientTests(TestCase):
    def test_manago_v3_url(self):
        self.assertEqual(
            _manago_v3_url("product/catalogList"),
            "https://api.manago.ai/v3/product/catalogList",
        )

    def test_manago_v3_headers_include_api_key_and_user_agent(self):
        headers = _manago_v3_headers(api_v3_key="  test-v3-key  ")
        self.assertEqual(headers["API-KEY"], "test-v3-key")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["User-Agent"], _MANAGO_V3_USER_AGENT)

    def test_manago_v3_headers_merge_extra(self):
        headers = _manago_v3_headers(
            api_v3_key="key",
            extra={"Content-Type": "application/json"},
        )
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["User-Agent"], _MANAGO_V3_USER_AGENT)

    @patch("dataruns.connectors.manago_ai.client.urllib.request.urlopen")
    def test_fetch_product_catalogs_v3_sends_user_agent(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"catalogs":[]}'
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = False
        mock_urlopen.return_value = mock_response

        catalogs, note = _fetch_product_catalogs_v3(
            config={"api_v3_key": "test-v3-key"},
            timeout=5.0,
        )

        self.assertEqual(catalogs, [])
        self.assertIsNone(note)
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.get_full_url(), _manago_v3_url("product/catalogList"))
        self.assertEqual(request.get_header("User-agent"), _MANAGO_V3_USER_AGENT)
        self.assertEqual(request.get_header("Api-key"), "test-v3-key")
