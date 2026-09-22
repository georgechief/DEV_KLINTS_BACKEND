"""PRD-WB-09 — SP-07 namespace clean writeback."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from dataruns.dcs.segment_join import (
    build_segment_snapshot,
    is_klints_owned_detail,
    legacy_namespace_rename,
)
from dataruns.models import WritebackAllowedCheck
from dataruns.writebacks.gates import execute_allowed, is_check_allowlisted
from dataruns.writebacks.registry import get_check_mapping
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.transform import (
    _sp07_collision_catalog,
    _sp07_evidence_rows,
    build_intents_from_mapping,
)
from dataruns.writebacks.types import WriteIntent
from tenants.models import Company, Tenant, User


class Sp07OwnedAllowlistTests(SimpleTestCase):
    def test_owned_consent_evidence_not_collision(self):
        from dataruns.dcs.segment_join import clear_klints_owned_keys_cache

        clear_klints_owned_keys_cache()
        self.assertTrue(is_klints_owned_detail("klints_consent_evidence"))
        self.assertTrue(is_klints_owned_detail("KLINTS_BACKFILL"))
        # WB-11: PT-04 mapping owns klints_net_ltv
        self.assertTrue(is_klints_owned_detail("klints_net_ltv"))
        self.assertFalse(is_klints_owned_detail("klints_foreign_example"))

    def test_legacy_rename_prefix(self):
        self.assertEqual(legacy_namespace_rename("klints_net_ltv"), "legacy_klints_net_ltv")
        self.assertEqual(legacy_namespace_rename("klints:vip"), "legacy_klints:vip")
        self.assertEqual(legacy_namespace_rename("legacy_klints_x"), "legacy_klints_x")

    def test_segment_join_skips_owned_keys(self):
        from dataruns.dcs.segment_join import clear_klints_owned_keys_cache

        clear_klints_owned_keys_cache()
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, source_run_id=None, snapshot_id=None):
            return {
                "contacts": [
                    {
                        "properties": [
                            {"name": "klints_backfill", "value": "true"},
                            {"name": "klints_consent_evidence", "value": "shopify_verified"},
                            {"name": "klints_net_ltv", "value": "1"},
                            {"name": "klints_foreign_example", "value": "1"},
                        ],
                        "contactTags": [{"name": "klints:foreign"}],
                    }
                ]
            }

        with patch(
            "dataruns.dcs.segment_join._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_segment_snapshot(company=company)
        seg = payload["segment"]
        self.assertNotIn("klints_net_ltv", seg["klints_detail_collisions"])
        self.assertIn("klints_foreign_example", seg["klints_detail_collisions"])
        self.assertNotIn("klints_backfill", seg["klints_detail_collisions"])
        self.assertNotIn("klints_consent_evidence", seg["klints_detail_collisions"])
        self.assertIn("klints:foreign", seg["klints_tag_collisions"])
        self.assertEqual(seg["klints_collision_count"], 2)


class Sp07TransformTests(SimpleTestCase):
    def test_collision_catalog_from_evidence_value(self):
        from dataruns.dcs.segment_join import clear_klints_owned_keys_cache

        clear_klints_owned_keys_cache()
        details, tags = _sp07_collision_catalog(
            [
                {
                    "value": {
                        "klints_detail_collisions": [
                            "klints_foreign_example",
                            "klints_consent_evidence",
                        ],
                        "klints_tag_collisions": ["klints:legacy"],
                    }
                }
            ]
        )
        self.assertEqual(details, ["klints_foreign_example"])
        self.assertEqual(tags, ["klints:legacy"])

    def test_collision_catalog_merges_mismatch_and_evidence_shapes(self):
        details, tags = _sp07_collision_catalog(
            [
                {
                    "value": {
                        "side": "klints_detail_collision",
                        "key": "klints_foo",
                    }
                },
                {
                    "value": {
                        "klints_detail_collisions": ["klints_bar"],
                        "klints_tag_collisions": ["klints:z"],
                    }
                },
            ]
        )
        self.assertEqual(sorted(details), ["klints_bar", "klints_foo"])
        self.assertEqual(tags, ["klints:z"])

    def test_fan_out_to_contacts(self):
        from dataruns.dcs.segment_join import clear_klints_owned_keys_cache

        clear_klints_owned_keys_cache()
        company = SimpleNamespace(id="c1")
        contacts = [
            {
                "email": "a@example.com",
                "contactId": "c1",
                "properties": {"klints_foreign_example": "10"},
                "contactTags": ["klints:old"],
            },
            {
                "email": "b@example.com",
                "contactId": "c2",
                "properties": {"other": "1"},
                "contactTags": [],
            },
        ]
        with patch(
            "dataruns.writebacks.transform._snapshot_contacts",
            return_value=contacts,
        ):
            rows = _sp07_evidence_rows(
                company=company,
                rows=[
                    {
                        "side": "klints_detail_collision",
                        "key": "klints_foreign_example",
                    },
                    {"side": "klints_tag_collision", "tag": "klints:old"},
                ],
                max_rows=None,
            )
        self.assertEqual(len(rows), 2)
        detail = next(r for r in rows if r["side"] == "klints_detail_collision")
        self.assertEqual(detail["rename_to"], "legacy_klints_foreign_example")
        self.assertEqual(detail["detail_value"], "10")
        self.assertEqual(detail["person.email"], "a@example.com")
        self.assertEqual(detail["entity_key"], "a@example.com")
        tag = next(r for r in rows if r["side"] == "klints_tag_collision")
        self.assertEqual(tag["rename_to"], "legacy_klints:old")

    def test_fan_out_contact_id_only_no_fake_email(self):
        from dataruns.dcs.segment_join import clear_klints_owned_keys_cache

        clear_klints_owned_keys_cache()
        company = SimpleNamespace(id="c1")
        contacts = [
            {
                "contactId": "mc-only",
                "properties": {"klints_foreign_example": "9"},
                "contactTags": [],
            },
        ]
        with patch(
            "dataruns.writebacks.transform._snapshot_contacts",
            return_value=contacts,
        ):
            rows = _sp07_evidence_rows(
                company=company,
                rows=[
                    {
                        "side": "klints_detail_collision",
                        "key": "klints_foreign_example",
                    }
                ],
                max_rows=None,
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_key"], "mc-only")
        self.assertIsNone(rows[0]["person.email"])
        self.assertNotIn("@manago.invalid", str(rows[0].get("person.email") or ""))

    def test_build_intents_detail_and_tag_rename(self):
        company = SimpleNamespace(id="c1")
        mapping = get_check_mapping("SP-07")
        self.assertFalse(mapping.get("requires_consent_namespace_clean"))
        self.assertEqual(mapping.get("rollback", {}).get("strategy"), "reverse_rename_map")

        with patch(
            "dataruns.writebacks.transform.find_manago_contact",
            return_value={
                "email": "a@example.com",
                "contactId": "c1",
                "properties": {"klints_net_ltv": "10"},
                "contactTags": ["klints:old"],
            },
        ):
            intents = build_intents_from_mapping(
                company=company,
                mapping=mapping,
                evidence_rows=[
                    {
                        "side": "klints_detail_collision",
                        "key": "klints_net_ltv",
                        "rename_to": "legacy_klints_net_ltv",
                        "detail_value": "10",
                        "entity_key": "a@example.com",
                        "person.email": "a@example.com",
                        "manago_contact_id": "c1",
                    },
                    {
                        "side": "klints_tag_collision",
                        "tag": "klints:old",
                        "rename_to": "legacy_klints:old",
                        "entity_key": "a@example.com",
                        "person.email": "a@example.com",
                        "manago_contact_id": "c1",
                    },
                ],
            )
        self.assertEqual(len(intents), 2)
        detail = next(i for i in intents if i.op_kind == "detail_set")
        self.assertEqual(detail.status, "ready")
        self.assertEqual(detail.rollback_strategy, "reverse_rename_map")
        props = detail.payload.get("properties") or {}
        self.assertEqual(props.get("legacy_klints_net_ltv"), "10")
        self.assertEqual(props.get("klints_net_ltv"), "")
        self.assertEqual((detail.payload.get("_rename") or {}).get("from"), "klints_net_ltv")
        tag = next(i for i in intents if i.op_kind == "tag_add")
        self.assertEqual(tag.payload.get("tag"), "legacy_klints:old")
        self.assertEqual(tag.payload.get("_remove_tag"), "klints:old")
        supported, reason = rollback_supported(detail)
        self.assertTrue(supported)
        self.assertIsNone(reason)


@override_settings(
    WRITEBACK_SANDBOX_COMPANY_IDS=[],
)
class Sp07AllowlistTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="SP07", slug="sp07")
        self.company = Company.objects.create(
            tenant=tenant,
            name="SP07 Co",
            domain="sp07.test",
        )
        WritebackAllowedCheck.objects.get_or_create(
            check_id="SP-07",
            defaults={"enabled": True, "note": "test"},
        )
        self.admin = User.objects.create_user(
            email="sp07-admin@example.com",
            password="x",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )

    def test_sp07_allowlisted(self):
        self.assertTrue(is_check_allowlisted("SP-07"))

    def test_execute_denied_when_settings_off(self):
        self.company.writeback_execute_enabled = False
        self.company.save(update_fields=["writeback_execute_enabled"])
        allowed, reason = execute_allowed(company=self.company, check_id="SP-07")
        self.assertFalse(allowed)
        self.assertEqual(reason, "writebacks_disabled")

    def test_mapping_no_self_preflight(self):
        mapping = get_check_mapping("SP-07")
        self.assertFalse(mapping.get("requires_consent_namespace_clean"))
        self.assertTrue(mapping.get("enabled"))
        ops = mapping.get("operations") or []
        self.assertEqual(len(ops), 2)


class Sp07PipelineCapTests(SimpleTestCase):
    def test_sp07_default_cap_uses_upsert_batch_not_sandbox_10(self):
        """WB-09 recheck: account-wide rename must not default to WRITEBACK_SANDBOX_MAX_ROWS=10."""
        from dataruns.writebacks.capabilities import capability_batch_max

        cap = capability_batch_max("RESTV2.CONTACT.UPSERT") or 1000
        self.assertGreaterEqual(int(cap), 100)
        self.assertEqual(min(int(cap), 1000), 1000)


class Sp07AdapterRenameRollbackTests(SimpleTestCase):
    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_detail_rename_rollback_restores_keys(self, mock_ctx, mock_upsert):
        from dataruns.writebacks.adapters.manago import ManagoWriteAdapter

        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True}
        adapter = ManagoWriteAdapter()
        intent = WriteIntent(
            check_id="SP-07",
            op_kind="detail_set",
            operation="manago.detail_rename.off_klints",
            target_system="manago",
            entity_type="contact",
            entity_key="a@example.com",
            namespace="native",
            payload={
                "email": "a@example.com",
                "contactId": "c1",
                "properties": {
                    "legacy_klints_net_ltv": "10",
                    "klints_net_ltv": "",
                },
                "_rename": {
                    "from": "klints_net_ltv",
                    "to": "legacy_klints_net_ltv",
                    "op": "detail",
                    "prior_from_value": "10",
                    "prior_to_value": None,
                },
            },
            rollback_snapshot={
                "rename": {
                    "from": "klints_net_ltv",
                    "to": "legacy_klints_net_ltv",
                    "op": "detail",
                    "prior_from_value": "10",
                    "prior_to_value": None,
                }
            },
            status="executed",
            rollback_strategy="reverse_rename_map",
        )
        outcome = adapter.rollback_intent(SimpleNamespace(id="c"), intent)
        self.assertTrue(outcome.get("ok"))
        props = mock_upsert.call_args[0][1][0]["properties"]
        self.assertEqual(props["klints_net_ltv"], "10")
        self.assertEqual(props["legacy_klints_net_ltv"], "")
