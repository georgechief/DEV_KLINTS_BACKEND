"""Overview Export brief only — DCS legacy PDF unchanged."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.fix_ownership import KLINTS_AUTOMATED_OWNER
from dataruns.models import CheckMaster, DataRun, DimensionMaster
from dataruns.reports.compose import compose_assessment_report
from dataruns.reports.constants import (
    OVERVIEW_BRIEF_TEMPLATE_VERSION,
    REPORT_PROFILE_OVERVIEW_BRIEF,
    TEMPLATE_VERSION,
)
from dataruns.reports.humanize import connector_strip_labels, format_impact_overview
from dataruns.reports.payload import (
    _connector_status_from_foundation_gates,
    build_report_payload,
    parse_report_profile,
)
from dataruns.reports.remediation_ai import (
    compact_suggested_fix_for_pdf,
    format_fix_suggestion_for_pdf,
)
from dataruns.reports.render_overview_brief_pdf import render_overview_brief_pdf
from dataruns.reports.render_pdf import (
    _escape_pdf_cell,
    _remediation_pdf_cell,
    render_assessment_pdf,
)
from tenants.models import Company, Connector, Tenant, User


class OverviewBriefProfileTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Overview Co", slug="overview-co")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Lumera Skin",
            domain="lumera.example.com",
        )
        self.admin = User.objects.create_user(
            email="admin@overview.example.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.now = timezone.now()
        self.dimension = DimensionMaster.objects.create(
            dimension_id="01",
            key="01 Customer Identity",
            name="Customer Identity",
            purpose="",
        )
        CheckMaster.objects.create(
            sequence=9001,
            check_id="LE-04",
            check_name="Duplicate purchase events per order",
            dimension=self.dimension,
            check_class=CheckMaster.CheckClass.RULE_BASED,
            check_type="Consistency",
            role=CheckMaster.Role.SCORED,
            cadence="Daily",
            phase="MVP1-A",
            systems_compared="Shopify / Manago",
            numeric_weight=5,
            severity=CheckMaster.Severity.HIGH,
            root_cause_ids=["RC-04"],
            suggested_fix="Deduplicate PURCHASE events by order externalId.",
            fix_type="Automated writeback",
            fix_owner=KLINTS_AUTOMATED_OWNER,
        )

    def _checks(self):
        return [
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

    def _create_run(self):
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            finished_at=self.now,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 69.28,
                "dcs_run": {
                    "run_state": "INCOMPLETE",
                    "headline_score": 69.28,
                    "check_results": self._checks(),
                },
                "check_results": self._checks(),
                "business_impact": {"currency": "USD", "estimate": 1847.79},
            },
        )

    def test_parse_report_profile(self):
        self.assertEqual(
            parse_report_profile({"report_profile": "overview_brief"}),
            REPORT_PROFILE_OVERVIEW_BRIEF,
        )
        self.assertIsNone(parse_report_profile({}))

    def test_foundation_gates_override_shopify_connector(self):
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="commerce",
            status="connected",
            config={},
        )
        connectors = _connector_status_from_foundation_gates(
            self.company,
            check_results=self._checks(),
        )
        strip = connector_strip_labels(connectors)
        self.assertIn("Shopify not connected", strip)
        self.assertNotIn("Shopify connected", strip)

    @override_settings(AI_ENABLED=True, AI_PROVIDER="mock")
    def test_overview_compose_uses_new_template_and_ai_remediation(self):
        self._create_run()
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={
                "since": (self.now - timedelta(days=14)).isoformat(),
                "until": self.now.isoformat(),
                "report_profile": "overview_brief",
            },
        )
        self.assertEqual(report.template_version, OVERVIEW_BRIEF_TEMPLATE_VERSION)
        ctx = report.payload["content"]["render_context"]
        self.assertEqual(ctx["report_profile"], REPORT_PROFILE_OVERVIEW_BRIEF)
        rem = next(
            row
            for row in report.payload["content"]["remediation"]["items"]
            if row["check_id"] == "LE-04"
        )
        self.assertEqual(rem["source"], "ai")
        self.assertNotEqual(rem["suggested_fix"], "See Data Center for this check")
        pdf = render_overview_brief_pdf(report.payload)
        self.assertTrue(pdf.startswith(b"%PDF"))

    @override_settings(AI_ENABLED=True, AI_PROVIDER="mock")
    def test_legacy_dcs_compose_unchanged_template(self):
        self._create_run()
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={
                "since": (self.now - timedelta(days=14)).isoformat(),
                "until": self.now.isoformat(),
            },
        )
        self.assertEqual(report.template_version, TEMPLATE_VERSION)
        ctx = report.payload["content"]["render_context"]
        self.assertNotIn("report_profile", ctx)
        rem = next(
            row
            for row in report.payload["content"]["remediation"]["items"]
            if row["check_id"] == "LE-04"
        )
        self.assertNotIn("source", rem)
        self.assertIn("Deduplicate", rem["suggested_fix"])
        pdf = render_assessment_pdf(report.payload)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_impact_rounding_overview_only_helper(self):
        self.assertEqual(format_impact_overview(1847.79, "USD"), "USD 1,848")

    @override_settings(AI_ENABLED=True, AI_PROVIDER="mock")
    def test_overview_and_legacy_pdfs_differ(self):
        run = self._create_run()
        window = {
            "since": (self.now - timedelta(days=14)).isoformat(),
            "until": self.now.isoformat(),
        }
        overview = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={**window, "report_profile": "overview_brief"},
        )
        legacy = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body=window,
        )
        overview_pdf = render_overview_brief_pdf(overview.payload)
        legacy_pdf = render_assessment_pdf(legacy.payload)
        self.assertNotEqual(overview_pdf, legacy_pdf)
        self.assertNotEqual(overview.template_version, legacy.template_version)

    def test_fix_suggestion_pdf_copy_is_short_without_ellipsis(self):
        text = format_fix_suggestion_for_pdf(
            {
                "headline": "Duplicate purchase events per order needs attention",
                "suggestions": [
                    {"title": "Review the suggested fix", "detail": "Long detail " * 40},
                    {"title": "Execute automated writeback", "detail": "More detail " * 40},
                ],
            }
        )
        self.assertNotIn("...", text)
        self.assertIn("<br/>", text)
        self.assertIn("1. Review the suggested fix", text)
        self.assertNotIn("Long detail", text)

    def test_compact_legacy_multistep_fix_text(self):
        long_text = (
            "Duplicate purchase events per order needs attention. "
            "1) Review the Duplicate Purchase Events per Order issue in the Data Consistency Center. "
            "2) Execute Automated writeback for missing rows in Shopify."
        )
        compact = compact_suggested_fix_for_pdf(long_text)
        self.assertNotIn("...", compact)
        self.assertIn("<br/>", compact)
        self.assertIn("Execute Automated writeback", compact)

    def test_remediation_pdf_cell_never_truncates_with_dots(self):
        cell = _remediation_pdf_cell("x" * 400)
        self.assertNotIn("...", cell)
        escaped = _escape_pdf_cell(cell, limit=None)
        self.assertNotIn("...", escaped)
