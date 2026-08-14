"""Tests for DCS worklist APIs (PRD-FE-06 §4 / §8.1)."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.dcs.status import resolve_dcs_app_status
from dataruns.dcs.views import DcsWorklistDetailView, DcsWorklistView
from dataruns.dcs.worklist import (
    build_enriched_issues,
    build_worklist_detail,
    build_worklist_payload,
)
from dataruns.models import DataRun, Run, RunIssue, RunIssueImpact
from tenants.models import Company, Tenant, User


class DcsWorklistTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme-wl")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme-wl.com",
        )
        self.admin = User.objects.create_user(
            email="admin@acme-wl.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.viewer = User.objects.create_user(
            email="viewer@acme-wl.com",
            password="TestPass123!",
            name="Viewer",
            tenant=self.tenant,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )
        self.factory = APIRequestFactory()

    def _create_dcs_run(self, **kwargs):
        defaults = {
            "tenant": self.tenant,
            "name": DCS_SCORE_DATA_RUN_NAME,
            "status": DataRun.Status.SUCCEEDED,
            "metadata": {
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
            },
        }
        defaults.update(kwargs)
        return DataRun.objects.create(**defaults)

    def _seed_run_with_issues(self):
        domain_run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        data_run = self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "run_id": str(domain_run.id),
                "dcs_run": {
                    "run_id": str(domain_run.id),
                    "run_state": "CONDITIONALLY_READY",
                    "headline_score": 72.4,
                    "dimensions": {
                        "01 Customer Identity": {
                            "score": 81.8,
                            "coverage": 1.0,
                            "confidence": 1.0,
                            "weight_percent": 18,
                        }
                    },
                },
                "business_impact": {
                    "currency": "EUR",
                    "estimate": 12000.0,
                    "by_check": {"LE-05": 12000.0},
                    "excluded_from_rollup": {},
                    "window_days": 30,
                    "formula_version": "dcs_revenue_impact.v1",
                    "revenue_mixed_currency": False,
                },
                "check_results": [
                    {
                        "check_id": "LE-05",
                        "status": "FAIL",
                        "severity": "critical",
                        "message": "48 orders missing PURCHASE",
                        "suggested_fix": "Upsert contacts before events",
                        "root_cause_ids": ["RC-01"],
                        "evidence": [
                            {
                                "source": "snapshot",
                                "locator": "lifecycle_join.missing_purchases",
                                "value": {"missing_count": 48},
                                "observed_at": "2026-08-03T09:14:00Z",
                            }
                        ],
                        "provenance": {
                            "revenue_impact": 12000.0,
                            "revenue_currency": "EUR",
                            "revenue_formula_id": "LE-05.missing_purchase_gmv.v1",
                        },
                    },
                    {
                        "check_id": "CI-01",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "Contact count mismatch",
                        "suggested_fix": "Reconcile contacts",
                        "root_cause_ids": ["RC-02"],
                        "provenance": {"revenue_impact": 0},
                    },
                    {
                        "check_id": "LE-09",
                        "status": "WARN",
                        "severity": "medium",
                        "message": "Return gap",
                        "suggested_fix": "Backfill returns",
                        "root_cause_ids": [],
                        "provenance": {
                            "revenue_impact": 1800.0,
                            "revenue_currency": "EUR",
                        },
                    },
                    {
                        "check_id": "CI-99",
                        "status": "PASS",
                        "message": "ok",
                    },
                    {
                        "check_id": "XX-01",
                        "status": "UNKNOWN",
                        "reason_code": "EXECUTOR_NOT_IMPLEMENTED",
                        "message": "stub",
                    },
                    {
                        "check_id": "FD-99",
                        "status": "NOT_CONNECTED",
                        "message": "erp",
                    },
                    {
                        "check_id": "NA-01",
                        "status": "NOT_APPLICABLE",
                        "message": "n/a",
                    },
                    {
                        "check_id": "UN-01",
                        "status": "UNKNOWN",
                        "message": "unknown non-stub",
                    },
                ],
            },
        )

        le05 = RunIssue.objects.create(
            run=domain_run,
            entity_type="dcs_check",
            entity_id=self.company.id,
            issue_type="LE-05",
            severity="Critical",
            details={
                "check_id": "LE-05",
                "status": "FAIL",
                "message": "48 orders missing PURCHASE",
                "suggested_fix": "Upsert contacts before events",
                "root_cause_ids": ["RC-01"],
                "evidence": [
                    {
                        "source": "snapshot",
                        "locator": "lifecycle_join.missing_purchases",
                        "value": {"missing_count": 48, "amount": 12000},
                        "observed_at": "2026-08-03T09:14:00Z",
                    }
                ],
                "matches": [],
                "mismatches": [
                    {
                        "source": "snapshot",
                        "locator": "lifecycle_join.missing_purchases",
                        "value": {"missing_count": 48},
                        "observed_at": "2026-08-03T09:14:00Z",
                    }
                ],
            },
        )
        RunIssueImpact.objects.create(
            run_issue=le05,
            revenue_impact=12000,
            risk_score=1,
        )

        ci01 = RunIssue.objects.create(
            run=domain_run,
            entity_type="dcs_check",
            entity_id=self.company.id,
            issue_type="CI-01",
            severity="High",
            details={
                "check_id": "CI-01",
                "status": "FAIL",
                "message": "Contact count mismatch",
                "suggested_fix": "Reconcile contacts",
                "root_cause_ids": ["RC-02"],
                "evidence": [],
                "matches": [],
                "mismatches": [],
            },
        )
        RunIssueImpact.objects.create(
            run_issue=ci01,
            revenue_impact=0,
            risk_score=0.75,
        )

        le09 = RunIssue.objects.create(
            run=domain_run,
            entity_type="dcs_check",
            entity_id=self.company.id,
            issue_type="LE-09",
            severity="Medium",
            details={
                "check_id": "LE-09",
                "status": "WARN",
                "message": "Return gap",
                "suggested_fix": "Backfill returns",
                "root_cause_ids": [],
                "evidence": [],
                "matches": [],
                "mismatches": [],
            },
        )
        RunIssueImpact.objects.create(
            run_issue=le09,
            revenue_impact=1800,
            risk_score=0.5,
        )
        return data_run, domain_run

    def test_worklist_empty_200_when_no_terminal_run(self):
        payload = build_worklist_payload(company=self.company)
        self.assertIsNone(payload["data_run_id"])
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["issues"], [])

        request = self.factory.get("/api/v1/dcs/worklist/")
        force_authenticate(request, user=self.viewer)
        response = DcsWorklistView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)

    def test_worklist_returns_fail_and_warn_excludes_others(self):
        self._seed_run_with_issues()
        payload = build_worklist_payload(company=self.company)
        check_ids = {issue["check_id"] for issue in payload["issues"]}
        self.assertEqual(check_ids, {"LE-05", "CI-01", "LE-09"})
        statuses = {issue["status"] for issue in payload["issues"]}
        self.assertEqual(statuses, {"FAIL", "WARN"})
        self.assertNotIn("CI-99", check_ids)
        self.assertNotIn("XX-01", check_ids)
        self.assertNotIn("FD-99", check_ids)
        self.assertNotIn("NA-01", check_ids)
        self.assertNotIn("UN-01", check_ids)

    def test_required_before_optional_when_revenue_equal(self):
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "check_results": [
                    {
                        "check_id": "FD-03",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "optional erp",
                        "provenance": {"revenue_impact": 0},
                    },
                    {
                        "check_id": "FD-02",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "required shopify",
                        "provenance": {"revenue_impact": 0},
                    },
                ],
            },
        )
        payload = build_worklist_payload(company=self.company)
        ordered = [issue["check_id"] for issue in payload["issues"]]
        self.assertEqual(ordered[0], "FD-02")
        self.assertEqual(ordered[1], "FD-03")
        self.assertFalse(payload["issues"][0]["is_optional"])
        self.assertTrue(payload["issues"][1]["is_optional"])

    def test_evidence_preview_prefers_mismatches(self):
        domain_run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "dcs_run": {"run_id": str(domain_run.id)},
                "check_results": [
                    {
                        "check_id": "LE-05",
                        "status": "FAIL",
                        "severity": "critical",
                        "message": "gap",
                    }
                ],
            },
        )
        issue = RunIssue.objects.create(
            run=domain_run,
            entity_type="dcs_check",
            entity_id=self.company.id,
            issue_type="LE-05",
            severity="Critical",
            details={
                "check_id": "LE-05",
                "status": "FAIL",
                "mismatches": [
                    {
                        "source": "mismatch-src",
                        "locator": "m1",
                        "value": {"k": 1},
                        "observed_at": "2026-08-03T09:14:00Z",
                    }
                ],
                "evidence": [
                    {
                        "source": "evidence-src",
                        "locator": "e1",
                        "value": {"k": 2},
                        "observed_at": "2026-08-03T09:14:00Z",
                    }
                ],
                "matches": [
                    {
                        "source": "match-src",
                        "locator": "x1",
                        "value": {"k": 3},
                        "observed_at": "2026-08-03T09:14:00Z",
                    }
                ],
            },
        )
        RunIssueImpact.objects.create(
            run_issue=issue, revenue_impact=1, risk_score=1
        )
        payload = build_worklist_payload(company=self.company)
        preview = payload["issues"][0]["evidence_preview"]
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]["source"], "mismatch-src")

    def test_status_issues_capped_at_30(self):
        check_results = [
            {
                "check_id": f"ZZ-{i:02d}",
                "status": "FAIL",
                "severity": "low",
                "message": f"issue {i}",
                "provenance": {"revenue_impact": 0},
            }
            for i in range(35)
        ]
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "dcs_run": {
                    "run_state": "CONDITIONALLY_READY",
                    "headline_score": 70.0,
                },
                "check_results": check_results,
            },
        )
        from dataruns.dcs.status import resolve_dcs_app_status
        from dataruns.dcs.worklist import build_worklist_payload as wl

        status = resolve_dcs_app_status(company=self.company)
        self.assertEqual(len(status["issues"]), 30)
        worklist = wl(company=self.company)
        self.assertEqual(worklist["count"], 35)
        self.assertEqual(len(worklist["issues"]), 35)

    def test_revenue_sort_le05_above_ci01(self):
        self._seed_run_with_issues()
        payload = build_worklist_payload(company=self.company)
        ordered = [issue["check_id"] for issue in payload["issues"]]
        self.assertEqual(ordered[0], "LE-05")
        self.assertEqual(ordered[1], "LE-09")
        self.assertEqual(ordered[2], "CI-01")
        self.assertEqual(payload["issues"][0]["revenue_impact"], 12000.0)
        self.assertEqual(payload["issues"][0]["currency"], "EUR")

    def test_detail_200_has_evidence_with_source_and_observed_at(self):
        self._seed_run_with_issues()
        detail = build_worklist_detail(company=self.company, check_id="LE-05")
        self.assertEqual(detail["check_id"], "LE-05")
        self.assertEqual(detail["status"], "FAIL")
        self.assertEqual(detail["revenue_impact"], 12000.0)
        self.assertEqual(
            detail["revenue_formula_id"], "LE-05.missing_purchase_gmv.v1"
        )
        self.assertTrue(detail["evidence"] or detail["mismatches"])
        row = (detail["mismatches"] or detail["evidence"])[0]
        self.assertIn("source", row)
        self.assertIn("observed_at", row)
        self.assertEqual(row["source"], "snapshot")
        self.assertTrue(row["observed_at"])

        request = self.factory.get("/api/v1/dcs/worklist/LE-05/")
        force_authenticate(request, user=self.viewer)
        response = DcsWorklistDetailView.as_view()(request, check_id="LE-05")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["check_id"], "LE-05")

    def test_detail_404_for_pass_check(self):
        self._seed_run_with_issues()
        request = self.factory.get("/api/v1/dcs/worklist/CI-99/")
        force_authenticate(request, user=self.viewer)
        response = DcsWorklistDetailView.as_view()(request, check_id="CI-99")
        self.assertEqual(response.status_code, 404)

    def test_detail_404_when_no_terminal_run(self):
        request = self.factory.get("/api/v1/dcs/worklist/LE-05/")
        force_authenticate(request, user=self.viewer)
        response = DcsWorklistDetailView.as_view()(request, check_id="LE-05")
        self.assertEqual(response.status_code, 404)

    def test_synthetic_failed_run_issue_in_worklist(self):
        self._create_dcs_run(
            status=DataRun.Status.FAILED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "error": "Shopify token expired",
            },
        )
        payload = build_worklist_payload(company=self.company)
        synthetic = next(
            issue for issue in payload["issues"] if issue["title"] == "DCS run failed"
        )
        self.assertIsNone(synthetic["check_id"])
        self.assertIn("Shopify token expired", synthetic["detail"])

    def test_evidence_preview_capped_at_five(self):
        domain_run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        mismatches = [
            {
                "source": "snapshot",
                "locator": f"row.{i}",
                "value": {"i": i},
                "observed_at": "2026-08-03T09:14:00Z",
            }
            for i in range(8)
        ]
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "dcs_run": {"run_id": str(domain_run.id)},
                "check_results": [
                    {
                        "check_id": "LE-05",
                        "status": "FAIL",
                        "severity": "critical",
                        "message": "many",
                    }
                ],
            },
        )
        issue = RunIssue.objects.create(
            run=domain_run,
            entity_type="dcs_check",
            entity_id=self.company.id,
            issue_type="LE-05",
            severity="Critical",
            details={
                "check_id": "LE-05",
                "status": "FAIL",
                "mismatches": mismatches,
                "evidence": mismatches,
            },
        )
        RunIssueImpact.objects.create(
            run_issue=issue, revenue_impact=1, risk_score=1
        )
        issues = build_enriched_issues(
            data_run=DataRun.objects.filter(
                metadata__company_id=str(self.company.id)
            ).first()
        )
        self.assertEqual(len(issues[0]["evidence_preview"]), 5)

    def test_worklist_viewer_can_access(self):
        self._seed_run_with_issues()
        request = self.factory.get("/api/v1/dcs/worklist/")
        force_authenticate(request, user=self.viewer)
        response = DcsWorklistView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.data["count"], 3)

    def test_worklist_unauthenticated_401(self):
        request = self.factory.get("/api/v1/dcs/worklist/")
        response = DcsWorklistView.as_view()(request)
        self.assertIn(response.status_code, (401, 403))

    def test_status_includes_business_impact_and_warn(self):
        self._seed_run_with_issues()
        status = resolve_dcs_app_status(company=self.company)
        self.assertIsNotNone(status["business_impact"])
        self.assertEqual(status["business_impact"]["estimate"], 12000.0)
        self.assertIsNotNone(status["check_summary"])
        self.assertGreaterEqual(status["check_summary"]["FAIL"], 2)
        self.assertGreaterEqual(status["check_summary"]["WARN"], 1)
        self.assertIsNotNone(status["dimensions"])
        warn_ids = [
            i["check_id"] for i in status["issues"] if i["status"] == "WARN"
        ]
        self.assertIn("LE-09", warn_ids)
        ordered = [i["check_id"] for i in status["issues"] if i["check_id"]]
        self.assertEqual(ordered[0], "LE-05")
