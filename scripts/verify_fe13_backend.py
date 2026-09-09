"""Read-only FE-13 backend verification — audit deep-link fields + href resolver."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.audit import extract_audit_link_fields, resolve_audit_href
from dataruns.audit_views import _serialize_audit_event
from dataruns.models import AuditLog
from tenants.models import Company, Tenant


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("=== FE-13 BACKEND VERIFICATION ===")
    print("Bar: audit events expose check_id/package_id/use_case_id/report_id + href\n")

    writeback = resolve_audit_href(
        action="writeback.executed",
        metadata={"check_id": "CC-03"},
    )
    print(f"writeback.executed -> {writeback}")
    _assert(writeback == "/fix?issue=CC-03", "writeback must deep-link to Fix")

    workflow = resolve_audit_href(
        action="workflow.build_package_generated",
        metadata={"package_id": "pkg-1", "use_case_id": "UC-01"},
    )
    print(f"workflow.build_package_generated -> {workflow}")
    _assert(
        workflow == "/workflow?uc=UC-01&package_id=pkg-1",
        "workflow package must deep-link to Studio",
    )

    report = resolve_audit_href(
        action="report.downloaded",
        metadata={"report_id": "rpt-1"},
    )
    print(f"report.downloaded -> {report}")
    _assert(report == "/activity", "report download must deep-link to Activity")

    dcs = resolve_audit_href(
        action="dcs.score_completed",
        metadata={"run_state": "ready"},
        run_id="run-123",
    )
    print(f"dcs.score_completed -> {dcs}")
    _assert(dcs == "/data-consistency#dcs-score", "DCS run must deep-link to Data Consistency")

    connector = resolve_audit_href(
        action="connector.connected",
        metadata={"platform": "shopify"},
    )
    print(f"connector.connected -> {connector}")
    _assert(connector == "/integrations", "connector must deep-link to Integrations")

    explicit = resolve_audit_href(
        action="writeback.executed",
        metadata={"check_id": "CI-01", "href": "/data-consistency?check=CI-01"},
    )
    print(f"explicit href -> {explicit}")
    _assert(explicit == "/data-consistency?check=CI-01", "same-origin href must win")

    fields = extract_audit_link_fields({"object_id": "le-04", "package_id": "pkg-2"})
    print(f"extract_audit_link_fields -> {fields}")
    _assert(fields["check_id"] == "LE-04", "object_id must normalize to check_id")
    _assert(fields.get("job_id") is None, "job_id absent when not in metadata")

    job_fields = extract_audit_link_fields(
        {"check_id": "CC-03", "job_id": "b840ae3f-12e9-428e-a201-e0776bb7fc2d"}
    )
    _assert(
        job_fields["job_id"] == "b840ae3f-12e9-428e-a201-e0776bb7fc2d",
        "job_id extracted from metadata",
    )
    print(f"extract job_id -> {job_fields['job_id']}")

    # Reuse fixture tenant/company — prior runs cannot delete AuditLog (POLISH-01).
    tenant, _ = Tenant.objects.get_or_create(
        slug="fe13-verify",
        defaults={"name": "FE13 Verify"},
    )
    company, _ = Company.objects.get_or_create(
        tenant=tenant,
        domain="fe13-verify.com",
        defaults={"name": "FE13 Verify"},
    )
    import uuid

    entry = AuditLog.objects.create(
        company=company,
        action="writeback.executed",
        tone=AuditLog.Tone.INFO,
        summary="Writeback executed for CC-03",
        performed_by="system",
        metadata={
            "check_id": "CC-03",
            "job_id": "b840ae3f-12e9-428e-a201-e0776bb7fc2d",
        },
        prev_hash="0" * 64,
        entry_hash=uuid.uuid4().hex + uuid.uuid4().hex[:32],
    )
    serialized = _serialize_audit_event(entry)
    print(f"serialized keys -> {sorted(serialized.keys())}")
    for key in ("check_id", "package_id", "use_case_id", "report_id", "job_id", "href"):
        _assert(key in serialized, f"serializer must include {key}")
    _assert(serialized["check_id"] == "CC-03", "serializer check_id")
    _assert(
        serialized["job_id"] == "b840ae3f-12e9-428e-a201-e0776bb7fc2d",
        "serializer job_id",
    )
    _assert(serialized["href"] == "/fix?issue=CC-03", "serializer href")

    # POLISH-01 / M2-OPS-01: audit_logs are immutable (UPDATE/DELETE blocked).
    # Leave the verify fixture rows; do not attempt AuditLog/company cascade delete.
    print(
        "(skip AuditLog cleanup — immutability triggers; "
        f"left company={company.id} tenant={tenant.id})"
    )

    print("\nFE-13 backend verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
