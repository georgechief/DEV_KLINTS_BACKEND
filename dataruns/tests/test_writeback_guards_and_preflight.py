"""Namespace guards, capability gate, SP-07 preflight, rollback snapshot (PRD-WB-01 §10–11)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import DataRun, Run
from dataruns.writebacks.adapters.manago import ManagoWriteAdapter
from dataruns.writebacks.guards import apply_guards
from dataruns.writebacks.registry import get_check_mapping
from dataruns.writebacks.rollback_snapshot import refresh_rollback_snapshot
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.transform import build_intents_from_mapping
from dataruns.writebacks.types import WriteIntent
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User

_MAPPINGS_DIR = Path(__file__).resolve().parents[1] / "writebacks" / "mappings"


class WritebackGuardsAndPreflightTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="WBG", slug="wbg")
        self.company = Company.objects.create(
            tenant=tenant,
            name="Guard Co",
            domain="wbg.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wbg.test",
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

    def test_klints_prefix_guard_rejects_bad_detail_key(self):
        reason = apply_guards(
            guards=["klints_prefix"],
            entity_key="user@example.com",
            namespace="klints_",
            fields={"detail_key": "vip_candidate"},
        )
        self.assertEqual(reason, "klints_prefix")

    def test_klints_prefix_guard_rejects_bad_tag(self):
        reason = apply_guards(
            guards=["klints_prefix"],
            entity_key="order-1",
            namespace="klints:",
            fields={"tag": "duplicate_review"},
        )
        self.assertEqual(reason, "klints_prefix")

    def test_ci01_payload_includes_klints_backfill_marker(self):
        mapping = get_check_mapping("CI-01")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only",
                    "email": "buyer@example.com",
                    "shopify_customer_id": "gid://shopify/Customer/1",
                }
            ],
        )
        payload = intents[0].payload
        self.assertTrue(payload.get("_mark_klints_backfill"))
        props = payload.get("properties") or {}
        self.assertEqual(props.get("klints_backfill"), "true")

    def test_le01_event_ingest_dry_run_ready(self):
        path = _MAPPINGS_DIR / "LE-01.event_backfill.v1.json"
        mapping = json.loads(path.read_text(encoding="utf-8"))
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "missing_purchase_event",
                    "order.id": "order-42",
                    "count": 1,
                }
            ],
        )
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.op_kind, "event_ingest")
        self.assertEqual(intent.status, "ready")
        self.assertEqual(intent.payload.get("externalId"), "order-42")

    def test_capability_gate_blocks_discovery_required(self):
        adapter = ManagoWriteAdapter()
        intent = WriteIntent(
            check_id="PT-01",
            op_kind="contact_upsert",
            operation="manago.contact_upsert",
            target_system="manago",
            entity_type="contact",
            entity_key="buyer@example.com",
            namespace="native",
            payload={"email": "buyer@example.com"},
            capability_id="RESTV2.PRODUCT.IMPORT",
            status="ready",
        )
        results = adapter.dry_run(self.company, [intent])
        self.assertEqual(results[0].status, "error")
        self.assertEqual(results[0].error_reason, "capability_not_confirmed")

    @override_settings(
        WRITEBACKS_ENABLED=False,
        WRITEBACK_CHECK_ALLOWLIST=["CC-03"],
    )
    def test_sp07_preflight_blocks_cc03_preview(self):
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
                    {"check_id": "CC-03", "status": "FAIL"},
                ],
            },
        )
        result = writeback_run(
            company=self.company,
            check_id="CC-03",
            mode="dry_run",
            actor=self.admin,
        )
        self.assertEqual(result.blocked_reason, "consent_namespace_not_clean")
        self.assertEqual(result.summary.ready, 0)

    @patch("dataruns.writebacks.rollback_snapshot.find_manago_contact")
    def test_rollback_snapshot_refreshed_before_detail_set_execute(self, mock_find):
        mock_find.return_value = {
            "contactId": "mc-1",
            "properties": {"klints_consent_evidence": "old_value"},
        }
        intent = WriteIntent(
            check_id="CC-03",
            op_kind="detail_set",
            operation="manago.detail_set.klints_consent_evidence",
            target_system="manago",
            entity_type="contact",
            entity_key="user@example.com",
            namespace="klints_",
            payload={
                "email": "user@example.com",
                "properties": {"klints_consent_evidence": "shopify_verified"},
            },
            rollback_snapshot={"klints_consent_evidence": None},
            status="ready",
            capability_id="RESTV2.CONTACT.UPSERT",
        )
        refresh_rollback_snapshot(self.company, intent)
        self.assertEqual(
            intent.rollback_snapshot,
            {"klints_consent_evidence": "old_value"},
        )

    def test_connector_preflight_blocks_without_manago(self):
        result = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.admin,
            max_rows=0,
        )
        self.assertIsNone(result.blocked_reason)

        Connector.objects.filter(company=self.company, name="manago_ai").update(
            status="disconnected"
        )
        blocked = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.admin,
            max_rows=0,
        )
        self.assertEqual(blocked.blocked_reason, "connector_not_connected:manago_ai")

    def test_ci01_extras_merge_from_operation(self):
        mapping = get_check_mapping("CI-01")
        mapping = dict(mapping)
        mapping["operations"] = [dict(mapping["operations"][0])]
        mapping["operations"][0]["extras"] = {"contactId": "mc-extras"}
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "shopify_only",
                    "email": "buyer@example.com",
                    "shopify_customer_id": "gid://shopify/Customer/1",
                }
            ],
        )
        self.assertEqual(intents[0].payload.get("contactId"), "mc-extras")
