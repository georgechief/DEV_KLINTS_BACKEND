"""Customer Identity CI-01/02/03/05 executor tests (Excel / PRD-DCS-04)."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.executors.identity import (
    evaluate_ci_01,
    evaluate_ci_02,
    evaluate_ci_03,
    evaluate_ci_05,
)
from dataruns.dcs.identity_join import build_identity_snapshot, normalize_email
from dataruns.models import Contact, Order
from tenants.models import Company, Tenant


def _ctx(snapshot: dict) -> FoundationGateContext:
    return FoundationGateContext(
        tenant_id="t1",
        run_id="r1",
        evaluated_at="2026-07-31T12:00:00Z",
        extra={"scoring_snapshot": snapshot},
    )


def _base_snapshot(**identity_overrides) -> dict:
    identity = {
        "shopify_customers": 100,
        "manago_contacts": 100,
        "in_both": 90,
        "manago_only": 10,
        "shopify_only": 10,
        "guest_orders": 5,
        "guest_orders_with_email": 5,
        "shopify_orders": 50,
        "manago_with_link_key": 80,
        "link_key_matched": 80,
        "link_key_dangling": [],
        "link_key_reused": [],
        "duplicate_clusters": {"email": [], "phone": [], "externalId": []},
    }
    identity.update(identity_overrides)
    return {
        "connectors": {
            "shopify": {"status": "connected"},
            "manago_ai": {"status": "connected"},
        },
        "identity": identity,
        "contacts": [],
        "orders": [],
    }


class NormalizeEmailTests(SimpleTestCase):
    def test_plus_alias_and_case(self):
        self.assertEqual(
            normalize_email("  Foo.Bar+promo@Example.COM "),
            "foo.bar@example.com",
        )


class EvaluateCi01Tests(SimpleTestCase):
    def test_pass_when_counts_close(self):
        result = evaluate_ci_01(_ctx(_base_snapshot()))
        self.assertEqual(result.status, "PASS")

    def test_fail_when_delta_large(self):
        result = evaluate_ci_01(
            _ctx(
                _base_snapshot(
                    manago_contacts=100,
                    shopify_customers=50,
                    in_both=40,
                    manago_only=60,
                    shopify_only=10,
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-01")

    def test_mismatches_list_real_contacts(self):
        snap = _base_snapshot(
            manago_contacts=14,
            shopify_customers=13,
            in_both=12,
            manago_only=1,
            shopify_only=0,
        )
        snap["contacts"] = [
            {
                "person.email": "both@example.com",
                "person.external_key": "1001",
                "source": "both",
                "shopify_customer_id": "1001",
                "manago_contact_id": "m-1",
            },
            {
                "person.email": "only.manago@example.com",
                "person.external_key": "",
                "source": "manago_ai",
                "shopify_customer_id": "",
                "manago_contact_id": "m-orphan",
            },
        ]
        result = evaluate_ci_01(_ctx(snap))
        self.assertEqual(result.status, "PASS")
        mismatches = (result.provenance or {}).get("mismatches") or []
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0]["side"], "manago_only")
        self.assertEqual(mismatches[0]["email"], "only.manago@example.com")
        self.assertEqual(mismatches[0]["manago_contact_id"], "m-orphan")
        sample = result.evidence[0].value["mismatch_contacts_sample"]
        self.assertEqual(sample[0]["email"], "only.manago@example.com")
        self.assertFalse(result.evidence[0].value["mismatch_contacts_truncated"])

        from dataruns.dcs.issues import build_issue_details

        details = build_issue_details(result)
        self.assertEqual(details["mismatches"][0]["email"], "only.manago@example.com")

    def test_truncation_flag_false_when_exactly_at_limit(self):
        from dataruns.dcs.executors.identity import (
            CI01_MISMATCH_SAMPLE,
            _ci01_contact_mismatches,
        )

        contacts = [
            {
                "person.email": f"m{i}@example.com",
                "source": "manago_ai",
                "manago_contact_id": f"m-{i}",
                "shopify_customer_id": "",
                "person.external_key": "",
            }
            for i in range(CI01_MISMATCH_SAMPLE)
        ]
        sample, truncated = _ci01_contact_mismatches({"contacts": contacts})
        self.assertEqual(len(sample), CI01_MISMATCH_SAMPLE)
        self.assertFalse(truncated)

        contacts.append(
            {
                "person.email": "extra@example.com",
                "source": "shopify",
                "manago_contact_id": "",
                "shopify_customer_id": "s-extra",
                "person.external_key": "",
            }
        )
        sample, truncated = _ci01_contact_mismatches({"contacts": contacts})
        self.assertEqual(len(sample), CI01_MISMATCH_SAMPLE)
        self.assertTrue(truncated)

    def test_unknown_without_both_platforms(self):
        snap = _base_snapshot()
        snap["connectors"]["manago_ai"] = {"status": "not_connected"}
        result = evaluate_ci_01(_ctx(snap))
        self.assertEqual(result.status, "UNKNOWN")


class EvaluateCi02Tests(SimpleTestCase):
    def test_pass_low_guest_share(self):
        result = evaluate_ci_02(_ctx(_base_snapshot()))
        self.assertEqual(result.status, "PASS")

    def test_warn_high_guest_share(self):
        result = evaluate_ci_02(
            _ctx(
                _base_snapshot(
                    shopify_orders=100,
                    guest_orders=55,
                    guest_orders_with_email=55,
                )
            )
        )
        self.assertEqual(result.status, "WARN")
        self.assertEqual(result.reason_code, "RC-03")

    def test_fail_guests_without_email(self):
        result = evaluate_ci_02(
            _ctx(
                _base_snapshot(
                    shopify_orders=100,
                    guest_orders=20,
                    guest_orders_with_email=10,
                )
            )
        )
        self.assertEqual(result.status, "FAIL")


class EvaluateCi03Tests(SimpleTestCase):
    def test_pass_no_duplicates(self):
        result = evaluate_ci_03(_ctx(_base_snapshot()))
        self.assertEqual(result.status, "PASS")

    def test_warn_on_email_cluster(self):
        result = evaluate_ci_03(
            _ctx(
                _base_snapshot(
                    manago_contacts=100,
                    duplicate_clusters={
                        "email": [{"key": "email", "value": "a@x.com", "count": 2}],
                        "phone": [],
                        "externalId": [],
                    },
                )
            )
        )
        self.assertEqual(result.status, "WARN")


class EvaluateCi05Tests(SimpleTestCase):
    def test_unknown_when_no_link_keys(self):
        result = evaluate_ci_05(
            _ctx(_base_snapshot(manago_with_link_key=0, link_key_matched=0))
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:person.external_key")

    def test_pass_high_coverage(self):
        result = evaluate_ci_05(_ctx(_base_snapshot()))
        self.assertEqual(result.status, "PASS")

    def test_fail_dangling_or_reused(self):
        result = evaluate_ci_05(
            _ctx(
                _base_snapshot(
                    manago_with_link_key=10,
                    link_key_matched=8,
                    link_key_dangling=["999"],
                    link_key_reused=[],
                )
            )
        )
        self.assertEqual(result.status, "FAIL")


class IdentityJoinDbTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="CI Tenant", slug="ci-tenant")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="CI Co",
            domain="ci.example",
        )

    def test_join_both_and_guest_order(self):
        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="1001",
            email="Same@Example.com",
            phone="",
        )
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="m-1",
            email="same@example.com",
            phone="",
            link_key="1001",
        )
        guest = Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="email:guest@example.com",
            email="guest@example.com",
        )
        Order.objects.create(
            company=self.company,
            contact=guest,
            source="shopify",
            external_id="o-guest",
            amount="12.00",
            currency="EUR",
            status="paid",
        )

        payload = build_identity_snapshot(company=self.company)
        identity = payload["identity"]
        self.assertEqual(identity["in_both"], 1)
        self.assertEqual(identity["shopify_only"], 1)
        self.assertEqual(identity["guest_orders"], 1)
        self.assertEqual(identity["link_key_matched"], 1)
        sources = {c["source"] for c in payload["contacts"]}
        self.assertIn("both", sources)
        self.assertIn("shopify", sources)
