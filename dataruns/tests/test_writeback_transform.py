"""Transform tests — evidence rows to write intents."""

from django.test import TestCase

from dataruns.writebacks.registry import get_check_mapping
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

    def test_le04_duplicate_purchase_builds_tag_add(self):
        mapping = get_check_mapping("LE-04")
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
