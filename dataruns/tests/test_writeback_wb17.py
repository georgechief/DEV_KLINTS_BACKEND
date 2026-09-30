"""PRD-WB-17 — CC-01 email consent reconcile plan (Phase A) tests."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase, override_settings

from dataruns.dcs.consent_join import CC_SAMPLE
from dataruns.dcs.executors.consent import evaluate_cc_01
from dataruns.models import WritebackAllowedCheck
from dataruns.tests.test_consent_pt04_checks import _consent_snap, _ctx
from dataruns.writebacks.messages import writeback_execute_denial_detail
from dataruns.writebacks.pipeline import run_writeback_pipeline
from dataruns.writebacks.registry import get_check_mapping
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.transform import (
    _cc01_evidence_gate_pass,
    _cc01_filter_plan_rows,
    build_intents_from_mapping,
)
from tenants.models import Company, Connector, Tenant


class Cc01GateHelperTests(SimpleTestCase):
    def test_out_in_always_force_opt_out(self):
        company = Company(id=1)
        rows = _cc01_filter_plan_rows(
            company=company,
            rows=[
                {
                    "side": "out_in",
                    "person.email": "a@b.com",
                    "manago_contact_id": "m1",
                    "optedOut": False,
                    "provenance_ok": False,
                }
            ],
            max_rows=10,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["proposed_action"], "FORCE_OPT_OUT")
        self.assertEqual(rows[0]["evidence_gate"], "opt_out_wins")

    def test_in_out_skip_without_evidence(self):
        company = Company(id=1)
        rows = _cc01_filter_plan_rows(
            company=company,
            rows=[
                {
                    "side": "in_out",
                    "person.email": "a@b.com",
                    "manago_contact_id": "m1",
                    "optedOut": True,
                    "provenance_ok": False,
                    "provenance_weak": True,
                    # Skip find_manago_contact DB hit in SimpleTestCase
                    "klints_consent_evidence": "none",
                }
            ],
            max_rows=10,
        )
        self.assertEqual(rows[0]["proposed_action"], "SKIP_UNEVIDENCED")
        self.assertEqual(rows[0]["evidence_gate"], "fail")

    def test_in_out_force_opt_in_with_provenance(self):
        ok, gate = _cc01_evidence_gate_pass(
            {
                "provenance_ok": True,
                "shopify_email_opt_in_level": "",
            }
        )
        self.assertTrue(ok)
        self.assertEqual(gate, "provenance_ok")

    def test_in_out_force_opt_in_with_shopify_level_and_ts(self):
        ok, gate = _cc01_evidence_gate_pass(
            {
                "provenance_ok": False,
                "shopify_email_opt_in_level": "single_opt_in",
                "shopify_email_consent_updated_at": "2026-01-01T00:00:00Z",
            }
        )
        self.assertTrue(ok)
        self.assertEqual(gate, "shopify_opt_in_level+ts")


class Cc01ProvenanceEnrichTests(SimpleTestCase):
    def test_evaluate_cc01_provenance_carries_gate_fields(self):
        snap = _consent_snap(
            linked_identities=2,
            email_quadrant_matrix={
                "in_in": 0,
                "in_out": 1,
                "out_in": 1,
                "out_out": 0,
                "unknown": 0,
            },
            compliance_exposure_email=1,
            lost_reach_email=1,
            email_mismatches=2,
            mismatch_samples={
                "email_out_in": [
                    {
                        "email_quadrant": "out_in",
                        "person.email": "out@ex.com",
                        "shopify_customer_id": "s1",
                        "manago_contact_id": "m1",
                        "optedOut": False,
                        "prior_optedOut": False,
                        "provenance_ok": False,
                        "provenance_weak": True,
                        "manago_email_in": True,
                        "shopify_email_in": False,
                        "link_kind": "email",
                    }
                ],
                "email_in_out": [
                    {
                        "email_quadrant": "in_out",
                        "person.email": "in@ex.com",
                        "shopify_customer_id": "s2",
                        "manago_contact_id": "m2",
                        "optedOut": True,
                        "prior_optedOut": True,
                        "provenance_ok": True,
                        "provenance_weak": False,
                        "manago_email_in": False,
                        "shopify_email_in": True,
                        "link_kind": "external_key",
                        "shopify_email_opt_in_level": "single_opt_in",
                        "shopify_email_consent_updated_at": "2026-01-01",
                    }
                ],
            },
        )
        result = evaluate_cc_01(_ctx(snap))
        self.assertEqual(result.status, "FAIL")
        mismatches = (result.provenance or {}).get("mismatches") or []
        self.assertGreaterEqual(len(mismatches), 2)
        sides = {m.get("side") for m in mismatches}
        self.assertIn("out_in", sides)
        self.assertIn("in_out", sides)
        for m in mismatches:
            self.assertIn("provenance_ok", m)
            self.assertIn("prior_optedOut", m)
            self.assertIn("proposed_action", m)
            self.assertIn("evidence_gate", m)
        by_side = {m.get("side"): m for m in mismatches}
        self.assertEqual(by_side["out_in"]["proposed_action"], "FORCE_OPT_OUT")
        self.assertEqual(by_side["in_out"]["proposed_action"], "FORCE_OPT_IN")
        evidence_val = {}
        if result.evidence:
            first = result.evidence[0]
            evidence_val = getattr(first, "value", None) or {}
            if not isinstance(evidence_val, dict):
                evidence_val = {}
        self.assertEqual(evidence_val.get("consent_mismatch_email_count"), 2)
        self.assertEqual(evidence_val.get("preview_sample_cap"), CC_SAMPLE)

    def test_evaluate_cc01_uses_uncapped_consent_mismatch_email(self):
        """Download SoT prefers full list over sample keys (PRD-WB-17 §3.4)."""
        rows = [
            {
                "email_quadrant": "out_in",
                "person.email": f"out{i}@ex.com",
                "shopify_customer_id": f"s{i}",
                "manago_contact_id": f"m{i}",
                "optedOut": False,
                "provenance_ok": False,
                "manago_email_in": True,
                "shopify_email_in": False,
            }
            for i in range(CC_SAMPLE + 5)
        ]
        snap = _consent_snap(
            linked_identities=CC_SAMPLE + 5,
            email_quadrant_matrix={
                "in_in": 0,
                "in_out": 0,
                "out_in": CC_SAMPLE + 5,
                "out_out": 0,
                "unknown": 0,
            },
            compliance_exposure_email=CC_SAMPLE + 5,
            email_mismatches=CC_SAMPLE + 5,
            mismatch_samples={"email_out_in": rows[:3], "email_in_out": []},
        )
        # Top-level uncapped list (scoring snapshot shape).
        snap["consent_mismatch_email"] = rows
        result = evaluate_cc_01(_ctx(snap))
        mismatches = (result.provenance or {}).get("mismatches") or []
        self.assertEqual(len(mismatches), CC_SAMPLE + 5)
        self.assertTrue(all(m.get("proposed_action") == "FORCE_OPT_OUT" for m in mismatches))


class Cc01MappingIntentTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB17M", slug="wb17-map")
        self.company = Company.objects.create(
            tenant=self.tenant, name="WB17 Map", domain="wb17-map.test"
        )

    def test_mapping_plan_only_and_two_const_ops(self):
        mapping = get_check_mapping("CC-01")
        self.assertEqual(mapping.get("execute_mode"), "plan_only")
        self.assertEqual(mapping.get("template_id"), "T8")
        self.assertEqual(mapping.get("approval_tier"), "batch")
        self.assertTrue(mapping.get("irreversible"))
        self.assertFalse(mapping.get("requires_consent_namespace_clean"))
        ops = mapping.get("operations") or []
        self.assertEqual(len(ops), 2)
        consts = {
            ((o.get("from_evidence") or {}).get("match") or {}).get("const") for o in ops
        }
        self.assertEqual(consts, {"out_in", "in_out"})
        for o in ops:
            self.assertNotIn("oneOf", (o.get("from_evidence") or {}).get("match") or {})
            self.assertIn("plan_only", o.get("guards") or [])

    def test_transform_builds_plan_intents(self):
        mapping = get_check_mapping("CC-01")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "out_in",
                    "person.email": "out@ex.com",
                    "manago_contact_id": "m1",
                    "shopify_customer_id": "s1",
                    "proposed_action": "FORCE_OPT_OUT",
                    "evidence_gate": "opt_out_wins",
                    "prior_optedOut": False,
                },
                {
                    "side": "in_out",
                    "person.email": "in@ex.com",
                    "manago_contact_id": "m2",
                    "shopify_customer_id": "s2",
                    "proposed_action": "FORCE_OPT_IN",
                    "evidence_gate": "provenance_ok",
                    "prior_optedOut": True,
                    "provenance_ok": True,
                },
                {
                    "side": "in_out",
                    "person.email": "skip@ex.com",
                    "manago_contact_id": "m3",
                    "proposed_action": "SKIP_UNEVIDENCED",
                    "evidence_gate": "fail",
                    "prior_optedOut": True,
                },
                {"side": "driver", "note": "ignore"},
            ],
        )
        plan = [i for i in intents if (i.payload or {}).get("mode") == "plan"]
        self.assertEqual(len(plan), 3)
        actions = {i.payload.get("proposed_action") for i in plan}
        self.assertEqual(
            actions, {"FORCE_OPT_OUT", "FORCE_OPT_IN", "SKIP_UNEVIDENCED"}
        )
        for intent in plan:
            self.assertEqual(intent.op_kind, "contact_upsert")
            self.assertTrue(str(intent.payload.get("email") or "").strip())
            ok, reason = rollback_supported(intent)
            self.assertFalse(ok)
            self.assertEqual(reason, "rollback_not_supported")
            action = intent.payload.get("proposed_action")
            if action == "SKIP_UNEVIDENCED":
                self.assertEqual(intent.status, "skipped")
                self.assertEqual(intent.error_reason, "skip_unevidenced")
            else:
                self.assertEqual(intent.status, "ready")
                self.assertIsNone(intent.error_reason)

    def test_no_writeback_allowed_seed(self):
        self.assertFalse(
            WritebackAllowedCheck.objects.filter(check_id="CC-01", enabled=True).exists()
        )


@override_settings(WRITEBACKS_ENABLED=False)
class Cc01PipelinePlanOnlyTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB17P", slug="wb17-pipe")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="WB17 Pipe",
            domain="wb17-pipe.test",
            writeback_execute_enabled=True,
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
        )

    def test_execute_blocked_cc01_plan_only_not_ci03(self):
        result = run_writeback_pipeline(
            company=self.company,
            check_id="CC-01",
            mode="execute",
            max_rows=CC_SAMPLE,
            intents=None,
        )
        self.assertEqual(result.blocked_reason, "cc01_plan_only")
        self.assertNotEqual(result.blocked_reason, "ci03_plan_only")
        detail = writeback_execute_denial_detail("cc01_plan_only")
        self.assertIn("Data lead", detail)
        self.assertIn("forceOpt", detail)

    def test_messages_and_sample_constant(self):
        self.assertEqual(CC_SAMPLE, 50)
        self.assertIn("plan-only", writeback_execute_denial_detail("cc01_plan_only").lower())

    def test_preview_default_max_rows_is_cc_sample(self):
        """Fix UI omits max_rows — pipeline must default to CC_SAMPLE, not unlimited."""
        result = run_writeback_pipeline(
            company=self.company,
            check_id="CC-01",
            mode="preview",
            max_rows=None,
            intents=None,
        )
        self.assertIsNone(result.blocked_reason)
        # Empty estate still proves the default path (no TypeError / wrong check branch).
        self.assertEqual(result.check_id, "CC-01")
        self.assertLessEqual(len(result.intents), CC_SAMPLE)