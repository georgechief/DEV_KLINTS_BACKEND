"""PRD-WB-11 — PT-04 klints_net_ltv governed net writeback."""

from __future__ import annotations

import importlib
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.executors.product import _pt04_mismatch_rows, evaluate_pt_04
from dataruns.dcs.segment_join import clear_klints_owned_keys_cache, is_klints_owned_detail
from dataruns.models import WritebackAllowedCheck
from dataruns.tests.writeback_helpers import seed_writeback_allowlist
from dataruns.writebacks.gates import execute_allowed
from dataruns.writebacks.registry import get_check_mapping, list_mapping_entries
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.transform import (
    build_intents_from_mapping,
    collect_evidence_rows,
)
from tenants.models import Company, Tenant, User


def _pt04_ctx(snapshot: dict) -> FoundationGateContext:
    return FoundationGateContext(
        tenant_id="t1",
        run_id="r1",
        evaluated_at="2026-09-22T00:00:00Z",
        extra={"scoring_snapshot": snapshot},
    )


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb11RegistryAndAllowlistTests(TestCase):
    def test_pt04_enabled_detail_set_net_ltv(self):
        clear_klints_owned_keys_cache()
        by_id = {
            str(row.get("check_id") or "").upper(): row for row in list_mapping_entries()
        }
        self.assertTrue(by_id["PT-04"].get("enabled"))

        pt04 = get_check_mapping("PT-04")
        self.assertTrue(pt04.get("enabled"))
        self.assertTrue(pt04.get("requires_consent_namespace_clean"))
        self.assertFalse(pt04.get("irreversible"))
        self.assertEqual(pt04.get("approval_tier"), "batch")
        self.assertEqual(pt04.get("rollback", {}).get("strategy"), "revert_detail")
        disclosure = pt04.get("operator_disclosure") or ""
        self.assertNotIn("may not make PT-04 PASS", disclosure)
        self.assertIn("re-run DCS", disclosure)
        self.assertIn("PASS", disclosure)

        op = pt04["operations"][0]
        self.assertEqual(op["op_kind"], "detail_set")
        self.assertEqual(op["namespace"], "klints_")
        self.assertEqual(
            op["from_evidence"]["match"]["const"],
            "net_overstatement",
        )
        self.assertEqual(
            op["from_evidence"]["entity_key"]["path"],
            "write_entity_key",
        )
        fields = op["from_evidence"]["fields"]
        self.assertEqual(fields["detail_key"]["const"], "klints_net_ltv")
        self.assertEqual(fields["detail_value"]["path"], "shopify_net")

    def test_allowlist_seeds_pt04(self):
        from django.apps import apps as django_apps

        mod = importlib.import_module("dataruns.migrations.0039_writeback_allowed_pt04")
        WritebackAllowedCheck.objects.filter(check_id="PT-04").delete()
        mod.seed_wb11_allowlist(django_apps, None)
        self.assertTrue(
            WritebackAllowedCheck.objects.filter(check_id="PT-04", enabled=True).exists()
        )

    def test_klints_net_ltv_owned_when_pt04_enabled(self):
        clear_klints_owned_keys_cache()
        self.assertTrue(is_klints_owned_detail("klints_net_ltv"))


class Pt04ProvenanceUnionTests(SimpleTestCase):
    def test_union_includes_refund_blind_only(self):
        failing = [
            {
                "person.email": "a@x.com",
                "manago_contact_id": "m1",
                "shopify_net": 50,
                "overstatement": 50,
            }
        ]
        refund_blind = [
            {
                "person.email": "b@x.com",
                "manago_contact_id": "m2",
                "shopify_net": 100,
                "refund_blind": True,
                "overstatement": 2,
            }
        ]
        rows = _pt04_mismatch_rows(failing, refund_blind)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["side"] == "net_overstatement" for r in rows))
        ids = {r["manago_contact_id"] for r in rows}
        self.assertEqual(ids, {"m1", "m2"})

    def test_dedupe_by_contact_id(self):
        row = {
            "person.email": "a@x.com",
            "manago_contact_id": "m1",
            "shopify_net": 50,
            "refund_blind": True,
        }
        rows = _pt04_mismatch_rows([row], [row])
        self.assertEqual(len(rows), 1)

    def test_evaluate_pt04_refund_blind_only_has_mismatches(self):
        snap = {
            "connectors": {
                "shopify": {"status": "connected"},
                "manago_ai": {"status": "connected"},
            },
            "product_truth": {
                "linked_contacts": 1,
                "contacts_over_delta": 0,
                "contacts_refund_blind": 1,
                "total_overstatement": 5.0,
                "fail_delta": 0.02,
                "failing_sample": [],
                "refund_blind_sample": [
                    {
                        "person.email": "blind@x.com",
                        "shopify_customer_id": "s1",
                        "manago_contact_id": "mb",
                        "shopify_net": 95,
                        "manago_purchase_value_deduped": 100,
                        "delta_vs_net": 0.05,
                        "refund_blind": True,
                        "overstatement": 5,
                    }
                ],
                "raw_enrichment": {
                    "shopify_from_raw": True,
                    "manago_from_raw": True,
                },
            },
        }
        # delta 0.05 > 0.02 would normally be failing — use tiny relative gap
        snap["product_truth"]["refund_blind_sample"][0]["delta_vs_net"] = 0.01
        result = evaluate_pt_04(_pt04_ctx(snap))
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(len(result.provenance["mismatches"]), 1)
        self.assertEqual(
            result.provenance["mismatches"][0]["side"], "net_overstatement"
        )
        self.assertEqual(
            result.provenance["mismatches"][0]["manago_contact_id"], "mb"
        )


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb11TransformTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="WB11T", slug="wb11-transform")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB11 Co",
            domain="wb11-transform.test",
        )

    def test_net_overstatement_builds_detail_set(self):
        mapping = get_check_mapping("PT-04")
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={
                "email": "buyer@net.test",
                "contactId": "mc-1",
                "properties": {},
            },
        ):
            intents = build_intents_from_mapping(
                company=self.company,
                mapping=mapping,
                evidence_rows=[
                    {
                        "side": "net_overstatement",
                        "person.email": "buyer@net.test",
                        "manago_contact_id": "mc-1",
                        "shopify_net": 123.45,
                        "write_entity_key": "buyer@net.test",
                    }
                ],
            )
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.op_kind, "detail_set")
        self.assertEqual(intent.status, "ready")
        self.assertEqual(intent.rollback_strategy, "revert_detail")
        props = intent.payload.get("properties") or {}
        self.assertEqual(props.get("klints_net_ltv"), 123.45)
        supported, reason = rollback_supported(intent)
        self.assertTrue(supported)
        self.assertIsNone(reason)

    def test_contact_id_only_entity_key(self):
        mapping = get_check_mapping("PT-04")
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={"contactId": "mc-only", "properties": {}},
        ):
            intents = build_intents_from_mapping(
                company=self.company,
                mapping=mapping,
                evidence_rows=[
                    {
                        "side": "net_overstatement",
                        "manago_contact_id": "mc-only",
                        "shopify_net": 10,
                        "write_entity_key": "mc-only",
                    }
                ],
            )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].status, "ready")
        self.assertEqual(intents[0].entity_key, "mc-only")
        self.assertEqual(intents[0].payload.get("contactId"), "mc-only")

    def test_missing_identity_skipped_in_collect(self):
        with patch(
            "dataruns.writebacks.transform._worklist_evidence_rows",
            return_value=[
                {
                    "side": "net_overstatement",
                    "shopify_net": 10,
                }
            ],
        ):
            with patch(
                "dataruns.writebacks.transform.find_manago_contact",
                return_value=None,
            ):
                rows = collect_evidence_rows(
                    company=self.company, check_id="PT-04", max_rows=10
                )
        self.assertEqual(rows, [])

    def test_missing_shopify_net_skipped(self):
        with patch(
            "dataruns.writebacks.transform._worklist_evidence_rows",
            return_value=[
                {
                    "side": "net_overstatement",
                    "person.email": "a@b.c",
                    "manago_contact_id": "m1",
                }
            ],
        ):
            rows = collect_evidence_rows(
                company=self.company, check_id="PT-04", max_rows=10
            )
        self.assertEqual(rows, [])

    def test_enrich_sets_write_entity_key(self):
        with patch(
            "dataruns.writebacks.transform._worklist_evidence_rows",
            return_value=[
                {
                    "side": "net_overstatement",
                    "person.email": "a@example.com",
                    "manago_contact_id": "m9",
                    "shopify_net": 0,
                }
            ],
        ):
            rows = collect_evidence_rows(
                company=self.company, check_id="PT-04", max_rows=10
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["write_entity_key"], "a@example.com")
        self.assertEqual(rows[0]["shopify_net"], 0)

    def test_already_at_target_skipped(self):
        mapping = get_check_mapping("PT-04")
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={
                "email": "a@example.com",
                "contactId": "mc-1",
                "properties": {"klints_net_ltv": 50},
            },
        ):
            intents = build_intents_from_mapping(
                company=self.company,
                mapping=mapping,
                evidence_rows=[
                    {
                        "side": "net_overstatement",
                        "person.email": "a@example.com",
                        "manago_contact_id": "mc-1",
                        "shopify_net": 50,
                        "write_entity_key": "a@example.com",
                    }
                ],
            )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].status, "skipped")
        self.assertEqual(intents[0].error_reason, "already_at_target")

    def test_already_at_target_numeric_string_vs_float(self):
        """Manago often stores detail values as strings — still already_at_target."""
        mapping = get_check_mapping("PT-04")
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={
                "email": "a@example.com",
                "contactId": "mc-1",
                "properties": {"klints_net_ltv": "123.45"},
            },
        ):
            intents = build_intents_from_mapping(
                company=self.company,
                mapping=mapping,
                evidence_rows=[
                    {
                        "side": "net_overstatement",
                        "person.email": "a@example.com",
                        "manago_contact_id": "mc-1",
                        "shopify_net": 123.45,
                        "write_entity_key": "a@example.com",
                    }
                ],
            )
        self.assertEqual(intents[0].status, "skipped")
        self.assertEqual(intents[0].error_reason, "already_at_target")

    def test_resolves_identity_from_contact_db(self):
        from dataruns.models import Contact

        Contact.objects.create(
            company=self.company,
            email="db@example.com",
            source=Contact.Source.MANAGO_AI,
            external_id="mc-db",
        )
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value=None,
        ):
            with patch(
                "dataruns.writebacks.transform._worklist_evidence_rows",
                return_value=[
                    {
                        "side": "net_overstatement",
                        "manago_contact_id": "mc-db",
                        "shopify_net": 9.5,
                    }
                ],
            ):
                rows = collect_evidence_rows(
                    company=self.company, check_id="PT-04", max_rows=10
                )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["person.email"], "db@example.com")
        self.assertEqual(rows[0]["write_entity_key"], "db@example.com")

    def test_discards_worklist_pii_masked_email(self):
        """Worklist masks emails as a***@x.com — must re-resolve, never upsert mask."""
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={
                "email": "real@example.com",
                "contactId": "mc-mask",
            },
        ):
            with patch(
                "dataruns.writebacks.transform._worklist_evidence_rows",
                return_value=[
                    {
                        "side": "net_overstatement",
                        "person.email": "r***@example.com",
                        "manago_contact_id": "mc-mask",
                        "shopify_net": 42,
                    }
                ],
            ):
                rows = collect_evidence_rows(
                    company=self.company, check_id="PT-04", max_rows=10
                )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["person.email"], "real@example.com")
        self.assertEqual(rows[0]["write_entity_key"], "real@example.com")
        self.assertNotIn("***", rows[0]["write_entity_key"])

    def test_masked_email_falls_back_to_contact_id_entity_key(self):
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={"contactId": "mc-only"},
        ):
            with patch(
                "dataruns.writebacks.transform._worklist_evidence_rows",
                return_value=[
                    {
                        "side": "net_overstatement",
                        "person.email": "x***@hidden.test",
                        "manago_contact_id": "mc-only",
                        "shopify_net": 7,
                    }
                ],
            ):
                rows = collect_evidence_rows(
                    company=self.company, check_id="PT-04", max_rows=10
                )
        self.assertEqual(rows[0]["write_entity_key"], "mc-only")
        self.assertIsNone(rows[0]["person.email"])

    def test_default_row_cap_uses_upsert_batch_not_sandbox_10(self):
        """WB-11: PT-04 DCS sample ≤50 must not default to WRITEBACK_SANDBOX_MAX_ROWS=10."""
        from dataruns.writebacks.capabilities import capability_batch_max

        cap = capability_batch_max("RESTV2.CONTACT.UPSERT") or 1000
        self.assertGreaterEqual(int(cap), 50)
        self.assertEqual(min(int(cap), 1000), 1000)

        from dataruns.writebacks.pipeline import run_writeback_pipeline

        with patch(
            "dataruns.writebacks.pipeline.collect_evidence_rows",
            return_value=[],
        ) as mock_collect:
            with patch(
                "dataruns.writebacks.pipeline.run_preflight",
                return_value=None,
            ):
                with patch(
                    "dataruns.writebacks.pipeline.get_check_mapping",
                    return_value=get_check_mapping("PT-04"),
                ):
                    run_writeback_pipeline(
                        company=self.company,
                        check_id="PT-04",
                        mode="dry_run",
                        actor=None,
                    )
        self.assertEqual(mock_collect.call_args.kwargs["max_rows"], min(int(cap), 1000))

    def test_no_sandbox_when_empty(self):
        with patch(
            "dataruns.writebacks.transform._worklist_evidence_rows",
            return_value=[],
        ):
            self.assertEqual(
                collect_evidence_rows(
                    company=self.company, check_id="PT-04", max_rows=5
                ),
                [],
            )

    def test_ignores_other_sides(self):
        mapping = get_check_mapping("PT-04")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only_return",
                    "person.email": "a@b.c",
                    "shopify_net": 1,
                    "write_entity_key": "a@b.c",
                }
            ],
        )
        self.assertEqual(intents, [])


@override_settings(WRITEBACK_SANDBOX_COMPANY_IDS=[])
class WritebackWb11GateTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("PT-04")
        tenant = Tenant.objects.create(name="WB11G", slug="wb11-gate")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB11 Gate",
            domain="wb11-gate.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb11-gate.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )

    def test_execute_denied_when_settings_off(self):
        self.company.writeback_execute_enabled = False
        self.company.save(update_fields=["writeback_execute_enabled"])
        allowed, reason = execute_allowed(company=self.company, check_id="PT-04")
        self.assertFalse(allowed)
        self.assertEqual(reason, "writebacks_disabled")

    def test_preview_blocked_when_sp07_fail(self):
        from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
        from dataruns.models import DataRun, Run
        from dataruns.writebacks.service import writeback_run
        from tenants.crypto import encrypt_config
        from tenants.models import Connector

        self.company.writeback_execute_enabled = False
        self.company.save(update_fields=["writeback_execute_enabled"])
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            config=encrypt_config(
                {
                    "workspace_id": "cid",
                    "api_key": "secret",
                    "owner": "owner@test.com",
                    "endpoint": "https://app2.manago.ai",
                }
            ),
            status="connected",
        )
        domain_run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        DataRun.objects.create(
            tenant=self.company.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "run_id": str(domain_run.id),
                "dcs_run": {"run_id": str(domain_run.id), "run_state": "SCORED"},
                "check_results": [
                    {"check_id": "SP-07", "status": "FAIL"},
                    {"check_id": "PT-04", "status": "FAIL"},
                ],
            },
        )
        result = writeback_run(
            company=self.company,
            check_id="PT-04",
            mode="dry_run",
            actor=self.admin,
        )
        self.assertEqual(result.blocked_reason, "consent_namespace_not_clean")
        self.assertEqual(result.summary.ready, 0)
