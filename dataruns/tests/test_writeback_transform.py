"""Transform tests — evidence rows to write intents."""

import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from dataruns.models import Contact, Order
from dataruns.writebacks.registry import MappingDisabled, get_check_mapping
from dataruns.writebacks.transform import (
    build_intents_from_mapping,
    collect_evidence_rows,
)
from tenants.models import Company, Tenant


class WritebackTransformTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="T", slug="wb-transform")
        self.company = Company.objects.create(
            tenant=tenant,
            name="Co",
            domain="wb-transform.test",
        )

    def test_ci01_shopify_only_row_builds_contact_upsert(self):
        mapping = get_check_mapping("CI-01")
        rows = [
            {
                "side": "shopify_only",
                "email": "buyer@example.com",
                "shopify_customer_id": "gid://shopify/Customer/1",
            }
        ]
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=rows,
        )
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.op_kind, "contact_upsert")
        self.assertEqual(intent.status, "ready")
        self.assertEqual(intent.payload.get("email"), "buyer@example.com")

    def test_cc03_shopify_holds_evidence_builds_detail_set(self):
        mapping = get_check_mapping("CC-03")
        rows = [
            {
                "side": "shopify_holds_evidence",
                "person.email": "consent@example.com",
                "manago_contact_id": "mc-99",
            }
        ]
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=rows,
        )
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.op_kind, "detail_set")
        self.assertEqual(intent.after.get("klints_consent_evidence"), "shopify_verified")

    def test_le04_duplicate_purchase_builds_tag_add_from_disabled_mapping_file(self):
        """LE-04 stays in repo for transform/rollback unit coverage but registry is disabled."""
        with self.assertRaises(MappingDisabled):
            get_check_mapping("LE-04")

        path = (
            Path(__file__).resolve().parents[1]
            / "writebacks"
            / "mappings"
            / "LE-04.duplicate_purchase.v1.json"
        )
        mapping = json.loads(path.read_text(encoding="utf-8"))
        rows = [
            {
                "side": "duplicate_purchase",
                "order.id": "order-123",
                "count": 2,
            }
        ]
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=rows,
        )
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.op_kind, "tag_add")
        self.assertEqual(intent.payload.get("tag"), "klints:duplicate_review")

    def test_wb_shop_01_builds_customer_note_update(self):
        mapping = get_check_mapping("WB-SHOP-01")
        rows = [
            {
                "side": "sandbox_customer_note",
                "email": "buyer@example.com",
                "shopify_customer_id": "gid://shopify/Customer/999",
            }
        ]
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=rows,
        )
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.op_kind, "shopify_customer_update")
        self.assertEqual(intent.target_system, "shopify")
        self.assertEqual(intent.payload.get("id"), "999")
        self.assertEqual(intent.payload.get("note"), "klints_wb_test")
        self.assertEqual(intent.rollback_strategy, "restore_prior_field")

    def test_le01_shopify_only_builds_event_ingest(self):
        """WB-08 Phase 1/2: match shopify_only + amount_gross (not missing_purchase_event)."""
        mapping = get_check_mapping("LE-01")
        rows = [
            {
                "side": "shopify_only",
                "order.id": "501",
                "person.email": "buyer@example.com",
                "manago_contact_id": "mc-1",
                "amount_gross": 99.5,
            }
        ]
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=rows,
        )
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.op_kind, "event_ingest")
        self.assertEqual(intent.status, "ready")
        self.assertEqual(intent.payload.get("externalId"), "501")
        self.assertEqual(intent.payload.get("email"), "buyer@example.com")
        self.assertEqual(intent.payload.get("contactId"), "mc-1")
        self.assertEqual(intent.payload.get("value"), 99.5)

    def test_le01_ignores_legacy_missing_purchase_event_side(self):
        mapping = get_check_mapping("LE-01")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "missing_purchase_event",
                    "order.id": "legacy",
                    "person.email": "x@y.com",
                }
            ],
        )
        self.assertEqual(intents, [])

    def test_le01_missing_email_is_error_not_ready(self):
        mapping = get_check_mapping("LE-01")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only",
                    "order.id": "orphan-1",
                    "amount_gross": 1.0,
                }
            ],
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].status, "error")
        self.assertEqual(intents[0].error_reason, "missing_contact_reference")

    def test_sp01_tag_consolidation_stays_disabled_not_mvp1_42(self):
        with self.assertRaises(MappingDisabled):
            get_check_mapping("SP-01")

        path = (
            Path(__file__).resolve().parents[1]
            / "writebacks"
            / "mappings"
            / "SP-01.tag_consolidation.v1.json"
        )
        mapping = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(mapping.get("enabled"))
        self.assertEqual(mapping.get("operations"), [])

    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    @patch("dataruns.writebacks.transform.find_manago_contact")
    def test_le01_collect_enriches_shopify_only_from_order(self, mock_find, mock_worklist):
        contact = Contact.objects.create(
            company=self.company,
            source=Contact.Source.SHOPIFY,
            external_id="cust-1",
            email="enrich@example.com",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="ord-enrich",
            amount="12.34",
            currency="EUR",
            status=Order.Status.PAID,
        )
        mock_worklist.return_value = [
            {"side": "shopify_only", "order.id": "ord-enrich"},
        ]
        mock_find.return_value = {"contactId": "mc-enrich", "email": "enrich@example.com"}

        rows = collect_evidence_rows(
            company=self.company,
            check_id="LE-01",
            max_rows=10,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["person.email"], "enrich@example.com")
        self.assertEqual(rows[0]["manago_contact_id"], "mc-enrich")
        self.assertEqual(rows[0]["amount_gross"], 12.34)

    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    @patch("dataruns.writebacks.transform.find_manago_contact")
    def test_le01_enriches_worklist_normalized_value_nesting(
        self, mock_find, mock_worklist
    ):
        """Worklist wraps bare DCS mismatches as value={side, order.id}."""
        contact = Contact.objects.create(
            company=self.company,
            source=Contact.Source.SHOPIFY,
            external_id="cust-nest",
            email="nested@example.com",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="ord-nested",
            amount="55.00",
            currency="EUR",
            status=Order.Status.PAID,
        )
        mock_worklist.return_value = [
            {
                "source": "shopify",
                "locator": "",
                "observed_at": "",
                "value": {"side": "shopify_only", "order.id": "ord-nested"},
            }
        ]
        mock_find.return_value = {"contactId": "mc-nested", "email": "nested@example.com"}

        rows = collect_evidence_rows(
            company=self.company,
            check_id="LE-01",
            max_rows=10,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["side"], "shopify_only")
        self.assertEqual(rows[0]["order.id"], "ord-nested")
        self.assertEqual(rows[0]["person.email"], "nested@example.com")
        self.assertEqual(rows[0]["manago_contact_id"], "mc-nested")
        self.assertEqual(rows[0]["amount_gross"], 55.0)

        mapping = get_check_mapping("LE-01")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=rows,
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].status, "ready")
        self.assertEqual(intents[0].payload.get("externalId"), "ord-nested")
        self.assertEqual(intents[0].payload.get("email"), "nested@example.com")

    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    @patch("dataruns.writebacks.transform._le01_sandbox_evidence_rows")
    def test_le01_aggregate_only_worklist_does_not_sandbox(
        self, mock_sandbox, mock_worklist
    ):
        """FAIL with aggregate evidence but no shopify_only → empty, not fake orders."""
        mock_worklist.return_value = [
            {
                "locator": "lifecycle.purchase_count_parity",
                "value": {"shopify_paid_orders": 10, "manago_purchase_events": 8},
            }
        ]
        self.company.writeback_execute_enabled = True
        self.company.save(update_fields=["writeback_execute_enabled"])

        rows = collect_evidence_rows(
            company=self.company,
            check_id="LE-01",
            max_rows=10,
        )
        self.assertEqual(rows, [])
        mock_sandbox.assert_not_called()
