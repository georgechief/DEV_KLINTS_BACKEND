"""
PRD-GAP-01 Slice B0/B1 — Manago MCP credential check + read-only discovery.

Run from klints_backend (requires .env credentials — never commit secrets):

  python scripts/run_manago_mcp_b0_discovery.py
  python scripts/run_manago_mcp_b0_discovery.py --write-evidence

Required .env:
  MANAGO_MCP_CLIENT_ID=...
  MANAGO_MCP_CLIENT_SECRET=...
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.capabilities.manago_mcp_client import (  # noqa: E402
    ManagoMcpError,
    run_read_only_discovery,
)
from dataruns.capabilities.manago_mcp_config import (  # noqa: E402
    ManagoMcpConfig,
    PACK_DISCOVERY_REL,
)
from dataruns.capabilities.manago_mcp_discovery import (  # noqa: E402
    build_discovery_update,
    default_discovery_path,
    load_discovery_document,
    merge_discovery_document,
    write_discovery_document,
)


def _print_safe_summary(result) -> None:
    print("\n  MCP discovery summary (no secrets)")
    print(f"  tools listed: {len(result.tools)}")
    if result.workflow_read_tools:
        print(f"  workflow READ tools: {', '.join(result.workflow_read_tools)}")
    else:
        print("  workflow READ tools: (none matched by name)")
    if result.write_tools_detected:
        print(
            "  write-class tools detected (NOT called): "
            + ", ".join(result.write_tools_detected[:10])
        )
    for tool in result.tools[:20]:
        desc = (tool.description or "")[:80].replace("\n", " ")
        print(f"    - {tool.name} [{tool.read_write}] {desc}")
    if len(result.tools) > 20:
        print(f"    ... +{len(result.tools) - 20} more")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manago MCP B0/B1 read-only discovery")
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help=f"Persist evidence to pack {PACK_DISCOVERY_REL}",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Optional alternate discovery JSON output path",
    )
    args = parser.parse_args()

    print("\nGAP-01 Slice B0 — Manago MCP credential + read-only discovery\n")

    try:
        config = ManagoMcpConfig.from_env()
    except ValueError as exc:
        print(f"  [BLOCKED] {exc}")
        print("\n  Add to klints_backend/.env (do not commit):")
        print("    MANAGO_MCP_CLIENT_ID=<mcp-oauth-client-id>")
        print("    MANAGO_MCP_CLIENT_SECRET=<mcp-oauth-client-secret>")
        print("  Optional: MANAGO_MCP_URL, MANAGO_MCP_TOKEN_URL, MANAGO_MCP_READ_SCOPE")
        return 1

    print(f"  MCP URL: {config.mcp_url}")
    print(f"  Token URL: {config.token_url}")
    print(f"  Read scope: {config.read_scope}")
    print(f"  Client ID: {config.client_id[:4]}…{config.client_id[-4:]}" if len(config.client_id) > 8 else "  Client ID: (set)")

    try:
        result = run_read_only_discovery(config)
    except ManagoMcpError as exc:
        print(f"\n  [FAIL] B0 blocked — {exc.code}: {exc.detail}")
        if exc.status == 401:
            print(
                "\n  Hint: credentials may be REST API v2 keys, not MCP OAuth app keys."
            )
            print("  Try Cursor MCP OAuth, or ask Manago for MCP OAuth client credentials.")
        return 1

    _print_safe_summary(result)

    if not result.tools:
        print("\n  [FAIL] B0 — token OK but no MCP tools returned.")
        return 1

    print("\n  [ok] B0 PASS — MCP OAuth + tools/list succeeded (read-only).")

    if args.write_evidence:
        out_path = Path(args.output).resolve() if args.output else default_discovery_path()
        existing = load_discovery_document(out_path) if out_path.is_file() else {"tests": []}
        update = build_discovery_update(
            result=result,
            mcp_url=config.mcp_url,
            token_url=config.token_url,
            read_scope=config.read_scope,
        )
        merged = merge_discovery_document(existing, update)
        write_discovery_document(merged, path=out_path)
        print(f"\n  [ok] B1 evidence written: {out_path}")
        print("  Matrix MCP.* remains DISCOVERY_REQUIRED (no CONFIRMED_LIVE flip).")
    else:
        print("\n  Re-run with --write-evidence to persist B1 pack evidence.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
