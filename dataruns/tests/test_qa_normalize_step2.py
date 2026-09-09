"""PRD-QA-01 Step 2 — package normalizers (gates + graph + field resolvers)."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import TestCase

from dataruns.use_cases.build_package import (
    _agent_spec_from_blueprint,
    assemble_build_package_payload,
)
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot
from dataruns.use_cases.qa_normalize import (
    data_gates_blocking_checks,
    find_entry_node_ids,
    hard_gate_blocks_data_gates_pass,
    is_hard_gate,
    is_terminal_node,
    node_references_consent,
    nodes_missing_terminal,
    normalize_gates_snapshot,
    orphan_node_ids,
    resolve_audience_consent,
    resolve_collision_policy,
    resolve_primary_metric,
    resolve_rollback_strategy,
    resolve_workflow_nodes,
    supplemental_gate_blocks_data_gates_pass,
)
from dataruns.use_cases.recommend import (
    _gates_from_blueprint,
    build_gates_snapshot,
    is_supplemental_gate,
)
from tenants.models import Company, Tenant


class QaNormalizeStep2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="QA Norm", slug="qa-norm")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="QA Norm Co",
            domain="qa-norm.example.com",
        )
        cls.pilot = (
            UseCasePilot.objects.select_related("blueprint")
            .get(use_case_id="UC-02")
        )
        cls.blueprint = cls.pilot.blueprint
        cls.body = cls.blueprint.body if isinstance(cls.blueprint.body, dict) else {}
        gates = _gates_from_blueprint(cls.body)
        # Realistic WF-01 snapshot: hard CC-03 PASS; supplementals provisional.
        from dataruns.use_cases.recommend import RecommendationContext
        from django.utils import timezone

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
        cls.package_payload = assemble_build_package_payload(
            package_id="00000000-0000-0000-0000-000000000002",
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

    # --- gates ---

    def test_gates_snapshot_uses_nested_checks(self):
        snap = self.package_payload["gates_snapshot"]
        self.assertIn("checks", snap)
        normalized = normalize_gates_snapshot(snap)
        self.assertIn("CC-03", normalized["checks"])
        self.assertEqual(normalized["checks"]["CC-03"], "PASS")
        self.assertTrue(normalized["provisional_supplemental"])

    def test_cc03_is_hard_cc06_ci08_are_supplemental(self):
        self.assertTrue(is_hard_gate("CC-03"))
        self.assertFalse(is_hard_gate("CC-06"))
        self.assertFalse(is_hard_gate("CI-08"))
        self.assertTrue(is_supplemental_gate("CC-06"))
        self.assertTrue(is_supplemental_gate("CI-08"))

    def test_warn_does_not_block_hard_gate(self):
        self.assertFalse(hard_gate_blocks_data_gates_pass("WARN"))
        self.assertFalse(hard_gate_blocks_data_gates_pass("PASS"))
        self.assertTrue(hard_gate_blocks_data_gates_pass("FAIL"))
        self.assertTrue(hard_gate_blocks_data_gates_pass("not_evaluated"))

    def test_supplemental_not_evaluated_ok_when_provisional(self):
        self.assertFalse(
            supplemental_gate_blocks_data_gates_pass(
                "not_evaluated",
                provisional_supplemental=True,
            )
        )
        self.assertTrue(
            supplemental_gate_blocks_data_gates_pass(
                "not_evaluated",
                provisional_supplemental=False,
            )
        )
        self.assertTrue(
            supplemental_gate_blocks_data_gates_pass(
                "FAIL",
                provisional_supplemental=True,
            )
        )
        # UNKNOWN / WARN are evaluated outcomes — never provisional-exempt.
        self.assertTrue(
            supplemental_gate_blocks_data_gates_pass(
                "UNKNOWN",
                provisional_supplemental=True,
            )
        )
        self.assertTrue(
            supplemental_gate_blocks_data_gates_pass(
                "WARN",
                provisional_supplemental=True,
            )
        )

    def test_uc02_provisional_snapshot_has_no_blocking_gates(self):
        blocking = data_gates_blocking_checks(self.package_payload["gates_snapshot"])
        self.assertEqual(blocking, [])

    def test_hard_fail_blocks(self):
        snap = {
            "checks": {"CC-03": "FAIL", "CC-06": "not_evaluated"},
            "provisional_supplemental": True,
        }
        blocking = data_gates_blocking_checks(snap)
        self.assertEqual([r["check_id"] for r in blocking], ["CC-03"])
        self.assertEqual(blocking[0]["locator"], "gates_snapshot.checks.CC-03")

    def test_supplemental_fail_blocks_data_gates_even_when_provisional(self):
        # DCS-09 Step 9: supplemental FAIL always blocks data_gates_pass.
        snap = {
            "checks": {"CC-03": "PASS", "CC-06": "FAIL", "CI-08": "PASS"},
            "provisional_supplemental": True,
        }
        blocking = data_gates_blocking_checks(snap)
        self.assertEqual([r["check_id"] for r in blocking], ["CC-06"])
        self.assertFalse(blocking[0]["is_hard"])

    def test_supplemental_not_evaluated_blocks_when_not_provisional(self):
        snap = {
            "checks": {"CC-03": "PASS", "CC-06": "not_evaluated"},
            "provisional_supplemental": False,
        }
        blocking = data_gates_blocking_checks(snap)
        self.assertEqual([r["check_id"] for r in blocking], ["CC-06"])

    def test_unknown_not_collapsed_to_not_evaluated(self):
        from dataruns.use_cases.qa_normalize import normalize_gate_label

        self.assertEqual(normalize_gate_label("UNKNOWN"), "UNKNOWN")
        self.assertEqual(normalize_gate_label("not_evaluated"), "NOT_EVALUATED")

    def test_not_connected_supplemental_blocks_data_gates(self):
        snap = {
            "checks": {"CC-03": "PASS", "BR-09": "NOT_CONNECTED"},
            "provisional_supplemental": True,
        }
        blocking = data_gates_blocking_checks(snap)
        self.assertEqual([r["check_id"] for r in blocking], ["BR-09"])
        self.assertFalse(blocking[0]["is_hard"])

    def test_flat_gates_map_fallback(self):
        normalized = normalize_gates_snapshot({"CC-03": "pass", "min_dcs": 70})
        self.assertEqual(normalized["checks"]["CC-03"], "PASS")

    # --- graph / nodes ---

    def test_resolve_nodes_from_agent_spec_not_workflow_nest(self):
        agent_spec = self.package_payload["agent_spec"]
        self.assertIn("nodes", agent_spec)
        self.assertNotIn("workflow", agent_spec)
        nodes = resolve_workflow_nodes(self.package_payload)
        self.assertGreaterEqual(len(nodes), 7)
        ids = {n.get("node_id") for n in nodes}
        self.assertIn("n01", ids)
        self.assertIn("n07", ids)

    def test_uc02_finish_is_terminal(self):
        nodes = resolve_workflow_nodes(self.package_payload)
        finish = next(n for n in nodes if n.get("node_id") == "n07")
        self.assertEqual(str(finish.get("node_type")).upper(), "FINISH")
        self.assertTrue(is_terminal_node(finish))

    def test_uc02_no_orphans_and_all_reach_terminal(self):
        nodes = resolve_workflow_nodes(self.package_payload)
        self.assertEqual(find_entry_node_ids(nodes), ["n01"])
        self.assertEqual(orphan_node_ids(nodes), [])
        self.assertEqual(nodes_missing_terminal(nodes), [])

    def test_orphan_detected(self):
        nodes = [
            {
                "node_id": "n01",
                "node_type": "TRIGGER",
                "next": ["n02"],
            },
            {
                "node_id": "n02",
                "node_type": "FINISH",
                "next": [],
            },
            {
                "node_id": "orphan",
                "node_type": "ACTION",
                "next": [],
            },
        ]
        self.assertEqual(orphan_node_ids(nodes), ["orphan"])

    def test_cycle_without_terminal_detected(self):
        nodes = [
            {"node_id": "a", "node_type": "TRIGGER", "next": ["b"]},
            {"node_id": "b", "node_type": "ACTION", "next": ["a"]},
        ]
        self.assertEqual(nodes_missing_terminal(nodes), ["a", "b"])

    def test_mixed_valid_and_dangling_branch_missing_terminal(self):
        nodes = [
            {
                "node_id": "a",
                "node_type": "TRIGGER",
                "next": ["finish", "ghost"],
            },
            {
                "node_id": "finish",
                "node_type": "TERMINAL",
                "next": [],
            },
        ]
        self.assertIn("a", nodes_missing_terminal(nodes))

    def test_blueprint_fallback_when_agent_spec_nodes_empty(self):
        payload = {
            "agent_spec": {"nodes": []},
        }
        nodes = resolve_workflow_nodes(payload, blueprint_body=self.body)
        self.assertGreaterEqual(len(nodes), 7)

    # --- field resolvers ---

    def test_collision_measurement_rollback_from_package(self):
        self.assertIsNotNone(resolve_collision_policy(self.package_payload))
        self.assertEqual(
            resolve_primary_metric(self.package_payload),
            "welcome_entry_rate",
        )
        strategy = resolve_rollback_strategy(self.package_payload)
        self.assertTrue(strategy)
        self.assertIn("Deactivate", strategy)

    def test_audience_consent_and_consent_node(self):
        consent = resolve_audience_consent(self.package_payload)
        self.assertTrue(consent)
        nodes = resolve_workflow_nodes(self.package_payload)
        consent_nodes = [n for n in nodes if node_references_consent(n)]
        self.assertTrue(consent_nodes)
        # UC-02 n02 is "Email opt-in = true"
        self.assertTrue(
            any(n.get("node_id") == "n02" for n in consent_nodes),
        )

    def test_agent_spec_shape_matches_wf01_builder(self):
        rebuilt = _agent_spec_from_blueprint(self.body)
        self.assertEqual(
            len(rebuilt["nodes"]),
            len(self.package_payload["agent_spec"]["nodes"]),
        )
        self.assertIn("collision_policy", rebuilt)
        self.assertIn("measurement", rebuilt)
