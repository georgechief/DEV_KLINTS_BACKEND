"""Transform tests — evidence rows to write intents."""

import json
from pathlib import Path

from django.test import TestCase

from dataruns.writebacks.registry import MappingDisabled, get_check_mapping
from dataruns.writebacks.transform import build_intents_from_mapping
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
