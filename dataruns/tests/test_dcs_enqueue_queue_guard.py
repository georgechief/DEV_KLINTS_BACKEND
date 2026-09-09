"""DCS enqueue fail-clean + stale active run unlock."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import (
    DCS_SCORE_DATA_RUN_NAME,
    DcsQueueUnavailableError,
    enqueue_dcs_score,
    fail_stale_active_dcs_runs,
    find_active_dcs_data_run,
)
from dataruns.dcs.status import resolve_dcs_app_status
from dataruns.models import DataRun, Run
from tenants.models import Company, Connector, Tenant


class DcsEnqueueQueueGuardTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Q", slug="q-dcs")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Q Co",
            domain="q-dcs.test",
        )
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="commerce",
            status="connected",
            config={},
        )

    @patch("dataruns.dcs.enqueue.celery_workers_available", return_value=True)
    @patch("dataruns.tasks.run_dcs_score.delay", side_effect=ConnectionError("redis down"))
    def test_queue_failure_marks_run_failed_and_raises(self, _mock_delay, _mock_workers):
        with self.assertRaises(DcsQueueUnavailableError):
            enqueue_dcs_score(self.company, triggered_by="manual", queue=True)

        self.assertIsNone(find_active_dcs_data_run(company=self.company))
        failed = (
            DataRun.objects.filter(
                tenant=self.tenant,
                name=DCS_SCORE_DATA_RUN_NAME,
                status=DataRun.Status.FAILED,
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(failed)
        self.assertIn("worker unavailable", (failed.metadata or {}).get("error", "").lower())

    @patch("dataruns.dcs.enqueue.celery_workers_available", return_value=False)
    def test_no_celery_workers_raises_without_creating_active_run(self, _mock_workers):
        with self.assertRaises(DcsQueueUnavailableError):
            enqueue_dcs_score(self.company, triggered_by="manual", queue=True)

        self.assertIsNone(find_active_dcs_data_run(company=self.company))
        self.assertFalse(
            DataRun.objects.filter(
                tenant=self.tenant,
                name=DCS_SCORE_DATA_RUN_NAME,
            ).exists()
        )

    @patch("dataruns.dcs.enqueue.celery_workers_available", return_value=True)
    def test_manual_rerun_clears_stale_pending_before_enqueue(self, _mock_workers):
        domain = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.RUNNING,
            started_at=timezone.now() - timedelta(seconds=45),
        )
        data_run = DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.PENDING,
            started_at=timezone.now() - timedelta(seconds=45),
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "run_id": str(domain.id),
            },
        )
        DataRun.objects.filter(pk=data_run.pk).update(
            started_at=timezone.now() - timedelta(seconds=45),
            created_at=timezone.now() - timedelta(seconds=45),
        )

        with patch("dataruns.tasks.run_dcs_score.delay") as mock_delay:
            result = enqueue_dcs_score(self.company, triggered_by="manual", queue=True)
            mock_delay.assert_called_once()

        data_run.refresh_from_db()
        self.assertEqual(data_run.status, DataRun.Status.FAILED)
        self.assertIsNotNone(result.data_run)
        self.assertNotEqual(result.data_run.id, data_run.id)
        self.assertEqual(result.data_run.status, DataRun.Status.PENDING)

    def test_fail_stale_active_unlocks_soft_lock(self):
        domain = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=20),
        )
        data_run = DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.PENDING,
            started_at=timezone.now() - timedelta(minutes=20),
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "run_id": str(domain.id),
            },
        )
        # created_at is auto_now_add — force old timestamps via update
        DataRun.objects.filter(pk=data_run.pk).update(
            started_at=timezone.now() - timedelta(minutes=20),
            created_at=timezone.now() - timedelta(minutes=20),
        )

        self.assertIsNotNone(find_active_dcs_data_run(company=self.company))
        failed = fail_stale_active_dcs_runs(company=self.company)
        self.assertIsNotNone(failed)
        data_run.refresh_from_db()
        self.assertEqual(data_run.status, DataRun.Status.FAILED)
        self.assertIsNone(find_active_dcs_data_run(company=self.company))

        status = resolve_dcs_app_status(company=self.company)
        self.assertNotEqual(status["app_access"], "soft_locked_running")

    def test_running_not_stale_at_pending_budget(self):
        """A live RUNNING job at 20m must not be killed by the 10m PENDING budget."""
        domain = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=20),
        )
        data_run = DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=20),
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "run_id": str(domain.id),
            },
        )
        DataRun.objects.filter(pk=data_run.pk).update(
            started_at=timezone.now() - timedelta(minutes=20),
            created_at=timezone.now() - timedelta(minutes=20),
        )
        self.assertIsNone(fail_stale_active_dcs_runs(company=self.company))
        data_run.refresh_from_db()
        self.assertEqual(data_run.status, DataRun.Status.RUNNING)

    def test_running_stale_after_long_budget(self):
        domain = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=50),
        )
        data_run = DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=50),
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "run_id": str(domain.id),
            },
        )
        DataRun.objects.filter(pk=data_run.pk).update(
            started_at=timezone.now() - timedelta(minutes=50),
            created_at=timezone.now() - timedelta(minutes=50),
        )
        self.assertIsNotNone(fail_stale_active_dcs_runs(company=self.company))
        data_run.refresh_from_db()
        self.assertEqual(data_run.status, DataRun.Status.FAILED)
