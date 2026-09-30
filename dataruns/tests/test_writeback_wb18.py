"""PRD-WB-18 — CC-02 SMS consent reconcile plan (Phase A) tests."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase, override_settings

from dataruns.dcs.consent_join import CC_SAMPLE
from dataruns.dcs.executors.consent import evaluate_cc_02
from dataruns.models import WritebackAllowedCheck
from dataruns.tests.test_consent_pt04_checks import _consent_snap, _ctx
from dataruns.writebacks.messages import writeback_execute_denial_detail
from dataruns.writebacks.pipeline import run_writeback_pipeline
from dataruns.writebacks.registry import get_check_mapping
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.transform import (
    _cc02_evidence_gate_pass,
    _cc02_filter_plan_rows,
    build_intents_from_mapping,
)
from tenants.models import Company, Connector, Tenant


class Cc02GateHelperTests(SimpleTestCase):
    def test_out_in_always_force_phone_opt_out(self):
        company = Company(id=1)
        rows = _cc02_filter_plan_rows(
            company=company,
            rows=[
                {
                    "side": "out_in",
                    "channel": "sms",
                    "person.email": "a@b.com",
                    "person.phone": "+15551234567",
                    "manago_contact_id": "m1",
                    "optedOutPhone": False,
                    "provenance_ok": False,
                }
            ],
            max_rows=10,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["proposed_action"], "FORCE_PHONE_OPT_OUT")
        self.assertEqual(rows[0]["evidence_gate"], "opt_out_wins")

    def test_in_out_skip_without_evidence(self):
        company = Company(id=1)
        rows = _cc02_filter_plan_rows(
            company=company,
            rows=[
                {
                    "side": "in_out",
                    "channel": "sms",
                    "person.email": "a@b.com",
                    "manago_contact_id": "m1",
                    "optedOutPhone": True,
                    "provenance_ok": False,
                    "provenance_weak": True,
                    "klints_consent_evidence": "none",
                }
            ],
            max_rows=10,
        )
        self.assertEqual(rows[0]["proposed_action"], "SKIP_UNEVIDENCED")
        self.assertEqual(rows[0]["evidence_gate"], "fail")

    def test_in_out_force_phone_opt_in_with_sms_level_and_ts(self):
        ok, gate = _cc02_evidence_gate_pass(
            {
                "provenance_ok": False,
                "shopify_sms_opt_in_level": "single_opt_in",
                "shopify_sms_consent_updated_at": "2026-01-01T00:00:00Z",
            }
        )
        self.assertTrue(ok)
        self.assertEqual(gate, "shopify_sms_opt_in_level+ts")

    def test_email_opt_in_level_does_not_pass_sms_gate(self):
        ok, gate = _cc02_evidence_gate_pass(
            {
                "provenance_ok": False,
                "shopify_email_opt_in_level": "single_opt_in",
                "shopify_email_consent_updated_at": "2026-01-01T00:00:00Z",
            }
        )
        self.assertFalse(ok)
        self.assertEqual(gate, "fail")

    def test_unreachable_side_never_becomes_plan_row(self):
        company = Company(id=1)
        rows = _cc02_filter_plan_rows(
            company=company,
            rows=[
                {
                    "side": "consented_but_unreachable",
                    "person.email": "u@ex.com",
                    "person.phone": "bad",
                    "channel": "sms",
                }
            ],
            max_rows=10,
        )
        self.assertEqual(rows, [])

    def test_sms_quadrant_wins_over_stale_email_side(self):
        """Lock 15: email_quadrant/side collision must not drive FORCE_PHONE_*."""
        company = Company(id=1)
        rows = _cc02_filter_plan_rows(
            company=company,
            rows=[
                {
                    "side": "out_in",  # stale / email-shaped
                    "email_quadrant": "out_in",
                    "sms_quadrant": "in_in",
                    "channel": "sms",
                    "person.email": "ok@ex.com",
                    "manago_contact_id": "m1",
                }
            ],
            max_rows=10,
        )
        self.assertEqual(rows, [])

    def test_email_channel_without_sms_quadrant_skipped(self):
        company = Company(id=1)
        rows = _cc02_filter_plan_rows(
            company=company,
            rows=[
                {
                    "side": "out_in",
                    "channel": "email",
                    "person.email": "e@ex.com",
                    "manago_contact_id": "m1",
                    "prior_optedOut": False,
                }
            ],
            max_rows=10,
        )
        self.assertEqual(rows, [])


class Cc02SampleEnrichTests(SimpleTestCase):
    """PRD-WB-18 §3.3 — channel-conditional _sample; no CC-01 email regression."""

    def test_sms_sample_carries_phone_priors_not_email_priors(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from dataruns.dcs.consent_join import build_consent_snapshot

        company = SimpleNamespace(id="wb18-sample")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return {
                    "customers": [
                        {
                            "id": 201,
                            "email": "sms@ex.com",
                            "phone": "+15551234567",
                            "email_marketing_consent": {
                                "state": "subscribed",
                                "opt_in_level": "single_opt_in",
                                "consent_updated_at": "2026-01-01T00:00:00Z",
                            },
                            # Shopify SMS out / Manago in → sms out_in
                            "sms_marketing_consent": {
                                "state": "not_subscribed",
                                "opt_in_level": "single_opt_in",
                                "consent_updated_at": "2026-02-01T00:00:00Z",
                            },
                        }
                    ]
                }
            return {
                "contacts": [
                    {
                        "contactId": "m201",
                        "externalId": "201",
                        "email": "sms@ex.com",
                        "phone": "+15551234567",
                        "optedOut": False,
                        "optedOutPhone": False,
                        "consents": [
                            {
                                "channel": "SMS",
                                "status": "OPT_IN",
                                "source": "SHOPIFY",
                            }
                        ],
                    }
                ]
            }

        with patch(
            "dataruns.dcs.consent_join._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_consent_snapshot(company=company)

        sms_samples = (payload["consent"]["mismatch_samples"] or {}).get("sms_out_in") or []
        self.assertEqual(len(sms_samples), 1)
        row = sms_samples[0]
        self.assertEqual(row.get("channel"), "sms")
        self.assertIn("prior_optedOutPhone", row)
        self.assertIn("optedOutPhone", row)
        self.assertIn("shopify_sms_opt_in_level", row)
        self.assertIn("shopify_sms_consent_updated_at", row)
        self.assertIn("manago_sms_in", row)
        self.assertIn("shopify_sms_in", row)
        self.assertNotIn("prior_optedOut", row)
        self.assertNotIn("optedOut", row)
        self.assertTrue(isinstance(payload.get("consent_mismatch_sms"), list))
        self.assertGreaterEqual(len(payload["consent_mismatch_sms"]), 1)

    def test_email_sample_still_carries_email_priors(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from dataruns.dcs.consent_join import build_consent_snapshot

        company = SimpleNamespace(id="wb18-email-reg")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return {
                    "customers": [
                        {
                            "id": 301,
                            "email": "em@ex.com",
                            "email_marketing_consent": {
                                "state": "not_subscribed",
                                "opt_in_level": "single_opt_in",
                                "consent_updated_at": "2026-01-01T00:00:00Z",
                            },
                            "sms_marketing_consent": {"state": "not_subscribed"},
                        }
                    ]
                }
            return {
                "contacts": [
                    {
                        "contactId": "m301",
                        "externalId": "301",
                        "email": "em@ex.com",
                        "optedOut": False,
                        "optedOutPhone": True,
                        "consents": [],
                    }
                ]
            }

        with patch(
            "dataruns.dcs.consent_join._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_consent_snapshot(company=company)

        email_samples = (payload["consent"]["mismatch_samples"] or {}).get(
            "email_out_in"
        ) or []
        self.assertEqual(len(email_samples), 1)
        row = email_samples[0]
        self.assertEqual(row.get("channel"), "email")
        self.assertIn("prior_optedOut", row)
        self.assertIn("optedOut", row)
        self.assertIn("shopify_email_opt_in_level", row)
        self.assertNotIn("prior_optedOutPhone", row)


class Cc02ProvenanceEnrichTests(SimpleTestCase):
    def test_evaluate_cc02_provenance_carries_gate_fields(self):
        snap = _consent_snap(
            linked_identities=2,
            sms_quadrant_matrix={
                "in_in": 0,
                "in_out": 1,
                "out_in": 1,
                "out_out": 0,
                "unknown": 0,
            },
            compliance_exposure_sms=1,
            lost_reach_sms=1,
            sms_mismatches=2,
            mismatch_samples={
                "sms_out_in": [
                    {
                        "sms_quadrant": "out_in",
                        "person.email": "out@ex.com",
                        "person.phone": "+15551111111",
                        "shopify_customer_id": "s1",
                        "manago_contact_id": "m1",
                        "optedOutPhone": False,
                        "prior_optedOutPhone": False,
                        "provenance_ok": False,
                        "provenance_weak": True,
                        "manago_sms_in": True,
                        "shopify_sms_in": False,
                        "link_kind": "email",
                    }
                ],
                "sms_in_out": [
                    {
                        "sms_quadrant": "in_out",
                        "person.email": "in@ex.com",
                        "person.phone": "+15552222222",
                        "shopify_customer_id": "s2",
                        "manago_contact_id": "m2",
                        "optedOutPhone": True,
                        "prior_optedOutPhone": True,
                        "provenance_ok": True,
                        "provenance_weak": False,
                        "manago_sms_in": False,
                        "shopify_sms_in": True,
                        "link_kind": "external_key",
                        "shopify_sms_opt_in_level": "single_opt_in",
                        "shopify_sms_consent_updated_at": "2026-01-01",
                    }
                ],
                "consented_unreachable_sms": [
                    {
                        "person.email": "bad@ex.com",
                        "person.phone": "not-e164",
                        "phone_valid": False,
                        "shopify_customer_id": "s3",
                        "manago_contact_id": "m3",
                    }
                ],
            },
        )
        result = evaluate_cc_02(_ctx(snap))
        self.assertEqual(result.status, "FAIL")
        mismatches = (result.provenance or {}).get("mismatches") or []
        sides = {m.get("side") for m in mismatches}
        self.assertIn("out_in", sides)
        self.assertIn("in_out", sides)
        self.assertIn("consented_but_unreachable", sides)
        by_side = {m.get("side"): m for m in mismatches if m.get("side") != "consented_but_unreachable"}
        self.assertEqual(by_side["out_in"]["proposed_action"], "FORCE_PHONE_OPT_OUT")
        self.assertEqual(by_side["in_out"]["proposed_action"], "FORCE_PHONE_OPT_IN")
        for m in mismatches:
            if m.get("side") in ("out_in", "in_out"):
                self.assertIn("proposed_action", m)
                self.assertIn("evidence_gate", m)
                self.assertIn("prior_optedOutPhone", m)
        evidence_val = {}
        if result.evidence:
            first = result.evidence[0]
            evidence_val = getattr(first, "value", None) or {}
            if not isinstance(evidence_val, dict):
                evidence_val = {}
        self.assertEqual(evidence_val.get("consent_mismatch_sms_count"), 2)
        self.assertEqual(evidence_val.get("preview_sample_cap"), CC_SAMPLE)

    def test_evaluate_cc02_uses_uncapped_consent_mismatch_sms(self):
        rows = [
            {
                "sms_quadrant": "out_in",
                "person.email": f"out{i}@ex.com",
                "person.phone": f"+1555000{i:04d}",
                "shopify_customer_id": f"s{i}",
                "manago_contact_id": f"m{i}",
                "optedOutPhone": False,
                "provenance_ok": False,
                "manago_sms_in": True,
                "shopify_sms_in": False,
            }
            for i in range(CC_SAMPLE + 5)
        ]
        snap = _consent_snap(
            linked_identities=CC_SAMPLE + 5,
            sms_quadrant_matrix={
                "in_in": 0,
                "in_out": 0,
                "out_in": CC_SAMPLE + 5,
                "out_out": 0,
                "unknown": 0,
            },
            compliance_exposure_sms=CC_SAMPLE + 5,
            sms_mismatches=CC_SAMPLE + 5,
            mismatch_samples={"sms_out_in": rows[:3], "sms_in_out": []},
        )
        snap["consent_mismatch_sms"] = rows
        result = evaluate_cc_02(_ctx(snap))
        mismatches = (result.provenance or {}).get("mismatches") or []
        plan = [m for m in mismatches if m.get("side") in ("out_in", "in_out")]
        self.assertEqual(len(plan), CC_SAMPLE + 5)
        self.assertTrue(
            all(m.get("proposed_action") == "FORCE_PHONE_OPT_OUT" for m in plan)
        )


class Cc02MappingIntentTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB18M", slug="wb18-map")
        self.company = Company.objects.create(
            tenant=self.tenant, name="WB18 Map", domain="wb18-map.test"
        )

    def test_mapping_plan_only_and_two_const_ops(self):
        mapping = get_check_mapping("CC-02")
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
            fields = (o.get("from_evidence") or {}).get("fields") or {}
            self.assertIn("prior_optedOutPhone", fields)
            self.assertIn("phone", fields)

    def test_transform_builds_plan_intents(self):
        mapping = get_check_mapping("CC-02")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "out_in",
                    "channel": "sms",
                    "person.email": "out@ex.com",
                    "person.phone": "+15551111111",
                    "manago_contact_id": "m1",
                    "shopify_customer_id": "s1",
                    "proposed_action": "FORCE_PHONE_OPT_OUT",
                    "evidence_gate": "opt_out_wins",
                    "prior_optedOutPhone": False,
                },
                {
                    "side": "in_out",
                    "channel": "sms",
                    "person.email": "in@ex.com",
                    "person.phone": "+15552222222",
                    "manago_contact_id": "m2",
                    "shopify_customer_id": "s2",
                    "proposed_action": "FORCE_PHONE_OPT_IN",
                    "evidence_gate": "provenance_ok",
                    "prior_optedOutPhone": True,
                    "provenance_ok": True,
                },
                {
                    "side": "in_out",
                    "channel": "sms",
                    "person.email": "skip@ex.com",
                    "manago_contact_id": "m3",
                    "proposed_action": "SKIP_UNEVIDENCED",
                    "evidence_gate": "fail",
                    "prior_optedOutPhone": True,
                },
                {
                    "side": "consented_but_unreachable",
                    "person.email": "bad@ex.com",
                    "person.phone": "x",
                },
                {"side": "driver", "note": "ignore"},
            ],
        )
        plan = [i for i in intents if (i.payload or {}).get("mode") == "plan"]
        self.assertEqual(len(plan), 3)
        actions = {i.payload.get("proposed_action") for i in plan}
        self.assertEqual(
            actions,
            {"FORCE_PHONE_OPT_OUT", "FORCE_PHONE_OPT_IN", "SKIP_UNEVIDENCED"},
        )
        for intent in plan:
            self.assertEqual(intent.op_kind, "contact_upsert")
            self.assertTrue(str(intent.payload.get("email") or "").strip())
            self.assertIn("prior_optedOutPhone", intent.payload)
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
            WritebackAllowedCheck.objects.filter(check_id="CC-02", enabled=True).exists()
        )


@override_settings(WRITEBACKS_ENABLED=False)
class Cc02PipelinePlanOnlyTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB18P", slug="wb18-pipe")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="WB18 Pipe",
            domain="wb18-pipe.test",
            writeback_execute_enabled=True,
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
        )

    def test_execute_blocked_cc02_plan_only(self):
        result = run_writeback_pipeline(
            company=self.company,
            check_id="CC-02",
            mode="execute",
            max_rows=CC_SAMPLE,
            intents=None,
        )
        self.assertEqual(result.blocked_reason, "cc02_plan_only")
        self.assertNotEqual(result.blocked_reason, "cc01_plan_only")
        detail = writeback_execute_denial_detail("cc02_plan_only")
        self.assertIn("Data lead", detail)
        self.assertIn("forcePhoneOpt", detail)

    def test_messages_and_sample_constant(self):
        self.assertEqual(CC_SAMPLE, 50)
        self.assertIn(
            "plan-only", writeback_execute_denial_detail("cc02_plan_only").lower()
        )

    def test_preview_default_max_rows_is_cc_sample(self):
        result = run_writeback_pipeline(
            company=self.company,
            check_id="CC-02",
            mode="preview",
            max_rows=None,
            intents=None,
        )
        self.assertIsNone(result.blocked_reason)
        self.assertEqual(result.check_id, "CC-02")
        self.assertLessEqual(len(result.intents), CC_SAMPLE)
