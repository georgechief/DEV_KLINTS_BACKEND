"""PRD-RPT-01B — assessment PDF polish (payload enrichment + humanize + render)."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.fix_ownership import KLINTS_AUTOMATED_OWNER
from dataruns.models import CheckMaster, DataRun, DimensionMaster
from dataruns.reports.compose import compose_assessment_report
from dataruns.reports.humanize import (
    format_customer_title,
    format_display_domain,
    format_generated_at,
    humanize_check_detail,
)
from dataruns.reports.payload import _build_remediation, build_report_payload
from dataruns.reports.render_pdf import render_assessment_pdf
from tenants.models import Company, Connector, Tenant, User


class ReportCopyHumanizeTests(TestCase):
    def test_humanize_duplicate_purchase(self):
        out = humanize_check_detail("Duplicate PURCHASE rate=50.00% clusters=8.")
        self.assertIn("duplicated", out.lower())
        self.assertIn("half", out.lower())
        self.assertIn("8", out)
        self.assertNotIn("rate=", out)

    def test_humanize_gaps_history(self):
        out = humanize_check_detail("Baseline not computable; gaps=['history'].")
        self.assertIn("more history", out.lower())
        self.assertNotIn("gaps=[", out)

    def test_humanize_cluster_true(self):
        out = humanize_check_detail("Elevated dead-state share=21.4% cluster=True.")
        self.assertIn("Dead-state", out)
        self.assertNotIn("cluster=True", out)

    def test_humanize_deliverability(self):
        out = humanize_check_detail(
            "Deliverability posture damaged rate=21.4% dead_share=21.4%."
        )
        self.assertIn("deliverability", out.lower())
        self.assertNotIn("Dead-state contact share", out)

    def test_humanize_provenance(self):
        out = humanize_check_detail(
            "Unevidenced opt-ins: provenance_share=0.00% weak_or_missing=1/1 "
            "(agent-set / empty consents)."
        )
        self.assertIn("Consent", out)
        self.assertNotIn("provenance_share=", out)

    def test_title_case_and_localhost_domain(self):
        self.assertEqual(
            format_customer_title("duplicate purchase events per order"),
            "Duplicate Purchase Events Per Order",
        )
        self.assertIsNone(format_display_domain("localhost"))
        self.assertEqual(format_display_domain("lumera.example.com"), "lumera.example.com")

    def test_generated_at_human(self):
        self.assertEqual(
            format_generated_at("2026-08-12T14:19:46.256531Z"),
            "12 Aug 2026, 14:19 UTC",
        )


class ReportRemediationEnrichmentTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Polish Co", slug="polish-co")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Lumera Skin",
            domain="localhost",
        )
        self.admin = User.objects.create_user(
            email="admin@polish.example.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.now = timezone.now()
        self.dimension = DimensionMaster.objects.create(
            dimension_id="02",
            key="02 Lifecycle Event",
            name="Lifecycle Event",
            purpose="",
        )
        CheckMaster.objects.create(
            sequence=20,
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

    def _create_dcs_run(self, *, score: float = 69.28, state: str = "INCOMPLETE") -> DataRun:
        checks = [
            {
                "check_id": "LE-04",
                "status": "FAIL",
                "severity": "high",
                "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
            },
            {
                "check_id": "ME-08",
                "status": "FAIL",
                "severity": "medium",
                "message": "Baseline not computable; gaps=['history'].",
            },
            {
                "check_id": "FD-01",
                "status": "PASS",
                "severity": "low",
                "message": "ok",
            },
            {
                "check_id": "FD-02",
                "status": "NOT_CONNECTED",
                "severity": "critical",
                "message": "Shopify missing",
            },
            {
                "check_id": "CI-01",
                "status": "UNKNOWN",
                "severity": "medium",
                "message": "unknown",
            },
        ]
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            finished_at=self.now,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": score,
                "dcs_run": {
                    "run_state": state,
                    "headline_score": score,
                    "check_results": checks,
                },
                "check_results": checks,
                "business_impact": {"currency": "USD", "estimate": 1847.79},
            },
        )

    def test_remediation_uses_check_master_not_dashes(self):
        remediation = _build_remediation(
            [
                {
                    "check_id": "LE-04",
                    "title": "Duplicate purchase events per order",
                    "suggested_fix": "",
                    "fix_type": "",
                    "fix_owner": "",
                    "severity": "high",
                    "revenue_impact": 100,
                }
            ],
            master_by_id={
                "LE-04": CheckMaster.objects.get(check_id="LE-04"),
            },
        )
        item = remediation["items"][0]
        self.assertNotEqual(item["suggested_fix"], "-")
        self.assertIn("Deduplicate", item["suggested_fix"])
        self.assertEqual(item["fix_owner"], KLINTS_AUTOMATED_OWNER)
        self.assertEqual(item["fix_type"], "Automated writeback")

    def test_remediation_fallback_when_master_empty(self):
        remediation = _build_remediation(
            [
                {
                    "check_id": "ZZ-99",
                    "title": "Mystery",
                    "suggested_fix": "",
                    "fix_type": None,
                    "fix_owner": None,
                }
            ],
            master_by_id={},
        )
        item = remediation["items"][0]
        self.assertEqual(item["suggested_fix"], "See Data Center for this check")
        self.assertEqual(item["fix_owner"], "See Data Center for this check")

    def test_remediation_rejects_lone_dash_placeholders(self):
        remediation = _build_remediation(
            [
                {
                    "check_id": "ZZ-98",
                    "title": "Dashy",
                    "suggested_fix": "-",
                    "fix_type": "—",
                    "fix_owner": "-",
                }
            ],
            master_by_id={},
        )
        item = remediation["items"][0]
        self.assertEqual(item["suggested_fix"], "See Data Center for this check")
        self.assertEqual(item["fix_type"], "See Data Center for this check")
        self.assertEqual(item["fix_owner"], "See Data Center for this check")

    def test_compose_payload_whats_wrong_and_domain(self):
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config={},
        )
        self._create_dcs_run()
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={
                "since": (self.now - timedelta(days=14)).isoformat(),
                "until": self.now.isoformat(),
            },
        )
        content = report.payload["content"]
        open_rows = content["check_register"]["open_checks"]
        le04 = next(row for row in open_rows if row["check_id"] == "LE-04")
        self.assertIn("dimension", le04)
        self.assertTrue(le04.get("systems"))
        self.assertIn("Manago", le04["systems"])
        self.assertIn("Shopify", le04["systems"])
        self.assertNotIn("rate=", le04["whats_wrong"])
        self.assertIn("duplicated", le04["whats_wrong"].lower())
        self.assertIn("half", le04["whats_wrong"].lower())

        rem = next(
            row for row in content["remediation"]["items"] if row["check_id"] == "LE-04"
        )
        self.assertNotEqual(rem["suggested_fix"].strip(), "-")
        self.assertIn("Deduplicate", rem["suggested_fix"])

        self.assertIsNone(content["render_context"]["company_domain"])
        self.assertTrue(content["dcs"]["incomplete_banner"])
        self.assertTrue(
            any(c["key"] == "manago" and c["status"] == "connected" for c in content["render_context"]["connector_status"])
        )

        pdf = render_assessment_pdf(report.payload)
        self.assertTrue(pdf.startswith(b"%PDF"))
        # Extractable text sanity: remediation must not be dash-only for LE-04
        # (ReportLab stores strings; soft check via payload already done above)
        self.assertGreater(len(pdf), 800)

    def test_pdf_what_to_fix_not_dashes_from_payload(self):
        payload = build_report_payload(
            report_id=__import__("uuid").uuid4(),
            company=self.company,
            dcs_run=self._create_dcs_run(),
            architecture_assessment=None,
            open_issues=[
                {
                    "check_id": "LE-04",
                    "title": "duplicate purchase events per order",
                    "status": "FAIL",
                    "severity": "high",
                    "detail": "Duplicate PURCHASE rate=50.00% clusters=8.",
                    "suggested_fix": "",
                    "fix_type": "",
                    "fix_owner": "",
                    "systems_compared": "Shopify / Manago",
                    "revenue_impact": 500.0,
                    "currency": "USD",
                    "root_cause_ids": [],
                }
            ],
            plan_tasks=[],
            created_by_email=self.admin.email,
            period_from="2026-07-29",
            period_to="2026-08-12",
        )
        rem = payload["content"]["remediation"]["items"][0]
        self.assertNotIn(rem["suggested_fix"], {"", "-"})
        self.assertNotIn(rem["fix_owner"], {"", "-"})
        self.assertNotIn(rem["fix_type"], {"", "-"})
        self.assertIsNone(payload["content"]["render_context"]["company_domain"])
        pdf = render_assessment_pdf(payload)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_systems_falls_back_to_check_master_when_issue_blank(self):
        from dataruns.reports.payload import _build_check_register

        master = CheckMaster.objects.get(check_id="LE-04")
        register = _build_check_register(
            check_results=[
                {
                    "check_id": "LE-04",
                    "status": "FAIL",
                    "severity": "high",
                    "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
                }
            ],
            open_issues=[
                {
                    "check_id": "LE-04",
                    "title": "Duplicate purchase events per order",
                    "status": "FAIL",
                    "severity": "high",
                    "detail": "Duplicate PURCHASE rate=50.00% clusters=8.",
                    "systems_compared": "",
                    "revenue_impact": 4200.0,
                    "currency": "USD",
                }
            ],
            plan_tasks=[],
            master_by_id={"LE-04": master},
        )
        row = register["open_checks"][0]
        self.assertIn("Shopify", row["systems"])
        self.assertIn("Manago", row["systems"])
        self.assertTrue(row.get("dimension"))
        self.assertEqual(row.get("revenue_impact"), 4200.0)

    def test_architecture_incomplete_reason_when_mode_incomplete(self):
        from dataruns.reports.payload import _architecture_content
        from dataruns.architecture.models import ArchitectureAssessment
        from dataruns.architecture.constants import (
            ARCHITECTURE_ASSESSMENT_DATA_RUN_NAME,
            ARCHITECTURE_ASSESSMENT_KIND,
        )

        af_run = DataRun.objects.create(
            tenant=self.tenant,
            name=ARCHITECTURE_ASSESSMENT_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            finished_at=self.now,
            metadata={"kind": ARCHITECTURE_ASSESSMENT_KIND, "company_id": str(self.company.id)},
        )
        assessment = ArchitectureAssessment.objects.create(
            company=self.company,
            tenant=self.tenant,
            data_run=af_run,
            status=ArchitectureAssessment.Status.SUCCEEDED,
            mode=ArchitectureAssessment.Mode.INCOMPLETE,
            weighted_score=None,
        )
        content = _architecture_content(assessment)
        self.assertTrue(content["assessed"])
        self.assertEqual(content["mode"], "INCOMPLETE")
        self.assertIsNotNone(content["incomplete_reason"])
        self.assertIn("incomplete", content["incomplete_reason"].lower())
