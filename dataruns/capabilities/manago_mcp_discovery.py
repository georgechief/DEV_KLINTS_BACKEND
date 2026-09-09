"""Persist Manago MCP discovery evidence (PRD-GAP-01 Slice B1).

Updates pack-shaped manago_mcp_discovery_results.json — does NOT flip matrix_seed.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.conf import settings

from dataruns.capabilities.manago_mcp_client import ManagoMcpDiscoveryResult
from dataruns.capabilities.manago_mcp_config import PACK_DISCOVERY_REL


def default_discovery_path() -> Path:
    return Path(settings.BASE_DIR) / PACK_DISCOVERY_REL


def load_discovery_document(path: Path | None = None) -> dict[str, Any]:
    target = path or default_discovery_path()
    with target.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Discovery document root must be an object.")
    return data


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tool_summaries(tools: list) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tool in tools[:50]:
        rows.append(
            {
                "name": tool.name,
                "read_write": tool.read_write,
                "description": (tool.description or "")[:240],
                "input_schema_keys": tool.input_schema_keys[:20],
            }
        )
    return rows


def build_discovery_update(
    *,
    result: ManagoMcpDiscoveryResult,
    mcp_url: str,
    token_url: str,
    read_scope: str,
) -> dict[str, Any]:
    """Merge discovery run into pack document (no bearer tokens)."""
    verified_at = _iso_now()
    tool_names = [t.name for t in result.tools]
    auth_evidence = {
        "mcp_url": mcp_url,
        "token_url": token_url,
        "read_scope": read_scope,
        "token_type": result.token_type,
        "scope_granted": result.scope,
        "resource_metadata": result.resource_metadata,
        "oauth_metadata": result.oauth_metadata,
        "tool_count": len(result.tools),
        "tool_names": tool_names[:100],
        "workflow_read_tools": result.workflow_read_tools,
        "write_tools_detected": result.write_tools_detected,
        "session_id_present": bool(result.mcp_session_id),
    }
    workflow_list_evidence = {
        "workflow_read_tools": result.workflow_read_tools,
        "tool_count": len(result.tools),
        "tools_sample": _tool_summaries(result.tools)[:15],
    }
    top_status = "EXECUTED_READ_ONLY" if result.tools else "PARTIAL"
    doc = {
        "schema_version": "1.0.0",
        "status": top_status,
        "reason": (
            "Read-only MCP discovery executed from Klints Slice B0/B1. "
            "Matrix MCP.* remains DISCOVERY_REQUIRED until Rohan reviews evidence."
        ),
        "generated_at": verified_at,
        "discovery_run": {
            "executed_at": verified_at,
            "mode": "READ_ONLY",
            "mcp_url": mcp_url,
            "token_url": token_url,
            "tools_listed": len(result.tools),
            "workflow_read_tools": result.workflow_read_tools,
            "write_tools_detected_count": len(result.write_tools_detected),
        },
    }
    tests = []
    for test_id, capability_id in [
        ("MCP-D-01", "MCP.AUTH.DISCOVER"),
        ("MCP-D-02", "MCP.WORKFLOW.LIST"),
        ("MCP-D-15", "MCP.AUTH.DISCOVER"),
    ]:
        if test_id == "MCP-D-02":
            passed = bool(result.workflow_read_tools or result.tools)
            evidence = workflow_list_evidence if passed else {"error": "no_tools_listed"}
            status = "PASSED" if passed else "FAILED"
        else:
            passed = bool(result.tools)
            evidence = auth_evidence if passed else {"error": "token_or_tools_failed"}
            status = "PASSED" if passed else "FAILED"
        tests.append(
            {
                "test_id": test_id,
                "capability_id": capability_id,
                "mode": "READ",
                "status": status,
                "evidence": evidence if passed else evidence,
                "verified_at": verified_at if passed else None,
            }
        )
    # Preserve remaining pack tests as PENDING unless already set.
    doc["tests"] = tests
    return doc


def merge_discovery_document(
    existing: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    """Keep un-run WRITE tests from pack template."""
    merged = deepcopy(existing)
    merged.update(
        {
            k: update[k]
            for k in ("schema_version", "status", "reason", "generated_at", "discovery_run")
            if k in update
        }
    )
    updated_ids = {row["test_id"] for row in update.get("tests", []) if isinstance(row, dict)}
    preserved = [
        row
        for row in existing.get("tests", [])
        if isinstance(row, dict) and row.get("test_id") not in updated_ids
    ]
    merged["tests"] = list(update.get("tests", [])) + preserved
    return merged


def write_discovery_document(
    doc: dict[str, Any],
    *,
    path: Path | None = None,
) -> Path:
    target = path or default_discovery_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return target
