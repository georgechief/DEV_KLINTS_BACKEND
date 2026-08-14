"""DCS-10 consecutive run-diff tests."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.run_diff import (
    build_consecutive_run_diff,
    format_audit_at_stake_meta,
    format_audit_score_summary,
    persist_consecutive_run_diff,
)
from dataruns.models import AuditLog, DataRun
from tenants.models import Company, Tenant


class RunDiffTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="DiffCo", slug="diffco")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="DiffCo",
            domain="diffco.com",
        )

    def _metadata(
        self,
        *,
        score: float,
        dimensions: dict | None = None,
        estimate: float | None = None,
        check_results: list | None = None,
        blocking_gates_failed: int = 0,
    ) -> dict:
        metadata = {
            "kind": DCS_SCORE_KIND,
            "company_id": str(self.company.id),
            "triggered_by": "manual",
            "dcs_run": {
                "run_state": "COMPLETE",
                "headline_score": score,
                "blocking_gates_failed": blocking_gates_failed,
            },
            "check_results": check_results
            or [
                {"check_id": "CI-01", "status": "PASS"},
                {"check_id": "CI-02", "status": "FAIL"},
            ],
        }
        if dimensions is not None:
            metadata["dcs_run"]["dimensions"] = dimensions
        if estimate is not None:
            metadata["business_impact"] = {
                "estimate": estimate,
                "currency": "EUR",
            }
        return metadata

    def _create_scored_run(self, *, score: float, finished_at, metadata: dict) -> DataRun:
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            finished_at=finished_at,
            metadata=metadata,
        )

    def test_first_run_is_baseline(self):
        now = timezone.now()
        current = self._create_scored_run(
            score=70.0,
            finished_at=now,
            metadata=self._metadata(score=70.0),
        )

        run_diff = persist_consecutive_run_diff(company=self.company, data_run=current)

        self.assertIsNotNone(run_diff)
        assert run_diff is not None
        self.assertTrue(run_diff["baseline"])
        self.assertIsNone(run_diff["headline_score"])

    def test_second_run_has_consecutive_deltas(self):
        now = timezone.now()
        previous = self._create_scored_run(
            score=62.0,
            finished_at=now - timedelta(days=2),
            metadata=self._metadata(
                score=62.0,
                dimensions={"01 Customer Identity": {"score": 70.0}},
                estimate=120000.0,
                check_results=[
                    {"check_id": "CI-01", "status": "PASS"},
                    {"check_id": "CI-02", "status": "FAIL"},
                ],
                blocking_gates_failed=1,
            ),
        )
        current = self._create_scored_run(
            score=71.0,
            finished_at=now - timedelta(days=1),
            metadata=self._metadata(
                score=71.0,
                dimensions={"01 Customer Identity": {"score": 78.0}},
                estimate=95000.0,
                check_results=[
                    {"check_id": "CI-01", "status": "PASS"},
                    {"check_id": "CI-02", "status": "PASS"},
                ],
                blocking_gates_failed=0,
            ),
        )

        run_diff = persist_consecutive_run_diff(company=self.company, data_run=current)

        assert run_diff is not None
        self.assertFalse(run_diff["baseline"])
        self.assertEqual(run_diff["compared_to_data_run_id"], previous.id)
        self.assertEqual(run_diff["headline_score"]["delta"], 9)
        self.assertEqual(
            run_diff["dimensions"]["01 Customer Identity"]["delta"],
            8,
        )
        self.assertEqual(run_diff["business_impact"]["estimate"]["delta"], -25000)
        self.assertEqual(run_diff["check_summary"]["passed"]["delta"], 1)
        self.assertEqual(run_diff["check_summary"]["failed"]["delta"], -1)
        self.assertEqual(run_diff["check_summary"]["blocked"]["delta"], -1)

    def test_persist_is_idempotent(self):
        now = timezone.now()
        current = self._create_scored_run(
            score=70.0,
            finished_at=now,
            metadata=self._metadata(score=70.0),
        )
        first = persist_consecutive_run_diff(company=self.company, data_run=current)
        current.metadata = {
            **(current.metadata or {}),
            "run_diff": {
                **first,
                "headline_score": {"previous": 1, "current": 70, "delta": 69},
            },
        }
        current.save(update_fields=["metadata", "updated_at"])

        second = persist_consecutive_run_diff(company=self.company, data_run=current)

        assert second is not None
        self.assertEqual(second["headline_score"]["delta"], 69)

    def test_get_previous_scored_run_is_chronological_not_newest(self):
        now = timezone.now()
        self._create_scored_run(
            score=62.0,
            finished_at=now - timedelta(days=2),
            metadata=self._metadata(score=62.0),
        )
        middle = self._create_scored_run(
            score=75.0,
            finished_at=now - timedelta(days=1),
            metadata=self._metadata(score=75.0),
        )
        latest = self._create_scored_run(
            score=70.0,
            finished_at=now,
            metadata=self._metadata(score=70.0),
        )
        from dataruns.dcs.worklist import get_previous_scored_dcs_run

        previous = get_previous_scored_dcs_run(
            company=self.company,
            before_data_run_id=latest.id,
        )
        self.assertIsNotNone(previous)
        assert previous is not None
        self.assertEqual(previous.id, middle.id)

    def test_audit_summary_includes_positive_delta(self):
        summary = format_audit_score_summary(
            headline_score=71.0,
            run_state="COMPLETE",
            run_diff={
                "baseline": False,
                "headline_score": {"delta": 9},
            },
        )
        self.assertIn("(+9)", summary)

    def test_audit_at_stake_meta_when_estimate_improved(self):
        meta = format_audit_at_stake_meta(
            {
                "run_diff": {
                    "baseline": False,
                    "business_impact": {
                        "estimate": {
                            "delta": -25000,
                            "currency": "EUR",
                        }
                    },
                }
            }
        )
        self.assertEqual(meta, "At-stake −€25,000 vs prior run")

    def test_audit_at_stake_meta_skips_baseline(self):
        self.assertIsNone(
            format_audit_at_stake_meta({"run_diff": {"baseline": True}})
        )

    def test_build_consecutive_run_diff_without_persist(self):
        diff = build_consecutive_run_diff(
            current_metadata=self._metadata(score=71.0, estimate=90000.0),
            previous_metadata=self._metadata(score=62.0, estimate=120000.0),
            previous_data_run=DataRun(id=99),
        )
        self.assertEqual(diff["business_impact"]["estimate"]["delta"], -30000.0)

    def test_audit_event_can_include_run_diff_metadata(self):
        from dataruns.audit import append_audit_event

        run_diff = build_consecutive_run_diff(
            current_metadata=self._metadata(score=71.0),
            previous_metadata=None,
            previous_data_run=None,
        )
        append_audit_event(
            company=self.company,
            action="dcs.score_completed",
            summary="DCS score completed · 71 · COMPLETE",
            performed_by="admin@diffco.com",
            metadata={"run_diff": run_diff},
        )
        audit = AuditLog.objects.latest("created_at")
        self.assertIn("run_diff", audit.metadata)
        self.assertTrue(audit.metadata["run_diff"]["baseline"])
