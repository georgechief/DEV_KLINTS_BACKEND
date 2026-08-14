"""event_ingest sandbox execute tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.transform import build_intents_from_mapping
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User

_MAPPINGS_DIR = Path(__file__).resolve().parents[1] / "writebacks" / "mappings"


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_CHECK_ALLOWLIST=["LE-01"],
    WRITEBACK_SANDBOX_MAX_ROWS=10,
)
class WritebackEventIngestExecuteTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="LE01", slug="le01")
        self.company = Company.objects.create(
            tenant=tenant,
            name="Sandbox Co",
            domain="le01.test",
        )
        self.admin = User.objects.create_user(
            email="admin@le01.test",
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

    def _settings_with_sandbox(self):
        return self.settings(WRITEBACK_SANDBOX_COMPANY_IDS=[str(self.company.id)])

    def _build_le01_intents(self):
        mapping = json.loads(
            (_MAPPINGS_DIR / "LE-01.event_backfill.v1.json").read_text(encoding="utf-8")
        )
        return build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "missing_purchase_event",
                    "order.id": "order-900",
                    "person.email": "buyer@example.com",
                    "manago_contact_id": "mc-55",
                    "representative_value": 42.5,
                }
            ],
        )

    @patch("dataruns.writebacks.adapters.manago.batch_add_external_events")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_sandbox_event_ingest_execute(self, mock_ctx, mock_batch):
        mock_ctx.return_value = object()
        mock_batch.return_value = {"success": True}

        intents = self._build_le01_intents()
        self.assertEqual(intents[0].op_kind, "event_ingest")
        self.assertEqual(intents[0].rollback_strategy, "tagged_backfill_delete")

        mapping = json.loads(
            (_MAPPINGS_DIR / "LE-01.event_backfill.v1.json").read_text(encoding="utf-8")
        )
        mapping["check_id"] = "LE-01"

        with self._settings_with_sandbox(), patch(
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
            result = writeback_run(
                company=self.company,
                check_id="LE-01",
                mode="sandbox_execute",
                intents=intents,
                expected_diff_hash=preview.diff_hash,
                actor=self.admin,
            )

        self.assertEqual(result.summary.executed, 1)
        self.assertTrue(mock_batch.called)
        event = mock_batch.call_args[0][1][0]
        self.assertEqual(event["externalId"], "order-900")
        self.assertEqual(event["email"], "buyer@example.com")
        self.assertEqual(event["contactId"], "mc-55")
