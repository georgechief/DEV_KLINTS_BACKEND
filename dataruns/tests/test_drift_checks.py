"""DRIFT checks (all 14) — PRD-DCS-05."""

from __future__ import annotations

from django.test import SimpleTestCase

from dataruns.dcs.executors.drift import (
    DRIFT_EXECUTORS,
    evaluate_br_02,
    evaluate_br_12,
    evaluate_cc_12,
    evaluate_ci_13,
    evaluate_ci_14,
    evaluate_ci_15,
    evaluate_le_08,
    evaluate_le_11,
    evaluate_le_13,
    evaluate_me_08,
    evaluate_me_09,
    evaluate_pt_14,
    evaluate_sp_08,
    evaluate_sp_12,
)
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.executors.registry import get_executor


def _ctx(snapshot: dict, *, erp_in_scope: bool = False) -> FoundationGateContext:
    return FoundationGateContext(
        tenant_id="t1",
        run_id="r1",
        evaluated_at="2026-08-03T12:00:00Z",
        erp_in_scope=erp_in_scope,
        extra={"scoring_snapshot": snapshot},
    )


def _snap(drift: dict, **extra) -> dict:
    payload = {
        "connectors": {
            "shopify": {"status": "connected"},
            "manago_ai": {"status": "connected"},
        },
        "drift": drift,
    }
    payload.update(extra)
    return payload


class DriftRegistryTests(SimpleTestCase):
    def test_fourteen_registered(self):
        expected = {
            "CI-13",
            "CI-14",
            "CI-15",
            "LE-08",
            "LE-11",
            "LE-13",
            "PT-14",
            "SP-08",
            "SP-12",
            "CC-12",
            "ME-08",
            "ME-09",
            "BR-02",
            "BR-12",
        }
        self.assertEqual(set(DRIFT_EXECUTORS), expected)
        for cid in expected:
            self.assertIsNotNone(get_executor(cid))


class Ci13Tests(SimpleTestCase):
    def test_pass_low_dead_share(self):
        result = evaluate_ci_13(
            _ctx(
                _snap(
                    {
                        "contacts_scanned": 100,
                        "ci13_state_distribution": {
                            "opt_in": 90,
                            "opt_out": 8,
                            "blocked": 2,
                        },
                        "ci13_dead_share": 0.02,
                        "ci13_opt_out_share": 0.08,
                    }
                )
            )
        )
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.confidence, "MEDIUM")

    def test_fail_40_percent_blocked(self):
        result = evaluate_ci_13(
            _ctx(
                _snap(
                    {
                        "contacts_scanned": 100,
                        "ci13_state_distribution": {"blocked": 40, "opt_in": 60},
                        "ci13_dead_share": 0.40,
                        "ci13_opt_out_share": 0,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-08")


class Ci15Tests(SimpleTestCase):
    def test_fail_stale_majority(self):
        result = evaluate_ci_15(
            _ctx(
                _snap(
                    {
                        "ci15_modified_with_ts": 100,
                        "ci15_stale_modified_count": 60,
                        "ci15_stale_modified_share": 0.60,
                        "ci15_stale_months": 24,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")

    def test_unknown_without_timestamps(self):
        result = evaluate_ci_15(_ctx(_snap({"ci15_modified_with_ts": 0})))
        self.assertEqual(result.status, "UNKNOWN")


class Le08Tests(SimpleTestCase):
    def test_unknown_without_carts(self):
        result = evaluate_le_08(_ctx(_snap({"le08_cart_events": 0})))
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:cart_events")

    def test_fail_stale_carts(self):
        result = evaluate_le_08(
            _ctx(
                _snap(
                    {
                        "le08_cart_events": 20,
                        "le08_open_stale_carts": 8,
                        "le08_stale_cart_share": 0.40,
                        "le08_stale_days": 14,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")


class Le13Tests(SimpleTestCase):
    def test_pass_stable_volume(self):
        result = evaluate_le_13(
            _ctx(
                _snap(
                    {
                        "le13_manago_7d": 10,
                        "le13_manago_prior_21d": 30,
                        "le13_shopify_7d": 10,
                        "le13_shopify_orders_7d": 8,
                        "le13_shopify_checkouts_7d": 2,
                        "le13_shopify_prior_21d": 30,
                        "le13_manago_self_delta": 0.0,
                        "le13_cross_7d_delta": 0.0,
                        "le13_prior_cross_delta": None,
                    }
                )
            )
        )
        self.assertEqual(result.status, "PASS")

    def test_warn_at_three_percent(self):
        """Excel LE-13 BI: drift caught at ~3%."""
        result = evaluate_le_13(
            _ctx(
                _snap(
                    {
                        "le13_manago_7d": 10,
                        "le13_manago_prior_21d": 30,
                        "le13_shopify_7d": 10,
                        "le13_shopify_prior_21d": 30,
                        "le13_manago_self_delta": 0.05,
                        "le13_cross_7d_delta": 0.0,
                        "le13_prior_cross_delta": None,
                    }
                )
            )
        )
        self.assertEqual(result.status, "WARN")

    def test_fail_large_self_delta(self):
        result = evaluate_le_13(
            _ctx(
                _snap(
                    {
                        "le13_manago_7d": 2,
                        "le13_manago_prior_21d": 60,
                        "le13_shopify_7d": 20,
                        "le13_shopify_prior_21d": 60,
                        "le13_manago_self_delta": 0.90,
                        "le13_cross_7d_delta": 0.80,
                        "le13_prior_cross_delta": None,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")


class Pt14Tests(SimpleTestCase):
    def test_fail_unit_artifact(self):
        result = evaluate_pt_14(
            _ctx(
                _snap(
                    {
                        "pt14_manago_values_n": 10,
                        "pt14_shopify_values_n": 10,
                        "pt14_median_manago": 129900,
                        "pt14_median_shopify": 1299,
                        "pt14_median_ratio": 100.0,
                        "pt14_unit_artifact": True,
                        "pt14_truncation_suspect": False,
                        "pt14_huge_value_share": 0.5,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-13")

    def test_fail_truncation(self):
        result = evaluate_pt_14(
            _ctx(
                _snap(
                    {
                        "pt14_manago_values_n": 10,
                        "pt14_shopify_values_n": 10,
                        "pt14_median_manago": 100,
                        "pt14_median_shopify": 100.5,
                        "pt14_median_ratio": 0.995,
                        "pt14_unit_artifact": False,
                        "pt14_truncation_suspect": True,
                        "pt14_huge_value_share": 0.0,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")

    def test_pass_aligned_medians(self):
        result = evaluate_pt_14(
            _ctx(
                _snap(
                    {
                        "pt14_manago_values_n": 10,
                        "pt14_shopify_values_n": 10,
                        "pt14_median_manago": 100,
                        "pt14_median_shopify": 105,
                        "pt14_median_ratio": 0.95,
                        "pt14_unit_artifact": False,
                        "pt14_truncation_suspect": False,
                        "pt14_huge_value_share": 0.0,
                    }
                )
            )
        )
        self.assertEqual(result.status, "PASS")


class Sp08Tests(SimpleTestCase):
    def test_unknown_without_segments(self):
        result = evaluate_sp_08(
            _ctx(_snap({"sp08_tag_count": 0, "sp08_zero_population": 0}))
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:segments")

    def test_fail_all_contacts_tag(self):
        result = evaluate_sp_08(
            _ctx(
                _snap(
                    {
                        "sp08_tag_count": 2,
                        "sp08_zero_population": 0,
                        "sp08_all_contacts_tags": ["everyone"],
                        "sp08_all_contacts_tag_count": 1,
                        "sp08_shifted_count": 0,
                        "sp08_shift_unavailable": True,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")

    def test_fail_population_shift(self):
        result = evaluate_sp_08(
            _ctx(
                _snap(
                    {
                        "sp08_tag_count": 1,
                        "sp08_zero_population": 0,
                        "sp08_all_contacts_tags": [],
                        "sp08_shifted_count": 1,
                        "sp08_shifted_sample": [
                            {
                                "segment": "tag:vip",
                                "prev": 100,
                                "current": 20,
                                "delta": 0.8,
                            }
                        ],
                        "sp08_shift_unavailable": False,
                        "sp08_shift_threshold": 0.5,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")


class Ci13ClusterTests(SimpleTestCase):
    def test_warn_on_date_cluster_alone(self):
        result = evaluate_ci_13(
            _ctx(
                _snap(
                    {
                        "contacts_scanned": 100,
                        "ci13_state_distribution": {"blocked": 10, "opt_in": 90},
                        "ci13_dead_share": 0.10,
                        "ci13_opt_out_share": 0,
                        "ci13_dead_date_cluster": True,
                        "ci13_spike_day": "2026-08-01",
                        "ci13_spike_count": 8,
                        "ci13_spike_share_of_dead": 0.8,
                    }
                )
            )
        )
        self.assertEqual(result.status, "WARN")


class Ci15PairTests(SimpleTestCase):
    def test_fail_stale_linked_pairs(self):
        result = evaluate_ci_15(
            _ctx(
                _snap(
                    {
                        "ci15_modified_with_ts": 100,
                        "ci15_stale_modified_count": 5,
                        "ci15_stale_modified_share": 0.05,
                        "ci15_stale_months": 24,
                        "ci15_linked_pairs": 40,
                        "ci15_pair_stale_count": 25,
                        "ci15_pair_stale_share": 0.625,
                        "ci15_pair_lag_days_median": 45,
                        "ci15_pair_lag_sla_days": 30,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")


class Cc12Tests(SimpleTestCase):
    def test_pass_fresh_consent(self):
        result = evaluate_cc_12(
            _ctx(
                _snap(
                    {
                        "cc12_opted_in": 50,
                        "cc12_consent_with_ts": 50,
                        "cc12_stale_consent_count": 2,
                        "cc12_stale_consent_share": 0.04,
                        "cc12_stale_months": 24,
                        "cc12_policy_version_count": 1,
                        "cc12_policy_versions": {"v1": 50},
                    }
                )
            )
        )
        self.assertEqual(result.status, "PASS")

    def test_warn_multi_policy(self):
        result = evaluate_cc_12(
            _ctx(
                _snap(
                    {
                        "cc12_opted_in": 50,
                        "cc12_consent_with_ts": 50,
                        "cc12_stale_consent_count": 2,
                        "cc12_stale_consent_share": 0.04,
                        "cc12_stale_months": 24,
                        "cc12_policy_version_count": 2,
                        "cc12_policy_versions": {"v1": 20, "v2": 30},
                    }
                )
            )
        )
        self.assertEqual(result.status, "WARN")

    def test_fail_stale_consent(self):
        result = evaluate_cc_12(
            _ctx(
                _snap(
                    {
                        "cc12_opted_in": 50,
                        "cc12_consent_with_ts": 50,
                        "cc12_stale_consent_count": 25,
                        "cc12_stale_consent_share": 0.50,
                        "cc12_stale_months": 24,
                        "cc12_policy_version_count": 1,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")

class Ci14Tests(SimpleTestCase):
    def test_fail_low_match(self):
        result = evaluate_ci_14(
            _ctx(_snap({"ci14_identity_match_rate": 0.10, "ci14_source": "visit_events", "ci14_visit_total": 100, "ci14_visit_identified": 10}))
        )
        self.assertEqual(result.status, "FAIL")

    def test_pass(self):
        result = evaluate_ci_14(
            _ctx(_snap({"ci14_identity_match_rate": 0.55, "ci14_source": "visit_events", "ci14_visit_total": 100, "ci14_visit_identified": 55}))
        )
        self.assertEqual(result.status, "PASS")


class Le11Tests(SimpleTestCase):
    def test_fail_race_loss(self):
        result = evaluate_le_11(
            _ctx(
                _snap(
                    {
                        "le11_lifecycle_events": 10,
                        "le11_race_loss_orders": 5,
                        "le11_race_loss_share": 0.40,
                        "le11_race_drop_risk_events": 0,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")

    def test_pass(self):
        result = evaluate_le_11(
            _ctx(
                _snap(
                    {
                        "le11_lifecycle_events": 10,
                        "le11_race_loss_orders": 0,
                        "le11_race_loss_share": 0.0,
                        "le11_race_drop_risk_events": 0,
                    }
                )
            )
        )
        self.assertEqual(result.status, "PASS")


class Sp12Tests(SimpleTestCase):
    def test_unknown_without_fields(self):
        result = evaluate_sp_12(_ctx(_snap({"sp12_decision_field_count": 0})))
        self.assertEqual(result.status, "UNKNOWN")

    def test_fail_stale(self):
        result = evaluate_sp_12(
            _ctx(
                _snap(
                    {
                        "sp12_decision_field_count": 10,
                        "sp12_stale_field_count": 6,
                        "sp12_stale_field_share": 0.60,
                        "sp12_archaeology_field_count": 0,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")


class Me08Tests(SimpleTestCase):
    def test_fail_not_computable(self):
        result = evaluate_me_08(
            _ctx(
                _snap(
                    {
                        "me08_paid_order_n": 5,
                        "me08_manago_purchase_n": 0,
                        "me08_history_ok": False,
                        "me08_volume_ok": False,
                        "me08_aov_ok": True,
                        "me08_repeat_ok": False,
                        "me08_baseline_computable": False,
                        "me08_min_history_days": 30,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")

    def test_pass(self):
        result = evaluate_me_08(
            _ctx(
                _snap(
                    {
                        "me08_paid_order_n": 40,
                        "me08_manago_purchase_n": 40,
                        "me08_history_ok": True,
                        "me08_volume_ok": True,
                        "me08_aov_ok": True,
                        "me08_repeat_ok": True,
                        "me08_baseline_computable": True,
                        "me08_min_history_days": 30,
                    }
                )
            )
        )
        self.assertEqual(result.status, "PASS")


class Me09Tests(SimpleTestCase):
    def test_unknown_without_invalid_field(self):
        result = evaluate_me_09(
            _ctx(_snap({"contacts_scanned": 10, "me09_invalid_field_seen": False}))
        )
        self.assertEqual(result.status, "UNKNOWN")

    def test_fail_invalid(self):
        result = evaluate_me_09(
            _ctx(
                _snap(
                    {
                        "contacts_scanned": 100,
                        "me09_invalid_field_seen": True,
                        "me09_invalid_share": 0.12,
                        "me09_dead_share": 0.05,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")

    def test_pass_from_email_stats(self):
        result = evaluate_me_09(
            _ctx(
                _snap(
                    {
                        "contacts_scanned": 0,
                        "me09_invalid_field_seen": False,
                        "me09_stats_available": True,
                        "me09_bounce_rate": 0.02,
                        "me09_hard_bounce_rate": 0.005,
                        "me09_email_sent": 1000,
                        "me09_dead_share": 0.01,
                    }
                )
            )
        )
        self.assertEqual(result.status, "PASS")

    def test_fail_from_bounce_rate(self):
        result = evaluate_me_09(
            _ctx(
                _snap(
                    {
                        "contacts_scanned": 10,
                        "me09_stats_available": True,
                        "me09_bounce_rate": 0.15,
                        "me09_email_sent": 500,
                        "me09_dead_share": 0.0,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")


class Br02Tests(SimpleTestCase):
    def test_not_connected_when_erp_out(self):
        result = evaluate_br_02(_ctx(_snap({}), erp_in_scope=False))
        self.assertEqual(result.status, "NOT_CONNECTED")
        self.assertEqual(result.reason_code, "ERP_OUT_OF_SCOPE")

    def test_fail_stale_when_erp_in(self):
        result = evaluate_br_02(
            _ctx(
                _snap(
                    {
                        "br02_shopify_inventory_n": 20,
                        "br02_manago_inventory_n": 10,
                        "br02_shopify_stale_share": 0.40,
                        "br02_manago_stale_share": 0.10,
                        "br02_sla_hours": 24,
                    }
                ),
                erp_in_scope=True,
            )
        )
        self.assertEqual(result.status, "FAIL")


class Br12Tests(SimpleTestCase):
    def test_not_connected_when_erp_out(self):
        result = evaluate_br_12(_ctx(_snap({}), erp_in_scope=False))
        self.assertEqual(result.status, "NOT_CONNECTED")

    def test_fail_stale_heartbeat(self):
        result = evaluate_br_12(
            _ctx(
                _snap(
                    {
                        "br12_domain_ages_hours": {"stock": 72.0, "prices": 10.0},
                        "br12_stalled_domains": [],
                    }
                ),
                erp_in_scope=True,
            )
        )
        self.assertEqual(result.status, "FAIL")
