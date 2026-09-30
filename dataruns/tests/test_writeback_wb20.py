"""PRD-WB-20 — PT-03 catalog completeness reconcile tests."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase, override_settings

from dataruns.dcs.catalog_join import PT_SAMPLE, _manago_product_in_assortment
from dataruns.writebacks.adapters.manago import ManagoWriteAdapter
from dataruns.writebacks.capabilities import (
    capability_allows_execute,
    capability_status,
)
from dataruns.writebacks.pipeline import run_writeback_pipeline
from dataruns.writebacks.registry import get_check_mapping
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.transform import build_intents_from_mapping
from dataruns.writebacks.types import WriteIntent
from tenants.models import Company, Connector, Tenant


class Pt03AssortmentHelperTests(SimpleTestCase):
    def test_inactive_excluded_from_assortment(self):
        self.assertFalse(_manago_product_in_assortment({"active": False}))
        self.assertFalse(_manago_product_in_assortment({"archived": True}))
        self.assertTrue(_manago_product_in_assortment({"active": True}))
        self.assertTrue(_manago_product_in_assortment({}))


class Pt03MappingIntentTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB20M", slug="wb20-map")
        self.company = Company.objects.create(
            tenant=self.tenant, name="WB20 Map", domain="wb20-map.test"
        )

    def test_mapping_t7_irreversible_and_ops(self):
        mapping = get_check_mapping("PT-03")
        self.assertEqual(mapping.get("template_id"), "T7")
        self.assertTrue(mapping.get("irreversible"))
        self.assertFalse(mapping.get("archive_enabled"))
        self.assertEqual((mapping.get("rollback") or {}).get("strategy"), "none")
        ops = mapping.get("operations") or []
        self.assertEqual(len(ops), 2)
        self.assertEqual(ops[0].get("op_kind"), "product_upsert")
        self.assertEqual(
            (ops[0].get("from_evidence") or {}).get("match", {}).get("const"),
            "missing_in_manago",
        )
        self.assertEqual(
            (ops[1].get("from_evidence") or {}).get("match", {}).get("const"),
            "surplus_in_manago",
        )

    def test_missing_ready_surplus_skipped_without_archive_loom(self):
        mapping = get_check_mapping("PT-03")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "missing_in_manago",
                    "product_id": "1001",
                    "write_entity_key": "1001",
                    "shopify_title": "Tee",
                    "shopify_sku": "TEE-1",
                    "proposed_action": "UPSERT_FROM_SHOPIFY",
                    "evidence_gate": "pins_rebuild",
                },
                {
                    "side": "surplus_in_manago",
                    "product_id": "9001",
                    "write_entity_key": "9001",
                    "proposed_action": "ARCHIVE_FLAG",
                    "evidence_gate": "archive_semantics_unknown",
                },
                {
                    "side": "attribute_empty",
                    "product_id": "8001",
                },
            ],
        )
        self.assertEqual(len(intents), 2)
        by_id = {i.entity_key: i for i in intents}
        ready = by_id["1001"]
        self.assertEqual(ready.status, "ready")
        self.assertEqual(ready.op_kind, "product_upsert")
        self.assertEqual(ready.payload["product"]["productId"], "1001")
        self.assertEqual(ready.payload["product"]["name"], "Tee")
        self.assertNotIn("proposed_action", ready.payload.get("product") or {})
        ok, reason = rollback_supported(ready)
        self.assertFalse(ok)
        self.assertEqual(reason, "rollback_not_supported")
        skip = by_id["9001"]
        self.assertEqual(skip.status, "skipped")
        self.assertEqual(skip.error_reason, "archive_semantics_unknown")

    def test_needs_catalog_id_skipped(self):
        mapping = get_check_mapping("PT-03")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "missing_in_manago",
                    "product_id": "1001",
                    "write_entity_key": "1001",
                    "shopify_title": "Tee",
                    "proposed_action": "UPSERT_FROM_SHOPIFY",
                    "evidence_gate": "needs_catalog_id",
                },
            ],
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].status, "skipped")
        self.assertEqual(intents[0].error_reason, "needs_catalog_id")

    def test_capability_still_discovery(self):
        self.assertEqual(
            capability_status("RESTV2.PRODUCT.IMPORT"), "DISCOVERY_REQUIRED"
        )
        self.assertFalse(capability_allows_execute("RESTV2.PRODUCT.IMPORT"))


@override_settings(WRITEBACKS_ENABLED=False)
class Pt03PipelineTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB20P", slug="wb20-pipe")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="WB20 Pipe",
            domain="wb20-pipe.test",
            writeback_execute_enabled=True,
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
        )
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="commerce",
            status="connected",
        )

    def test_preview_default_max_rows_is_pt_sample(self):
        result = run_writeback_pipeline(
            company=self.company,
            check_id="PT-03",
            mode="preview",
            max_rows=None,
            intents=None,
        )
        self.assertEqual(result.check_id, "PT-03")
        self.assertLessEqual(len(result.intents), PT_SAMPLE)
        self.assertEqual(PT_SAMPLE, 50)
        disclosure = result.operator_disclosure or ""
        self.assertIn("PRODUCT.IMPORT", disclosure)

    def test_pipeline_preserves_surplus_archive_skip(self):
        """PRD §2.1 / §8 — dry_run must not flip archive_semantics_unknown → ready."""
        mapping = get_check_mapping("PT-03")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "missing_in_manago",
                    "product_id": "1001",
                    "write_entity_key": "1001",
                    "shopify_title": "Tee",
                    "proposed_action": "UPSERT_FROM_SHOPIFY",
                    "evidence_gate": "pins_rebuild",
                },
                {
                    "side": "surplus_in_manago",
                    "product_id": "9001",
                    "write_entity_key": "9001",
                    "proposed_action": "ARCHIVE_FLAG",
                    "evidence_gate": "archive_semantics_unknown",
                },
            ],
        )
        result = run_writeback_pipeline(
            company=self.company,
            check_id="PT-03",
            mode="preview",
            max_rows=50,
            intents=intents,
        )
        by_id = {i.entity_key: i for i in result.intents}
        self.assertEqual(by_id["1001"].status, "ready")
        self.assertEqual(by_id["9001"].status, "skipped")
        self.assertEqual(by_id["9001"].error_reason, "archive_semantics_unknown")

    def test_adapter_dry_run_preserves_skipped(self):
        probe = WriteIntent(
            check_id="PT-03",
            op_kind="product_upsert",
            operation="manago.product_upsert.archive_surplus",
            target_system="manago",
            entity_type="product",
            entity_key="9001",
            namespace="native",
            payload={
                "product": {"productId": "9001", "active": False},
                "proposed_action": "ARCHIVE_FLAG",
            },
            status="skipped",
            error_reason="archive_semantics_unknown",
            capability_id="RESTV2.PRODUCT.IMPORT",
        )
        out = ManagoWriteAdapter().dry_run(self.company, [probe])
        self.assertEqual(out[0].status, "skipped")
        self.assertEqual(out[0].error_reason, "archive_semantics_unknown")


class Pt03RollbackProbeTests(SimpleTestCase):
    def test_none_strategy_not_supported(self):
        probe = WriteIntent(
            check_id="PT-03",
            op_kind="product_upsert",
            operation="manago.product_upsert.from_shopify",
            target_system="manago",
            entity_type="product",
            entity_key="1001",
            namespace="native",
            payload={"product": {"productId": "1001", "active": True}},
            rollback_strategy="none",
        )
        ok, reason = rollback_supported(probe)
        self.assertFalse(ok)
        self.assertEqual(reason, "rollback_not_supported")
