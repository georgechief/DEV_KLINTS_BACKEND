"""Slice B0 — Manago MCP client unit tests (mocked HTTP, no live credentials)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dataruns.capabilities.manago_mcp_client import (
    ManagoMcpClient,
    ManagoMcpConfig,
    ManagoMcpError,
    _classify_tool,
    obtain_client_credentials_token,
    run_read_only_discovery,
)


def _config() -> ManagoMcpConfig:
    return ManagoMcpConfig(
        mcp_url="https://mcp.manago.ai/mcp",
        token_url="https://app.manago.ai/oauth2/mcp/token",
        client_id="test-client-id",
        client_secret="test-client-secret",
        read_scope="mcp.read",
        resource_metadata_url="https://mcp.manago.ai/.well-known/oauth-protected-resource",
        oauth_metadata_url="https://app.manago.ai/.well-known/oauth-authorization-server",
        oauth_issuer="https://app.manago.ai",
        http_timeout_s=5.0,
    )


class ManagoMcpClientTests(unittest.TestCase):
    def test_classify_tool_write_vs_read(self):
        self.assertEqual(_classify_tool("workflow_upsert", "create workflow"), "WRITE")
        self.assertEqual(_classify_tool("list_workflows", "List workflows"), "READ")

    def test_assert_read_only_tool_blocks_write(self):
        client = ManagoMcpClient(_config(), access_token="token")
        with self.assertRaises(ManagoMcpError) as ctx:
            client.assert_read_only_tool("workflow_publish")
        self.assertEqual(ctx.exception.code, "write_tool_blocked")

    @patch("dataruns.capabilities.manago_mcp_client._http_json")
    def test_obtain_client_credentials_token(self, mock_http):
        mock_http.return_value = (
            200,
            {"access_token": "abc", "token_type": "bearer", "scope": "mcp.read"},
            {},
        )
        payload = obtain_client_credentials_token(_config())
        self.assertEqual(payload["access_token"], "abc")
        args, kwargs = mock_http.call_args
        self.assertEqual(kwargs["method"], "POST")
        self.assertIn("Authorization", kwargs["headers"])

    @patch("dataruns.capabilities.manago_mcp_client.ManagoMcpClient.list_tools")
    @patch("dataruns.capabilities.manago_mcp_client.ManagoMcpClient.initialize")
    @patch("dataruns.capabilities.manago_mcp_client.obtain_client_credentials_token")
    @patch("dataruns.capabilities.manago_mcp_client.fetch_oauth_metadata")
    @patch("dataruns.capabilities.manago_mcp_client.fetch_resource_metadata")
    def test_run_read_only_discovery(
        self,
        mock_resource,
        mock_oauth,
        mock_token,
        mock_init,
        mock_tools,
    ):
        from dataruns.capabilities.manago_mcp_client import ManagoMcpToolInfo

        mock_resource.return_value = {"resource": "https://mcp.manago.ai/"}
        mock_oauth.return_value = {"issuer": "https://app.manago.ai"}
        mock_token.return_value = {"access_token": "tok", "token_type": "bearer"}
        mock_init.return_value = {"result": {}}
        mock_tools.return_value = [
            ManagoMcpToolInfo(
                name="list_workflows",
                description="List workflows",
                read_write="READ",
            ),
            ManagoMcpToolInfo(
                name="publish_workflow",
                description="Publish workflow",
                read_write="WRITE",
            ),
        ]
        result = run_read_only_discovery(_config())
        self.assertEqual(result.workflow_read_tools, ["list_workflows"])
        self.assertEqual(result.write_tools_detected, ["publish_workflow"])
        mock_init.assert_called_once()
        mock_tools.assert_called_once()

    @patch("dataruns.capabilities.manago_mcp_client._http_json")
    def test_list_tools_parses_response(self, mock_http):
        mock_http.return_value = (
            200,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {
                            "name": "list_workflows",
                            "description": "List workflows",
                            "inputSchema": {"properties": {"page": {}}},
                        }
                    ]
                },
            },
            {},
        )
        client = ManagoMcpClient(_config(), access_token="token")
        tools = client.list_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "list_workflows")
        self.assertIn("page", tools[0].input_schema_keys)

    @patch("dataruns.capabilities.manago_mcp_client._http_json")
    def test_token_http_error_surfaces_safe_detail(self, mock_http):
        mock_http.side_effect = ManagoMcpError(
            "http_error",
            "invalid_client",
            status=401,
        )
        with self.assertRaises(ManagoMcpError) as ctx:
            obtain_client_credentials_token(_config())
        self.assertEqual(ctx.exception.status, 401)


class ManagoMcpConfigEnvTests(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "MANAGO_MCP_CLIENT_ID": "cid",
            "MANAGO_MCP_CLIENT_SECRET": "sec",
        },
        clear=False,
    )
    def test_from_env(self):
        cfg = ManagoMcpConfig.from_env()
        self.assertEqual(cfg.client_id, "cid")
        self.assertEqual(cfg.read_scope, "mcp.read")

    @patch.dict("os.environ", {}, clear=True)
    def test_from_env_missing_raises(self):
        with self.assertRaises(ValueError):
            ManagoMcpConfig.from_env()


if __name__ == "__main__":
    unittest.main()
