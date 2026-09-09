"""Manago MCP endpoint + OAuth metadata (PRD-GAP-01 Slice B — no secrets in code)."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MANAGO_MCP_URL = "https://mcp.manago.ai/mcp"
DEFAULT_MANAGO_OAUTH_ISSUER = "https://app.manago.ai"
DEFAULT_MANAGO_MCP_RESOURCE = "https://mcp.manago.ai/"
DEFAULT_MANAGO_MCP_TOKEN_URL = f"{DEFAULT_MANAGO_OAUTH_ISSUER}/oauth2/mcp/token"
DEFAULT_MANAGO_MCP_RESOURCE_METADATA_URL = (
    "https://mcp.manago.ai/.well-known/oauth-protected-resource"
)
DEFAULT_MANAGO_OAUTH_METADATA_URL = (
    f"{DEFAULT_MANAGO_OAUTH_ISSUER}/.well-known/oauth-authorization-server"
)
DEFAULT_MANAGO_MCP_READ_SCOPE = "mcp.read"

PACK_DISCOVERY_REL = (
    "Klints_MVP1_Rohan_Build_Pack_v1.2_20260718"
    "/02_Execution_Capabilities/manago_mcp_discovery_results.json"
)


@dataclass(frozen=True)
class ManagoMcpConfig:
    mcp_url: str
    token_url: str
    client_id: str
    client_secret: str
    read_scope: str
    resource_metadata_url: str
    oauth_metadata_url: str
    oauth_issuer: str
    http_timeout_s: float

    @classmethod
    def from_env(cls) -> ManagoMcpConfig:
        client_id = (
            os.environ.get("MANAGO_MCP_CLIENT_ID")
            or os.environ.get("MANAGO_MCP_OAUTH_CLIENT_ID")
            or ""
        ).strip()
        client_secret = (
            os.environ.get("MANAGO_MCP_CLIENT_SECRET")
            or os.environ.get("MANAGO_MCP_OAUTH_CLIENT_SECRET")
            or ""
        ).strip()
        if not client_id or not client_secret:
            raise ValueError(
                "Set MANAGO_MCP_CLIENT_ID and MANAGO_MCP_CLIENT_SECRET in .env "
                "(MCP OAuth app credentials — not the REST apiSecret alone)."
            )
        timeout_raw = os.environ.get("MANAGO_MCP_HTTP_TIMEOUT_S", "30").strip()
        try:
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise ValueError("MANAGO_MCP_HTTP_TIMEOUT_S must be a number.") from exc
        return cls(
            mcp_url=os.environ.get("MANAGO_MCP_URL", DEFAULT_MANAGO_MCP_URL).strip(),
            token_url=os.environ.get(
                "MANAGO_MCP_TOKEN_URL",
                DEFAULT_MANAGO_MCP_TOKEN_URL,
            ).strip(),
            client_id=client_id,
            client_secret=client_secret,
            read_scope=os.environ.get(
                "MANAGO_MCP_READ_SCOPE",
                DEFAULT_MANAGO_MCP_READ_SCOPE,
            ).strip(),
            resource_metadata_url=os.environ.get(
                "MANAGO_MCP_RESOURCE_METADATA_URL",
                DEFAULT_MANAGO_MCP_RESOURCE_METADATA_URL,
            ).strip(),
            oauth_metadata_url=os.environ.get(
                "MANAGO_MCP_OAUTH_METADATA_URL",
                DEFAULT_MANAGO_OAUTH_METADATA_URL,
            ).strip(),
            oauth_issuer=os.environ.get(
                "MANAGO_MCP_OAUTH_ISSUER",
                DEFAULT_MANAGO_OAUTH_ISSUER,
            ).strip(),
            http_timeout_s=timeout,
        )
