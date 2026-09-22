"""PRD-WB-10 — LE-09 RETURN/CANCELLATION event writeback."""

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
from dataruns.writebacks.serializers import execute_rollback_supported, serialize_result
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
class WritebackWb10RegistryAndAllowlistTests(TestCase):
    def test_le09_enabled_match_shopify_only_return(self):
        by_id = {
            str(row.get("check_id") or "").upper(): row for row in list_mapping_entries()
        }
        self.assertTrue(by_id["LE-09"].get("enabled"))

        le09 = get_check_mapping("LE-09")
        self.assertTrue(le09.get("irreversible"))
        self.assertEqual(le09["operations"][0]["op_kind"], "event_ingest")
        self.assertEqual(
            le09["operations"][0]["from_evidence"]["match"]["const"],
            "shopify_only_return",
        )
        self.assertIn(
            "event_type",
            le09["operations"][0]["from_evidence"]["fields"],
        )

    def test_allowlist_seeds_le09(self):
        from django.apps import apps as django_apps

        mod = importlib.import_module("dataruns.migrations.0038_writeback_allowed_le09")
        WritebackAllowedCheck.objects.filter(check_id="LE-09").delete()
        mod.seed_wb10_allowlist(django_apps, None)
        self.assertTrue(
            WritebackAllowedCheck.objects.filter(check_id="LE-09", enabled=True).exists()
        )


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb10TransformTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="WB10T", slug="wb10-transform")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB10 Co",
            domain="wb10-transform.test",
        )

    def test_shopify_only_return_builds_return_event(self):
        mapping = get_check_mapping("LE-09")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only_return",
                    "order.id": "671-1",
                    "person.email": "buyer@return.test",
                    "manago_contact_id": "mc-r1",
                    "amount_gross": 48.0,
                    "event_type": "RETURN",
                }
            ],
        )
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.op_kind, "event_ingest")
        self.assertEqual(intent.status, "ready")
        self.assertEqual(intent.payload.get("externalId"), "671-1")
        self.assertEqual(intent.payload.get("contactExtEventType"), "RETURN")
        self.assertEqual(intent.payload.get("value"), 48.0)
        self.assertEqual(intent.payload.get("email"), "buyer@return.test")

    def test_missing_event_type_defaults_return_not_purchase(self):
        mapping = get_check_mapping("LE-09")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only_return",
                    "order.id": "671-3",
                    "person.email": "n@x.test",
                    "manago_contact_id": "mc-n",
                    "amount_gross": 9,
                }
            ],
        )
        self.assertEqual(intents[0].payload.get("contactExtEventType"), "RETURN")

    @patch("dataruns.writebacks.transform._le09_shopify_raw_order")
    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    def test_refunded_with_cancelled_at_is_cancellation(self, mock_worklist, mock_raw):
        mock_worklist.return_value = [
            {"side": "shopify_only_return", "order.id": "RC-1"}
        ]
        mock_raw.return_value = {
            "id": "RC-1",
            "financial_status": "refunded",
            "cancelled_at": "2026-09-01T00:00:00Z",
            "total_price": "20.00",
            "email": "both@example.com",
        }
        contact = Contact.objects.create(
            company=self.company,
            email="both@example.com",
            source=Contact.Source.SHOPIFY,
            external_id="cust-rc",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="RC-1",
            amount="20",
            currency="USD",
            status=Order.Status.REFUNDED,
        )
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={"contactId": "mc-rc"},
        ):
            rows = collect_evidence_rows(
                company=self.company, check_id="LE-09", max_rows=10
            )
        self.assertEqual(rows[0]["event_type"], "CANCELLATION")

    @patch("dataruns.writebacks.transform.find_manago_contact")
    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    def test_enriches_nested_worklist_value_shape(self, mock_worklist, mock_find):
        """Worklist normalizes mismatches into value={side, order.id}."""
        mock_worklist.return_value = [
            {
                "source": "snapshot",
                "locator": "lifecycle.returns",
                "value": {"side": "shopify_only_return", "order.id": "NEST-1"},
            }
        ]
        mock_find.return_value = {"contactId": "mc-nest"}
        contact = Contact.objects.create(
            company=self.company,
            email="nest@example.com",
            source=Contact.Source.SHOPIFY,
            external_id="cust-nest",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="NEST-1",
            amount="15.5",
            currency="USD",
            status=Order.Status.REFUNDED,
        )
        rows = collect_evidence_rows(
            company=self.company, check_id="LE-09", max_rows=10
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["person.email"], "nest@example.com")
        self.assertEqual(rows[0]["amount_gross"], 15.5)
        self.assertEqual(rows[0]["event_type"], "RETURN")

        mapping = get_check_mapping("LE-09")
        intents = build_intents_from_mapping(
            company=self.company, mapping=mapping, evidence_rows=rows
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].payload.get("contactExtEventType"), "RETURN")

    @patch("dataruns.writebacks.transform._le09_shopify_raw_order")
    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    def test_failed_order_wins_over_raw_refunded_signal(self, mock_worklist, mock_raw):
        """Order FAILED (cancel) must not become RETURN just because raw looks refunded."""
        mock_worklist.return_value = [
            {"side": "shopify_only_return", "order.id": "FAIL-1"}
        ]
        mock_raw.return_value = {
            "id": "FAIL-1",
            "financial_status": "refunded",
            "cancelled_at": None,
            "total_price": "8.00",
        }
        contact = Contact.objects.create(
            company=self.company,
            email="fail@example.com",
            source=Contact.Source.SHOPIFY,
            external_id="cust-fail",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="FAIL-1",
            amount="8",
            currency="USD",
            status=Order.Status.FAILED,
        )
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={"contactId": "mc-fail"},
        ):
            rows = collect_evidence_rows(
                company=self.company, check_id="LE-09", max_rows=10
            )
        self.assertEqual(rows[0]["event_type"], "CANCELLATION")

    def test_ignores_manago_only_return_and_le01_shopify_only(self):
        mapping = get_check_mapping("LE-09")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {"side": "manago_only_return", "order.id": "m1", "person.email": "a@b.c"},
                {
                    "side": "shopify_only",
                    "order.id": "p1",
                    "person.email": "a@b.c",
                    "amount_gross": 1,
                },
            ],
        )
        self.assertEqual(intents, [])

    def test_missing_identity_errors(self):
        mapping = get_check_mapping("LE-09")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only_return",
                    "order.id": "orphan-r",
                    "amount_gross": 1.0,
                    "event_type": "RETURN",
                }
            ],
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].status, "error")
        self.assertEqual(intents[0].error_reason, "missing_contact_reference")

    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    @patch("dataruns.writebacks.transform.find_manago_contact")
    def test_collect_enriches_from_refunded_order(self, mock_find, mock_worklist):
        mock_worklist.return_value = [
            {"side": "shopify_only_return", "order.id": "R-100"}
        ]
        mock_find.return_value = {"contactId": "mc-enrich"}
        contact = Contact.objects.create(
            company=self.company,
            email="refund@example.com",
            source=Contact.Source.SHOPIFY,
            external_id="cust-1",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="R-100",
            amount="77.25",
            currency="USD",
            status=Order.Status.REFUNDED,
        )
        rows = collect_evidence_rows(
            company=self.company, check_id="LE-09", max_rows=10
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["person.email"], "refund@example.com")
        self.assertEqual(rows[0]["amount_gross"], 77.25)
        self.assertEqual(rows[0]["event_type"], "RETURN")
        self.assertEqual(rows[0]["manago_contact_id"], "mc-enrich")

    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    def test_failed_order_maps_to_cancellation(self, mock_worklist):
        mock_worklist.return_value = [
            {"side": "shopify_only_return", "order.id": "C-100"}
        ]
        contact = Contact.objects.create(
            company=self.company,
            email="cancel@example.com",
            source=Contact.Source.SHOPIFY,
            external_id="cust-2",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="C-100",
            amount="12",
            currency="USD",
            status=Order.Status.FAILED,
        )
        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={"contactId": "mc-c"},
        ):
            rows = collect_evidence_rows(
                company=self.company, check_id="LE-09", max_rows=10
            )
        self.assertEqual(rows[0]["event_type"], "CANCELLATION")

    @patch("dataruns.writebacks.transform._worklist_evidence_rows")
    def test_no_sandbox_when_empty_or_aggregate_only(self, mock_worklist):
        mock_worklist.return_value = []
        self.assertEqual(
            collect_evidence_rows(company=self.company, check_id="LE-09", max_rows=5),
            [],
        )
        mock_worklist.return_value = [
            {"side": "aggregate", "shopify_refund_cancel_orders": 9}
        ]
        self.assertEqual(
            collect_evidence_rows(company=self.company, check_id="LE-09", max_rows=5),
            [],
        )

    def test_event_ingest_batch_cap_available_for_le09(self):
        from dataruns.writebacks.capabilities import capability_batch_max

        cap = capability_batch_max("RESTV2.EVENT.INGEST") or 1000
        self.assertGreaterEqual(int(cap), 50)
        self.assertEqual(min(int(cap), 1000), 1000)


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb10ExecuteHonestyTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("LE-09")
        tenant = Tenant.objects.create(name="WB10", slug="wb10")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB10 Co",
            domain="wb10.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb10.test",
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
        allowed, reason = execute_allowed(company=self.company, check_id="LE-09")
        self.assertFalse(allowed)
        self.assertEqual(reason, "writebacks_disabled")

    def test_rollback_not_supported_for_event_ingest(self):
        intent = WriteIntent(
            check_id="LE-09",
            op_kind="event_ingest",
            operation="manago.event_ingest.return_cancel",
            target_system="manago",
            entity_type="event",
            entity_key="671",
            namespace="native",
            payload={"externalId": "671", "email": "a@b.com", "contactExtEventType": "RETURN"},
            rollback_strategy="tagged_backfill_delete",
            status="executed",
        )
        ok, reason = rollback_supported(intent)
        self.assertFalse(ok)
        self.assertEqual(reason, "rollback_not_supported")

    def test_preview_exposes_irreversible(self):
        mapping = get_check_mapping("LE-09")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only_return",
                    "order.id": "671-p",
                    "person.email": "p@t.test",
                    "manago_contact_id": "mc",
                    "amount_gross": 5,
                    "event_type": "RETURN",
                }
            ],
        )
        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="LE-09",
                mode="dry_run",
                intents=intents,
                actor=self.admin,
            )
        self.assertTrue(preview.irreversible)
        self.assertIn("RETURN", preview.operator_disclosure or "")
        self.assertTrue(
            "not supported" in (preview.operator_disclosure or "").lower()
            or "best-effort" in (preview.operator_disclosure or "").lower()
            or "not be fully reversible" in (preview.operator_disclosure or "").lower()
        )
    @patch("dataruns.writebacks.adapters.manago.batch_add_external_events")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_execute_writes_return_event_and_no_full_rollback(
        self, mock_ctx, mock_batch
    ):
        mock_ctx.return_value = object()
        mock_batch.return_value = {"success": True}
        mapping = get_check_mapping("LE-09")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only_return",
                    "order.id": "671-exec",
                    "person.email": "exec@return.test",
                    "manago_contact_id": "mc-exec",
                    "amount_gross": 33.0,
                    "event_type": "RETURN",
                }
            ],
        )
        self.assertEqual(intents[0].payload.get("contactExtEventType"), "RETURN")

        with sandbox_company(self.company), patch(
            "dataruns.writebacks.pipeline.get_check_mapping",
            return_value=mapping,
        ):
            preview = writeback_run(
                company=self.company,
                check_id="LE-09",
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
                check_id="LE-09",
                mode="sandbox_execute",
                intents=intents,
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                actor=self.admin,
            )

        self.assertEqual(result.summary.executed, 1)
        self.assertTrue(result.irreversible)
        self.assertFalse(execute_rollback_supported(result))
        payload = serialize_result(result, action="execute")
        self.assertFalse(payload["rollback"]["supported"])
        mock_batch.assert_called()
        events = mock_batch.call_args[0][1]
        self.assertEqual(events[0].get("contactExtEventType"), "RETURN")
        self.assertEqual(events[0].get("externalId"), "671-exec")

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
        self.assertEqual(audit.metadata.get("check_id"), "LE-09")
        self.assertTrue(audit.metadata.get("irreversible"))
