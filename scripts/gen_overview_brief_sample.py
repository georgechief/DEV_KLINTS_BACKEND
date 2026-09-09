"""Generate Overview Export brief proof PDF (DCS legacy unchanged).

Usage:
  python scripts/gen_overview_brief_sample.py
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

from django.test.utils import override_settings
from django.utils import timezone

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import DataRun
from dataruns.reports.compose import compose_assessment_report
from dataruns.reports.constants import TEMPLATE_VERSION
from dataruns.reports.humanize import connector_strip_labels
from dataruns.reports.render_overview_brief_pdf import render_overview_brief_pdf
from dataruns.reports.render_pdf import render_assessment_pdf
from tenants.models import Company, Connector, Tenant, User


def main() -> None:
    tenant, _ = Tenant.objects.get_or_create(
        slug="overview-brief-proof", defaults={"name": "Overview Brief Proof"}
    )
    company, _ = Company.objects.get_or_create(
        tenant=tenant,
        name="Lumera Skin",
        defaults={"domain": "lumera.example.com"},
    )
    admin, _ = User.objects.get_or_create(
        email="overview-brief-proof@example.com",
        defaults={
            "name": "Proof Admin",
            "tenant": tenant,
            "role": User.Role.ADMIN,
            "email_verified": True,
            "is_active": True,
        },
    )

    Connector.objects.update_or_create(
        company=company,
        name="shopify",
        defaults={"type": "commerce", "status": "connected", "config": {}},
    )
    Connector.objects.update_or_create(
        company=company,
        name="manago_ai",
        defaults={"type": "cdp", "status": "connected", "config": {}},
    )

    now = timezone.now()
    checks = [
        {
            "check_id": "LE-04",
            "status": "FAIL",
            "severity": "high",
            "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
        },
        {"check_id": "FD-01", "status": "PASS", "severity": "low", "message": "ok"},
        {
            "check_id": "FD-02",
            "status": "NOT_CONNECTED",
            "severity": "critical",
            "message": "Shopify API authentication and scopes",
        },
    ]
    DataRun.objects.create(
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

    window = {
        "since": (now - timedelta(days=14)).isoformat(),
        "until": now.isoformat(),
    }

    with override_settings(AI_ENABLED=True, AI_PROVIDER="mock"):
        overview = compose_assessment_report(
            company=company,
            user=admin,
            body={**window, "report_profile": "overview_brief"},
        )
        legacy = compose_assessment_report(
            company=company,
            user=admin,
            body=window,
        )

    out_dir = ROOT / "docs" / "sahil"
    out_dir.mkdir(parents=True, exist_ok=True)
    overview_path = out_dir / "klints-overview-brief-proof.pdf"
    legacy_path = out_dir / "klints-dcs-legacy-unchanged-proof.pdf"
    overview_path.write_bytes(
        render_overview_brief_pdf(overview.payload, ai_narratives=overview.ai_narratives)
    )
    legacy_path.write_bytes(render_assessment_pdf(legacy.payload))

    ctx = overview.payload["content"]["render_context"]
    rem = next(
        row
        for row in overview.payload["content"]["remediation"]["items"]
        if row["check_id"] == "LE-04"
    )

    print("=== Overview Export brief (NEW) ===")
    print(f"template={overview.template_version}")
    print(f"profile={ctx.get('report_profile')}")
    print(f"connector_strip={connector_strip_labels(ctx['connector_status'])}")
    print(f"LE-04 source={rem.get('source')}")
    print(f"LE-04 fix={rem.get('suggested_fix')[:120]}...")
    print(f"pdf={overview_path}")

    print("\n=== DCS Export fix plan (LEGACY unchanged) ===")
    print(f"template={legacy.template_version} (expected {TEMPLATE_VERSION})")
    print(f"pdf={legacy_path}")


if __name__ == "__main__":
    main()
