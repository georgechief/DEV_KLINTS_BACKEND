"""PRD-ORCH-01 Phase A — four-factor priority scoring (pack sheet 02)."""

from __future__ import annotations

from django.test import SimpleTestCase

from dataruns.orchestration.constants import (
    WEIGHT_BLOCKER_STATUS,
    WEIGHT_DEPENDENCY_READINESS,
    WEIGHT_EFFORT_IMPACT,
    WEIGHT_SEVERITY_RISK,
)
from dataruns.orchestration.scoring import (
    build_priority_explain,
    clamp_factor,
    compute_priority_score,
    normalize_priority_inputs,
    priority_class_from_score,
    sort_tasks_by_priority,
)


class OrchPriorityWeightsTests(SimpleTestCase):
    def test_weights_match_pack(self):
        self.assertEqual(WEIGHT_BLOCKER_STATUS, 0.40)
        self.assertEqual(WEIGHT_SEVERITY_RISK, 0.30)
        self.assertEqual(WEIGHT_DEPENDENCY_READINESS, 0.20)
        self.assertEqual(WEIGHT_EFFORT_IMPACT, 0.10)
        total = (
            WEIGHT_BLOCKER_STATUS
            + WEIGHT_SEVERITY_RISK
            + WEIGHT_DEPENDENCY_READINESS
            + WEIGHT_EFFORT_IMPACT
        )
        self.assertAlmostEqual(total, 1.0, places=6)


class OrchPackSheet02ArithmeticTests(SimpleTestCase):
    """Sheet 02 worked examples — must stay within ±0.01."""

    def test_cc07_style_consent_harm(self):
        # B=1 S=3 R=3 E=3 → 0.4+0.9+0.6+0.3 = 2.2
        score = compute_priority_score(
            {
                "blocker_status": 1,
                "severity_risk": 3,
                "dependency_readiness": 3,
                "effort_impact": 3,
            }
        )
        self.assertAlmostEqual(score, 2.2, delta=0.01)

    def test_le09_style_returns_unblocker(self):
        # B=3 S=3 R=3 E=2 → 1.2+0.9+0.6+0.2 = 2.9
        score = compute_priority_score(
            {
                "blocker_status": 3,
                "severity_risk": 3,
                "dependency_readiness": 3,
                "effort_impact": 2,
            }
        )
        self.assertAlmostEqual(score, 2.9, delta=0.01)

    def test_uc23_style_dependent_not_ready(self):
        # B=1 S=2 R=1 E=2 → 0.4+0.6+0.2+0.2 = 1.4
        score = compute_priority_score(
            {
                "blocker_status": 1,
                "severity_risk": 2,
                "dependency_readiness": 1,
                "effort_impact": 2,
            }
        )
        self.assertAlmostEqual(score, 1.4, delta=0.01)

    def test_le09_ranks_above_dependent_uc(self):
        le09 = compute_priority_score(
            {
                "blocker_status": 3,
                "severity_risk": 3,
                "dependency_readiness": 3,
                "effort_impact": 2,
            }
        )
        uc23 = compute_priority_score(
            {
                "blocker_status": 1,
                "severity_risk": 2,
                "dependency_readiness": 1,
                "effort_impact": 2,
            }
        )
        self.assertGreater(le09, uc23)


class OrchPriorityClassTests(SimpleTestCase):
    def test_class_thresholds(self):
        self.assertEqual(priority_class_from_score(2.9), "P0")
        self.assertEqual(priority_class_from_score(2.0), "P0")
        self.assertEqual(priority_class_from_score(1.99), "P1")
        self.assertEqual(priority_class_from_score(1.0), "P1")
        self.assertEqual(priority_class_from_score(0.99), "P2")
        self.assertEqual(priority_class_from_score(0.0), "P2")


class OrchClampAndNormalizeTests(SimpleTestCase):
    def test_clamp_out_of_range(self):
        self.assertEqual(clamp_factor(-1), 0)
        self.assertEqual(clamp_factor(4), 3)
        self.assertEqual(clamp_factor(2), 2)

    def test_clamp_invalid(self):
        self.assertEqual(clamp_factor("x"), 0)
        self.assertEqual(clamp_factor(None), 0)

    def test_normalize_missing_defaults_zero(self):
        inputs = normalize_priority_inputs({})
        self.assertEqual(
            inputs,
            {
                "blocker_status": 0,
                "severity_risk": 0,
                "dependency_readiness": 0,
                "effort_impact": 0,
            },
        )
        self.assertEqual(compute_priority_score({}), 0.0)

    def test_score_bounds(self):
        self.assertEqual(
            compute_priority_score(
                {
                    "blocker_status": 3,
                    "severity_risk": 3,
                    "dependency_readiness": 3,
                    "effort_impact": 3,
                }
            ),
            3.0,
        )


class OrchExplainAndSortTests(SimpleTestCase):
    def test_explain_contributions(self):
        rows = build_priority_explain(
            {
                "blocker_status": 3,
                "severity_risk": 3,
                "dependency_readiness": 3,
                "effort_impact": 2,
            },
            reasons={"blocker_status": "Foundation gate"},
        )
        by_factor = {r["factor"]: r for r in rows}
        self.assertAlmostEqual(by_factor["blocker_status"]["contribution"], 1.2, delta=0.01)
        self.assertEqual(by_factor["blocker_status"]["reason"], "Foundation gate")
        # Highest contribution first
        self.assertEqual(rows[0]["factor"], "blocker_status")

    def test_sort_tie_break_score_then_class_then_task_id(self):
        tasks = [
            {
                "task_id": "FIX-B",
                "priority_score": 2.0,
                "priority_class": "P0",
            },
            {
                "task_id": "FIX-A",
                "priority_score": 2.0,
                "priority_class": "P0",
            },
            {
                "task_id": "FIX-C",
                "priority_score": 2.9,
                "priority_class": "P0",
            },
            {
                "task_id": "FIX-D",
                "priority_score": 1.4,
                "priority_class": "P1",
            },
        ]
        ordered = sort_tasks_by_priority(tasks)
        self.assertEqual(
            [t["task_id"] for t in ordered],
            ["FIX-C", "FIX-A", "FIX-B", "FIX-D"],
        )
