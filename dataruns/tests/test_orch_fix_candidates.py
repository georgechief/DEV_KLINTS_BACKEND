"""PRD-ORCH-01 Phase B — DCS → FIX factor maps + candidates."""

from __future__ import annotations

from django.test import SimpleTestCase

from dataruns.orchestration.candidates import build_fix_tasks_from_issues
from dataruns.orchestration.factors_dcs import (
    blocker_status,
    dependency_readiness,
    effort_impact,
    is_foundation_gate,
    map_dcs_issue_to_priority_inputs,
    severity_risk,
    top_quartile_revenue_threshold,
    worklist_has_open_foundation_fail,
)
from dataruns.orchestration.scoring import compute_priority_score


def _issue(**kwargs):
    base = {
        "check_id": "LE-04",
        "title": "Duplicate purchases",
        "status": "FAIL",
        "severity": "high",
        "dimension": "02 Lifecycle",
        "is_optional": False,
        "revenue_impact": 100.0,
        "currency": "USD",
    }
    base.update(kwargs)
    return base


class OrchFoundationDetectTests(SimpleTestCase):
    def test_fd_prefix(self):
        self.assertTrue(is_foundation_gate(_issue(check_id="FD-01")))

    def test_dimension_foundation(self):
        self.assertTrue(
            is_foundation_gate(
                _issue(check_id="XX-01", dimension="00 Foundation gates")
            )
        )

    def test_role_flag(self):
        self.assertTrue(is_foundation_gate(_issue(check_id="ZZ-01", role="GATE")))

    def test_normal_lifecycle(self):
        self.assertFalse(is_foundation_gate(_issue()))


class OrchSeverityFactorTests(SimpleTestCase):
    def test_ladder(self):
        self.assertEqual(severity_risk(_issue(severity="critical"))[0], 3)
        self.assertEqual(severity_risk(_issue(severity="High"))[0], 2)
        self.assertEqual(severity_risk(_issue(severity="medium"))[0], 1)
        self.assertEqual(severity_risk(_issue(severity="low"))[0], 0)
        self.assertEqual(severity_risk(_issue(severity=""))[0], 0)


class OrchBlockerFactorTests(SimpleTestCase):
    def test_foundation_wins(self):
        score, reason = blocker_status(_issue(check_id="FD-02"))
        self.assertEqual(score, 3)
        self.assertIn("Foundation", reason)

    def test_gating_pilot(self):
        score, _ = blocker_status(
            _issue(check_id="LE-09", revenue_impact=0),
            gating_check_ids=frozenset({"LE-09"}),
        )
        self.assertEqual(score, 2)

    def test_non_optional_fail_with_revenue(self):
        score, _ = blocker_status(_issue(status="FAIL", revenue_impact=50))
        self.assertEqual(score, 1)

    def test_warn_optional_zero(self):
        self.assertEqual(
            blocker_status(_issue(status="WARN", revenue_impact=0))[0],
            0,
        )
        self.assertEqual(
            blocker_status(_issue(is_optional=True, revenue_impact=0))[0],
            0,
        )


class OrchReadinessFactorTests(SimpleTestCase):
    def test_self_foundation_always_ready(self):
        score, _ = dependency_readiness(
            _issue(check_id="FD-01"),
            has_open_foundation_fail=True,
        )
        self.assertEqual(score, 3)

    def test_blocked_by_foundation(self):
        score, _ = dependency_readiness(
            _issue(),
            has_open_foundation_fail=True,
        )
        self.assertEqual(score, 1)

    def test_clear(self):
        score, _ = dependency_readiness(
            _issue(),
            has_open_foundation_fail=False,
        )
        self.assertEqual(score, 3)


class OrchEffortQuartileTests(SimpleTestCase):
    def test_empty(self):
        self.assertIsNone(top_quartile_revenue_threshold([]))

    def test_small_set_uses_max(self):
        self.assertEqual(top_quartile_revenue_threshold([10, 20, 30]), 30)

    def test_four_plus_percentile(self):
        # values 10,20,30,40 → 75th nearest-rank index ceil(3)-1 = 2 → 30
        self.assertEqual(top_quartile_revenue_threshold([10, 20, 30, 40]), 30)

    def test_critical_or_top_quartile(self):
        self.assertEqual(
            effort_impact(
                _issue(severity="critical", revenue_impact=0),
                top_quartile_threshold=100,
            )[0],
            3,
        )
        self.assertEqual(
            effort_impact(
                _issue(severity="medium", revenue_impact=100),
                top_quartile_threshold=100,
            )[0],
            3,
        )

    def test_positive_revenue_or_high(self):
        self.assertEqual(
            effort_impact(
                _issue(severity="low", revenue_impact=5),
                top_quartile_threshold=100,
            )[0],
            2,
        )
        self.assertEqual(
            effort_impact(
                _issue(severity="high", revenue_impact=0),
                top_quartile_threshold=None,
            )[0],
            2,
        )


class OrchCandidateBuilderTests(SimpleTestCase):
    def test_skips_null_check_id(self):
        tasks = build_fix_tasks_from_issues(
            [
                _issue(check_id=None, title="Synthetic"),
                _issue(check_id="LE-04"),
            ],
            company_id=1,
            data_run_id=99,
        )
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["task_id"], "FIX-LE-04")
        self.assertEqual(tasks[0]["href"], "/fix?issue=LE-04")
        self.assertEqual(tasks[0]["status"], "READY")
        self.assertEqual(tasks[0]["depends_on"], [])
        self.assertIsNone(tasks[0]["wave"])
        self.assertIn("1:FIX-LE-04:dcs:99", tasks[0]["idempotency_key"])

    def test_dedupe_check_id(self):
        tasks = build_fix_tasks_from_issues(
            [_issue(title="First"), _issue(title="Second")],
            company_id=1,
            data_run_id=1,
        )
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "First")

    def test_foundation_fail_lowers_non_foundation_readiness(self):
        issues = [
            _issue(
                check_id="FD-01",
                severity="critical",
                status="FAIL",
                revenue_impact=0,
                dimension="00 Foundation",
            ),
            _issue(
                check_id="LE-04",
                severity="high",
                status="FAIL",
                revenue_impact=50,
            ),
        ]
        self.assertTrue(worklist_has_open_foundation_fail(issues))
        tasks = build_fix_tasks_from_issues(
            issues, company_id=1, data_run_id=1
        )
        by_id = {t["check_id"]: t for t in tasks}
        self.assertEqual(by_id["FD-01"]["priority_inputs"]["dependency_readiness"], 3)
        self.assertEqual(by_id["LE-04"]["priority_inputs"]["dependency_readiness"], 1)
        self.assertGreater(
            by_id["FD-01"]["priority_score"],
            by_id["LE-04"]["priority_score"],
        )

    def test_gating_check_raises_blocker(self):
        tasks = build_fix_tasks_from_issues(
            [
                _issue(
                    check_id="LE-09",
                    severity="critical",
                    revenue_impact=0,
                    status="FAIL",
                )
            ],
            company_id=1,
            data_run_id=1,
            gating_check_ids=frozenset({"LE-09"}),
        )
        self.assertEqual(tasks[0]["priority_inputs"]["blocker_status"], 2)

    def test_map_inputs_round_trip_score(self):
        issue = _issue(
            check_id="CC-07",
            severity="critical",
            revenue_impact=1000,
            status="FAIL",
        )
        inputs, reasons = map_dcs_issue_to_priority_inputs(
            issue,
            has_open_foundation_fail=False,
            gating_check_ids=frozenset(),
            top_quartile_threshold=1000,
        )
        # Not foundation → blocker 1 (non-optional fail + revenue)
        # severity 3, readiness 3, effort 3 (critical + quartile)
        self.assertEqual(inputs["blocker_status"], 1)
        self.assertEqual(inputs["severity_risk"], 3)
        self.assertEqual(inputs["dependency_readiness"], 3)
        self.assertEqual(inputs["effort_impact"], 3)
        self.assertAlmostEqual(compute_priority_score(inputs), 2.2, delta=0.01)
        self.assertIn("severity_risk", reasons)

    def test_gating_match_is_case_insensitive(self):
        tasks = build_fix_tasks_from_issues(
            [
                _issue(
                    check_id="LE-09",
                    severity="critical",
                    revenue_impact=0,
                    status="FAIL",
                )
            ],
            company_id=1,
            data_run_id=1,
            gating_check_ids=frozenset({"le-09"}),
        )
        self.assertEqual(tasks[0]["priority_inputs"]["blocker_status"], 2)

    def test_non_finite_revenue_sanitized(self):
        tasks = build_fix_tasks_from_issues(
            [_issue(revenue_impact=float("inf"), severity="high")],
            company_id=1,
            data_run_id=1,
        )
        self.assertEqual(tasks[0]["revenue_impact"], 0.0)

    def test_build_fix_task_dict_rejects_empty_check_id(self):
        from dataruns.orchestration.candidates import build_fix_task_dict

        with self.assertRaises(ValueError):
            build_fix_task_dict(
                issue=_issue(check_id=None),
                company_id=1,
                data_run_id=1,
                priority_inputs={
                    "blocker_status": 0,
                    "severity_risk": 0,
                    "dependency_readiness": 0,
                    "effort_impact": 0,
                },
                priority_score=0.0,
                priority_class="P2",
                priority_explain=[],
            )
