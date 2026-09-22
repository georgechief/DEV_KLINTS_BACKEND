#!/usr/bin/env python3
"""Static gate for PRD-M3-SEC-01 (RBAC matrix, isolation evidence, security packet).

Phase 1: assert matrix file exists and covers every /api/v1/* family from core/urls.py.
Later phases extend packet, tests, ViewSet scoping, audit evidence, theater register.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILED: list[str] = []

# Families from core/urls.py api/v1 includes (must appear in RBAC matrix).
_API_V1_FAMILIES = (
    "/api/v1/auth/",
    "/api/v1/tenants/",
    "/api/v1/team/",
    "/api/v1/connectors/",
    "/api/v1/dataruns/",
    "/api/v1/dcs/",
    "/api/v1/writebacks/",
    "/api/v1/architecture/",
    "/api/v1/use-cases/",
    "/api/v1/build-packages/",
    "/api/v1/capabilities/",
    "/api/v1/qa-runs/",
    "/api/v1/handoffs/",
    "/api/v1/orchestration/",
    "/api/v1/assessment-reports/",
    "/api/v1/ai/",
    "/api/v1/audit/",
    "/api/v1/search/",
)

_MATRIX_REL = "docs/security/M3_SEC_01_RBAC_MATRIX.md"
_PACKET_REL = "docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md"


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def bad(msg: str) -> None:
    print(f" FAIL {msg}")
    FAILED.append(msg)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        bad(f"missing file: {rel}")
        return ""
    return path.read_text(encoding="utf-8")


def _section_after(text: str, heading_substring: str) -> str:
    """Return markdown body after a ## heading containing heading_substring."""
    pattern = re.compile(
        rf"^##[^\n]*{re.escape(heading_substring)}[^\n]*\n",
        flags=re.I | re.M,
    )
    match = pattern.search(text)
    if not match:
        return ""
    body = text[match.end() :]
    next_h = re.search(r"^##\s+", body, flags=re.M)
    if next_h:
        return body[: next_h.start()]
    return body


def main() -> int:
    print("=== M3-SEC-01 backend verification ===\n")

    # --- Phase 1: RBAC matrix ---
    matrix = read(_MATRIX_REL)
    if matrix:
        ok(f"matrix present: {_MATRIX_REL}")
        for family in _API_V1_FAMILIES:
            # Accept either full prefix or shortened heading form.
            needle = family.rstrip("/")
            if needle in matrix or family in matrix:
                ok(f"matrix covers {family}")
            else:
                bad(f"matrix missing family {family}")

        for marker in ("Admin", "Analyst", "Viewer", "User.Role"):
            if marker in matrix:
                ok(f"matrix mentions {marker}")
            else:
                bad(f"matrix should mention {marker}")

        if "/admin/" in matrix or "Django admin" in matrix:
            ok("matrix documents Django /admin/ separately")
        else:
            bad("matrix must document Django /admin/ as staff path")

        if "TenantViewSet" in matrix and "DataRunViewSet" in matrix:
            ok("matrix flags TenantViewSet / DataRunViewSet")
        else:
            bad("matrix must mention TenantViewSet and DataRunViewSet")

    # --- Phase 5: security review packet (required) ---
    packet_path = ROOT / _PACKET_REL
    packet = ""
    if packet_path.is_file():
        ok(f"packet present: {_PACKET_REL}")
        packet = packet_path.read_text(encoding="utf-8")
        for heading in (
            "## 1. Executive summary",
            "## 2. Control inventory",
            "## 3. RBAC summary",
            "## 4. Isolation summary",
            "## 5. Audit tamper detection",
            "## 6. Findings fixed",
            "## 7. Residual risks",
            "## 8. Theater register",
            "## 9. Employer checklist",
        ):
            # Allow slight heading wording variance via keyword.
            key = heading.split(". ", 1)[-1].split("(")[0].strip().lower()
            if key in packet.lower() or heading in packet:
                ok(f"packet has section: {key}")
            else:
                bad(f"packet missing section: {key}")

        residual = _section_after(packet, "Residual risks")
        if not residual.strip():
            bad("packet Residual risks section is empty")
        else:
            for needle in ("get_user_company", "Grafana", "/admin/", "MCP"):
                if needle in residual:
                    ok(f"residual risks mention {needle}")
                else:
                    bad(f"residual risks must mention {needle}")

        theater = _section_after(packet, "Theater register")
        if not theater.strip():
            bad("packet missing Theater register body")
        else:
            for term in ("pen-test", "SOC2", "DP1"):
                if term.lower() in theater.lower():
                    ok(f"theater register lists {term}")
                else:
                    bad(f"theater register must list forbidden claim term: {term}")

            for banned in (
                "pen-test passed",
                "soc2 certified",
                "iso certified",
                "dp1 live",
            ):
                packet_l = packet.lower()
                theater_l = theater.lower()
                total = packet_l.count(banned)
                if total == 0:
                    continue
                in_theater = theater_l.count(banned)
                if in_theater >= total:
                    ok(f"forbidden phrase '{banned}' confined to theater framing")
                else:
                    bad(f"packet must not claim '{banned}' outside theater register")
    else:
        bad(f"missing security review packet: {_PACKET_REL}")

    isolation_tests = list(
        (ROOT / "dataruns" / "tests").glob("test_m3_sec01_tenant_isolation*.py")
    ) + list(
        (ROOT / "tenants" / "tests").glob("test_m3_sec01_tenant_isolation*.py")
    )
    if isolation_tests:
        ok(f"isolation test modules: {len(isolation_tests)}")
    else:
        bad("missing isolation test modules (test_m3_sec01_tenant_isolation*.py)")

    # Phase notes 0–6 must exist for employer trail.
    for n in range(0, 7):
        rel = f"docs/sahil/M3_SEC_01_PHASE_{n}.md"
        if (ROOT / rel).is_file():
            ok(f"phase note present: PHASE_{n}")
        else:
            bad(f"missing phase note: {rel}")

    if (ROOT / "docs/sahil/M3_SEC_01_WORKING_GAPS.md").is_file():
        ok("WORKING_GAPS present")
    else:
        bad("missing docs/sahil/M3_SEC_01_WORKING_GAPS.md")

    rbac_tests = list(
        (ROOT / "dataruns" / "tests").glob("test_m3_sec01_rbac_negatives*.py")
    ) + list(
        (ROOT / "tenants" / "tests").glob("test_m3_sec01_rbac_negatives*.py")
    )
    if rbac_tests:
        ok(f"RBAC negative test modules: {len(rbac_tests)}")
    else:
        bad("missing RBAC negative test modules (test_m3_sec01_rbac_negatives*.py)")

    # --- Phase 4: audit evidence + critical helpers ---
    audit_doc = "docs/security/M3_SEC_01_AUDIT_EVIDENCE.md"
    audit_text = ""
    if (ROOT / audit_doc).is_file():
        ok(f"audit evidence present: {audit_doc}")
        audit_text = (ROOT / audit_doc).read_text(encoding="utf-8")
        for needle in (
            "verify_audit_chain",
            "0030",
            "verify_audit_chain_for_company",
            "SECRET_CONFIG_FIELDS",
            "test_sanitize_metadata",
        ):
            if needle in audit_text:
                ok(f"audit evidence mentions {needle}")
            else:
                bad(f"audit evidence must mention {needle}")
    else:
        bad(f"missing audit evidence: {audit_doc}")

    rbac_paths = list(
        (ROOT / "dataruns" / "tests").glob("test_m3_sec01_rbac_negatives*.py")
    ) + list(
        (ROOT / "tenants" / "tests").glob("test_m3_sec01_rbac_negatives*.py")
    )
    # Content gate: must exercise viewer 403 + unauth 401 + writeback /run/.
    if rbac_paths:
        rbac_src = "\n".join(p.read_text(encoding="utf-8") for p in rbac_paths)
        for needle, label in (
            ("403", "viewer/wrong-role 403 assertions"),
            ("401", "unauth 401 assertions"),
            ("/api/v1/writebacks/run/", "writeback /run/ negatives"),
            ("/api/v1/writebacks/execute/", "writeback execute negatives"),
            ("/api/v1/dcs/runs/", "DCS runs negatives"),
            ("/api/v1/team/invites/", "team invite negatives"),
            ("/api/v1/assessment-reports/", "report compose/pdf negatives"),
            ("/api/v1/auth/workspace/", "workspace negatives"),
            ("/bootstrap/", "connector bootstrap negatives"),
            ("manago_ai/owners/", "manago owners negatives"),
            ("manago_ai/api-v3-key/", "manago api-v3-key negatives"),
        ):
            if needle in rbac_src:
                ok(f"RBAC negatives cover {label}")
            else:
                bad(f"RBAC negatives missing coverage: {label}")

    if (ROOT / "dataruns/management/commands/verify_audit_chain.py").is_file():
        ok("verify_audit_chain management command present")
    else:
        bad("missing dataruns/management/commands/verify_audit_chain.py")

    if (ROOT / "dataruns/migrations/0030_audit_logs_immutability_triggers.py").is_file():
        ok("migration 0030 audit immutability triggers present")
    else:
        bad("missing migration 0030_audit_logs_immutability_triggers.py")

    audit_py = read("dataruns/audit.py")
    if audit_py and "def verify_audit_chain_for_company" in audit_py:
        ok("verify_audit_chain_for_company helper present")
    else:
        bad("dataruns/audit.py must define verify_audit_chain_for_company")

    auth_services = (ROOT / "tenants/auth/services.py").read_text(encoding="utf-8")
    if "def get_user_company" in auth_services:
        ok("get_user_company helper present")
    else:
        bad("tenants/auth/services.py must define get_user_company")

    wb_views = read("dataruns/writebacks/views.py")
    if wb_views:
        run_block = wb_views.split("class WritebackRunView", 1)[-1].split(
            "\nclass ", 1
        )[0]
        viewer_pos = run_block.find("User.Role.VIEWER")
        missing_pos = run_block.find("_missing_run_keys")
        action_msg_pos = run_block.find("action must be preview")
        if viewer_pos != -1 and missing_pos != -1 and viewer_pos < missing_pos:
            ok("WritebackRunView gates Viewer before required-key validation")
        else:
            bad(
                "WritebackRunView must check Viewer role before _missing_run_keys "
                "(avoid 400 leak to wrong roles)"
            )
        if (
            viewer_pos != -1
            and action_msg_pos != -1
            and viewer_pos < action_msg_pos
        ):
            ok("WritebackRunView gates Viewer before action-name validation")
        else:
            bad(
                "WritebackRunView must check Viewer role before validating action "
                "(avoid teaching action names to Viewer)"
            )

    # --- Phase 3: ViewSet scoping (source) ---
    tenant_views = read("tenants/views.py")
    if tenant_views:
        if "def get_queryset" in tenant_views and "tenant_id" in tenant_views:
            ok("TenantViewSet get_queryset scopes by tenant_id")
        else:
            bad("TenantViewSet must define get_queryset scoped by caller tenant_id")
        if re.search(r"queryset\s*=\s*Tenant\.objects\.all\(\)", tenant_views):
            bad("TenantViewSet must not set queryset = Tenant.objects.all()")
        if "HTTP_403_FORBIDDEN" in tenant_views and "def create" in tenant_views:
            ok("TenantViewSet create returns 403")
        else:
            bad("TenantViewSet create must return 403")
        if "HTTP_403_FORBIDDEN" in tenant_views and "def destroy" in tenant_views:
            ok("TenantViewSet destroy returns 403")
        else:
            bad("TenantViewSet destroy must return 403")
        if "User.Role.ADMIN" in tenant_views and "def update" in tenant_views:
            ok("TenantViewSet update gated to Admin")
        else:
            bad("TenantViewSet update must require Admin (align with workspace)")
        if "User.Role.ADMIN" in tenant_views and "def partial_update" in tenant_views:
            ok("TenantViewSet partial_update gated to Admin")
        else:
            bad("TenantViewSet partial_update must require Admin (align with workspace)")

    tenant_ser = read("tenants/serializers.py")
    if tenant_ser:
        # Grab TenantSerializer through the next top-level class (avoid "class Meta").
        m = re.search(
            r"class TenantSerializer\b.*?(?=\nclass [A-Z]|\Z)",
            tenant_ser,
            flags=re.S,
        )
        block = m.group(0) if m else ""
        ro = ""
        if "read_only_fields" in block:
            ro = block.split("read_only_fields", 1)[-1]
        if '"slug"' in ro or "'slug'" in ro:
            ok("TenantSerializer locks slug as read-only")
        else:
            bad("TenantSerializer must include slug in read_only_fields")
        if '"is_active"' in ro or "'is_active'" in ro:
            ok("TenantSerializer locks is_active as read-only")
        else:
            bad("TenantSerializer must include is_active in read_only_fields")

    datarun_views = read("dataruns/views.py")
    if datarun_views:
        if "def get_queryset" in datarun_views and "filter(" in datarun_views and (
            "tenant_id=tenant_id" in datarun_views.replace(" ", "")
            or "tenant_id=user.tenant_id" in datarun_views.replace(" ", "")
        ):
            ok("DataRunViewSet get_queryset scopes by tenant_id")
        else:
            bad("DataRunViewSet must define get_queryset scoped by caller tenant_id")
        # Foreign ?tenant= filter-by-slug alone is a leak — must be absent.
        if re.search(r"filter\(\s*tenant__slug\s*=", datarun_views):
            bad("DataRunViewSet must not filter by foreign ?tenant= slug")
        elif "ignore" in datarun_views.lower() and "?tenant=" in datarun_views:
            ok("DataRunViewSet documents ignoring foreign ?tenant=")
        else:
            bad("DataRunViewSet must document ignoring foreign ?tenant=")
        if "def perform_create" in datarun_views and "tenant=" in datarun_views:
            ok("DataRunViewSet perform_create forces caller tenant")
        else:
            bad("DataRunViewSet perform_create must force caller tenant")
        if "def perform_update" in datarun_views and "tenant=" in datarun_views:
            ok("DataRunViewSet perform_update forces caller tenant")
        else:
            bad("DataRunViewSet perform_update must force caller tenant")

    datarun_ser = read("dataruns/serializers.py")
    if datarun_ser:
        block = datarun_ser.split("class DataRunSerializer", 1)[-1]
        # Tenant FK must not be a writable serializer field (only read-only tenant_slug).
        fields_m = re.search(r"fields\s*=\s*\((.*?)\)", block, flags=re.S)
        fields_blob = fields_m.group(1) if fields_m else ""
        if re.search(r"""['"]tenant['"]""", fields_blob) and not re.search(
            r"""['"]tenant_slug['"]""", fields_blob
        ):
            bad("DataRunSerializer must not expose writable tenant FK")
        elif '"tenant"' in fields_blob or "'tenant'" in fields_blob:
            bad("DataRunSerializer must not include tenant FK in fields")
        else:
            ok("DataRunSerializer omits tenant FK from fields")
        if "read_only=True" in block or (
            "read_only_fields" in block and "tenant_slug" in block.split(
                "read_only_fields", 1
            )[-1]
        ):
            ok("DataRunSerializer tenant_slug is read-only")
        else:
            bad("DataRunSerializer tenant_slug must be read-only")

    print()
    if FAILED:
        print(f"FAIL — {len(FAILED)} check(s)")
        for item in FAILED:
            print(f"  - {item}")
        return 1

    print("PASS — M3-SEC-01 static gate (Phase 1–5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
