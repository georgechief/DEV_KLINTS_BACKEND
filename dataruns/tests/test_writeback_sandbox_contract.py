"""PRD-WB-21 Phase A — sandbox contract for CI-01, CC-03, WB-SHOP-01.

Real pipeline: Allow writebacks → preview → approve → execute → rollback.
Mocked connector transports only (no demo Fix PASS badges).
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import Contact, DataRun, Run, RunIssue
from dataruns.tests.writeback_helpers import (
    PHASE_A_SANDBOX_CHECK_IDS,
    TIER_A_SANDBOX_CHECK_IDS,
    TIER_B_PLAN_ONLY_CHECK_IDS,
    TIER_C_EXECUTE_BLOCKED_CHECK_IDS,
    TIER_D_DISABLED_CHECK_IDS,
    assert_tier_a_sandbox_pass,
    assert_tier_b_plan_only_blocks_execute,
    assert_tier_c_execute_blocked,
    assert_tier_d_mapping_disabled,
    seed_writeback_allowlist,
)
from dataruns.writebacks.capabilities import capability_allows_execute
from dataruns.writebacks.registry import get_check_mapping
from dataruns.writebacks.transform import build_intents_from_mapping
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


def _seed_dcs_shell(*, company: Company, tenant: Tenant, check_id: str, status: str = "FAIL"):
    domain_run = Run.objects.create(
        company=company,
        run_type=Run.RunType.FULL,
        status=Run.Status.COMPLETED,
    )
    DataRun.objects.create(
        tenant=tenant,
        name=DCS_SCORE_DATA_RUN_NAME,
        status=DataRun.Status.SUCCEEDED,
        metadata={
            "kind": DCS_SCORE_KIND,
            "company_id": str(company.id),
            "run_id": str(domain_run.id),
            "dcs_run": {"run_id": str(domain_run.id), "run_state": "SCORED"},
            "check_results": [
                {"check_id": check_id, "status": status, "severity": "high"},
            ],
        },
    )
    return domain_run


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=1)
class WritebackSandboxContractPhaseATests(TestCase):
    """PRD-WB-21 §6 Phase A — dual-connector original three."""

    def test_phase_a_check_ids_locked(self):
        self.assertEqual(
            PHASE_A_SANDBOX_CHECK_IDS,
            ("CI-01", "CC-03", "WB-SHOP-01"),
        )

    def _make_admin_company(self, *, slug: str, connectors: list[str]):
        tenant = Tenant.objects.create(name=f"WB21-{slug}", slug=f"wb21-{slug}")
        company = Company.objects.create(
            tenant=tenant,
            name=f"WB21 {slug}",
            domain=f"wb21-{slug}.test",
        )
        admin = User.objects.create_user(
            email=f"admin@{slug}.wb21.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        if "manago" in connectors:
            Connector.objects.create(
                company=company,
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
        if "shopify" in connectors:
            Connector.objects.create(
                company=company,
                name="shopify",
                type="commerce",
                config=encrypt_config(
                    {
                        "shop_domain": "demo.myshopify.com",
                        "access_token": "shpat_test",
                        "api_version": "2024-10",
                    }
                ),
                status="connected",
            )
        return tenant, company, admin

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_tier_a_ci01_sandbox_pass(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-ci01"}
        seed_writeback_allowlist("CI-01")
        tenant, company, admin = self._make_admin_company(
            slug="ci01",
            connectors=["manago"],
        )
        domain_run = _seed_dcs_shell(company=company, tenant=tenant, check_id="CI-01")
        RunIssue.objects.create(
            run=domain_run,
            entity_type="dcs_check",
            entity_id=company.id,
            issue_type="CI-01",
            severity="High",
            details={
                "check_id": "CI-01",
                "status": "FAIL",
                "mismatches": [
                    {
                        "side": "shopify_only",
                        "email": "buyer@example.com",
                        "shopify_customer_id": "gid://shopify/Customer/1",
                    }
                ],
            },
        )

        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="CI-01",
            actor=admin,
            max_rows=1,
            expect_rollback=True,
        )
        self.assertEqual(outcome["rollback"]["status"], "rolled_back")
        self.assertGreaterEqual(outcome["rollback"]["rolled_back"], 1)
        self.assertTrue(mock_upsert.called)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_tier_a_cc03_sandbox_pass(self, mock_ctx, mock_upsert):
        """CC-03: Allow writebacks invent-from-Manago-contact when no FAIL (WB-01B)."""
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True}
        seed_writeback_allowlist("CC-03")
        tenant, company, admin = self._make_admin_company(
            slug="cc03",
            connectors=["manago"],
        )
        Contact.objects.create(
            company=company,
            source=Contact.Source.MANAGO_AI,
            external_id="mc-sandbox-cc03",
            email="consent@example.com",
        )
        # PASS on worklist — original sandbox fallback must still produce ready intents.
        _seed_dcs_shell(
            company=company,
            tenant=tenant,
            check_id="CC-03",
            status="PASS",
        )

        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="CC-03",
            actor=admin,
            max_rows=1,
            expect_rollback=True,
        )
        self.assertEqual(outcome["rollback"]["status"], "rolled_back")
        self.assertGreaterEqual(outcome["rollback"]["rolled_back"], 1)
        self.assertTrue(mock_upsert.called)

    @patch("dataruns.writebacks.adapters.shopify.update_customer")
    @patch("dataruns.writebacks.adapters.shopify.get_customer")
    @patch("dataruns.writebacks.adapters.shopify.resolve_shopify_write_context")
    def test_tier_a_wb_shop_01_sandbox_pass(self, mock_ctx, mock_get, mock_update):
        """WB-SHOP-01: Shopify Contact seed — no DCS FAIL required."""
        mock_ctx.return_value = object()
        mock_get.return_value = {"id": 4242, "note": "prior note"}
        mock_update.return_value = {"customer": {"id": 4242, "note": "klints_wb_test"}}
        seed_writeback_allowlist("WB-SHOP-01")
        _tenant, company, admin = self._make_admin_company(
            slug="shop01",
            connectors=["shopify"],
        )
        Contact.objects.create(
            company=company,
            source=Contact.Source.SHOPIFY,
            external_id="gid://shopify/Customer/4242",
            email="buyer@example.com",
        )
        # Minimal DCS run so once-per-run / status helpers have a pin if needed.
        _seed_dcs_shell(
            company=company,
            tenant=_tenant,
            check_id="CI-01",
            status="PASS",
        )

        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="WB-SHOP-01",
            actor=admin,
            max_rows=1,
            expect_rollback=True,
        )
        self.assertEqual(outcome["rollback"]["status"], "rolled_back")
        self.assertGreaterEqual(outcome["rollback"]["rolled_back"], 1)
        self.assertGreaterEqual(mock_update.call_count, 2)


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=1)
class WritebackSandboxContractPhaseBTests(TestCase):
    """PRD-WB-21 §6 Phase B — remaining Tier A execute checks."""

    def test_tier_a_ids_include_phase_b(self):
        for check_id in (
            "CI-05",
            "LE-01",
            "LE-02",
            "LE-05",
            "LE-09",
            "SP-03",
            "SP-07",
            "PT-04",
        ):
            self.assertIn(check_id, TIER_A_SANDBOX_CHECK_IDS)

    def _make_admin_company(self, *, slug: str):
        tenant = Tenant.objects.create(name=f"WB21B-{slug}", slug=f"wb21b-{slug}")
        company = Company.objects.create(
            tenant=tenant,
            name=f"WB21B {slug}",
            domain=f"wb21b-{slug}.test",
        )
        admin = User.objects.create_user(
            email=f"admin@{slug}.wb21b.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        Connector.objects.create(
            company=company,
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
        _seed_dcs_shell(company=company, tenant=tenant, check_id="CI-01", status="PASS")
        return company, admin

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_tier_a_ci05_sandbox_pass(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True}
        seed_writeback_allowlist("CI-05")
        company, admin = self._make_admin_company(slug="ci05")
        mapping = get_check_mapping("CI-05")
        intents = build_intents_from_mapping(
            company=company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "missing_link_key",
                    "person.email": "ok@example.com",
                    "manago_contact_id": "m-ok",
                    "shopify_customer_id": "8001",
                    "prior_external_id": "",
                }
            ],
        )
        self.assertGreaterEqual(len(intents), 1)
        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="CI-05",
            actor=admin,
            intents=intents,
            expect_rollback=True,
        )
        self.assertEqual(outcome["rollback"]["status"], "rolled_back")
        self.assertTrue(mock_upsert.called)

    @patch("dataruns.writebacks.adapters.manago.batch_add_external_events")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_tier_a_le01_sandbox_pass(self, mock_ctx, mock_batch):
        mock_ctx.return_value = object()
        mock_batch.return_value = {"success": True}
        seed_writeback_allowlist("LE-01")
        company, admin = self._make_admin_company(slug="le01")
        mapping = get_check_mapping("LE-01")
        intents = build_intents_from_mapping(
            company=company,
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
        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="LE-01",
            actor=admin,
            intents=intents,
            expect_rollback=False,
            expect_irreversible=True,
            expect_rollback_supported=False,
        )
        self.assertIsNone(outcome["rollback"])
        self.assertTrue(mock_batch.called)

    @patch("dataruns.writebacks.adapters.manago.batch_add_external_events")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_tier_a_le05_sandbox_pass(self, mock_ctx, mock_batch):
        mock_ctx.return_value = object()
        mock_batch.return_value = {"success": True}
        seed_writeback_allowlist("LE-05")
        company, admin = self._make_admin_company(slug="le05")
        mapping = get_check_mapping("LE-05")
        intents = build_intents_from_mapping(
            company=company,
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
        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="LE-05",
            actor=admin,
            intents=intents,
            expect_rollback=False,
            expect_irreversible=True,
            expect_rollback_supported=False,
        )
        self.assertIsNone(outcome["rollback"])
        self.assertTrue(mock_batch.called)

    @patch("dataruns.writebacks.adapters.manago.update_contact_ext_event")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_tier_a_le02_sandbox_pass(self, mock_ctx, mock_update):
        mock_ctx.return_value = object()
        mock_update.return_value = {"success": True}
        seed_writeback_allowlist("LE-02")
        company, admin = self._make_admin_company(slug="le02")
        mapping = get_check_mapping("LE-02")
        intents = build_intents_from_mapping(
            company=company,
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
        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="LE-02",
            actor=admin,
            intents=intents,
            expect_rollback=False,
            expect_irreversible=True,
            expect_rollback_supported=False,
        )
        self.assertIsNone(outcome["rollback"])
        self.assertTrue(mock_update.called)

    @patch("dataruns.writebacks.adapters.manago.batch_add_external_events")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_tier_a_le09_sandbox_pass(self, mock_ctx, mock_batch):
        mock_ctx.return_value = object()
        mock_batch.return_value = {"success": True}
        seed_writeback_allowlist("LE-09")
        company, admin = self._make_admin_company(slug="le09")
        mapping = get_check_mapping("LE-09")
        intents = build_intents_from_mapping(
            company=company,
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
        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="LE-09",
            actor=admin,
            intents=intents,
            expect_rollback=False,
            expect_irreversible=True,
            expect_rollback_supported=False,
        )
        self.assertIsNone(outcome["rollback"])
        self.assertTrue(mock_batch.called)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_tier_a_sp03_sandbox_pass(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True}
        seed_writeback_allowlist("SP-03")
        company, admin = self._make_admin_company(slug="sp03")
        mapping = get_check_mapping("SP-03")
        intents = build_intents_from_mapping(
            company=company,
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
                }
            ],
        )
        ready = [i for i in intents if i.status == "ready"]
        self.assertGreaterEqual(len(ready), 1)
        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="SP-03",
            actor=admin,
            intents=ready,
            expect_rollback=True,
        )
        self.assertEqual(outcome["rollback"]["status"], "rolled_back")
        self.assertTrue(mock_upsert.called)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_tier_a_sp07_sandbox_pass(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True}
        seed_writeback_allowlist("SP-07")
        company, admin = self._make_admin_company(slug="sp07")
        mapping = get_check_mapping("SP-07")
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
                    }
                ],
            )
        self.assertGreaterEqual(len(intents), 1)
        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="SP-07",
            actor=admin,
            intents=intents,
            expect_rollback=True,
        )
        self.assertEqual(outcome["rollback"]["status"], "rolled_back")
        self.assertTrue(mock_upsert.called)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_tier_a_pt04_sandbox_pass(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True}
        seed_writeback_allowlist("PT-04")
        company, admin = self._make_admin_company(slug="pt04")
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
                company=company,
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
        self.assertGreaterEqual(len(intents), 1)
        outcome = assert_tier_a_sandbox_pass(
            self,
            company=company,
            check_id="PT-04",
            actor=admin,
            intents=intents,
            expect_rollback=True,
        )
        self.assertEqual(outcome["rollback"]["status"], "rolled_back")
        self.assertTrue(mock_upsert.called)


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=1)
class WritebackSandboxContractPhaseCTests(TestCase):
    """PRD-WB-21 §6 Phase C — plan_only, PT-03 execute blocked, disabled skips."""

    def test_phase_c_tier_constants(self):
        self.assertEqual(TIER_B_PLAN_ONLY_CHECK_IDS, ("CI-03", "CC-01", "CC-02"))
        self.assertEqual(TIER_C_EXECUTE_BLOCKED_CHECK_IDS, ("PT-03",))
        self.assertEqual(TIER_D_DISABLED_CHECK_IDS, ("LE-04", "SP-01"))

    def _make_admin_company(self, *, slug: str):
        tenant = Tenant.objects.create(name=f"WB21C-{slug}", slug=f"wb21c-{slug}")
        company = Company.objects.create(
            tenant=tenant,
            name=f"WB21C {slug}",
            domain=f"wb21c-{slug}.test",
        )
        admin = User.objects.create_user(
            email=f"admin@{slug}.wb21c.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        Connector.objects.create(
            company=company,
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
        _seed_dcs_shell(company=company, tenant=tenant, check_id="CI-01", status="PASS")
        return company, admin

    def test_tier_b_ci03_plan_only_blocks_execute(self):
        company, admin = self._make_admin_company(slug="ci03")
        mapping = get_check_mapping("CI-03")
        intents = build_intents_from_mapping(
            company=company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "merge_candidate",
                    "cluster_kind": "externalId",
                    "cluster_key": "1001",
                    "survivor_manago_id": "surv",
                    "loser_manago_ids": ["lose"],
                    "safety_class": "SAFE_DELETE",
                    "safety_reason": "loser_events_0_survivor_holds_link_key",
                    "person.email": "x@y.com",
                    "link_key": "1001",
                }
            ],
        )
        outcome = assert_tier_b_plan_only_blocks_execute(
            self,
            company=company,
            check_id="CI-03",
            actor=admin,
            expected_blocked_reason="ci03_plan_only",
            intents=intents,
            require_preview_ready=True,
        )
        self.assertEqual(outcome["execute"].blocked_reason, "ci03_plan_only")

    def test_tier_b_cc01_plan_only_blocks_execute(self):
        company, admin = self._make_admin_company(slug="cc01")
        mapping = get_check_mapping("CC-01")
        intents = build_intents_from_mapping(
            company=company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "out_in",
                    "person.email": "out@ex.com",
                    "manago_contact_id": "m1",
                    "shopify_customer_id": "s1",
                    "proposed_action": "FORCE_OPT_OUT",
                    "evidence_gate": "opt_out_wins",
                    "prior_optedOut": False,
                }
            ],
        )
        outcome = assert_tier_b_plan_only_blocks_execute(
            self,
            company=company,
            check_id="CC-01",
            actor=admin,
            expected_blocked_reason="cc01_plan_only",
            intents=intents,
            require_preview_ready=True,
        )
        self.assertEqual(outcome["execute"].blocked_reason, "cc01_plan_only")

    def test_tier_b_cc02_plan_only_blocks_execute(self):
        company, admin = self._make_admin_company(slug="cc02")
        mapping = get_check_mapping("CC-02")
        intents = build_intents_from_mapping(
            company=company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "out_in",
                    "person.email": "sms@ex.com",
                    "manago_contact_id": "m1",
                    "shopify_customer_id": "s1",
                    "proposed_action": "FORCE_PHONE_OPT_OUT",
                    "evidence_gate": "opt_out_wins",
                    "prior_optedOut": False,
                }
            ],
        )
        outcome = assert_tier_b_plan_only_blocks_execute(
            self,
            company=company,
            check_id="CC-02",
            actor=admin,
            expected_blocked_reason="cc02_plan_only",
            intents=intents,
            require_preview_ready=True,
        )
        self.assertEqual(outcome["execute"].blocked_reason, "cc02_plan_only")

    def test_tier_c_pt03_preview_ok_execute_blocked(self):
        self.assertFalse(capability_allows_execute("RESTV2.PRODUCT.IMPORT"))
        company, admin = self._make_admin_company(slug="pt03")
        # Do NOT seed WritebackAllowedCheck for PT-03 — execute must stay blocked.
        mapping = get_check_mapping("PT-03")
        intents = build_intents_from_mapping(
            company=company,
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
                }
            ],
        )
        ready = [i for i in intents if i.status == "ready"]
        self.assertGreaterEqual(len(ready), 1)
        outcome = assert_tier_c_execute_blocked(
            self,
            company=company,
            check_id="PT-03",
            actor=admin,
            intents=ready,
            allowed_blocked_reasons={"check_not_allowlisted"},
        )
        self.assertEqual(outcome["execute"].blocked_reason, "check_not_allowlisted")
        self.assertEqual(outcome["execute"].summary.executed, 0)

    def test_tier_c_pt03_allowlisted_still_no_execute_without_capability(self):
        """PRD §9 Phase C — allowlisted PT-03 still must not write without PRODUCT.IMPORT."""
        from unittest.mock import patch

        self.assertFalse(capability_allows_execute("RESTV2.PRODUCT.IMPORT"))
        company, admin = self._make_admin_company(slug="pt03-cap")
        seed_writeback_allowlist("PT-03")
        mapping = get_check_mapping("PT-03")
        intents = build_intents_from_mapping(
            company=company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "missing_in_manago",
                    "product_id": "1002",
                    "write_entity_key": "1002",
                    "shopify_title": "Hoodie",
                    "shopify_sku": "HD-1",
                    "proposed_action": "UPSERT_FROM_SHOPIFY",
                    "evidence_gate": "pins_rebuild",
                }
            ],
        )
        ready = [i for i in intents if i.status == "ready"]
        self.assertGreaterEqual(len(ready), 1)

        with patch(
            "dataruns.writebacks.adapters.manago.resolve_manago_write_context",
            return_value=object(),
        ), patch(
            "dataruns.writebacks.adapters.manago_transport.upsert_products",
            side_effect=AssertionError("PRODUCT.IMPORT must not execute"),
        ):
            outcome = assert_tier_c_execute_blocked(
                self,
                company=company,
                check_id="PT-03",
                actor=admin,
                intents=ready,
            )
        self.assertEqual(outcome["execute"].summary.executed, 0)

    def test_tier_d_le04_disabled(self):
        assert_tier_d_mapping_disabled(self, check_id="LE-04")

    def test_tier_d_sp01_disabled(self):
        assert_tier_d_mapping_disabled(self, check_id="SP-01")


class WritebackSandboxContractPhaseDHonestyTests(TestCase):
    """PRD-WB-21 Phase D — API naming honesty (company + sandbox alias)."""

    def test_preflight_blocked_preview_keeps_company_execute_eligible(self):
        """PRD-WB-21 — connector preflight must not lie that Allow writebacks is off."""
        from unittest.mock import patch

        from dataruns.writebacks.service import writeback_run

        tenant = Tenant.objects.create(name="WB21-PF", slug="wb21-preflight")
        company = Company.objects.create(
            tenant=tenant,
            name="WB21 Preflight",
            domain="wb21-preflight.test",
            writeback_execute_enabled=True,
        )
        admin = User.objects.create_user(
            email="admin@preflight.wb21.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        seed_writeback_allowlist("CI-01")

        with patch(
            "dataruns.writebacks.pipeline.run_preflight",
            return_value="connector_not_connected:manago",
        ):
            preview = writeback_run(
                company=company,
                check_id="CI-01",
                mode="dry_run",
                max_rows=1,
                actor=admin,
            )
        self.assertEqual(preview.blocked_reason, "connector_not_connected:manago")
        self.assertTrue(preview.execute_eligible.sandbox)
        self.assertTrue(preview.execute_eligible.company)

    def test_preflight_blocked_preview_settings_off_execute_eligible_false(self):
        """Settings Allow writebacks OFF → company/sandbox must stay false on blocked preview."""
        from unittest.mock import patch

        from dataruns.writebacks.service import writeback_run

        tenant = Tenant.objects.create(name="WB21-PF-OFF", slug="wb21-preflight-off")
        company = Company.objects.create(
            tenant=tenant,
            name="WB21 Preflight Off",
            domain="wb21-preflight-off.test",
            writeback_execute_enabled=False,
        )
        admin = User.objects.create_user(
            email="admin@preflight-off.wb21.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        seed_writeback_allowlist("CI-01")

        with patch(
            "dataruns.writebacks.pipeline.run_preflight",
            return_value="connector_not_connected:manago",
        ):
            preview = writeback_run(
                company=company,
                check_id="CI-01",
                mode="dry_run",
                max_rows=1,
                actor=admin,
            )
        self.assertEqual(preview.blocked_reason, "connector_not_connected:manago")
        self.assertFalse(preview.execute_eligible.sandbox)
        self.assertFalse(preview.execute_eligible.company)

    def test_serialize_result_emits_company_and_sandbox_alias(self):
        from dataruns.writebacks.serializers import serialize_result
        from dataruns.writebacks.types import (
            ExecuteEligibility,
            WritebackResult,
            WritebackSummary,
        )

        result = WritebackResult(
            check_id="CI-01",
            mode="dry_run",
            diff_hash="a" * 64,
            intents=[],
            summary=WritebackSummary(ready=0, skipped=0, errors=0, executed=0),
            execute_eligible=ExecuteEligibility(sandbox=True, production=False),
        )
        payload = serialize_result(result, action="preview")
        self.assertTrue(payload["execute_eligible"]["company"])
        self.assertTrue(payload["execute_eligible"]["sandbox"])
        self.assertFalse(payload["execute_eligible"]["production"])
        self.assertTrue(result.execute_eligible.company)

    def test_status_preview_payload_emits_company(self):
        from django.conf import settings

        from dataruns.models import WritebackJob
        from dataruns.writebacks.run_gate import _serialize_preview_job

        tenant = Tenant.objects.create(name="WB21-D", slug="wb21-d-honesty")
        company = Company.objects.create(
            tenant=tenant,
            name="WB21 D",
            domain="wb21-d.test",
            writeback_execute_enabled=True,
        )
        job = WritebackJob.objects.create(
            company=company,
            check_id="CI-01",
            mode="dry_run",
            status="previewed",
            diff_hash="b" * 64,
            sandbox=True,
            summary={"ready": 1, "skipped": 0, "errors": 0, "executed": 0},
            intents=[],
            metadata={},
        )
        payload = _serialize_preview_job(job)
        assert payload is not None
        self.assertTrue(payload["execute_eligible"]["company"])
        self.assertTrue(payload["execute_eligible"]["sandbox"])
        self.assertEqual(
            payload["execute_eligible"]["production"],
            bool(settings.WRITEBACKS_ENABLED),
        )
