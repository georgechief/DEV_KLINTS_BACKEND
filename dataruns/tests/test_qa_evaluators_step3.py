"""PRD-QA-01 Step 3 — hard-test evaluators (PASS + FAIL per test_id)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from dataruns.use_cases.build_package import assemble_build_package_payload
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot
from dataruns.use_cases.qa_evaluators import (
    HARD_TEST_IDS,
    STATUS_FAIL,
    STATUS_PASS,
    collect_evidence_for_payload,
    evaluate_hard_test,
    evaluate_hard_tests,
    strip_evidence_ids_for_schema,
)
from dataruns.use_cases.recommend import (
    RecommendationContext,
    _gates_from_blueprint,
    build_gates_snapshot,
)
from tenants.models import Company, Tenant


class QaEvaluatorsStep3Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="QA Eval", slug="qa-eval")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="QA Eval Co",
            domain="qa-eval.example.com",
        )
        cls.pilot = (
            UseCasePilot.objects.select_related("blueprint").get(use_case_id="UC-02")
        )
        cls.blueprint = cls.pilot.blueprint
        cls.body = cls.blueprint.body if isinstance(cls.blueprint.body, dict) else {}
        gates = _gates_from_blueprint(cls.body)
        ctx = RecommendationContext(
            headline_score=85.0,
            score_ready=True,
            dcs_data_run_id=1,
            check_results={"CC-03": "PASS"},
            af_mode="AUGMENT",
            af_assessment_id=None,
            gap_stage_ids=[],
            as_of=timezone.now(),
        )
        gates_snapshot = build_gates_snapshot(
            gates=gates,
            ctx=ctx,
            provisional_supplemental=True,
        )
        cls.golden = assemble_build_package_payload(
            package_id="00000000-0000-0000-0000-000000000003",
            pilot=cls.pilot,
            blueprint=cls.blueprint,
            company=cls.company,
            ctx_snapshot={
                "dcs_data_run_id": 1,
                "af_assessment_id": None,
                "af_mode": "AUGMENT",
                "headline_score": 85.0,
            },
            gates=gates,
            gates_snapshot=gates_snapshot,
            provisional_supplemental=True,
            generated_by=None,
        )

    def _mutated(self, **overrides) -> dict:
        payload = deepcopy(self.golden)
        for key, value in overrides.items():
            payload[key] = value
        return payload

    def test_uc02_golden_all_seven_pass(self):
        results = evaluate_hard_tests(self.golden)
        self.assertEqual(len(results), 7)
        self.assertEqual([r.test_id for r in results], list(HARD_TEST_IDS))
        for result in results:
            self.assertEqual(
                result.status,
                STATUS_PASS,
                msg=f"{result.test_id} failed: {result.evidence}",
            )
            self.assertTrue(result.evidence)
            self.assertTrue(result.as_hard_test_row()["evidence_ids"])

    def test_unknown_test_fails_closed(self):
        result = evaluate_hard_test("made_up_test", self.golden)
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertEqual(result.evidence[0]["value"], "unknown_test")

    # --- data_gates_pass ---

    def test_data_gates_pass_ok(self):
        result = evaluate_hard_test("data_gates_pass", self.golden)
        self.assertEqual(result.status, STATUS_PASS)

    def test_data_gates_pass_fails_on_hard_fail(self):
        payload = self._mutated(
            gates_snapshot={
                "checks": {"CC-03": "FAIL", "CC-06": "not_evaluated"},
                "provisional_supplemental": True,
            }
        )
        result = evaluate_hard_test("data_gates_pass", payload)
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertIn("CC-03", result.evidence[0]["locator"])

    def test_data_gates_pass_fails_on_supplemental_fail_even_when_provisional(self):
        # DCS-09 Step 9: supplemental FAIL blocks data_gates_pass under provisional.
        payload = self._mutated(
            gates_snapshot={
                "checks": {"CC-03": "PASS", "CC-06": "FAIL", "CI-08": "PASS"},
                "provisional_supplemental": True,
            }
        )
        result = evaluate_hard_test("data_gates_pass", payload)
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertIn("CC-06", result.evidence[0]["locator"])

    def test_data_gates_pass_ok_supplemental_not_evaluated_under_provisional(self):
        payload = self._mutated(
            gates_snapshot={
                "checks": {"CC-03": "PASS", "CC-06": "not_evaluated", "CI-08": "not_evaluated"},
                "provisional_supplemental": True,
            }
        )
        result = evaluate_hard_test("data_gates_pass", payload)
        self.assertEqual(result.status, STATUS_PASS)

    def test_data_gates_pass_warn_does_not_fail(self):
        payload = self._mutated(
            gates_snapshot={
                "checks": {"CC-03": "WARN"},
                "provisional_supplemental": False,
            }
        )
        result = evaluate_hard_test("data_gates_pass", payload)
        self.assertEqual(result.status, STATUS_PASS)

    # --- consent_branching ---

    def test_consent_branching_pass(self):
        result = evaluate_hard_test("consent_branching", self.golden)
        self.assertEqual(result.status, STATUS_PASS)

    def test_consent_branching_fail(self):
        payload = deepcopy(self.golden)
        # Strip consent keywords from nodes and audience consent.
        for node in payload["agent_spec"]["nodes"]:
            if node.get("node_id") == "n02":
                node["platform_primitive"] = "Purchase count check"
                node["config"] = {"description": "Purchase count check"}
        payload["agent_spec"]["audience"] = {
            "definition": "Anyone",
            "consent": "",
        }
        result = evaluate_hard_test("consent_branching", payload)
        self.assertEqual(result.status, STATUS_FAIL)

    def test_consent_action_with_keyword_is_not_enough(self):
        """PRD requires CONDITION (or equivalent), not any ACTION mentioning consent."""
        payload = deepcopy(self.golden)
        for node in payload["agent_spec"]["nodes"]:
            if node.get("node_id") == "n02":
                node["platform_primitive"] = "Purchase count check"
                node["config"] = {"description": "Purchase count check"}
        payload["agent_spec"]["audience"] = {"consent": ""}
        # ACTION with consent text must not unlock the keyword path alone.
        payload["agent_spec"]["nodes"].append(
            {
                "node_id": "n_action_consent",
                "node_type": "ACTION",
                "platform_primitive": "Log consent event",
                "config": {"description": "Record consent"},
                "next": [],
            }
        )
        # Keep graph connected from trigger so orphan test isn't the focus.
        result = evaluate_hard_test(
            "consent_branching",
            payload,
            blueprint_body={},
        )
        self.assertEqual(result.status, STATUS_FAIL)

    def test_consent_pass_via_audience_only(self):
        """Audience consent + CONDITION after trigger (branch), no consent keyword on CONDITION."""
        payload = deepcopy(self.golden)
        for node in payload["agent_spec"]["nodes"]:
            if node.get("node_id") == "n02":
                node["platform_primitive"] = "Purchase count check"
                node["config"] = {"description": "Purchase count check"}
        payload["agent_spec"]["audience"] = {
            "consent": "Explicit per-channel consent at send time",
        }
        result = evaluate_hard_test(
            "consent_branching",
            payload,
            blueprint_body={},
        )
        self.assertEqual(result.status, STATUS_PASS)

    def test_consent_audience_linear_no_condition_fails(self):
        """Audience consent alone on TRIGGER→ACTION→FINISH must not PASS (no branch)."""
        payload = deepcopy(self.golden)
        payload["agent_spec"]["audience"] = {
            "consent": "Explicit per-channel consent at send time",
        }
        payload["agent_spec"]["nodes"] = [
            {
                "node_id": "t1",
                "node_type": "TRIGGER",
                "platform_primitive": "Tag assigned",
                "config": {},
                "next": ["a1"],
            },
            {
                "node_id": "a1",
                "node_type": "ACTION",
                "platform_primitive": "Send email",
                "config": {},
                "next": ["f1"],
            },
            {
                "node_id": "f1",
                "node_type": "FINISH",
                "platform_primitive": "Terminal",
                "config": {},
                "next": [],
            },
        ]
        result = evaluate_hard_test(
            "consent_branching",
            payload,
            blueprint_body={},
        )
        self.assertEqual(result.status, STATUS_FAIL)

    def test_data_gates_pass_fails_on_hard_not_evaluated(self):
        payload = self._mutated(
            gates_snapshot={
                "checks": {"CC-03": "not_evaluated"},
                "provisional_supplemental": True,
            }
        )
        result = evaluate_hard_test("data_gates_pass", payload)
        self.assertEqual(result.status, STATUS_FAIL)

    def test_terminal_broken_next_pointer_fails(self):
        payload = self._mutated(
            agent_spec={
                **self.golden["agent_spec"],
                "nodes": [
                    {"node_id": "a", "node_type": "TRIGGER", "next": ["missing"]},
                ],
            }
        )
        result = evaluate_hard_test("terminal_reachable", payload)
        self.assertEqual(result.status, STATUS_FAIL)

    def test_terminal_mixed_valid_and_dangling_branch_fails(self):
        """One good exit is not enough — every next edge must reach a terminal."""
        payload = self._mutated(
            agent_spec={
                **self.golden["agent_spec"],
                "nodes": [
                    {
                        "node_id": "a",
                        "node_type": "TRIGGER",
                        "next": ["finish", "ghost"],
                    },
                    {"node_id": "finish", "node_type": "TERMINAL", "next": []},
                ],
            }
        )
        result = evaluate_hard_test("terminal_reachable", payload)
        self.assertEqual(result.status, STATUS_FAIL)

    # --- terminal_reachable ---

    def test_terminal_reachable_pass(self):
        result = evaluate_hard_test("terminal_reachable", self.golden)
        self.assertEqual(result.status, STATUS_PASS)

    def test_terminal_reachable_fail_on_cycle(self):
        payload = self._mutated(
            agent_spec={
                **self.golden["agent_spec"],
                "nodes": [
                    {"node_id": "a", "node_type": "TRIGGER", "next": ["b"]},
                    {"node_id": "b", "node_type": "ACTION", "next": ["a"]},
                ],
            }
        )
        result = evaluate_hard_test("terminal_reachable", payload)
        self.assertEqual(result.status, STATUS_FAIL)

    # --- no_orphan_nodes ---

    def test_no_orphan_nodes_pass(self):
        result = evaluate_hard_test("no_orphan_nodes", self.golden)
        self.assertEqual(result.status, STATUS_PASS)

    def test_no_orphan_nodes_fail(self):
        nodes = deepcopy(self.golden["agent_spec"]["nodes"])
        nodes.append(
            {
                "node_id": "orphan_x",
                "node_type": "ACTION",
                "config": {"description": "lost"},
                "next": [],
            }
        )
        payload = self._mutated(
            agent_spec={**self.golden["agent_spec"], "nodes": nodes}
        )
        result = evaluate_hard_test("no_orphan_nodes", payload)
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertIn("orphan_x", result.evidence[0]["value"])

    # --- collision_policy ---

    def test_collision_policy_pass(self):
        result = evaluate_hard_test("collision_policy", self.golden)
        self.assertEqual(result.status, STATUS_PASS)

    def test_collision_policy_fail(self):
        agent_spec = deepcopy(self.golden["agent_spec"])
        agent_spec["collision_policy"] = {}
        payload = self._mutated(agent_spec=agent_spec)
        result = evaluate_hard_test(
            "collision_policy",
            payload,
            blueprint_body={},  # no blueprint fallback
        )
        self.assertEqual(result.status, STATUS_FAIL)

    # --- measurement_wired ---

    def test_measurement_wired_pass(self):
        result = evaluate_hard_test("measurement_wired", self.golden)
        self.assertEqual(result.status, STATUS_PASS)
        self.assertEqual(result.evidence[0]["value"], "welcome_entry_rate")

    def test_measurement_wired_fail(self):
        agent_spec = deepcopy(self.golden["agent_spec"])
        agent_spec["measurement"] = {"secondary_metrics": ["x"]}
        payload = self._mutated(agent_spec=agent_spec)
        result = evaluate_hard_test(
            "measurement_wired",
            payload,
            blueprint_body={},
        )
        self.assertEqual(result.status, STATUS_FAIL)

    # --- rollback_defined ---

    def test_rollback_defined_pass(self):
        result = evaluate_hard_test("rollback_defined", self.golden)
        self.assertEqual(result.status, STATUS_PASS)

    def test_rollback_defined_fail(self):
        payload = self._mutated(rollback={"strategy": "  "})
        result = evaluate_hard_test("rollback_defined", payload)
        self.assertEqual(result.status, STATUS_FAIL)

    # --- payload helpers ---

    def test_collect_evidence_for_payload(self):
        results = evaluate_hard_tests(self.golden)
        hard_rows, evidence = collect_evidence_for_payload(results)
        self.assertEqual(len(hard_rows), 7)
        self.assertTrue(evidence)
        schema_evidence = strip_evidence_ids_for_schema(evidence)
        for row in schema_evidence:
            self.assertNotIn("id", row)
            self.assertIn("source", row)
            self.assertIn("locator", row)
            self.assertIn("observed_at", row)
        # evidence_ids still reference original ids
        all_ids = {e["id"] for e in evidence}
        for row in hard_rows:
            for eid in row["evidence_ids"]:
                self.assertIn(eid, all_ids)
