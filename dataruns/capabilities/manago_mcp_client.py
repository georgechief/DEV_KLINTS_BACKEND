"""Thin read-first Manago MCP client (PRD-GAP-01 Slice B0/B2).

No write/mutation tool calls. Never logs secrets or bearer tokens.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dataruns.capabilities.manago_mcp_config import ManagoMcpConfig

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_CLIENT_NAME = "klints-gap01-slice-b"
MCP_CLIENT_VERSION = "0.1.0"

WRITE_TOOL_HINTS = frozenset(
    {
        "upsert",
        "publish",
        "create",
        "update",
        "delete",
        "write",
        "insert",
        "modify",
        "send",
    }
)


class ManagoMcpError(Exception):
    """MCP/OAuth failure with safe detail (no secrets)."""

    def __init__(self, code: str, detail: str, *, status: int | None = None) -> None:
        self.code = code
        self.detail = detail
        self.status = status
        super().__init__(detail)


@dataclass
class ManagoMcpToolInfo:
    name: str
    description: str
    read_write: str  # READ | WRITE | UNKNOWN
    input_schema_keys: list[str] = field(default_factory=list)


@dataclass
class ManagoMcpDiscoveryResult:
    resource_metadata: dict[str, Any]
    oauth_metadata: dict[str, Any]
    token_type: str
    scope: str | None
    tools: list[ManagoMcpToolInfo]
    workflow_read_tools: list[str]
    write_tools_detected: list[str]
    mcp_session_id: str | None = None


def _http_json(
    *,
    method: str,
    url: str,
    timeout_s: float,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | str, dict[str, str]]:
    req_headers = dict(headers or {})
    if body is not None and "Content-Type" not in req_headers:
        req_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=req_headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", errors="replace")
            resp_headers = {k.lower(): v for k, v in response.headers.items()}
            if not raw.strip():
                return response.status, {}, resp_headers
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw, resp_headers
            return response.status, parsed, resp_headers
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        detail = raw
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                detail = str(
                    payload.get("error_description")
                    or payload.get("detail")
                    or payload.get("error")
                    or payload.get("message")
                    or raw
                )
        except json.JSONDecodeError:
            pass
        raise ManagoMcpError(
            "http_error",
            f"{method} {url} failed: {detail}",
            status=exc.code,
        ) from exc
    except URLError as exc:
        raise ManagoMcpError(
            "connection_error",
            f"{method} {url} unreachable: {exc.reason}",
        ) from exc


def fetch_resource_metadata(config: ManagoMcpConfig) -> dict[str, Any]:
    _, payload, _ = _http_json(
        method="GET",
        url=config.resource_metadata_url,
        timeout_s=config.http_timeout_s,
        headers={"Accept": "application/json"},
    )
    if not isinstance(payload, dict):
        raise ManagoMcpError(
            "invalid_metadata",
            "MCP protected-resource metadata is not JSON object.",
        )
    return payload


def fetch_oauth_metadata(config: ManagoMcpConfig) -> dict[str, Any]:
    _, payload, _ = _http_json(
        method="GET",
        url=config.oauth_metadata_url,
        timeout_s=config.http_timeout_s,
        headers={"Accept": "application/json"},
    )
    if not isinstance(payload, dict):
        raise ManagoMcpError(
            "invalid_metadata",
            "OAuth authorization-server metadata is not JSON object.",
        )
    return payload


def obtain_client_credentials_token(config: ManagoMcpConfig) -> dict[str, Any]:
    basic = base64.b64encode(
        f"{config.client_id}:{config.client_secret}".encode("utf-8")
    ).decode("ascii")
    form = (
        f"grant_type=client_credentials&scope={config.read_scope.replace(' ', '%20')}"
    ).encode("utf-8")
    _, payload, _ = _http_json(
        method="POST",
        url=config.token_url,
        timeout_s=config.http_timeout_s,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        body=form,
    )
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise ManagoMcpError(
            "token_error",
            "OAuth token response missing access_token.",
        )
    return payload


def _classify_tool(name: str, description: str) -> str:
    blob = f"{name} {description}".lower()
    if any(hint in blob for hint in WRITE_TOOL_HINTS):
        return "WRITE"
    if "list" in blob or "get" in blob or "read" in blob or "stats" in blob:
        return "READ"
    return "UNKNOWN"


def _parse_tools(payload: dict[str, Any]) -> list[ManagoMcpToolInfo]:
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    tools_raw = result.get("tools")
    if not isinstance(tools_raw, list):
        return []
    tools: list[ManagoMcpToolInfo] = []
    for row in tools_raw:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        description = str(row.get("description") or "").strip()
        schema = row.get("inputSchema")
        keys: list[str] = []
        if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
            keys = sorted(str(k) for k in schema["properties"].keys())
        tools.append(
            ManagoMcpToolInfo(
                name=name,
                description=description,
                read_write=_classify_tool(name, description),
                input_schema_keys=keys,
            )
        )
    return tools


class ManagoMcpClient:
    """Read-first MCP JSON-RPC client."""

    def __init__(self, config: ManagoMcpConfig, *, access_token: str) -> None:
        self._config = config
        self._access_token = access_token
        self._session_id: str | None = None
        self._rpc_id = 0

    @classmethod
    def from_client_credentials(cls, config: ManagoMcpConfig) -> ManagoMcpClient:
        token_payload = obtain_client_credentials_token(config)
        return cls(config, access_token=str(token_payload["access_token"]))

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": method,
                "params": params or {},
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        _, payload, resp_headers = _http_json(
            method="POST",
            url=self._config.mcp_url,
            timeout_s=self._config.http_timeout_s,
            headers=headers,
            body=body,
        )
        session = resp_headers.get("mcp-session-id")
        if session:
            self._session_id = session
        if not isinstance(payload, dict):
            raise ManagoMcpError("invalid_rpc", f"MCP {method} returned non-object.")
        if payload.get("error"):
            err = payload["error"]
            if isinstance(err, dict):
                message = str(err.get("message") or err.get("code") or err)
            else:
                message = str(err)
            raise ManagoMcpError("mcp_rpc_error", f"MCP {method} error: {message}")
        return payload

    def initialize(self) -> dict[str, Any]:
        response = self._rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": MCP_CLIENT_NAME,
                    "version": MCP_CLIENT_VERSION,
                },
            },
        )
        # Best-effort initialized notification (ignore failures).
        try:
            self._rpc("notifications/initialized", {})
        except ManagoMcpError:
            logger.debug("MCP notifications/initialized not acknowledged", exc_info=True)
        return response

    def list_tools(self) -> list[ManagoMcpToolInfo]:
        response = self._rpc("tools/list", {})
        return _parse_tools(response)

    def assert_read_only_tool(self, tool_name: str) -> None:
        name = str(tool_name or "").strip()
        lower = name.lower()
        if any(hint in lower for hint in WRITE_TOOL_HINTS):
            raise ManagoMcpError(
                "write_tool_blocked",
                f"Refusing to call write-class MCP tool {name!r} during read-only discovery.",
            )


def run_read_only_discovery(config: ManagoMcpConfig) -> ManagoMcpDiscoveryResult:
    """B0/B1: metadata + token + initialize + tools/list (READ classification only)."""
    resource_metadata = fetch_resource_metadata(config)
    oauth_metadata = fetch_oauth_metadata(config)
    token_payload = obtain_client_credentials_token(config)
    client = ManagoMcpClient(config, access_token=str(token_payload["access_token"]))
    client.initialize()
    tools = client.list_tools()
    workflow_read_tools = [
        t.name
        for t in tools
        if t.read_write == "READ" and "workflow" in t.name.lower()
    ]
    write_tools = [t.name for t in tools if t.read_write == "WRITE"]
    return ManagoMcpDiscoveryResult(
        resource_metadata=resource_metadata,
        oauth_metadata={
            "issuer": oauth_metadata.get("issuer"),
            "token_endpoint": oauth_metadata.get("token_endpoint"),
            "authorization_endpoint": oauth_metadata.get("authorization_endpoint"),
            "registration_endpoint": oauth_metadata.get("registration_endpoint"),
            "scopes_supported": oauth_metadata.get("scopes_supported"),
        },
        token_type=str(token_payload.get("token_type") or "bearer"),
        scope=str(token_payload.get("scope") or config.read_scope),
        tools=tools,
        workflow_read_tools=workflow_read_tools,
        write_tools_detected=write_tools,
        mcp_session_id=client._session_id,
    )
