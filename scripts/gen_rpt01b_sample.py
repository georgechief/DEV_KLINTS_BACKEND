"""Generate after-sample PDF for PRD-RPT-01B PR evidence.

Usage:
  .venv\\Scripts\\python.exe manage.py shell < scripts/gen_rpt01b_sample.py
or:
  .venv\\Scripts\\python.exe scripts/gen_rpt01b_sample.py
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from django.utils import timezone

from dataruns.architecture.constants import (
    ARCHITECTURE_ASSESSMENT_DATA_RUN_NAME,
    ARCHITECTURE_ASSESSMENT_KIND,
)
from dataruns.architecture.models import (
    ArchitectureAssessment,
    ArchitectureAsset,
    ArchitectureAssetVerdict,
)
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.fix_ownership import KLINTS_AUTOMATED_OWNER
from dataruns.models import AssessmentReport, CheckMaster, DataRun, DimensionMaster
from dataruns.reports.compose import compose_assessment_report
from dataruns.reports.render_pdf import render_assessment_pdf
from tenants.models import Company, Connector, Tenant, User


def ensure_master(
    *,
    check_id: str,
    name: str,
    suggested: str,
    systems: str,
    sequence: int,
    severity: str = CheckMaster.Severity.MEDIUM,
) -> None:
    row = CheckMaster.objects.filter(check_id=check_id).first()
    if row is None:
        dim = DimensionMaster.objects.filter(dimension_id="02").first()
        if dim is None:
            dim = DimensionMaster.objects.create(
                dimension_id="02",
                key="02 Lifecycle Event",
                name="Lifecycle Event",
                purpose="",
            )
        CheckMaster.objects.create(
            sequence=sequence,
            check_id=check_id,
            check_name=name,
            dimension=dim,
            check_class=CheckMaster.CheckClass.RULE_BASED,
            check_type="Consistency",
            role=CheckMaster.Role.SCORED,
            cadence="Daily",
            phase="MVP1-A",
            systems_compared=systems,
            numeric_weight=3,
            severity=severity,
            root_cause_ids=[],
            suggested_fix=suggested,
            fix_type="Configuration",
            fix_owner="Data lead",
        )
        return
    changed = False
    if not (row.suggested_fix or "").strip():
        row.suggested_fix = suggested
        changed = True
    if not (row.fix_type or "").strip():
        row.fix_type = "Configuration"
        changed = True
    if not (row.fix_owner or "").strip():
        row.fix_owner = "Data lead"
        changed = True
    # Always refresh systems so sample PDF shows Shopify · Manago correctly
    if (row.systems_compared or "").strip() != systems:
        row.systems_compared = systems
        changed = True
    if changed:
        row.save()


def _seed_architecture(*, company: Company, tenant: Tenant, dcs_run: DataRun, now) -> None:
    ArchitectureAssessment.objects.filter(company=company).delete()
    DataRun.objects.filter(tenant=tenant, name=ARCHITECTURE_ASSESSMENT_DATA_RUN_NAME).delete()
    af_run = DataRun.objects.create(
        tenant=tenant,
        name=ARCHITECTURE_ASSESSMENT_DATA_RUN_NAME,
        status=DataRun.Status.SUCCEEDED,
        finished_at=now,
        metadata={
            "kind": ARCHITECTURE_ASSESSMENT_KIND,
            "company_id": str(company.id),
        },
    )
    assessment = ArchitectureAssessment.objects.create(
        company=company,
        tenant=tenant,
        data_run=af_run,
        source_dcs_data_run=dcs_run,
        status=ArchitectureAssessment.Status.SUCCEEDED,
        mode=ArchitectureAssessment.Mode.INCOMPLETE,
        weighted_score=None,
        finished_at=now,
    )
    assets = [
        ("wf-welcome", ArchitectureAsset.AssetType.WORKFLOW, "Welcome series"),
        ("seg-vip", ArchitectureAsset.AssetType.SEGMENT, "VIP buyers"),
        ("prop-ltv", ArchitectureAsset.AssetType.PROPERTY, "Lifetime LTV"),
        ("wf-winback", ArchitectureAsset.AssetType.WORKFLOW, "Winback flow"),
    ]
    for asset_id, asset_type, name in assets:
        ArchitectureAsset.objects.create(
            assessment=assessment,
            asset_id=asset_id,
            asset_type=asset_type,
            name=name,
        )
    ArchitectureAssetVerdict.objects.create(
        assessment=assessment,
        asset_id="wf-welcome",
        verdict=ArchitectureAssetVerdict.Verdict.FIX_FIRST,
    )
    ArchitectureAssetVerdict.objects.create(
        assessment=assessment,
        asset_id="seg-vip",
        verdict=ArchitectureAssetVerdict.Verdict.FIX_FIRST,
    )
    ArchitectureAssetVerdict.objects.create(
        assessment=assessment,
        asset_id="prop-ltv",
        verdict=ArchitectureAssetVerdict.Verdict.KEEP_IMPROVE,
    )
    ArchitectureAssetVerdict.objects.create(
        assessment=assessment,
        asset_id="wf-winback",
        verdict=ArchitectureAssetVerdict.Verdict.KEEP,
    )


def main() -> None:
    slug = "rpt01b-sample"
    tenant = Tenant.objects.filter(slug=slug).first()
    if tenant is None:
        tenant = Tenant.objects.create(name="Lumera Skin Sample", slug=slug)
    company, _ = Company.objects.get_or_create(
        tenant=tenant,
        defaults={"name": "Lumera Skin", "domain": "localhost"},
    )
    company.name = "Lumera Skin"
    company.domain = "localhost"
    company.save(update_fields=["name", "domain"])

    user = User.objects.filter(email="rpt01b@lumera.sample").first()
    if user is None:
        user = User.objects.create_user(
            email="rpt01b@lumera.sample",
            password="TestPass123!",
            name="Sample",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )

    Connector.objects.get_or_create(
        company=company,
        name="manago_ai",
        defaults={"type": "cdp", "status": "connected", "config": {}},
    )
    Connector.objects.get_or_create(
        company=company,
        name="shopify",
        defaults={"type": "ecommerce", "status": "disconnected", "config": {}},
    )

    ensure_master(
        check_id="LE-04",
        name="Duplicate purchase events per order",
        suggested="Deduplicate PURCHASE events by order externalId.",
        systems="Shopify / Manago",
        sequence=204,
        severity=CheckMaster.Severity.HIGH,
    )
    le = CheckMaster.objects.get(check_id="LE-04")
    if le.fix_owner != KLINTS_AUTOMATED_OWNER or not (le.suggested_fix or "").strip():
        le.suggested_fix = le.suggested_fix or "Deduplicate PURCHASE events by order externalId."
        le.fix_owner = KLINTS_AUTOMATED_OWNER
        le.fix_type = "Automated writeback"
        le.save(update_fields=["suggested_fix", "fix_owner", "fix_type", "updated_at"])

    ensure_master(
        check_id="CC-03",
        name="Consent provenance completeness",
        suggested="Backfill consent provenance evidence for unevidenced opt-ins.",
        systems="Manago / Shopify",
        sequence=205,
        severity=CheckMaster.Severity.HIGH,
    )
    ensure_master(
        check_id="CI-13",
        name="Contact state distribution sanity",
        suggested="Investigate dead-state spike; suppress or repair cluster day.",
        systems="Manago",
        sequence=206,
    )
    ensure_master(
        check_id="ME-08",
        name="Baseline computability for impact claims",
        suggested="Extend history window so baseline impact can be computed.",
        systems="Manago",
        sequence=207,
    )
    ensure_master(
        check_id="ME-09",
        name="Email deliverability posture snapshot",
        suggested="Clean damaged contacts and review send reputation.",
        systems="Manago",
        sequence=208,
    )

    now = timezone.now()
    checks = [
        {
            "check_id": "LE-04",
            "status": "FAIL",
            "severity": "high",
            "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
            "provenance": {
                "revenue_impact": 4200.0,
                "revenue_currency": "USD",
            },
        },
        {
            "check_id": "CC-03",
            "status": "FAIL",
            "severity": "high",
            "message": (
                "Unevidenced opt-ins: provenance_share=0.00% weak_or_missing=1/1 "
                "(agent-set / empty consents). shopify_backfill=0 "
                "manago_only_unevidenced=1."
            ),
            "provenance": {
                "revenue_impact": 1850.5,
                "revenue_currency": "USD",
            },
        },
        {
            "check_id": "CI-13",
            "status": "WARN",
            "severity": "medium",
            "message": "Elevated dead-state share=21.4% cluster=True.",
        },
        {
            "check_id": "ME-08",
            "status": "FAIL",
            "severity": "medium",
            "message": "Baseline not computable; gaps=['history'].",
        },
        {
            "check_id": "ME-09",
            "status": "FAIL",
            "severity": "medium",
            "message": "Deliverability posture damaged rate=21.4% dead_share=21.4%.",
        },
        {"check_id": "FD-01", "status": "PASS", "severity": "low", "message": "ok"},
        {
            "check_id": "FD-02",
            "status": "NOT_CONNECTED",
            "severity": "critical",
            "message": "Shopify missing",
        },
        {"check_id": "CI-01", "status": "UNKNOWN", "severity": "medium", "message": "unknown"},
    ]
    for cid in (
        "FD-03",
        "FD-07",
        "CI-02",
        "CI-05",
        "LE-01",
        "LE-02",
        "LE-05",
        "PT-03",
        "SP-08",
        "CC-01",
        "BR-01",
    ):
        status = (
            "NOT_CONNECTED"
            if cid.startswith("FD") or cid.startswith("BR") or cid == "CI-02"
            else "UNKNOWN"
        )
        checks.append(
            {"check_id": cid, "status": status, "severity": "medium", "message": status}
        )
    # A few real PASS rows for healthy appendix (no fake XX-* ids)
    for cid in ("LE-03", "CI-03", "PT-01", "SP-01", "ME-01"):
        checks.append(
            {"check_id": cid, "status": "PASS", "severity": "low", "message": "ok"}
        )

    AssessmentReport.objects.filter(company=company).delete()
    DataRun.objects.filter(tenant=tenant, name=DCS_SCORE_DATA_RUN_NAME).delete()
    dcs_run = DataRun.objects.create(
        tenant=tenant,
        name=DCS_SCORE_DATA_RUN_NAME,
        status=DataRun.Status.SUCCEEDED,
        finished_at=now,
        metadata={
            "kind": DCS_SCORE_KIND,
            "company_id": str(company.id),
            "headline_score": 69.28,
            "dcs_run": {
                "run_state": "INCOMPLETE",
                "headline_score": 69.28,
                "check_results": checks,
            },
            "check_results": checks,
            "business_impact": {"currency": "USD", "estimate": 1847.79},
        },
    )
    _seed_architecture(company=company, tenant=tenant, dcs_run=dcs_run, now=now)

    report = compose_assessment_report(
        company=company,
        user=user,
        body={
            "since": (now - timedelta(days=14)).isoformat(),
            "until": now.isoformat(),
        },
    )
    pdf = render_assessment_pdf(report.payload)
    path = ROOT / "docs/sahil/klints-assessment-lumera-skin-13-2026-08-13-AFTER-RPT01B.pdf"
    path.write_bytes(pdf)

    rem = report.payload["content"]["remediation"]["items"][0]
    arch = report.payload["content"]["architecture"]
    open0 = report.payload["content"]["check_register"]["open_checks"][0]
    print("wrote", path, "bytes", len(pdf))
    print("domain", report.payload["content"]["render_context"]["company_domain"])
    print("banner", bool(report.payload["content"]["dcs"].get("incomplete_banner")))
    print("fix0", rem["suggested_fix"][:100])
    print("whats0", open0["whats_wrong"][:120])
    print("systems0", open0.get("systems"))
    print("impact0", open0.get("revenue_impact"), open0.get("currency"))
    print(
        "arch",
        arch.get("assessed"),
        arch.get("mode"),
        arch.get("incomplete_reason"),
        arch.get("fix_first_assets"),
    )


if __name__ == "__main__":
    main()
