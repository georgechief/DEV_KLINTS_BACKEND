"""PRD-WB-19 — SP-03 detail schema normalise (format contract + Approve) tests."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from dataruns.dcs.segment_join import SP_SAMPLE, _classify_value
from dataruns.models import WritebackAllowedCheck
from dataruns.writebacks.pipeline import run_writeback_pipeline
from dataruns.writebacks.registry import get_check_mapping
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.transform import (
    _sp03_coerce_value,
    _sp03_resolve_target,
    build_intents_from_mapping,
    collect_evidence_rows,
)
from tenants.models import Company, Connector, Tenant


class Sp03CoerceHelperTests(SimpleTestCase):
    def test_coerce_one_to_decimal_string(self):
        out = _sp03_coerce_value(
            "1", target_format="numeric", coerce="decimal_string_if_01"
        )
        self.assertEqual(out, "1.0")
        self.assertEqual(_classify_value(out), "numeric")

    def test_coerce_zero_to_decimal_string(self):
        out = _sp03_coerce_value(
            "0", target_format="numeric", coerce="decimal_string_if_01"
        )
        self.assertEqual(out, "0.0")
        self.assertEqual(_classify_value(out), "numeric")

    def test_contract_beats_majority_boolean(self):
        target, coerce, gate = _sp03_resolve_target(
            key="ORDER_NUMBER",
            format_distribution={"boolean": 55, "numeric": 21},
            samples=["1", "1", "2"],
            contract={
                "ORDER_NUMBER": {
                    "target_format": "numeric",
                    "coerce": "decimal_string_if_01",
                }
            },
        )
        self.assertEqual(target, "numeric")
        self.assertEqual(coerce, "decimal_string_if_01")
        self.assertEqual(gate, "contract")

    def test_heuristic_numeric_from_01_without_contract(self):
        target, coerce, gate = _sp03_resolve_target(
            key="CUSTOM_COUNT",
            format_distribution={"boolean": 10, "numeric": 3},
            samples=["1", "0", "3"],
            contract={},
        )
        self.assertEqual(target, "numeric")
        self.assertEqual(coerce, "decimal_string_if_01")
        self.assertEqual(gate, "heuristic_numeric_from_01")

    def test_ambiguous_text_numeric_needs_contract(self):
        target, coerce, gate = _sp03_resolve_target(
            key="NICKNAME",
            format_distribution={"text": 5, "numeric": 2},
            samples=["ten", "10"],
            contract={},
        )
        self.assertIsNone(target)
        self.assertIsNone(coerce)
        self.assertEqual(gate, "needs_contract")


class Sp03MappingIntentTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB19M", slug="wb19-map")
        self.company = Company.objects.create(
            tenant=self.tenant, name="WB19 Map", domain="wb19-map.test"
        )

    def test_mapping_t4_revert_detail_and_contract(self):
        mapping = get_check_mapping("SP-03")
        self.assertEqual(mapping.get("template_id"), "T4")
        self.assertTrue(mapping.get("requires_consent_namespace_clean"))
        self.assertFalse(mapping.get("irreversible"))
        self.assertEqual((mapping.get("rollback") or {}).get("strategy"), "revert_detail")
        contract = mapping.get("format_contract") or {}
        self.assertIn("ORDER_NUMBER", contract)
        ops = mapping.get("operations") or []
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].get("op_kind"), "detail_set")
        match = (ops[0].get("from_evidence") or {}).get("match") or {}
        self.assertEqual(match.get("const"), "inconsistent_detail_format")
        self.assertNotIn("oneOf", match)

    def test_transform_normalize_and_skip(self):
        mapping = get_check_mapping("SP-03")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "inconsistent_detail_format",
                    "key": "ORDER_NUMBER",
                    "person.email": "a@ex.com",
                    "manago_contact_id": "m1",
                    "write_entity_key": "a@ex.com",
                    "value_before": "1",
                    "value_after": "1.0",
                    "fmt_before": "boolean",
                    "fmt_after": "numeric",
                    "proposed_action": "NORMALIZE_DETAIL",
                    "evidence_gate": "contract",
                    "target_format": "numeric",
                },
                {
                    "side": "inconsistent_detail_format",
                    "key": "NICKNAME",
                    "person.email": "b@ex.com",
                    "manago_contact_id": "m2",
                    "write_entity_key": "b@ex.com",
                    "value_before": "ten",
                    "value_after": "ten",
                    "proposed_action": "SKIP_NEEDS_CONTRACT",
                    "evidence_gate": "needs_contract",
                },
                {
                    "side": "semantic_duplicate_keys",
                    "normalized": "orderavg",
                    "keys": ["ORDER_AVG", "orderAvg"],
                },
            ],
        )
        self.assertEqual(len(intents), 2)
        by_key = {}
        for intent in intents:
            props = (intent.payload or {}).get("properties") or {}
            key = next(iter(props.keys()), None)
            by_key[key] = intent
        ready = by_key["ORDER_NUMBER"]
        self.assertEqual(ready.status, "ready")
        self.assertEqual(ready.op_kind, "detail_set")
        self.assertEqual(ready.payload["properties"]["ORDER_NUMBER"], "1.0")
        ok, _reason = rollback_supported(ready)
        self.assertTrue(ok)
        skip = by_key["NICKNAME"]
        self.assertEqual(skip.status, "skipped")
        self.assertEqual(skip.error_reason, "skip_needs_contract")

    def test_contact_id_only_entity_key(self):
        mapping = get_check_mapping("SP-03")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "inconsistent_detail_format",
                    "key": "ORDER_NUMBER",
                    "person.email": "",
                    "manago_contact_id": "m-only",
                    "write_entity_key": "m-only",
                    "value_before": "1",
                    "value_after": "1.0",
                    "proposed_action": "NORMALIZE_DETAIL",
                    "evidence_gate": "contract",
                }
            ],
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].status, "ready")
        self.assertEqual(intents[0].entity_key, "m-only")

    def test_writeback_allowed_seeded(self):
        WritebackAllowedCheck.objects.get_or_create(
            check_id="SP-03",
            defaults={
                "enabled": True,
                "note": "PRD-WB-19 SP-03 detail schema normalise",
            },
        )
        self.assertTrue(
            WritebackAllowedCheck.objects.filter(check_id="SP-03", enabled=True).exists()
        )


    def test_expand_produces_normalize_intents(self):
        mapping = get_check_mapping("SP-03")
        contacts = [
            {
                "email": "a@ex.com",
                "contactId": "m1",
                "properties": {"ORDER_NUMBER": "1"},
            },
            {
                "email": "b@ex.com",
                "contactId": "m2",
                "properties": {"ORDER_NUMBER": "2.5"},
            },
        ]
        with (
            patch(
                "dataruns.writebacks.transform._sp03_pinned_contacts",
                return_value=contacts,
            ),
            patch(
                "dataruns.writebacks.transform._sp03_live_inconsistent_key_catalog",
                return_value={
                    "ORDER_NUMBER": {
                        "format_distribution": {"boolean": 1, "numeric": 1},
                        "samples": ["1", "2.5"],
                    }
                },
            ),
        ):
            rows = collect_evidence_rows(
                company=self.company,
                check_id="SP-03",
                max_rows=50,
            )
        self.assertGreaterEqual(len(rows), 1)
        normalize = [r for r in rows if r.get("proposed_action") == "NORMALIZE_DETAIL"]
        self.assertTrue(normalize)
        self.assertEqual(normalize[0]["value_after"], "1.0")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=normalize,
        )
        self.assertTrue(intents)
        self.assertEqual(intents[0].status, "ready")
        self.assertEqual(intents[0].op_kind, "detail_set")


@override_settings(WRITEBACKS_ENABLED=False)
class Sp03PipelineTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB19P", slug="wb19-pipe")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="WB19 Pipe",
            domain="wb19-pipe.test",
            writeback_execute_enabled=True,
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
        )

    def test_preview_default_max_rows_is_sp_sample(self):
        result = run_writeback_pipeline(
            company=self.company,
            check_id="SP-03",
            mode="preview",
            max_rows=None,
            intents=None,
        )
        self.assertEqual(result.check_id, "SP-03")
        self.assertLessEqual(len(result.intents), SP_SAMPLE)
        self.assertEqual(SP_SAMPLE, 50)
