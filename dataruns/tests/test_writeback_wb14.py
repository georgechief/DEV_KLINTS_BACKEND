"""PRD-WB-14 — LE-02 purchase value correction writeback."""

from __future__ import annotations

import importlib
from unittest.mock import patch

from django.test import TestCase, override_settings

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import DataRun, Run, WritebackAllowedCheck
from dataruns.tests.writeback_helpers import (
    issue_approved_writeback_token,
    sandbox_company,
    seed_writeback_allowlist,
)
from dataruns.writebacks.registry import get_check_mapping, list_mapping_entries
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.transform import build_intents_from_mapping
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
class WritebackWb14RegistryTests(TestCase):
    def test_le02_enabled_event_correct_value_mismatch(self):
        by_id = {
            str(row.get("check_id") or "").upper(): row for row in list_mapping_entries()
        }
        self.assertTrue(by_id["LE-02"].get("enabled"))
        self.assertTrue(by_id["LE-05"].get("enabled"))
        self.assertTrue(by_id["LE-01"].get("enabled"))

        le02 = get_check_mapping("LE-02")
        self.assertTrue(le02.get("irreversible"))
        self.assertEqual(le02.get("approval_tier"), "individual")
        self.assertEqual(le02["operations"][0]["op_kind"], "event_correct")
        self.assertEqual(
            le02["operations"][0]["from_evidence"]["match"]["const"],
            "value_mismatch",
        )
        self.assertEqual(
            le02["operations"][0]["capability_id"],
            "RESTV2.EVENT.UPDATE",
        )
        self.assertNotIn("event_ingest", str(le02))

    def test_allowlist_seeds_le02(self):
        from django.apps import apps as django_apps

        mod = importlib.import_module("dataruns.migrations.0041_writeback_allowed_le02")
        WritebackAllowedCheck.objects.filter(check_id="LE-02").delete()
        mod.seed_wb14_allowlist(django_apps, None)
        self.assertTrue(
            WritebackAllowedCheck.objects.filter(check_id="LE-02", enabled=True).exists()
        )


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb14TransformTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="WB14T", slug="wb14-transform")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB14 Co",
            domain="wb14-transform.test",
        )

    def test_value_mismatch_builds_event_correct(self):
        mapping = get_check_mapping("LE-02")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "value_mismatch",
                    "order.id": "9001",
                    "event_external_id": "9001",
                    "person.email": "buyer@value.test",
                    "manago_contact_id": "mc-v1",
                    "shopify_gross": 120.0,
                    "manago_value": 100.0,
                    "occurred_at": "2026-01-15T12:00:00+00:00",
                    "currency": "USD",
                }
            ],
        )
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.op_kind, "event_correct")
        self.assertEqual(intent.status, "ready")
        self.assertEqual(intent.payload.get("externalId"), "9001")
        self.assertEqual(intent.payload.get("contactExtEventType"), "PURCHASE")
        self.assertEqual(intent.payload.get("value"), 120.0)
        self.assertEqual(intent.payload.get("email"), "buyer@value.test")
        self.assertEqual(intent.payload.get("currency"), "USD")
        self.assertIsInstance(intent.payload.get("date"), int)
        ok, reason = rollback_supported(intent)
        self.assertFalse(ok)
        self.assertEqual(reason, "rollback_not_supported")

    def test_order_number_match_uses_event_external_id_not_shopify_id(self):
        """Catalogue update keys Manago externalId — may differ from Shopify order.id."""
        mapping = get_check_mapping("LE-02")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "value_mismatch",
                    "order.id": "gid-shopify-55",
                    "event_external_id": "1001",
                    "match_kind": "order_number",
                    "person.email": "num@value.test",
                    "manago_contact_id": "mc-n1",
                    "shopify_gross": 55.5,
                    "manago_value": 40.0,
                }
            ],
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].payload.get("externalId"), "1001")
        self.assertEqual(intents[0].payload.get("value"), 55.5)
        self.assertEqual(intents[0].entity_key, "1001")

    def test_keeps_mismatch_shopify_gross_when_resolving_identity(self):
        """DCS shopify_gross is SoT — Order.amount must not overwrite it."""
        from dataruns.models import Contact, Order

        contact = Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="c-keep",
            email="keep@value.test",
            link_key="keep",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="9001",
            amount="999.00",  # different from mismatch — must not win
            currency="USD",
            status="paid",
        )
        mapping = get_check_mapping("LE-02")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "value_mismatch",
                    "order.id": "9001",
                    "event_external_id": "9001",
                    "person.email": "keep@value.test",
                    "manago_contact_id": "",  # force enrich Order lookup path
                    "shopify_gross": 120.0,
                    "manago_value": 100.0,
                }
            ],
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].payload.get("value"), 120.0)
        self.assertEqual(intents[0].payload.get("email"), "keep@value.test")

    def test_fills_missing_shopify_gross_from_order(self):
        """PRD §5.3 — Order.amount fallback only when mismatch amount missing."""
        from dataruns.models import Contact, Order
        from dataruns.writebacks.transform import _le02_evidence_rows

        contact = Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="c-fill",
            email="fill@value.test",
            link_key="fill",
        )
        Order.objects.create(
            company=self.company,
            contact=contact,
            source=Order.Source.SHOPIFY,
            external_id="9002",
            amount="88.50",
            currency="USD",
            status="paid",
        )
        enriched = _le02_evidence_rows(
            company=self.company,
            rows=[
                {
                    "side": "value_mismatch",
                    "order.id": "9002",
                    "event_external_id": "9002",
                    "person.email": "fill@value.test",
                    "manago_contact_id": "mc-fill",
                    "manago_value": 70.0,
                    # shopify_gross intentionally omitted
                }
            ],
            max_rows=None,
        )
        self.assertEqual(len(enriched), 1)
        self.assertEqual(enriched[0].get("shopify_gross"), 88.5)

        mapping = get_check_mapping("LE-02")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=enriched,
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].payload.get("value"), 88.5)

    def test_ignores_drivers_and_gap_sides(self):
        mapping = get_check_mapping("LE-02")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {"side": "driver", "driver": "value_field_mapping"},
                {"side": "shopify_only", "order.id": "s1", "person.email": "a@b.c"},
                {"side": "manago_only", "order.id": "m1", "person.email": "a@b.c"},
            ],
        )
        self.assertEqual(intents, [])

    def test_no_sandbox_when_empty(self):
        mapping = get_check_mapping("LE-02")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[],
        )
        self.assertEqual(intents, [])


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb14PipelineCeilingTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("LE-02")
        tenant = Tenant.objects.create(name="WB14C", slug="wb14-ceiling")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB14 Ceiling",
            domain="wb14-ceiling.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb14c.test",
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
    def test_le02_uses_event_update_ceiling_not_individual_one(self, mock_collect):
        from dataruns.writebacks.capabilities import capability_batch_max

        cap = min(int(capability_batch_max("RESTV2.EVENT.UPDATE") or 50), 1000)
        mock_collect.return_value = []
        with sandbox_company(self.company):
            writeback_run(
                company=self.company,
                check_id="LE-02",
                mode="dry_run",
                actor=self.admin,
            )
        kwargs = mock_collect.call_args.kwargs
        self.assertEqual(kwargs["check_id"], "LE-02")
        self.assertEqual(kwargs["max_rows"], cap)
        self.assertGreater(kwargs["max_rows"], 1)


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb14ExecuteTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("LE-02")
        tenant = Tenant.objects.create(name="WB14E", slug="wb14-exec")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB14 Exec",
            domain="wb14-exec.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb14e.test",
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

    @patch("dataruns.writebacks.adapters.manago.update_contact_ext_event")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_execute_calls_update_not_ingest(self, mock_ctx, mock_update):
        mock_ctx.return_value = object()
        mock_update.return_value = {"success": True}
        mapping = get_check_mapping("LE-02")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "value_mismatch",
                    "order.id": "9001-x",
                    "event_external_id": "9001-x",
                    "person.email": "x@v.test",
                    "manago_contact_id": "mc-x",
                    "shopify_gross": 77.0,
                    "manago_value": 50.0,
                }
            ],
        )
        self.assertEqual(intents[0].op_kind, "event_correct")

        with sandbox_company(self.company), patch(
            "dataruns.writebacks.pipeline.get_check_mapping",
            return_value=mapping,
        ):
            preview = writeback_run(
                company=self.company,
                check_id="LE-02",
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
                check_id="LE-02",
                mode="sandbox_execute",
                intents=intents,
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                actor=self.admin,
            )

        self.assertEqual(result.summary.executed, 1)
        mock_update.assert_called()
        event = mock_update.call_args[0][1]
        self.assertEqual(event.get("externalId"), "9001-x")
        self.assertEqual(event.get("value"), 77.0)
        self.assertEqual(event.get("contactExtEventType"), "PURCHASE")
