"""FD-06 topology loader and gate evaluation tests."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from dataruns.dcs.executors.foundation import (
    ConnectorGateInput,
    FoundationGateContext,
    evaluate_fd_06,
)
from dataruns.dcs.topology import (
    evaluate_topology_ok,
    load_manago_topology,
)


class EvaluateTopologyOkTests(SimpleTestCase):
    def test_single_account_passes_without_multi_class(self):
        ok, err = evaluate_topology_ok(
            [
                {
                    "account_id": "c1",
                    "owner": "owner@example.com",
                    "endpoint": "https://app3.manago.ai",
                    "classification": "unknown",
                    "in_scope": True,
                }
            ]
        )
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_multi_account_requires_excel_classification(self):
        ok, err = evaluate_topology_ok(
            [
                {
                    "account_id": "a",
                    "owner": "a@example.com",
                    "endpoint": "https://app3.manago.ai",
                    "classification": "unknown",
                    "in_scope": True,
                },
                {
                    "account_id": "b",
                    "owner": "b@example.com",
                    "endpoint": "https://app3.manago.ai",
                    "classification": "unknown",
                    "in_scope": True,
                },
            ]
        )
        self.assertFalse(ok)
        self.assertIn("relationship", (err or "").lower())
        self.assertNotIn("RC-11", err or "")
        self.assertNotIn("Excel", err or "")

    def test_multi_account_with_geo_and_segment_passes(self):
        ok, err = evaluate_topology_ok(
            [
                {
                    "account_id": "de",
                    "owner": "de@example.com",
                    "endpoint": "https://app3.manago.ai",
                    "classification": "geo_variant",
                    "in_scope": True,
                },
                {
                    "account_id": "b2b",
                    "owner": "b2b@example.com",
                    "endpoint": "https://app3.manago.ai",
                    "classification": "independent_business_line",
                    "in_scope": True,
                },
            ]
        )
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_missing_owner_fails(self):
        ok, err = evaluate_topology_ok(
            [
                {
                    "account_id": "c1",
                    "owner": "",
                    "endpoint": "https://app3.manago.ai",
                    "in_scope": True,
                }
            ]
        )
        self.assertFalse(ok)
        self.assertIn("owner", err or "")


class LoadManagoTopologyTests(SimpleTestCase):
    @patch("dataruns.dcs.topology.list_users_by_client")
    @patch("dataruns.dcs.topology.resolve_manago_credentials")
    def test_single_owner_maps_topology(self, mock_creds, mock_list):
        mock_creds.return_value = (
            "https://app3.manago.ai",
            "client-1",
            "secret",
        )
        mock_list.return_value = {
            "success": True,
            "users": ["owner@example.com"],
        }
        result = load_manago_topology(
            config={"workspace_id": "client-1", "api_key": "enc"},
            shopify_shop_domain="eu-shop.myshopify.com",
        )
        self.assertTrue(result.topology_ok)
        self.assertEqual(len(result.topology_accounts), 1)
        account = result.topology_accounts[0]
        self.assertEqual(account["owner"], "owner@example.com")
        self.assertEqual(account["endpoint"], "https://app3.manago.ai")
        self.assertEqual(account["shop_domain"], "eu-shop.myshopify.com")
        self.assertEqual(account["classification"], "single_account")

    @patch("dataruns.dcs.topology.list_users_by_client")
    @patch("dataruns.dcs.topology.resolve_manago_credentials")
    def test_multi_owner_without_primary_requires_selection(self, mock_creds, mock_list):
        mock_creds.return_value = (
            "https://app3.manago.ai",
            "client-1",
            "secret",
        )
        mock_list.return_value = {
            "success": True,
            "users": ["a@example.com", "b@example.com"],
        }
        result = load_manago_topology(
            config={"workspace_id": "client-1", "api_key": "enc"}
        )
        self.assertFalse(result.topology_ok)
        self.assertIn("primary owner", result.error or "")

    @patch("dataruns.dcs.topology.list_users_by_client")
    @patch("dataruns.dcs.topology.resolve_manago_credentials")
    def test_multi_owner_with_config_owner_only_passes(self, mock_creds, mock_list):
        mock_creds.return_value = (
            "https://app3.manago.ai",
            "client-1",
            "secret",
        )
        mock_list.return_value = {
            "success": True,
            "users": ["secondary@example.com", "primary@example.com"],
        }
        result = load_manago_topology(
            config={
                "workspace_id": "client-1",
                "api_key": "enc",
                "owner": "primary@example.com",
            },
            shopify_shop_domain="shop.myshopify.com",
        )
        self.assertTrue(result.topology_ok)
        in_scope = [a for a in result.topology_accounts if a.get("in_scope")]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["owner"].lower(), "primary@example.com")

    @patch("dataruns.dcs.topology.list_users_by_client")
    @patch("dataruns.dcs.topology.resolve_manago_credentials")
    def test_multi_owner_without_classification_fails(self, mock_creds, mock_list):
        mock_creds.return_value = (
            "https://app3.manago.ai",
            "client-1",
            "secret",
        )
        mock_list.return_value = {
            "success": True,
            "users": ["a@example.com", "b@example.com"],
        }
        result = load_manago_topology(
            config={
                "workspace_id": "client-1",
                "api_key": "enc",
                "topology": {
                    "accounts": [
                        {
                            "owner": "a@example.com",
                            "classification": "unknown",
                            "in_scope": True,
                        },
                        {
                            "owner": "b@example.com",
                            "classification": "unknown",
                            "in_scope": True,
                        },
                    ]
                },
            }
        )
        self.assertFalse(result.topology_ok)
        self.assertIn("RC-11", result.error or "")

    @patch("dataruns.dcs.topology.list_users_by_client")
    @patch("dataruns.dcs.topology.resolve_manago_credentials")
    def test_list_by_client_failure_fails(self, mock_creds, mock_list):
        mock_creds.return_value = (
            "https://app3.manago.ai",
            "client-1",
            "secret",
        )
        mock_list.side_effect = RuntimeError("timeout")
        result = load_manago_topology(
            config={"workspace_id": "client-1", "api_key": "enc"}
        )
        self.assertFalse(result.topology_ok)
        self.assertIn("listByClient", result.error or "")

    @patch("dataruns.dcs.topology.list_users_by_client")
    @patch("dataruns.dcs.topology.resolve_manago_credentials")
    def test_onboarding_classification_for_multi_account(
        self, mock_creds, mock_list
    ):
        mock_creds.return_value = (
            "https://app3.manago.ai",
            "client-1",
            "secret",
        )
        mock_list.return_value = {
            "success": True,
            "users": ["a@example.com", "b@example.com"],
        }
        result = load_manago_topology(
            config={
                "workspace_id": "client-1",
                "api_key": "enc",
                "topology": {
                    "accounts": [
                        {
                            "owner": "a@example.com",
                            "classification": "geo_variant",
                            "label": "DE",
                            "in_scope": True,
                        },
                        {
                            "owner": "b@example.com",
                            "classification": "segment_variant",
                            "label": "B2B",
                            "in_scope": True,
                        },
                    ]
                },
            }
        )
        self.assertTrue(result.topology_ok)
        in_scope = [a for a in result.topology_accounts if a.get("in_scope")]
        classes = {a["owner"].lower(): a["classification"] for a in in_scope}
        self.assertEqual(classes.get("a@example.com"), "geo_variant")
        self.assertEqual(classes.get("b@example.com"), "segment_variant")

    @patch("dataruns.dcs.topology.list_users_by_client")
    @patch("dataruns.dcs.topology.resolve_manago_credentials")
    def test_single_primary_owner_marks_secondary_out_of_scope(
        self, mock_creds, mock_list
    ):
        mock_creds.return_value = (
            "https://app.manago.ai",
            "client-1",
            "secret",
        )
        mock_list.return_value = {
            "success": True,
            "users": ["secondary@example.com", "primary@example.com"],
        }
        result = load_manago_topology(
            config={
                "workspace_id": "client-1",
                "api_key": "enc",
                "owner": "primary@example.com",
                "topology": {
                    "accounts": [
                        {
                            "owner": "primary@example.com",
                            "in_scope": True,
                            "classification": "single_account",
                            "label": "primary",
                        },
                        {
                            "owner": "secondary@example.com",
                            "in_scope": False,
                        },
                    ]
                },
            },
            shopify_shop_domain="shop.myshopify.com",
        )
        self.assertTrue(result.topology_ok)
        in_scope = [a for a in result.topology_accounts if a.get("in_scope")]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["owner"].lower(), "primary@example.com")
        self.assertEqual(in_scope[0].get("shop_domain"), "shop.myshopify.com")


class EvaluateFd06Tests(SimpleTestCase):
    def test_pass_when_topology_ok_with_accounts(self):
        accounts = [
            {
                "account_id": "c1",
                "owner": "owner@example.com",
                "endpoint": "https://app3.manago.ai",
                "classification": "single_account",
                "in_scope": True,
            }
        ]
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                topology_ok=True,
                topology_accounts=accounts,
            ),
            extra={"manago_topology": {"accounts": accounts, "topology_ok": True}},
        )
        result = evaluate_fd_06(ctx)
        self.assertEqual(result.status, "PASS")
        self.assertTrue(result.evidence)

    def test_fail_rc11_when_topology_not_ok(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                topology_ok=False,
                topology_accounts=[],
            ),
            extra={
                "manago_topology_error": "Multi-account topology lacks Excel classification"
            },
        )
        result = evaluate_fd_06(ctx)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-11")

    def test_does_not_pass_on_bootstrap_summary_alone(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                topology_ok=None,
                topology_accounts=None,
                health_report={"summary_status": "ok", "days": 30},
            )
        )
        result = evaluate_fd_06(ctx)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:topology")
