"""Round-trip tests for connector map.json reverse mapping (PRD-WB-01 §11)."""

from django.test import TestCase

from dataruns.connectors.mapping import (
    UnmappedFieldError,
    load_connector_map,
    map_api_to_db,
    map_db_to_api,
    mappings_for_entity,
    reverse_map_record,
)


class ConnectorReverseMapTests(TestCase):
    def test_shopify_contact_round_trip(self):
        connector_map = load_connector_map("shopify")
        mappings = mappings_for_entity(connector_map, "contact")
        api_item = {
            "id": "gid://shopify/Customer/123",
            "email": "buyer@example.com",
            "phone": "+353871234567",
            "created_at": "2026-01-15T10:00:00Z",
        }
        db_record = map_api_to_db(api_item, mappings, connector_map.get("status_map"))
        self.assertEqual(db_record["external_id"], api_item["id"])
        self.assertEqual(db_record["email"], api_item["email"])

        api_out = map_db_to_api(
            db_record,
            mappings,
            status_map=connector_map.get("status_map"),
        )
        self.assertEqual(api_out["id"], api_item["id"])
        self.assertEqual(api_out["email"], api_item["email"])
        self.assertEqual(api_out["phone"], api_item["phone"])

    def test_shopify_order_nested_customer_id_round_trip(self):
        connector_map = load_connector_map("shopify")
        mappings = mappings_for_entity(connector_map, "order")
        api_item = {
            "id": "gid://shopify/Order/999",
            "total_price": "42.50",
            "currency": "EUR",
            "financial_status": "paid",
            "customer": {"id": "gid://shopify/Customer/123"},
            "created_at": "2026-01-16T12:00:00Z",
        }
        db_record = map_api_to_db(api_item, mappings, connector_map.get("status_map"))
        self.assertEqual(db_record["contact_external_id"], "gid://shopify/Customer/123")
        self.assertEqual(db_record["status"], "paid")

        api_out = map_db_to_api(
            db_record,
            mappings,
            status_map=connector_map.get("status_map"),
        )
        self.assertEqual(api_out["customer"]["id"], "gid://shopify/Customer/123")
        self.assertEqual(api_out["financial_status"], "paid")

    def test_manago_order_status_round_trip(self):
        connector_map = load_connector_map("manago_ai")
        mappings = mappings_for_entity(connector_map, "order")
        api_item = {
            "transactionId": "tx-1",
            "value": 19.99,
            "currency": "EUR",
            "email": "buyer@example.com",
            "date": 1700000000000,
            "contactExtEventType": "PURCHASE",
        }
        db_record = map_api_to_db(api_item, mappings, connector_map.get("status_map"))
        self.assertEqual(db_record["status"], "paid")

        api_out = map_db_to_api(
            db_record,
            mappings,
            status_map=connector_map.get("status_map"),
        )
        self.assertEqual(api_out["contactExtEventType"], "PURCHASE")

    def test_reverse_map_record_with_extras(self):
        api_out = reverse_map_record(
            {"email": "a@b.com", "external_id": "c-1"},
            platform="manago_ai",
            entity="contact",
            extras={"contactId": "c-1", "properties": {"klints_wb_test": "1"}},
        )
        self.assertEqual(api_out["email"], "a@b.com")
        self.assertEqual(api_out["contactId"], "c-1")
        self.assertEqual(api_out["properties"]["klints_wb_test"], "1")

    def test_required_unmapped_field_raises(self):
        connector_map = load_connector_map("shopify")
        mappings = mappings_for_entity(connector_map, "contact")
        with self.assertRaises(UnmappedFieldError) as ctx:
            map_db_to_api(
                {"klints_cohort": "vip"},
                mappings,
                required_db_keys={"klints_cohort"},
            )
        self.assertEqual(ctx.exception.db_key, "klints_cohort")
