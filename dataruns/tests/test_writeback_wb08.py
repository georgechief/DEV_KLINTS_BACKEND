"""PRD-WB-08 Phase 3 — LE-01 writeback (SP-01 not in MVP1 42; stay disabled)."""

from __future__ import annotations

import importlib
from unittest.mock import patch

from django.apps import apps as django_apps
from django.test import TestCase, override_settings

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import DataRun, Run, WritebackAllowedCheck
from dataruns.tests.writeback_helpers import (
    issue_approved_writeback_token,
    sandbox_company,
    seed_writeback_allowlist,
)
from dataruns.writebacks.gates import execute_allowed
from dataruns.writebacks.registry import MappingDisabled, get_check_mapping, list_mapping_entries
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.serializers import execute_rollback_supported, serialize_result
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.transform import build_intents_from_mapping
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
class WritebackWb08RegistryAndAllowlistTests(TestCase):
    def test_le01_enabled_sp01_disabled_not_mvp1_42(self):
        by_id = {
            str(row.get("check_id") or "").upper(): row for row in list_mapping_entries()
        }
        self.assertTrue(by_id["LE-01"].get("enabled"))
        self.assertFalse(by_id["SP-01"].get("enabled"))

        with self.assertRaises(MappingDisabled):
            get_check_mapping("SP-01")

        le01 = get_check_mapping("LE-01")
        self.assertTrue(le01.get("irreversible"))
        self.assertEqual(le01["operations"][0]["op_kind"], "event_ingest")
        self.assertEqual(
            le01["operations"][0]["from_evidence"]["match"]["const"],
            "shopify_only",
        )

    def test_ci03_and_le04_stay_disabled(self):
        with self.assertRaises(MappingDisabled):
            get_check_mapping("CI-03")
        with self.assertRaises(MappingDisabled):
            get_check_mapping("LE-04")

    def test_allowlist_ensures_le01_and_sp01_removed(self):
        mod35 = importlib.import_module(
            "dataruns.migrations.0035_writeback_allowed_sp01_le01_ensure_enabled"
        )
        mod36 = importlib.import_module(
            "dataruns.migrations.0036_writeback_disallow_sp01_not_in_mvp1_42"
        )
        WritebackAllowedCheck.objects.filter(check_id__in=("SP-01", "LE-01")).delete()
        mod35.ensure_wb08_allowlist_enabled(django_apps, None)
        mod36.disable_sp01_allowlist(django_apps, None)

        self.assertTrue(
            WritebackAllowedCheck.objects.filter(check_id="LE-01", enabled=True).exists()
        )
        self.assertFalse(WritebackAllowedCheck.objects.filter(check_id="SP-01").exists())


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb08Le01PreviewAndExecuteTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("LE-01")
        tenant = Tenant.objects.create(name="WB08", slug="wb08")
        self.company = Company.objects.create(
            tenant=tenant,
            name="WB08 Co",
            domain="wb08.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb08.test",
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

    def test_preview_le01_exposes_irreversible_disclosure(self):
        mapping = get_check_mapping("LE-01")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only",
                    "order.id": "ord-wb08",
                    "person.email": "buyer@example.com",
                    "manago_contact_id": "mc-1",
                    "amount_gross": 12.5,
                }
            ],
        )
        self.assertEqual(intents[0].op_kind, "event_ingest")
        self.assertEqual(intents[0].payload.get("externalId"), "ord-wb08")

        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="LE-01",
                mode="dry_run",
                intents=intents,
                actor=self.admin,
            )
        self.assertTrue(preview.irreversible)
        self.assertIn("PURCHASE", preview.operator_disclosure or "")
        self.assertIn("best-effort", (preview.operator_disclosure or "").lower())

    def test_execute_denied_when_settings_off(self):
        self.company.writeback_execute_enabled = False
        self.company.save(update_fields=["writeback_execute_enabled"])
        allowed, reason = execute_allowed(company=self.company, check_id="LE-01")
        self.assertFalse(allowed)
        self.assertEqual(reason, "writebacks_disabled")

    def test_sp01_not_allowlisted(self):
        self.company.writeback_execute_enabled = True
        self.company.save(update_fields=["writeback_execute_enabled"])
        allowed, reason = execute_allowed(company=self.company, check_id="SP-01")
        self.assertFalse(allowed)
        self.assertEqual(reason, "check_not_allowlisted")

    def test_le01_rollback_strategy_not_supported_honest(self):
        intent = WriteIntent(
            check_id="LE-01",
            op_kind="event_ingest",
            operation="manago.event_ingest.purchase",
            target_system="manago",
            entity_type="event",
            entity_key="ord-1",
            namespace="native",
            payload={"externalId": "ord-1", "email": "a@b.com"},
            rollback_strategy="tagged_backfill_delete",
            status="executed",
        )
        supported, reason = rollback_supported(intent)
        self.assertFalse(supported)
        self.assertEqual(reason, "rollback_not_supported")

    @patch("dataruns.writebacks.adapters.manago.batch_add_external_events")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_le01_execute_does_not_claim_full_rollback_supported(
        self, mock_ctx, mock_batch
    ):
        mock_ctx.return_value = object()
        mock_batch.return_value = {"success": True}
        mapping = get_check_mapping("LE-01")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only",
                    "order.id": "ord-900",
                    "person.email": "buyer@example.com",
                    "manago_contact_id": "mc-55",
                    "amount_gross": 42.5,
                }
            ],
        )

        with sandbox_company(self.company), patch(
            "dataruns.writebacks.pipeline.get_check_mapping",
            return_value=mapping,
        ):
            preview = writeback_run(
                company=self.company,
                check_id="LE-01",
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
                check_id="LE-01",
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
        self.assertIn("best-effort", (payload.get("operator_disclosure") or "").lower())

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
        self.assertEqual(audit.metadata.get("check_id"), "LE-01")
        self.assertTrue(audit.metadata.get("irreversible"))
