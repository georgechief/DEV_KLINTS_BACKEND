"""Read-only WB-01C verification — possible/not sheet + /run/ contract."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.writebacks.possible_sheet import SHEET_COLUMNS, possible_sheet_payload
from dataruns.writebacks.registry import MappingDisabled, get_check_mapping
from dataruns.writebacks_urls import urlpatterns


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("=== WB-01C BACKEND VERIFICATION ===")

    payload = possible_sheet_payload()
    print(f"source={payload['source']}")
    print(f"count={payload['count']}")
    _assert(payload["schema_version"] == 1, "schema_version must be 1")
    _assert(payload["count"] >= 10, "sheet must have minimum coverage rows")

    rows = payload["rows"]
    _assert(tuple(rows[0].keys()) == SHEET_COLUMNS, "CSV columns must match PRD §2.2")

    # WB-02B runtime path requirement: Docker image excludes `docs/`, so the
    # possible sheet must load from the packaged runtime file.
    _assert(
        str(payload["source"]).replace("\\", "/").startswith("dataruns/writebacks/"),
        "possible sheet source must be the packaged runtime CSV",
    )

    by_check: dict[str, list] = {}
    for row in rows:
        by_check.setdefault(row["check_id"], []).append(row)

    cc03 = by_check["CC-03"][0]
    print(
        f"CC-03 write={cc03['write_possible_today']} "
        f"update={cc03['updates_existing']} rollback={cc03['rollback_possible_today']}"
    )
    _assert(cc03["write_possible_today"] == "yes", "CC-03 must be yes (Settings-gated)")
    _assert(cc03["field_or_key"] == "klints_consent_evidence", "CC-03 field")

    le04 = by_check["LE-04"][0]
    print(f"LE-04 write={le04['write_possible_today']} enabled={le04['registry_enabled']}")
    _assert(le04["write_possible_today"] == "disabled", "LE-04 must be disabled")
    _assert(le04["registry_enabled"] is False, "LE-04 registry_enabled must be false")
    try:
        get_check_mapping("LE-04")
        raise AssertionError("LE-04 get_check_mapping should raise MappingDisabled")
    except MappingDisabled:
        print("LE-04 MappingDisabled: OK")

    for topic in ("SHOPIFY-ORDER", "SHOPIFY-TRANSACTION", "MANAGO-ORDER"):
        _assert(by_check[topic][0]["write_possible_today"] == "no", f"{topic} must be no")
        print(f"{topic} write=no")

    names = {getattr(pattern, "name", None) for pattern in urlpatterns}
    _assert("writeback-possible" in names, "possible/ route missing")
    _assert("writeback-run" in names, "run/ route missing")
    _assert("writeback-preview" in names, "preview/ alias missing")
    _assert("writeback-execute" in names, "execute/ alias missing")
    _assert("writeback-rollback" in names, "rollback/ alias missing")
    print("routes: possible + run + aliases OK")

    print("\nWB-01C backend verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
