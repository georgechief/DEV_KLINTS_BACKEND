"""Tests for DCS run progress (PRD-FE-04)."""

from __future__ import annotations

from django.test import TestCase

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.dcs.master import load_check_master_from_json
from dataruns.dcs.run_progress import (
    STAGE_DIMENSION_ORDER,
    build_stage_progress_payload,
)
from dataruns.dcs.status import resolve_dcs_app_status
from dataruns.models import DataRun
from tenants.models import Company, Tenant


class RunProgressHelperTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.master = load_check_master_from_json()

    def test_build_stage_progress_marks_failed_dimension(self):
        payload = build_stage_progress_payload(
            check_results=[
                {"check_id": "FD-01", "status": "PASS"},
                {"check_id": "FD-02", "status": "FAIL"},
                {"check_id": "FD-03", "status": "PASS"},
                {"check_id": "FD-04", "status": "PASS"},
                {"check_id": "FD-05", "status": "PASS"},
                {"check_id": "FD-06", "status": "PASS"},
                {"check_id": "FD-07", "status": "PASS"},
            ],
            current_dimension_id=None,
            run_status="succeeded",
            master=self.master,
        )
        stages = {stage["dimension_id"]: stage for stage in payload["stages"]}
        self.assertEqual(stages["00"]["state"], "failed")
        self.assertEqual(stages["00"]["fail_count"], 1)
        self.assertEqual(stages["01"]["state"], "skipped")

    def test_running_dimension_is_orange_state(self):
        payload = build_stage_progress_payload(
            check_results=[
                {"check_id": f"FD-0{i}", "status": "PASS"}
                for i in range(1, 8)
            ],
            current_dimension_id="01",
            run_status="running",
            master=self.master,
        )
        stages = {stage["dimension_id"]: stage for stage in payload["stages"]}
        self.assertEqual(stages["00"]["state"], "passed")
        self.assertEqual(stages["01"]["state"], "running")
        self.assertEqual(stages["02"]["state"], "pending")

    def test_unknown_status_does_not_fail_dimension(self):
        payload = build_stage_progress_payload(
            check_results=[
                {"check_id": "CI-01", "status": "UNKNOWN"},
                {"check_id": "CI-02", "status": "UNKNOWN"},
                {"check_id": "CI-03", "status": "UNKNOWN"},
                {"check_id": "CI-05", "status": "UNKNOWN"},
            ],
            current_dimension_id=None,
            run_status="succeeded",
            master=self.master,
        )
        stages = {stage["dimension_id"]: stage for stage in payload["stages"]}
        self.assertNotEqual(stages["01"]["state"], "failed")

    def test_stage_catalog_has_eight_dimensions(self):
        payload = build_stage_progress_payload(
            check_results=[],
            current_dimension_id=None,
            run_status="pending",
            master=self.master,
        )
        self.assertEqual(len(payload["stages"]), len(STAGE_DIMENSION_ORDER))


class RunProgressStatusApiTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme.com",
        )

    def _create_dcs_run(self, **kwargs):
        defaults = {
            "tenant": self.tenant,
            "name": DCS_SCORE_DATA_RUN_NAME,
            "status": DataRun.Status.RUNNING,
            "metadata": {
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "stage_progress": {
                    "current_dimension_id": "02",
                    "stages": [
                        {
                            "dimension_id": "00",
                            "key": "foundation",
                            "label": "Foundation Gate",
                            "state": "passed",
                            "fail_count": 0,
                            "warn_count": 0,
                            "check_count": 7,
                            "evaluated_count": 7,
                        },
                        {
                            "dimension_id": "02",
                            "key": "lifecycle",
                            "label": "Lifecycle Event",
                            "state": "running",
                            "fail_count": 0,
                            "warn_count": 0,
                            "check_count": 4,
                            "evaluated_count": 1,
                        },
                    ],
                },
            },
        }
        defaults.update(kwargs)
        return DataRun.objects.create(**defaults)

    def test_no_run_returns_null_run_progress(self):
        status = resolve_dcs_app_status(company=self.company)
        self.assertIsNone(status["run_progress"])

    def test_active_run_exposes_run_progress(self):
        self._create_dcs_run()
        status = resolve_dcs_app_status(company=self.company)

        self.assertEqual(status["app_access"], "soft_locked_running")
        self.assertIsNotNone(status["run_progress"])
        self.assertEqual(status["run_progress"]["data_run_status"], "running")
        self.assertEqual(status["run_progress"]["current_dimension_id"], "02")
        self.assertTrue(status["run_progress"]["stages"])

    def test_terminal_run_derives_progress_from_check_results(self):
        master = load_check_master_from_json()
        foundation_passes = [
            {"check_id": f"FD-0{i}", "status": "PASS"} for i in range(1, 8)
        ]
        foundation_passes[1] = {"check_id": "FD-02", "status": "FAIL"}
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
                "check_results": foundation_passes,
                "dcs_run": {
                    "run_state": "BLOCKED",
                    "headline_score": None,
                    "blocking_gates_failed": 1,
                },
            },
        )

        status = resolve_dcs_app_status(company=self.company)
        stages = {
            stage["dimension_id"]: stage
            for stage in status["run_progress"]["stages"]
        }
        self.assertEqual(stages["00"]["state"], "failed")
