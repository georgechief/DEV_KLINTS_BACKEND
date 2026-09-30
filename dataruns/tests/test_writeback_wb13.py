"""PRD-WB-13 — LE-05 order-level PURCHASE gap writeback."""

from __future__ import annotations

import importlib
from unittest.mock import patch

from django.test import TestCase, override_settings

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import Contact, DataRun, Order, Run, WritebackAllowedCheck
from dataruns.tests.writeback_helpers import (
    issue_approved_writeback_token,
    sandbox_company,
    seed_writeback_allowlist,
)
from dataruns.writebacks.gates import execute_allowed
from dataruns.writebacks.registry import get_check_mapping, list_mapping_entries
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.serializers import serialize_result
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.transform import (
    build_intents_from_mapping,
    collect_evidence_rows,
)
from dataruns.writebacks.types import WriteIntent
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


def _seed_dcs_run(company: Company) -> None:
    domain_run = Run.objects.create(
        company=company,
        run_type=Run.RunType.FULL,
        status=Run.Status.COMPLETED,
    )
    DataRun.objects.create(
        tenant=company.tenant,
        name=DCS_SCORE_DATA_RUN_NAME,
        status=DataRun.Status.SUCCEEDED,
        metadata={
            "kind": DCS_SCORE_KIND,
            "company_id": str(company.id),
            "domain_run_id": str(domain_run.id),
        },
    )


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb13RegistryAndAllowlistTests(TestCase):
    def test_le05_enabled_match_shopify_only(self):
        by_id = {
            str(row.get("check_id") or "").upper(): row for row in list_mapping_entries()
        }
        self.assertTrue(by_id["LE-05"].get("enabled"))
        self.assertTrue(by_id["LE-01"].get("enabled"))

        le05 = get_check_mapping("LE-05")
        self.assertTrue(le05.get("irreversible"))
        self.assertEqual(le05["operations"][0]["op_kind"], "event_ingest")
        self.assertEqual(
            le05["operations"][0]["from_evidence"]["match"]["const"],
            "shopify_only",
        )
        fields = le05["operations"][0]["from_evidence"]["fields"]
        self.assertNotIn("event_type", fields)
        self.assertIn("order_id", fields)

    def test_allowlist_seeds_le05(self):
        from django.apps import apps as django_apps

        mod = importlib.import_module("dataruns.migrations.0040_writeback_allowed_le05")
        WritebackAllowedCheck.objects.filter(check_id="LE-05").delete()
        mod.seed_wb13_allowlist(django_apps, None)
        self.assertTrue(
            WritebackAllowedCheck.objects.filter(check_id="LE-05", enabled=True).exists()
        )


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb13TransformTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="WB13T", slug="wb13-transform")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB13 Co",
            domain="wb13-transform.test",
        )

    def test_shopify_only_builds_purchase_event(self):
        mapping = get_check_mapping("LE-05")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only",
                    "order.id": "5001",
                    "person.email": "buyer@gap.test",
                    "manago_contact_id": "mc-g1",
                    "amount_gross": 99.5,
                }
            ],
        )
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.op_kind, "event_ingest")
        self.assertEqual(intent.status, "ready")
        self.assertEqual(intent.payload.get("externalId"), "5001")
        self.assertEqual(intent.payload.get("contactExtEventType"), "PURCHASE")
        self.assertEqual(intent.payload.get("value"), 99.5)
        self.assertEqual(intent.payload.get("email"), "buyer@gap.test")

    def test_ignores_manago_only_and_le09_return_side(self):
        mapping = get_check_mapping("LE-05")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {"side": "manago_only", "order.id": "m1", "person.email": "a@b.c"},
                {
                    "side": "shopify_only_return",
                    "order.id": "r1",
                    "person.email": "r@b.c",
                    "amount_gross": 10,
                    "event_type": "RETURN",
                },
            ],
        )
        self.assertEqual(intents, [])

    def test_missing_contact_is_error_not_ready(self):
        mapping = get_check_mapping("LE-05")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only",
                    "order.id": "orphan-le05",
                    "amount_gross": 1.0,
                }
            ],
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].status, "error")
        self.assertEqual(intents[0].error_reason, "missing_contact_reference")

    def test_masked_email_re_resolves_from_order(self):
        contact = Contact.objects.create(
            company=self.company,
            email="clean@gap.test",
            source=Contact.Source.SHOPIFY,
            external_id="c-mask",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="MASK-1",
            amount="15",
            currency="EUR",
            status=Order.Status.PAID,
        )
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={"contactId": "mc-mask"},
        ):
            from dataruns.writebacks.transform import _le05_evidence_rows

            enriched = _le05_evidence_rows(
                company=self.company,
                rows=[
                    {
                        "side": "shopify_only",
                        "order.id": "MASK-1",
                        "person.email": "c***@gap.test",
                        "amount_gross": 15.0,
                    }
                ],
                max_rows=10,
            )
        self.assertEqual(len(enriched), 1)
        self.assertEqual(enriched[0]["person.email"], "clean@gap.test")
        self.assertEqual(enriched[0]["manago_contact_id"], "mc-mask")

    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    def test_expands_gap_sample_from_aggregate_evidence(self, mock_worklist):
        """When mismatches are missing, expand value.gap_sample shopify_only rows."""
        mock_worklist.return_value = [
            {
                "source": "snapshot",
                "locator": "lifecycle.order_level_gaps",
                "value": {
                    "shopify_only_count": 2,
                    "manago_only_count": 0,
                    "gap_sample": [
                        {"side": "shopify_only", "order.id": "GS-1"},
                        {"side": "manago_only", "order.id": "GS-m"},
                        {"side": "shopify_only", "order.id": "GS-2"},
                    ],
                },
            }
        ]
        contact = Contact.objects.create(
            company=self.company,
            email="gs@gap.test",
            source=Contact.Source.SHOPIFY,
            external_id="c-gs",
        )
        for oid in ("GS-1", "GS-2"):
            Order.objects.create(
                company=self.company,
                contact=contact,
                source=Order.Source.SHOPIFY,
                external_id=oid,
                amount="9",
                currency="EUR",
                status=Order.Status.PAID,
            )
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={"contactId": "mc-gs"},
        ):
            rows = collect_evidence_rows(
                company=self.company, check_id="LE-05", max_rows=10
            )
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["order.id"] for r in rows}, {"GS-1", "GS-2"})

    def test_enrich_attaches_email_amount_contact_from_order(self):
        contact = Contact.objects.create(
            company=self.company,
            email="enrich@gap.test",
            source=Contact.Source.SHOPIFY,
            external_id="c-5002",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="5002",
            amount="42",
            currency="EUR",
            status=Order.Status.PAID,
        )

        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={"contactId": "mc-enriched"},
        ):
            from dataruns.writebacks.transform import _le05_evidence_rows

            enriched = _le05_evidence_rows(
                company=self.company,
                rows=[{"side": "shopify_only", "order.id": "5002"}],
                max_rows=10,
            )
        self.assertEqual(len(enriched), 1)
        self.assertEqual(enriched[0]["person.email"], "enrich@gap.test")
        self.assertEqual(float(enriched[0]["amount_gross"]), 42.0)
        self.assertEqual(enriched[0]["manago_contact_id"], "mc-enriched")

    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    def test_enrich_from_worklist_nested_value(self, mock_worklist):
        mock_worklist.return_value = [
            {
                "value": {
                    "side": "shopify_only",
                    "order.id": "NEST-5",
                }
            }
        ]
        contact = Contact.objects.create(
            company=self.company,
            email="nest@gap.test",
            source=Contact.Source.SHOPIFY,
            external_id="c-nest",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="NEST-5",
            amount="12",
            currency="EUR",
            status=Order.Status.PAID,
        )
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={"contactId": "mc-nest"},
        ):
            rows = collect_evidence_rows(
                company=self.company, check_id="LE-05", max_rows=10
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["order.id"], "NEST-5")
        self.assertEqual(rows[0]["person.email"], "nest@gap.test")

        mapping = get_check_mapping("LE-05")
        intents = build_intents_from_mapping(
            company=self.company, mapping=mapping, evidence_rows=rows
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].payload.get("externalId"), "NEST-5")
        self.assertEqual(intents[0].payload.get("contactExtEventType"), "PURCHASE")

    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    def test_no_sandbox_when_empty_or_manago_only(self, mock_worklist):
        mock_worklist.return_value = []
        self.assertEqual(
            collect_evidence_rows(company=self.company, check_id="LE-05", max_rows=5),
            [],
        )
        mock_worklist.return_value = [
            {"side": "manago_only", "order.id": "only-m"},
            {"side": "aggregate", "shopify_only_count": 3},
        ]
        self.assertEqual(
            collect_evidence_rows(company=self.company, check_id="LE-05", max_rows=5),
            [],
        )

    def test_event_ingest_batch_cap_available_for_le05(self):
        from dataruns.writebacks.capabilities import capability_batch_max

        cap = capability_batch_max("RESTV2.EVENT.INGEST") or 1000
        self.assertGreaterEqual(int(cap), 50)
        self.assertEqual(min(int(cap), 1000), 1000)


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb13PipelineCeilingTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("LE-05")
        tenant = Tenant.objects.create(name="WB13P", slug="wb13-pipe")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB13 Pipe",
            domain="wb13-pipe.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb13-pipe.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
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
        _seed_dcs_run(self.company)

    @patch("dataruns.writebacks.pipeline.collect_evidence_rows")
    def test_preview_uses_event_ingest_ceiling_not_sandbox_10(self, mock_collect):
        """LE-05 must not default to WRITEBACK_SANDBOX_MAX_ROWS=10 (LE-01 trap)."""
        from dataruns.writebacks.capabilities import capability_batch_max

        cap = min(int(capability_batch_max("RESTV2.EVENT.INGEST") or 1000), 1000)
        mock_collect.return_value = []
        with sandbox_company(self.company):
            writeback_run(
                company=self.company,
                check_id="LE-05",
                mode="dry_run",
                actor=self.admin,
            )
        kwargs = mock_collect.call_args.kwargs
        self.assertEqual(kwargs["check_id"], "LE-05")
        self.assertEqual(kwargs["max_rows"], cap)
        self.assertGreater(kwargs["max_rows"], 10)


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb13ExecuteHonestyTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("LE-05")
        tenant = Tenant.objects.create(name="WB13", slug="wb13")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB13 Co",
            domain="wb13.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb13.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
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
        _seed_dcs_run(self.company)

    def test_settings_off_blocks_execute(self):
        self.company.writeback_execute_enabled = False
        self.company.save(update_fields=["writeback_execute_enabled"])
        allowed, reason = execute_allowed(company=self.company, check_id="LE-05")
        self.assertFalse(allowed)
        self.assertEqual(reason, "writebacks_disabled")

    def test_rollback_not_supported_for_event_ingest(self):
        intent = WriteIntent(
            check_id="LE-05",
            op_kind="event_ingest",
            operation="manago.event_ingest.purchase_le05",
            target_system="manago",
            entity_type="event",
            entity_key="5001",
            namespace="native",
            payload={
                "externalId": "5001",
                "email": "a@b.com",
                "contactExtEventType": "PURCHASE",
            },
            rollback_strategy="tagged_backfill_delete",
            status="executed",
        )
        ok, reason = rollback_supported(intent)
        self.assertFalse(ok)
        self.assertEqual(reason, "rollback_not_supported")

    def test_preview_exposes_irreversible(self):
        mapping = get_check_mapping("LE-05")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only",
                    "order.id": "5001-p",
                    "person.email": "p@t.test",
                    "manago_contact_id": "mc",
                    "amount_gross": 5,
                }
            ],
        )
        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="LE-05",
                mode="dry_run",
                intents=intents,
                actor=self.admin,
            )
        self.assertTrue(preview.irreversible)
        disclosure = preview.operator_disclosure or ""
        self.assertIn("Manago-only", disclosure)
        self.assertTrue(
            "not supported" in disclosure.lower()
            or "not be fully reversible" in disclosure.lower()
        )

    @patch("dataruns.writebacks.adapters.manago.batch_add_external_events")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_execute_writes_purchase_event(self, mock_ctx, mock_batch):
        mock_ctx.return_value = object()
        mock_batch.return_value = {"success": True}
        mapping = get_check_mapping("LE-05")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only",
                    "order.id": "5001-x",
                    "person.email": "x@t.test",
                    "manago_contact_id": "mc-x",
                    "amount_gross": 7,
                }
            ],
        )
        self.assertEqual(intents[0].payload.get("contactExtEventType"), "PURCHASE")

        with sandbox_company(self.company), patch(
            "dataruns.writebacks.pipeline.get_check_mapping",
            return_value=mapping,
        ):
            preview = writeback_run(
                company=self.company,
                check_id="LE-05",
                mode="dry_run",
                intents=intents,
                actor=self.admin,
            )
            token = issue_approved_writeback_token(
                company=self.company,
                job_id=preview.job_id,
                requester=self.admin,
                approver=self.admin,
            )
            result = writeback_run(
                company=self.company,
                check_id="LE-05",
                mode="sandbox_execute",
                intents=intents,
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                actor=self.admin,
            )

        self.assertEqual(result.summary.executed, 1)
        self.assertTrue(result.irreversible)
        payload = serialize_result(result, action="execute")
        self.assertFalse(payload["rollback"]["supported"])
        mock_batch.assert_called()
        events = mock_batch.call_args[0][1]
        self.assertEqual(events[0].get("contactExtEventType"), "PURCHASE")
        self.assertEqual(events[0].get("externalId"), "5001-x")

        from dataruns.models import AuditLog

        audit = (
            AuditLog.objects.filter(
                company=self.company,
                action="writeback.executed",
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.metadata.get("check_id"), "LE-05")
        self.assertTrue(audit.metadata.get("irreversible"))
