"""Consent CC-01/02/03/05 + PT-04 tests (Excel sheet 02 / PRD-DCS-04 batch 4b)."""

from __future__ import annotations

from django.test import SimpleTestCase

from dataruns.dcs.consent_join import (
    _manago_email_in,
    _quadrant,
    _shopify_consent_in,
    build_consent_snapshot,
    phone_valid_e164_lite,
)
from dataruns.dcs.executors.consent import (
    evaluate_cc_01,
    evaluate_cc_02,
    evaluate_cc_03,
    evaluate_cc_05,
)
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.executors.product import evaluate_pt_04
from dataruns.dcs.product_truth import build_product_truth_snapshot


def _ctx(snapshot: dict) -> FoundationGateContext:
    return FoundationGateContext(
        tenant_id="t1",
        run_id="r1",
        evaluated_at="2026-07-31T12:00:00Z",
        extra={"scoring_snapshot": snapshot},
    )


def _consent_snap(**overrides) -> dict:
    consent = {
        "linked_identities": 10,
        "email_quadrant_matrix": {
            "in_in": 10,
            "in_out": 0,
            "out_in": 0,
            "out_out": 0,
            "unknown": 0,
        },
        "sms_quadrant_matrix": {
            "in_in": 10,
            "in_out": 0,
            "out_in": 0,
            "out_out": 0,
            "unknown": 0,
        },
        "email_mismatches": 0,
        "sms_mismatches": 0,
        "compliance_exposure_email": 0,
        "compliance_exposure_sms": 0,
        "lost_reach_email": 0,
        "lost_reach_sms": 0,
        "opted_in_manago_email": 5,
        "opted_in_with_provenance": 5,
        "opted_in_weak_or_missing_provenance": 0,
        "provenance_share": 1.0,
        "propagation": {
            "email_manago_out_shopify_in": 0,
            "email_shopify_out_manago_in": 0,
            "sms_manago_out_shopify_in": 0,
            "sms_shopify_out_manago_in": 0,
        },
        "email_field_coverage": {
            "opt_in_level_distribution": {"single_opt_in": 10},
            "consent_updated_at_present": 10,
            "consent_updated_at_share": 1.0,
        },
        "sms_phone_reachability": {
            "sms_consented_linked": 10,
            "consented_but_unreachable": 0,
        },
        "shopify_evidence_backfill_candidates": 0,
        "manago_only_unevidenced_optins": 0,
        "propagation_lag": {
            "measurable_pairs": 0,
            "median_seconds": None,
            "p95_seconds": None,
            "max_seconds": None,
        },
        "suppression": {
            "invalid_field_present": True,
            "manago_invalid_linked": 0,
            "invalid_still_subscribed_shopify": 0,
        },
        "mismatch_samples": {
            "email_in_out": [],
            "email_out_in": [],
            "sms_in_out": [],
            "sms_out_in": [],
            "weak_provenance": [],
            "shopify_holds_evidence": [],
            "manago_only_unevidenced": [],
            "consented_unreachable_sms": [],
            "invalid_still_in_shopify": [],
        },
        "hard_bounce_complaint_available": True,
        "raw_enrichment": {
            "shopify_customers_from_raw": True,
            "manago_contacts_from_raw": True,
            "consent_fields_present": True,
        },
    }
    consent.update(overrides)
    return {
        "connectors": {
            "shopify": {"status": "connected"},
            "manago_ai": {"status": "connected"},
        },
        "consent": consent,
    }


class ConsentHelpersTests(SimpleTestCase):
    def test_shopify_and_manago_consent_mapping(self):
        self.assertTrue(
            _shopify_consent_in({"state": "subscribed", "opt_in_level": "single_opt_in"})
        )
        self.assertFalse(_shopify_consent_in({"state": "not_subscribed"}))
        self.assertTrue(_manago_email_in({"optedOut": False}))
        self.assertFalse(_manago_email_in({"optedOut": True}))
        self.assertEqual(_quadrant(True, False), "in_out")
        self.assertEqual(_quadrant(False, True), "out_in")

    def test_phone_valid_e164_lite(self):
        self.assertTrue(phone_valid_e164_lite("+16135550127"))
        self.assertTrue(phone_valid_e164_lite("16135550127"))
        self.assertFalse(phone_valid_e164_lite(""))
        self.assertFalse(phone_valid_e164_lite("123"))


class EvaluateCc01Tests(SimpleTestCase):
    def test_pass_when_all_agree(self):
        result = evaluate_cc_01(_ctx(_consent_snap()))
        self.assertEqual(result.status, "PASS")
        self.assertIn(
            "opt_in_level_distribution",
            result.evidence[0].value,
        )

    def test_fail_compliance_out_in(self):
        result = evaluate_cc_01(
            _ctx(
                _consent_snap(
                    email_quadrant_matrix={
                        "in_in": 8,
                        "in_out": 0,
                        "out_in": 2,
                        "out_out": 0,
                        "unknown": 0,
                    },
                    email_mismatches=2,
                    compliance_exposure_email=2,
                    mismatch_samples={
                        "email_out_in": [
                            {
                                "person.email": "a@x.com",
                                "shopify_customer_id": "1",
                                "manago_contact_id": "m1",
                                "email_quadrant": "out_in",
                            }
                        ],
                        "email_in_out": [],
                        "sms_in_out": [],
                        "sms_out_in": [],
                        "weak_provenance": [],
                    },
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-07")
        self.assertEqual(
            result.provenance["mismatches"][0]["person.email"], "a@x.com"
        )


class EvaluateCc02Tests(SimpleTestCase):
    def test_fail_sms_mismatch(self):
        result = evaluate_cc_02(
            _ctx(
                _consent_snap(
                    sms_mismatches=1,
                    lost_reach_sms=1,
                    sms_quadrant_matrix={
                        "in_in": 9,
                        "in_out": 1,
                        "out_in": 0,
                        "out_out": 0,
                        "unknown": 0,
                    },
                )
            )
        )
        self.assertEqual(result.status, "FAIL")

    def test_pass_surfaces_unreachable_phone(self):
        result = evaluate_cc_02(
            _ctx(
                _consent_snap(
                    sms_phone_reachability={
                        "sms_consented_linked": 2,
                        "consented_but_unreachable": 1,
                    },
                    mismatch_samples={
                        "email_in_out": [],
                        "email_out_in": [],
                        "sms_in_out": [],
                        "sms_out_in": [],
                        "weak_provenance": [],
                        "shopify_holds_evidence": [],
                        "manago_only_unevidenced": [],
                        "consented_unreachable_sms": [
                            {
                                "person.email": "a@x.com",
                                "person.phone": "bad",
                                "shopify_customer_id": "1",
                                "manago_contact_id": "m1",
                                "phone_valid": False,
                            }
                        ],
                        "invalid_still_in_shopify": [],
                    },
                )
            )
        )
        self.assertEqual(result.status, "PASS")
        self.assertIn("consented-but-unreachable", result.message or "")
        self.assertEqual(
            result.provenance["mismatches"][0]["side"], "consented_but_unreachable"
        )


class EvaluateCc03Tests(SimpleTestCase):
    def test_fail_unevidenced_optins(self):
        result = evaluate_cc_03(
            _ctx(
                _consent_snap(
                    opted_in_manago_email=10,
                    opted_in_with_provenance=0,
                    opted_in_weak_or_missing_provenance=10,
                    provenance_share=0.0,
                    shopify_evidence_backfill_candidates=4,
                    manago_only_unevidenced_optins=6,
                    mismatch_samples={
                        "weak_provenance": [
                            {
                                "person.email": "a@x.com",
                                "manago_contact_id": "m1",
                                "provenance_note": "empty_consents_array",
                            }
                        ],
                        "email_in_out": [],
                        "email_out_in": [],
                        "sms_in_out": [],
                        "sms_out_in": [],
                        "shopify_holds_evidence": [
                            {
                                "person.email": "b@x.com",
                                "manago_contact_id": "m2",
                                "shopify_customer_id": "2",
                                "shopify_email_consent_updated_at": "2026-01-01T00:00:00Z",
                                "shopify_email_opt_in_level": "single_opt_in",
                            }
                        ],
                        "manago_only_unevidenced": [
                            {
                                "person.email": "c@x.com",
                                "manago_contact_id": "m3",
                                "provenance_note": "empty_consents_array",
                            }
                        ],
                        "consented_unreachable_sms": [],
                        "invalid_still_in_shopify": [],
                    },
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-08")
        self.assertIn("shopify_backfill=4", result.message or "")
        sides = {m["side"] for m in result.provenance["mismatches"]}
        self.assertIn("shopify_holds_evidence", sides)
        self.assertIn("manago_only_unevidenced", sides)


class EvaluateCc05Tests(SimpleTestCase):
    def test_fail_propagation_gap(self):
        result = evaluate_cc_05(
            _ctx(
                _consent_snap(
                    propagation={
                        "email_manago_out_shopify_in": 3,
                        "email_shopify_out_manago_in": 0,
                        "sms_manago_out_shopify_in": 0,
                        "sms_shopify_out_manago_in": 0,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-01")

    def test_fail_invalid_still_subscribed(self):
        result = evaluate_cc_05(
            _ctx(
                _consent_snap(
                    suppression={
                        "invalid_field_present": True,
                        "manago_invalid_linked": 2,
                        "invalid_still_subscribed_shopify": 1,
                    },
                    mismatch_samples={
                        "email_in_out": [],
                        "email_out_in": [],
                        "sms_in_out": [],
                        "sms_out_in": [],
                        "weak_provenance": [],
                        "shopify_holds_evidence": [],
                        "manago_only_unevidenced": [],
                        "consented_unreachable_sms": [],
                        "invalid_still_in_shopify": [
                            {
                                "person.email": "a@x.com",
                                "shopify_customer_id": "1",
                                "manago_contact_id": "m1",
                                "manago_invalid": True,
                            }
                        ],
                    },
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertIn("invalid_still_subscribed_shopify=1", result.message or "")

    def test_warn_when_suppression_stream_missing(self):
        result = evaluate_cc_05(
            _ctx(_consent_snap(hard_bounce_complaint_available=False))
        )
        self.assertEqual(result.status, "WARN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:suppression_events")

    def test_warn_high_propagation_lag(self):
        result = evaluate_cc_05(
            _ctx(
                _consent_snap(
                    propagation_lag={
                        "measurable_pairs": 2,
                        "median_seconds": 90000,
                        "p95_seconds": 100000,
                        "max_seconds": 120000,
                    }
                )
            )
        )
        self.assertEqual(result.status, "WARN")
        self.assertEqual(result.reason_code, "RC-05")
        self.assertIn("propagation lag", result.message or "")

class EvaluatePt04Tests(SimpleTestCase):
    def test_fail_overstatement(self):
        snap = {
            "connectors": {
                "shopify": {"status": "connected"},
                "manago_ai": {"status": "connected"},
            },
            "product_truth": {
                "linked_contacts": 2,
                "contacts_over_delta": 1,
                "contacts_refund_blind": 1,
                "total_overstatement": 50.0,
                "fail_delta": 0.02,
                "failing_sample": [
                    {
                        "person.email": "a@x.com",
                        "shopify_customer_id": "1",
                        "manago_contact_id": "m1",
                        "shopify_net": 50,
                        "manago_purchase_value_deduped": 100,
                        "delta_vs_net": 0.5,
                        "refund_blind": True,
                        "overstatement": 50,
                    }
                ],
                "refund_blind_sample": [],
                "raw_enrichment": {
                    "shopify_from_raw": True,
                    "manago_from_raw": True,
                },
            },
        }
        result = evaluate_pt_04(_ctx(snap))
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.provenance["mismatches"][0]["overstatement"], 50)


class ConsentJoinUnitTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_build_from_mocked_raw(self):
        from unittest.mock import patch
        from types import SimpleNamespace

        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform):
            if platform == "shopify":
                return {
                    "customers": [
                        {
                            "id": 101,
                            "email": "A@X.com",
                            "email_marketing_consent": {
                                "state": "subscribed",
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
                        "contactId": "m1",
                        "externalId": "101",
                        "email": "a@x.com",
                        "phone": "+16135550127",
                        "optedOut": True,
                        "optedOutPhone": True,
                        "invalid": True,
                        "modifiedOn": 1735689600000,  # 2025-01-01
                        "consents": [],
                    },
                    {
                        "contactId": "m2",
                        "externalId": "102",
                        "email": "b@x.com",
                        "phone": "bad",
                        "optedOut": False,
                        "optedOutPhone": False,
                        "invalid": False,
                        "consents": [],
                    },
                ]
            }

        with patch(
            "dataruns.dcs.consent_join._latest_connector_raw", side_effect=fake_raw
        ):
            payload = build_consent_snapshot(company=company)
        consent = payload["consent"]
        self.assertEqual(consent["linked_identities"], 1)
        self.assertEqual(consent["email_quadrant_matrix"]["in_out"], 1)
        self.assertEqual(consent["compliance_exposure_email"], 0)
        self.assertEqual(consent["lost_reach_email"], 1)
        self.assertTrue(consent["hard_bounce_complaint_available"])
        self.assertEqual(consent["suppression"]["invalid_still_subscribed_shopify"], 1)
        self.assertGreaterEqual(consent["propagation_lag"]["measurable_pairs"], 1)
        # m2 opted-in with empty consents, linked? not linked (no shopify 102) —
        # shopify evidence cohort uses linked only; manago-only unevidenced includes m2
        self.assertGreaterEqual(consent["manago_only_unevidenced_optins"], 1)
        self.assertEqual(
            consent["email_field_coverage"]["opt_in_level_distribution"].get(
                "single_opt_in"
            ),
            1,
        )


class ProductTruthUnitTests(SimpleTestCase):
    def test_net_vs_manago_deduped(self):
        from unittest.mock import patch
        from types import SimpleNamespace

        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform):
            if platform == "shopify":
                return {
                    "customers": [{"id": 101, "email": "a@x.com"}],
                    "orders": [
                        {
                            "id": 1,
                            "customer": {"id": 101, "email": "a@x.com"},
                            "financial_status": "paid",
                            "total_price": "100.00",
                            "test": False,
                        },
                        {
                            "id": 2,
                            "customer": {"id": 101},
                            "financial_status": "refunded",
                            "total_price": "40.00",
                            "test": False,
                        },
                    ],
                }
            return {
                "contacts": [
                    {
                        "contactId": "m1",
                        "externalId": "101",
                        "email": "a@x.com",
                    }
                ],
                "transactions": [
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m1",
                        "externalId": "1",
                        "value": 100,
                    },
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m1",
                        "externalId": "1",
                        "value": 100,
                    },
                ],
            }

        with patch(
            "dataruns.dcs.product_truth._latest_connector_raw", side_effect=fake_raw
        ):
            payload = build_product_truth_snapshot(company=company)
        truth = payload["product_truth"]
        self.assertEqual(truth["linked_contacts"], 1)
        row = payload["product_truth_rows"][0]
        self.assertEqual(row["shopify_net"], 60.0)  # 100 - 40
        self.assertEqual(row["manago_purchase_value_deduped"], 100.0)
        self.assertTrue(row["refund_blind"])
        self.assertEqual(truth["contacts_over_delta"], 1)

    def test_dedupe_events_without_external_id(self):
        """Events missing externalId/transactionId must not inflate deduped value."""
        from unittest.mock import patch
        from types import SimpleNamespace

        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform):
            if platform == "shopify":
                return {
                    "customers": [{"id": 101, "email": "a@x.com"}],
                    "orders": [
                        {
                            "id": 1,
                            "customer": {"id": 101, "email": "a@x.com"},
                            "financial_status": "paid",
                            "total_price": "50.00",
                            "test": False,
                        }
                    ],
                }
            return {
                "contacts": [
                    {"contactId": "m1", "externalId": "101", "email": "a@x.com"}
                ],
                "transactions": [
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m1",
                        "date": "2026-01-15T10:00:00Z",
                        "value": 50,
                    },
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m1",
                        "date": "2026-01-15T10:00:00Z",
                        "value": 50,
                    },
                ],
            }

        with patch(
            "dataruns.dcs.product_truth._latest_connector_raw", side_effect=fake_raw
        ):
            payload = build_product_truth_snapshot(company=company)
        row = payload["product_truth_rows"][0]
        self.assertEqual(row["manago_purchase_value_all"], 100.0)
        self.assertEqual(row["manago_purchase_value_deduped"], 50.0)
