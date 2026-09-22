"""M3-SEC-01 Phase 2 — cross-tenant isolation (dataruns surfaces).

Pattern: Company A owns object → Company B must get 404 (preferred) or empty
lists with zero A rows. Includes positive controls (A can access own objects)
so 404s are not false positives from broken endpoints.

Covered elsewhere (do not duplicate):
- orch: test_orch_sm_phase2.test_wrong_company_not_found
- handoff: test_handoff_package_step6.test_s8_get_other_company_handoff_404
- handoff: test_handoff_package_step4.test_wrong_company_404
- QA/packages: test_qa_api_step5.test_get_wrong_company_404
- reports: test_report_compose.test_api_detail_cross_tenant_404
- reports: test_report_pdf_download_audit.test_cross_tenant_pdf_404
- search: test_search.test_company_isolation
- audit: test_audit.test_company_b_does_not_see_company_a_events
- audit: test_audit.test_company_b_cannot_mark_company_a_event
- pilot-gates: test_pilot_gates_step7.test_evaluate_rejects_other_company_data_run
- connectors disconnect: test_connector_disconnect.test_other_company_connector_not_found
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from dataruns.architecture.constants import ARCHITECTURE_ASSESSMENT_KIND
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import (
    AssessmentReport,
    DataRun,
    Run,
    RunIssue,
    WritebackApprovalToken,
    WritebackJob,
)
from dataruns.tests.helpers_m3_sec01 import make_sec01_tenant_pair
from tenants.models import User


class M3Sec01WritebackIsolationTests(TestCase):
    def setUp(self):
        self.pair = make_sec01_tenant_pair(slug_prefix="sec01-wb")
        self.job = WritebackJob.objects.create(
            company=self.pair.company_a,
            check_id="CI-01",
            mode="dry_run",
            status="succeeded",
            diff_hash="a" * 64,
            actor_user=self.pair.admin_a,
            summary={"matched": 0},
        )
        now = timezone.now()
        self.token = WritebackApprovalToken.objects.create(
            company=self.pair.company_a,
            writeback_job=self.job,
            actor_user=self.pair.admin_a,
            actor_id=str(self.pair.admin_a.id),
            actor_role=User.Role.ADMIN,
            object_id="CI-01",
            object_version="1.0.0",
            diff_hash=self.job.diff_hash,
            status=WritebackApprovalToken.Status.PENDING,
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )

    def test_a_can_get_own_approval(self):
        response = self.pair.client_a.get(
            f"/api/v1/writebacks/approvals/{self.token.id}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data.get("approval_id")), str(self.token.id))

    def test_b_cannot_get_a_approval(self):
        response = self.pair.client_b.get(
            f"/api/v1/writebacks/approvals/{self.token.id}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_b_cannot_approve_a_token(self):
        response = self.pair.client_b.post(
            f"/api/v1/writebacks/approvals/{self.token.id}/approve/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.token.refresh_from_db()
        self.assertEqual(self.token.status, WritebackApprovalToken.Status.PENDING)

    def test_b_cannot_reject_a_token(self):
        response = self.pair.client_b.post(
            f"/api/v1/writebacks/approvals/{self.token.id}/reject/",
            {"reason": "nope"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.token.refresh_from_db()
        self.assertEqual(self.token.status, WritebackApprovalToken.Status.PENDING)

    def test_b_cannot_rollback_a_job(self):
        response = self.pair.client_b.post(
            "/api/v1/writebacks/rollback/",
            {"job_id": str(self.job.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    @override_settings(WRITEBACKS_ENABLED=True)
    def test_b_cannot_execute_with_a_approval_id(self):
        response = self.pair.client_b.post(
            "/api/v1/writebacks/execute/",
            {
                "check_id": "CI-01",
                "diff_hash": self.job.diff_hash,
                "approval_id": str(self.token.id),
            },
            format="json",
        )
        # Fail closed for company B: client error only (not 5xx); A's approval unconsumed.
        self.assertIn(
            response.status_code,
            (400, 403, 404),
            msg=f"expected fail-closed 400/403/404, got {response.status_code} {response.data}",
        )
        self.token.refresh_from_db()
        self.assertIsNone(self.token.consumed_at)
        self.assertEqual(self.token.status, WritebackApprovalToken.Status.PENDING)


class M3Sec01DcsIsolationTests(TestCase):
    def setUp(self):
        self.pair = make_sec01_tenant_pair(slug_prefix="sec01-dcs")
        domain_run = Run.objects.create(
            company=self.pair.company_a,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        now = timezone.now()
        self.data_run_a = DataRun.objects.create(
            tenant=self.pair.tenant_a,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            finished_at=now,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.pair.company_a.id),
                "run_id": str(domain_run.id),
                "headline_score": 61.0,
                "dcs_run": {
                    "run_id": str(domain_run.id),
                    "run_state": "CONDITIONALLY_READY",
                    "headline_score": 61.0,
                    "check_results": [
                        {
                            "check_id": "CC-06",
                            "status": "FAIL",
                            "severity": "high",
                            "message": "Company A only issue",
                        }
                    ],
                },
                "check_results": [
                    {
                        "check_id": "CC-06",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "Company A only issue",
                    }
                ],
            },
        )
        RunIssue.objects.create(
            run=domain_run,
            entity_type="dcs_check",
            entity_id=self.pair.company_a.id,
            issue_type="CC-06",
            severity="High",
            details={
                "check_id": "CC-06",
                "status": "FAIL",
                "message": "Company A only issue",
            },
        )

    def test_a_status_shows_own_run(self):
        response = self.pair.client_a.get("/api/v1/dcs/status/")
        self.assertEqual(response.status_code, 200)
        latest = response.data.get("latest_run")
        self.assertIsInstance(latest, dict)
        self.assertEqual(latest.get("data_run_id"), self.data_run_a.id)

    def test_b_status_does_not_expose_a_run(self):
        response = self.pair.client_b.get("/api/v1/dcs/status/")
        self.assertEqual(response.status_code, 200)
        body = response.data
        self.assertIsNone(body.get("latest_run"))
        # Hard fail if A's run id appears anywhere in the payload.
        self.assertNotIn(str(self.data_run_a.id), str(body))

    def test_a_worklist_has_issue(self):
        response = self.pair.client_a.get("/api/v1/dcs/worklist/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("data_run_id"), self.data_run_a.id)
        check_ids = {
            (i.get("check_id") if isinstance(i, dict) else None)
            for i in (response.data.get("issues") or [])
        }
        self.assertIn("CC-06", check_ids)

    def test_b_worklist_empty_of_a_issues(self):
        response = self.pair.client_b.get("/api/v1/dcs/worklist/")
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data.get("data_run_id"), self.data_run_a.id)
        self.assertEqual(response.data.get("issues") or [], [])
        self.assertNotIn(str(self.data_run_a.id), str(response.data))

    def test_b_worklist_detail_a_check_404(self):
        own = self.pair.client_a.get("/api/v1/dcs/worklist/CC-06/")
        self.assertEqual(own.status_code, 200)
        response = self.pair.client_b.get("/api/v1/dcs/worklist/CC-06/")
        self.assertEqual(response.status_code, 404)

    def test_b_history_excludes_a_points(self):
        own = self.pair.client_a.get("/api/v1/dcs/history/?days=90")
        self.assertEqual(own.status_code, 200)
        own_points = own.data.get("points") or []
        self.assertTrue(own_points, "sanity: company A must have history points")
        own_ids = {
            p.get("data_run_id")
            for p in own_points
            if isinstance(p, dict)
        }
        self.assertIn(self.data_run_a.id, own_ids)

        response = self.pair.client_b.get("/api/v1/dcs/history/?days=90")
        self.assertEqual(response.status_code, 200)
        points = response.data.get("points") or []
        self.assertEqual(points, [])
        self.assertNotIn(str(self.data_run_a.id), str(response.data))


class M3Sec01ArchitectureIsolationTests(TestCase):
    def setUp(self):
        self.pair = make_sec01_tenant_pair(slug_prefix="sec01-af")
        af_run = DataRun.objects.create(
            tenant=self.pair.tenant_a,
            name="Architecture Assessment",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": ARCHITECTURE_ASSESSMENT_KIND,
                "company_id": str(self.pair.company_a.id),
            },
        )
        self.assessment = ArchitectureAssessment.objects.create(
            company=self.pair.company_a,
            tenant=self.pair.tenant_a,
            data_run=af_run,
            status=ArchitectureAssessment.Status.SUCCEEDED,
            mode=ArchitectureAssessment.Mode.AUGMENT,
            weighted_score=Decimal("70.00"),
        )

    def test_a_can_get_own_assessment(self):
        response = self.pair.client_a.get(
            f"/api/v1/architecture/assessments/{self.assessment.id}/"
        )
        self.assertEqual(response.status_code, 200)

    def test_b_cannot_get_a_assessment(self):
        response = self.pair.client_b.get(
            f"/api/v1/architecture/assessments/{self.assessment.id}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_b_cannot_get_a_assessment_subresources(self):
        for suffix in ("coverage", "assets", "graph", "gaps"):
            response = self.pair.client_b.get(
                f"/api/v1/architecture/assessments/{self.assessment.id}/{suffix}/"
            )
            self.assertEqual(
                response.status_code,
                404,
                msg=f"expected 404 for {suffix}, got {response.status_code}",
            )

    def test_b_latest_not_a_assessment(self):
        own = self.pair.client_a.get("/api/v1/architecture/assessments/latest/")
        self.assertEqual(own.status_code, 200)
        own_assessment = own.data.get("assessment")
        self.assertIsInstance(own_assessment, dict)
        self.assertEqual(
            str(own_assessment.get("assessment_id")),
            str(self.assessment.id),
        )

        response = self.pair.client_b.get("/api/v1/architecture/assessments/latest/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data.get("assessment"))
        self.assertNotIn(str(self.assessment.id), str(response.data))


@override_settings(AI_PROVIDER="mock")
class M3Sec01AiIsolationTests(TestCase):
    def setUp(self):
        self.pair = make_sec01_tenant_pair(slug_prefix="sec01-ai")
        self.data_run_a = DataRun.objects.create(
            tenant=self.pair.tenant_a,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            finished_at=timezone.now(),
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.pair.company_a.id),
                "check_results": [
                    {
                        "check_id": "LE-04",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "A-only LE-04",
                    }
                ],
                "dcs_run": {
                    "run_state": "SCORED",
                    "check_results": [
                        {
                            "check_id": "LE-04",
                            "status": "FAIL",
                            "severity": "high",
                            "message": "A-only LE-04",
                        }
                    ],
                },
            },
        )
        self.report_a = AssessmentReport.objects.create(
            company=self.pair.company_a,
            created_by=self.pair.admin_a,
            status=AssessmentReport.Status.READY,
            dcs_data_run=self.data_run_a,
            payload={"content": {"title": "A only"}},
            payload_hash="b" * 64,
            template_version="rpt-1.0.0",
        )

    def test_b_fix_suggestion_with_a_dcs_run_404(self):
        response = self.pair.client_b.post(
            "/api/v1/ai/suggestions/fix/",
            {"check_id": "LE-04", "dcs_run_id": self.data_run_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_b_explain_with_a_dcs_run_404(self):
        response = self.pair.client_b.post(
            "/api/v1/ai/suggestions/explain/",
            {"check_id": "LE-04", "dcs_run_id": self.data_run_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_b_nba_with_a_dcs_run_404(self):
        response = self.pair.client_b.post(
            "/api/v1/ai/suggestions/nba/",
            {"check_id": "LE-04", "dcs_run_id": self.data_run_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_b_report_narrative_with_a_report_404(self):
        response = self.pair.client_b.post(
            "/api/v1/ai/narratives/report/",
            {"assessment_report_id": str(self.report_a.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
