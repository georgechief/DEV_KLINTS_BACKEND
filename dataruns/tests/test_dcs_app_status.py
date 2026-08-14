from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.gates import (
    count_required_blocking_gate_failures,
    is_effectively_blocked,
    load_optional_check_ids,
    partition_gate_failures,
)
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.dcs.status import resolve_dcs_app_status
from dataruns.dcs.views import DcsStatusView
from dataruns.models import DataRun
from tenants.models import Company, Tenant, User


class DcsGateHelperTests(TestCase):
    def test_fd03_is_optional_in_master_options(self):
        self.assertIn("FD-03", load_optional_check_ids())

    def test_partition_gate_failures_splits_optional_fd03(self):
        check_results = [
            {"check_id": "FD-02", "status": "FAIL"},
            {"check_id": "FD-03", "status": "FAIL"},
            {"check_id": "FD-01", "status": "PASS"},
        ]
        required, optional = partition_gate_failures(
            check_results,
            optional_check_ids=load_optional_check_ids(),
        )
        self.assertEqual([item["check_id"] for item in required], ["FD-02"])
        self.assertEqual([item["check_id"] for item in optional], ["FD-03"])

    def test_only_fd03_fail_is_not_effectively_blocked(self):
        check_results = [{"check_id": "FD-03", "status": "FAIL"}]
        self.assertFalse(
            is_effectively_blocked(
                run_state="BLOCKED",
                headline_score=None,
                check_results=check_results,
                optional_check_ids=load_optional_check_ids(),
            )
        )
        self.assertEqual(
            count_required_blocking_gate_failures(
                check_results,
                optional_check_ids=load_optional_check_ids(),
            ),
            0,
        )


class DcsAppStatusTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme.com",
        )
        self.admin = User.objects.create_user(
            email="admin@acme.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.viewer = User.objects.create_user(
            email="viewer@acme.com",
            password="TestPass123!",
            name="Viewer",
            tenant=self.tenant,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )

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

    def test_no_dcs_run_is_hard_locked_no_run(self):
        status = resolve_dcs_app_status(company=self.company)

        self.assertEqual(status["app_access"], "hard_locked")
        self.assertEqual(status["lock_reason"], "no_run")
        self.assertEqual(status["score_display"]["label"], "Not calculated")
        self.assertEqual(
            status["allowed_routes"],
            ["/dashboard", "/integrations", "/settings", "/activity"],
        )

    def test_incomplete_no_headline_is_hard_locked(self):
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "management_command",
                "dcs_run": {
                    "run_state": "INCOMPLETE",
                    "headline_score": None,
                    "blocking_gates_failed": 0,
                },
                "check_results": [],
            },
        )

        status = resolve_dcs_app_status(company=self.company)

        self.assertEqual(status["app_access"], "hard_locked")
        self.assertEqual(status["lock_reason"], "incomplete_no_score")

    def test_required_gate_fail_is_blocked(self):
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "dcs_run": {
                    "run_state": "BLOCKED",
                    "headline_score": None,
                    "blocking_gates_failed": 1,
                },
                "check_results": [
                    {
                        "check_id": "FD-02",
                        "status": "FAIL",
                        "detail": "Missing scopes",
                        "suggested_fix": "Reconnect Shopify",
                        "severity": "critical",
                    }
                ],
            },
        )

        status = resolve_dcs_app_status(company=self.company)

        self.assertEqual(status["app_access"], "hard_locked")
        self.assertEqual(status["lock_reason"], "blocked")
        self.assertEqual(status["issues"][0]["check_id"], "FD-02")
        self.assertFalse(status["issues"][0]["is_optional"])

    def test_issues_include_fix_ownership_from_master(self):
        from dataruns.models import CheckMaster, DimensionMaster

        dimension = DimensionMaster.objects.create(
            dimension_id="00",
            key="00 Foundation Gate",
            name="Foundation Gate",
            purpose="",
        )
        CheckMaster.objects.create(
            sequence=1,
            check_id="FD-02",
            check_name="Shopify API authentication and scopes",
            dimension=dimension,
            check_class=CheckMaster.CheckClass.RULE_BASED,
            check_type="Connectivity",
            role=CheckMaster.Role.GATE,
            cadence="Initial",
            phase="MVP1-A",
            systems_compared="Shopify",
            numeric_weight=0,
            severity=CheckMaster.Severity.CRITICAL,
            root_cause_ids=["RC-12"],
            suggested_fix="Excel suggested fix for Shopify scopes.",
            fix_type="Configuration",
            fix_owner="Klints (automated)",
        )
        CheckMaster.objects.create(
            sequence=6,
            check_id="FD-06",
            check_name="Manago account/sub-account topology mapped",
            dimension=dimension,
            check_class=CheckMaster.CheckClass.RULE_BASED,
            check_type="Connectivity",
            role=CheckMaster.Role.GATE,
            cadence="Initial",
            phase="MVP1-A",
            systems_compared="Manago",
            numeric_weight=0,
            severity=CheckMaster.Severity.HIGH,
            root_cause_ids=["RC-11"],
            suggested_fix="Pick primary Manago owner.",
            fix_type="Configuration",
            fix_owner="Data lead",
            is_optional=False,
        )
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "dcs_run": {
                    "run_state": "BLOCKED",
                    "headline_score": None,
                    "blocking_gates_failed": 2,
                },
                "check_results": [
                    {
                        "check_id": "FD-06",
                        "status": "FAIL",
                        "detail": "Accounts need classification",
                        "severity": "high",
                    },
                    {
                        "check_id": "FD-02",
                        "status": "FAIL",
                        "detail": "Missing scopes",
                        "severity": "critical",
                    },
                ],
            },
        )

        status = resolve_dcs_app_status(company=self.company)
        issues = status["issues"]
        self.assertEqual(len(issues), 2)
        # Klints-owned first
        self.assertEqual(issues[0]["check_id"], "FD-02")
        self.assertTrue(issues[0]["fix_in_klints"])
        self.assertEqual(issues[0]["fix_owner"], "Klints (automated)")
        self.assertEqual(issues[0]["fix_type"], "Configuration")
        self.assertEqual(issues[1]["check_id"], "FD-06")
        self.assertFalse(issues[1]["fix_in_klints"])
        self.assertEqual(issues[1]["fix_owner"], "Data lead")

    def test_only_fd03_fail_with_headline_unlocks(self):
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "dcs_run": {
                    "run_state": "CONDITIONALLY_READY",
                    "headline_score": 84.267,
                    "blocking_gates_failed": 0,
                },
                "check_results": [
                    {
                        "check_id": "FD-03",
                        "status": "FAIL",
                        "detail": "ERP not connected",
                        "severity": "high",
                    }
                ],
            },
        )

        status = resolve_dcs_app_status(company=self.company)

        self.assertEqual(status["app_access"], "unlocked")
        self.assertIsNone(status["lock_reason"])
        self.assertEqual(status["score_display"]["headline_score"], 84.267)
        self.assertEqual(status["allowed_routes"], ["*"])
        self.assertTrue(status["issues"][0]["is_optional"])

    def test_only_fd03_fail_without_headline_is_incomplete_not_blocked(self):
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "dcs_run": {
                    "run_state": "BLOCKED",
                    "headline_score": None,
                    "blocking_gates_failed": 1,
                },
                "check_results": [
                    {
                        "check_id": "FD-03",
                        "status": "FAIL",
                        "detail": "ERP not connected",
                        "severity": "high",
                    }
                ],
            },
        )

        status = resolve_dcs_app_status(company=self.company)

        self.assertEqual(status["app_access"], "hard_locked")
        self.assertEqual(status["lock_reason"], "incomplete_no_score")
        self.assertNotEqual(status["lock_reason"], "blocked")

    def test_failed_run_is_hard_locked_with_synthetic_issue(self):
        self._create_dcs_run(
            status=DataRun.Status.FAILED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "error": "Shopify token expired",
            },
        )

        status = resolve_dcs_app_status(company=self.company)

        self.assertEqual(status["lock_reason"], "failed")
        self.assertEqual(status["issues"][0]["title"], "DCS run failed")
        self.assertIn("Shopify token expired", status["message"])

    def test_active_run_without_score_is_soft_locked(self):
        self._create_dcs_run(
            status=DataRun.Status.RUNNING,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "daily_beat",
            },
        )

        status = resolve_dcs_app_status(company=self.company)

        self.assertEqual(status["app_access"], "soft_locked_running")
        self.assertEqual(status["lock_reason"], "running_no_score")
        self.assertEqual(status["score_display"]["label"], "Calculating…")
        self.assertIsNone(status["latest_run"])
        self.assertEqual(status["active_run"]["status"], "running")

    def test_unlocked_while_scheduled_refresh_in_progress(self):
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "dcs_run": {
                    "run_state": "CONDITIONALLY_READY",
                    "headline_score": 84.267,
                },
            },
        )
        self._create_dcs_run(
            status=DataRun.Status.RUNNING,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "daily_beat",
            },
        )

        status = resolve_dcs_app_status(company=self.company)

        self.assertEqual(status["app_access"], "unlocked")
        self.assertTrue(status["scheduled"])

    def test_viewer_can_get_status_api(self):
        factory = APIRequestFactory()
        request = factory.get("/api/v1/dcs/status/")
        force_authenticate(request, user=self.viewer)
        response = DcsStatusView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("app_access", response.data)

    def test_status_response_does_not_include_secrets(self):
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "error": "access_token=shpat_secret refresh_token=shprt_secret",
            },
            status=DataRun.Status.FAILED,
        )

        status = resolve_dcs_app_status(company=self.company)
        payload = str(status)

        self.assertNotIn("shpat_secret", payload)
        self.assertNotIn("shprt_secret", payload)

    def test_status_issues_include_warn_and_revenue_sort(self):
        self._create_dcs_run(
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "dcs_run": {
                    "run_state": "CONDITIONALLY_READY",
                    "headline_score": 70.0,
                    "dimensions": {
                        "01 Customer Identity": {
                            "score": 80.0,
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
                        "check_id": "CI-01",
                        "status": "FAIL",
                        "severity": "high",
                        "detail": "Contact count",
                        "provenance": {"revenue_impact": 0},
                    },
                    {
                        "check_id": "LE-05",
                        "status": "FAIL",
                        "severity": "critical",
                        "detail": "Event gap",
                        "provenance": {
                            "revenue_impact": 12000.0,
                            "revenue_currency": "EUR",
                        },
                    },
                    {
                        "check_id": "LE-09",
                        "status": "WARN",
                        "severity": "medium",
                        "detail": "Returns",
                        "provenance": {
                            "revenue_impact": 1800.0,
                            "revenue_currency": "EUR",
                        },
                    },
                    {
                        "check_id": "XX-01",
                        "status": "UNKNOWN",
                        "reason_code": "EXECUTOR_NOT_IMPLEMENTED",
                    },
                ],
            },
        )

        status = resolve_dcs_app_status(company=self.company)
        check_ids = [i["check_id"] for i in status["issues"]]
        self.assertEqual(check_ids[:3], ["LE-05", "LE-09", "CI-01"])
        self.assertNotIn("XX-01", check_ids)
        self.assertEqual(status["issues"][0]["revenue_impact"], 12000.0)
        self.assertEqual(status["business_impact"]["estimate"], 12000.0)
        self.assertEqual(status["check_summary"]["FAIL"], 2)
        self.assertEqual(status["check_summary"]["WARN"], 1)
        self.assertIn("01 Customer Identity", status["dimensions"])
        self.assertIn("run_issue_id", status["issues"][0])
        self.assertIn("evidence_preview", status["issues"][0])

    def test_status_dimensions_include_score_delta_and_canonical_order(self):
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        self._create_dcs_run(
            finished_at=now - timedelta(days=2),
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "dcs_run": {
                    "run_state": "COMPLETE",
                    "headline_score": 60.0,
                    "dimensions": {
                        "06 Measurement": {"score": 50.0, "coverage": 1.0, "confidence": 1.0, "weight_percent": 10},
                        "01 Customer Identity": {"score": 80.0, "coverage": 1.0, "confidence": 1.0, "weight_percent": 18},
                    },
                },
            },
        )
        self._create_dcs_run(
            finished_at=now - timedelta(days=1),
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "dcs_run": {
                    "run_state": "COMPLETE",
                    "headline_score": 70.0,
                    "dimensions": {
                        "06 Measurement": {"score": 55.0, "coverage": 1.0, "confidence": 1.0, "weight_percent": 10},
                        "01 Customer Identity": {"score": 95.0, "coverage": 1.0, "confidence": 1.0, "weight_percent": 18},
                    },
                },
            },
        )

        status = resolve_dcs_app_status(company=self.company)
        dimensions = status["dimensions"]
        self.assertEqual(list(dimensions.keys()), ["01 Customer Identity", "06 Measurement"])
        self.assertEqual(dimensions["01 Customer Identity"]["score_delta"], 15)
        self.assertEqual(dimensions["06 Measurement"]["score_delta"], 5)


class DcsHistoryTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="HistCo", slug="histco")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="HistCo",
            domain="histco.com",
        )
        self.admin = User.objects.create_user(
            email="admin@histco.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )

    def _create_scored_run(self, *, score: float, finished_at, metadata_extra: dict | None = None):
        metadata = {
            "kind": DCS_SCORE_KIND,
            "company_id": str(self.company.id),
            "triggered_by": "daily_beat",
            "dcs_run": {
                "run_state": "COMPLETE",
                "headline_score": score,
            },
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            finished_at=finished_at,
            metadata=metadata,
        )

    def test_history_returns_chronological_scored_points(self):
        from datetime import timedelta

        from django.utils import timezone

        from dataruns.dcs.history import build_dcs_score_history
        from dataruns.dcs.views import DcsHistoryView

        now = timezone.now()
        self._create_scored_run(score=65.4, finished_at=now - timedelta(days=3))
        self._create_scored_run(score=71.2, finished_at=now - timedelta(days=1))

        points = build_dcs_score_history(
            company=self.company,
            days=7,
        )
        self.assertEqual(len(points), 2)
        self.assertAlmostEqual(points[0]["score"], 65.4)
        self.assertAlmostEqual(points[1]["score"], 71.2)

        factory = APIRequestFactory()
        request = factory.get("/api/v1/dcs/history/?days=7")
        force_authenticate(request, user=self.admin)
        response = DcsHistoryView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["points"]), 2)
        self.assertIn("value_capture", response.data)
        self.assertEqual(response.data["value_capture"]["revenue"], [])
        self.assertEqual(response.data["value_capture"]["margin"], [])

    def test_history_returns_value_capture_when_persisted(self):
        from datetime import timedelta

        from django.utils import timezone

        from dataruns.dcs.history import build_dcs_value_capture_history

        now = timezone.now()
        self._create_scored_run(
            score=70.0,
            finished_at=now - timedelta(days=2),
            metadata_extra={
                "business_impact": {
                    "revenue_captured": 12500.0,
                    "margin_captured": 3200.0,
                    "currency": "EUR",
                },
            },
        )

        capture = build_dcs_value_capture_history(company=self.company, days=7)
        self.assertEqual(len(capture["revenue"]), 1)
        self.assertEqual(len(capture["margin"]), 1)
        self.assertAlmostEqual(capture["revenue"][0]["value"], 12500.0)
        self.assertAlmostEqual(capture["margin"][0]["value"], 3200.0)

    def test_history_returns_dimension_scores_when_persisted(self):
        from datetime import timedelta

        from django.utils import timezone

        from dataruns.dcs.history import build_dcs_score_history

        now = timezone.now()
        self._create_scored_run(
            score=65.0,
            finished_at=now - timedelta(days=3),
            metadata_extra={
                "dcs_run": {
                    "run_state": "COMPLETE",
                    "headline_score": 65.0,
                    "dimensions": {
                        "01 Customer Identity": {"score": 80.0},
                        "02 Lifecycle Event": {"score": 45.0},
                    },
                },
            },
        )
        self._create_scored_run(
            score=71.0,
            finished_at=now - timedelta(days=1),
            metadata_extra={
                "dcs_run": {
                    "run_state": "COMPLETE",
                    "headline_score": 71.0,
                    "dimensions": {
                        "01 Customer Identity": {"score": 95.0},
                        "02 Lifecycle Event": {"score": 40.0},
                    },
                },
            },
        )

        points = build_dcs_score_history(company=self.company, days=7)
        self.assertEqual(len(points), 2)
        self.assertIn("dimensions", points[0])
        self.assertAlmostEqual(points[0]["dimensions"]["01 Customer Identity"], 80.0)
        self.assertAlmostEqual(points[1]["dimensions"]["02 Lifecycle Event"], 40.0)

    def test_history_orm_window_excludes_runs_outside_days(self):
        from datetime import timedelta

        from django.utils import timezone

        from dataruns.dcs.history import build_dcs_score_history

        now = timezone.now()
        self._create_scored_run(score=50.0, finished_at=now - timedelta(days=100))
        self._create_scored_run(score=65.4, finished_at=now - timedelta(days=3))
        self._create_scored_run(score=71.2, finished_at=now - timedelta(days=1))

        points = build_dcs_score_history(company=self.company, days=7)
        self.assertEqual(len(points), 2)
        self.assertAlmostEqual(points[0]["score"], 65.4)
        self.assertAlmostEqual(points[1]["score"], 71.2)

    def test_build_dcs_histories_uses_single_datarun_query(self):
        from datetime import timedelta

        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from django.utils import timezone

        from dataruns.dcs.history import build_dcs_histories

        now = timezone.now()
        self._create_scored_run(
            score=70.0,
            finished_at=now - timedelta(days=2),
            metadata_extra={
                "business_impact": {
                    "revenue_captured": 1000.0,
                    "margin_captured": 200.0,
                },
            },
        )

        with CaptureQueriesContext(connection) as captured:
            histories = build_dcs_histories(company=self.company, days=7)

        datarun_queries = [
            query
            for query in captured.captured_queries
            if "dataruns_datarun" in query["sql"].lower()
        ]
        self.assertEqual(len(datarun_queries), 1)
        self.assertEqual(len(histories["points"]), 1)
        self.assertEqual(len(histories["value_capture"]["revenue"]), 1)
        self.assertEqual(len(histories["value_capture"]["margin"]), 1)
        self.assertIn("period_compare", histories)
        self.assertIn("at_stake_series", histories)

    def test_resolve_history_fetches_runs_once(self):
        from datetime import timedelta

        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from django.utils import timezone

        from dataruns.dcs.history import resolve_dcs_score_history_for_user

        now = timezone.now()
        self._create_scored_run(score=80.0, finished_at=now - timedelta(days=1))

        with CaptureQueriesContext(connection) as captured:
            payload = resolve_dcs_score_history_for_user(
                user=self.admin,
                days_raw="7",
            )

        datarun_queries = [
            query
            for query in captured.captured_queries
            if "dataruns_datarun" in query["sql"].lower()
        ]
        self.assertEqual(len(datarun_queries), 1)
        self.assertEqual(len(payload["points"]), 1)
        self.assertIn("value_capture", payload)
        self.assertIn("period_compare", payload)
        self.assertIn("at_stake_series", payload)

    def test_history_period_compare_uses_oldest_and_newest_in_window(self):
        from datetime import timedelta

        from django.utils import timezone

        from dataruns.dcs.history import build_dcs_histories

        now = timezone.now()
        self._create_scored_run(
            score=62.0,
            finished_at=now - timedelta(days=10),
            metadata_extra={
                "business_impact": {"estimate": 120000.0, "currency": "EUR"},
                "dcs_run": {
                    "run_state": "COMPLETE",
                    "headline_score": 62.0,
                    "dimensions": {"01 Customer Identity": {"score": 70.0}},
                },
            },
        )
        self._create_scored_run(
            score=71.0,
            finished_at=now - timedelta(days=1),
            metadata_extra={
                "business_impact": {"estimate": 95000.0, "currency": "EUR"},
                "dcs_run": {
                    "run_state": "COMPLETE",
                    "headline_score": 71.0,
                    "dimensions": {"01 Customer Identity": {"score": 78.0}},
                },
            },
        )

        histories = build_dcs_histories(company=self.company, days=14)
        compare = histories["period_compare"]
        self.assertTrue(compare["available"])
        self.assertEqual(compare["run_count"], 2)
        self.assertEqual(compare["deltas"]["headline_score"], 9)
        self.assertEqual(compare["deltas"]["dimensions"]["01 Customer Identity"], 8)
        self.assertEqual(compare["deltas"]["estimate"], -25000)
        self.assertEqual(compare["deltas"]["captured_from_estimate"], 25000)
        self.assertEqual(len(histories["at_stake_series"]), 2)

    def test_history_period_compare_unavailable_with_single_run(self):
        from datetime import timedelta

        from django.utils import timezone

        from dataruns.dcs.history import build_dcs_histories

        now = timezone.now()
        self._create_scored_run(score=70.0, finished_at=now - timedelta(days=1))

        compare = build_dcs_histories(company=self.company, days=7)["period_compare"]
        self.assertFalse(compare["available"])
        self.assertEqual(compare["run_count"], 1)
        self.assertIsNone(compare["deltas"])

    def test_history_honors_until_query_param(self):
        from datetime import timedelta

        from django.utils import timezone
        from rest_framework.test import APIRequestFactory, force_authenticate

        from dataruns.dcs.views import DcsHistoryView

        now = timezone.now()
        until = now - timedelta(days=5)
        since = until - timedelta(days=14)
        self._create_scored_run(score=60.0, finished_at=until - timedelta(days=3))
        self._create_scored_run(score=80.0, finished_at=now - timedelta(days=1))

        factory = APIRequestFactory()
        request = factory.get(
            "/api/v1/dcs/history/",
            {
                "since": since.isoformat().replace("+00:00", "Z"),
                "until": until.isoformat().replace("+00:00", "Z"),
            },
        )
        force_authenticate(request, user=self.admin)
        response = DcsHistoryView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["points"]), 1)
        self.assertAlmostEqual(response.data["points"][0]["score"], 60.0)
        self.assertEqual(response.data["until"][:10], until.isoformat()[:10])
