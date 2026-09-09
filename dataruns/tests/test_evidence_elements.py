"""PRD-FE-11 — evidence element enrichment tests."""

from django.test import TestCase

from dataruns.dcs.evidence_elements import enrich_evidence_element
from dataruns.dcs.worklist import _normalize_evidence_item


class EvidenceElementsTests(TestCase):
    def test_ci13_bare_mismatch_gets_element_metadata(self):
        item = {"side": "dead_state", "bucket": "blocked", "count": 3}
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="CI-13"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["source"], "manago_ai")
        self.assertEqual(normalized["entity"], "contact")
        self.assertEqual(normalized["element"], "contact.state")
        self.assertIn("Contact state", normalized["element_label"])
        self.assertIn("blocked", normalized["element_label"])
        self.assertNotEqual(normalized.get("locator"), "—")
        self.assertEqual(normalized.get("locator"), "")

    def test_ci13_dead_date_cluster_side_label(self):
        item = {"side": "dead_date_cluster", "day": "2026-01-15", "count": 5}
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="CI-13"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(
            normalized["element_label"], "Contact state spike day"
        )

    def test_field_level_db_key_resolves_api_key(self):
        item = {
            "source": "manago_ai",
            "db_key": "email",
            "entity": "contact",
            "value": {"email": "a@example.com"},
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="CI-01"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["api_key"], "email")
        self.assertEqual(normalized["db_key"], "email")
        self.assertEqual(normalized["element"], "contact.email")

    def test_ci01_manago_only_side_sets_source(self):
        item = {
            "side": "manago_only",
            "email": "x@example.com",
            "manago_contact_id": "123",
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="CI-01"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["source"], "manago_ai")
        self.assertEqual(normalized["entity"], "contact")
        self.assertEqual(normalized["api_key"], "email")
        self.assertEqual(normalized["element"], "contact.email")
        self.assertEqual(normalized["element_label"], "Contact (Manago only)")
        self.assertNotEqual(normalized["element"], normalized["element_label"])

    def test_drift_locator_gets_element_label(self):
        item = {
            "source": "manago_ai",
            "locator": "drift.contact_state_distribution",
            "value": {"dead_share": 0.12},
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="CI-13"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(
            normalized["element_label"], "Contact state distribution"
        )

    def test_does_not_overwrite_executor_element(self):
        item = {
            "side": "dead_state",
            "element": "custom.element",
            "element_label": "Custom label",
            "api_key": "status",
            "db_key": "status",
            "entity": "order",
        }
        base = {
            "source": "shopify",
            "locator": "",
            "observed_at": "",
            "value": {"side": "dead_state", "count": 1},
        }
        enriched = enrich_evidence_element("CI-13", item, base)
        self.assertEqual(enriched["element"], "custom.element")
        self.assertEqual(enriched["element_label"], "Custom label")
        self.assertEqual(enriched["api_key"], "status")
        self.assertEqual(enriched["entity"], "order")

    def test_le04_duplicate_purchase_side_metadata(self):
        item = {"side": "duplicate_purchase", "count": 3}
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="LE-04"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["entity"], "order")
        self.assertEqual(normalized["element"], "lifecycle.duplicate_purchase")
        self.assertEqual(normalized["source"], "snapshot")
        self.assertEqual(normalized["element_label"], "Duplicate purchase events")

    def test_pt04_net_overstatement_email_map(self):
        item = {
            "side": "net_overstatement",
            "person.email": "buyer@example.com",
            "overstatement": 120.0,
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="PT-04"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["db_key"], "email")
        self.assertIn("Net overstatement", normalized["element_label"])

    def test_sp07_collision_source_is_manago(self):
        item = {"side": "klints_detail_collision", "key": "klints_vip"}
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="SP-07"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["source"], "manago_ai")
        self.assertEqual(
            normalized["element_label"], "Manago detail key collision"
        )

    def test_fd02_scopes_use_check_default_label(self):
        item = {
            "source": "shopify",
            "locator": "bootstrap:data_run:preflight.scopes",
            "value": {"missing": ["read_customers"]},
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="FD-02"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["element_label"], "Shopify API scopes")
        self.assertEqual(normalized["source"], "shopify")


class EvidenceElementsFe11bTests(TestCase):
    """PRD-FE-11B — Elements identity is {entity}.{api_key} from map.json."""

    def test_shopify_order_amount_uses_total_price(self):
        item = {
            "source": "shopify",
            "entity": "order",
            "db_key": "amount",
            "value": {"total_price": "42.00"},
            "locator": "—",
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="LE-02"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["api_key"], "total_price")
        self.assertEqual(normalized["element"], "order.total_price")
        self.assertEqual(normalized["db_key"], "amount")
        self.assertEqual(normalized["locator"], "")
        self.assertNotEqual(normalized["element"], normalized.get("element_label"))

    def test_manago_order_amount_uses_value(self):
        item = {
            "source": "manago_ai",
            "entity": "order",
            "db_key": "amount",
            "value": {"value": 42.0},
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="LE-02"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["api_key"], "value")
        self.assertEqual(normalized["element"], "order.value")
        self.assertEqual(normalized["db_key"], "amount")

    def test_same_db_key_amount_differs_by_platform(self):
        shared = {"entity": "order", "db_key": "amount", "value": {"amount": 10}}
        shopify = _normalize_evidence_item(
            {**shared, "source": "shopify"},
            truncate=False,
            check_id="LE-02",
        )
        manago = _normalize_evidence_item(
            {**shared, "source": "manago_ai"},
            truncate=False,
            check_id="LE-02",
        )
        self.assertIsNotNone(shopify)
        self.assertIsNotNone(manago)
        assert shopify is not None and manago is not None
        self.assertEqual(shopify["api_key"], "total_price")
        self.assertEqual(manago["api_key"], "value")
        self.assertEqual(shopify["element"], "order.total_price")
        self.assertEqual(manago["element"], "order.value")

    def test_ci01_shopify_email_is_contact_email(self):
        item = {
            "side": "shopify_only",
            "email": "buyer@example.com",
            "shopify_customer_id": "1",
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="CI-01"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["source"], "shopify")
        self.assertEqual(normalized["entity"], "contact")
        self.assertEqual(normalized["api_key"], "email")
        self.assertEqual(normalized["element"], "contact.email")
        self.assertEqual(normalized["element_label"], "Contact (Shopify only)")

    def test_ci01_manago_email_is_contact_email(self):
        item = {
            "side": "manago_only",
            "email": "buyer@example.com",
            "manago_contact_id": "abc",
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="CI-01"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["source"], "manago_ai")
        self.assertEqual(normalized["api_key"], "email")
        self.assertEqual(normalized["element"], "contact.email")

    def test_manago_transaction_id_uses_map_api_key(self):
        item = {
            "source": "manago_ai",
            "value": {"transactionId": "txn_9"},
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="LE-02"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["entity"], "order")
        self.assertEqual(normalized["db_key"], "external_id")
        self.assertEqual(normalized["api_key"], "transactionId")
        self.assertEqual(normalized["element"], "order.transactionId")

    def test_ci13_dead_state_has_no_invented_api_key(self):
        item = {"side": "dead_state", "bucket": "blocked", "count": 3}
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="CI-13"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["element"], "contact.state")
        self.assertFalse(bool(normalized.get("api_key")))
        self.assertNotEqual(normalized["element"], normalized["element_label"])
        self.assertIn("Contact state", normalized["element_label"])

    def test_infer_amount_from_total_price_without_db_key(self):
        item = {
            "source": "shopify",
            "value": {"total_price": "19.99"},
        }
        normalized = _normalize_evidence_item(
            item, truncate=False, check_id="LE-02"
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["entity"], "order")
        self.assertEqual(normalized["db_key"], "amount")
        self.assertEqual(normalized["api_key"], "total_price")
        self.assertEqual(normalized["element"], "order.total_price")
