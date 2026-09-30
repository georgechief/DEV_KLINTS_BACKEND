"""PRD-WB-15 — CI-05 identity key repair writeback tests."""

from __future__ import annotations

import importlib

from django.apps import apps as django_apps
from django.test import SimpleTestCase, TestCase

from dataruns.dcs.executors.identity import _ci05_mismatches
from dataruns.dcs.identity_join import build_identity_snapshot
from dataruns.dcs.worklist import (
    build_worklist_detail,
    build_worklist_payload,
    is_ci05_cold_estate_unknown,
    should_include_check_result,
)
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import Contact, DataRun, WritebackAllowedCheck
from dataruns.writebacks.registry import get_check_mapping, list_mapping_entries
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.transform import (
    _ci05_evidence_rows,
    build_intents_from_mapping,
    collect_evidence_rows,
)
from tenants.models import Company, Tenant


class Ci05MismatchHelperTests(SimpleTestCase):
    def test_drivers_survive_full_missing_sample(self):
        missing = [
            {
                "side": "missing_link_key",
                "person.email": f"u{i}@x.com",
                "manago_contact_id": f"m{i}",
                "shopify_customer_id": str(1000 + i),
                "prior_external_id": "",
            }
            for i in range(50)
        ]
        mismatches = _ci05_mismatches(
            {
                "missing_link_key": missing,
                "link_key_reused": ["999"],
                "link_key_dangling": [],
                "manago_with_link_key": 10,
                "link_key_matched": 4,
            }
        )
        self.assertEqual(
            sum(1 for m in mismatches if m.get("side") == "missing_link_key"), 50
        )
        drivers = [m.get("driver") for m in mismatches if m.get("side") == "driver"]
        self.assertIn("link_key_reused", drivers)
        self.assertIn("low_link_coverage", drivers)


class Ci05ColdEstateWorklistTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB15T", slug="wb15-worklist")
        self.company = Company.objects.create(
            tenant=self.tenant, name="WB15 Co", domain="wb15-wl.test"
        )

    def test_should_include_ci05_cold_unknown(self):
        result = {
            "check_id": "CI-05",
            "status": "UNKNOWN",
            "reason_code": "MISSING_INPUT:person.external_key",
        }
        self.assertTrue(is_ci05_cold_estate_unknown(result))
        self.assertTrue(should_include_check_result(result))
        # Other UNKNOWN still excluded.
        self.assertFalse(
            should_include_check_result(
                {
                    "check_id": "CI-05",
                    "status": "UNKNOWN",
                    "reason_code": "MISSING_INPUT:contacts",
                }
            )
        )
        self.assertFalse(
            should_include_check_result(
                {"check_id": "LE-01", "status": "UNKNOWN", "reason_code": "x"}
            )
        )

    def test_worklist_includes_ci05_cold_unknown(self):
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "check_results": [
                    {
                        "check_id": "CI-05",
                        "status": "UNKNOWN",
                        "reason_code": "MISSING_INPUT:person.external_key",
                        "severity": "critical",
                        "message": "no link keys",
                        "provenance": {
                            "mismatches": [
                                {
                                    "side": "missing_link_key",
                                    "person.email": "a@x.com",
                                    "manago_contact_id": "m1",
                                    "shopify_customer_id": "1001",
                                    "prior_external_id": "",
                                }
                            ]
                        },
                    },
                    {
                        "check_id": "CI-01",
                        "status": "PASS",
                        "severity": "high",
                    },
                ],
            },
        )
        payload = build_worklist_payload(company=self.company)
        check_ids = {issue["check_id"] for issue in payload["issues"]}
        self.assertIn("CI-05", check_ids)
        ci05 = next(i for i in payload["issues"] if i["check_id"] == "CI-05")
        self.assertEqual(ci05["status"], "UNKNOWN")

        detail = build_worklist_detail(company=self.company, check_id="CI-05")
        self.assertEqual(detail["status"], "UNKNOWN")
        mismatches = detail.get("mismatches") or []
        self.assertTrue(mismatches)
        # Worklist normalizes bare rows under ``value`` — side lives there.
        self.assertTrue(
            any(
                (m.get("side") == "missing_link_key")
                or (
                    isinstance(m.get("value"), dict)
                    and m["value"].get("side") == "missing_link_key"
                )
                for m in mismatches
            )
        )


class Ci05EmitAndTransformTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB15E", slug="wb15-emit")
        self.company = Company.objects.create(
            tenant=self.tenant, name="WB15 Emit", domain="wb15-emit.test"
        )

    def test_guest_shopify_id_not_emitted(self):
        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="email:guest@example.com",
            email="guest@example.com",
        )
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="m-guest",
            email="guest@example.com",
            link_key="",
        )
        identity = build_identity_snapshot(company=self.company)["identity"]
        self.assertEqual(identity.get("missing_link_key") or [], [])

    def test_guest_plus_real_shopify_emits_real_id(self):
        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="email:pair@example.com",
            email="pair@example.com",
        )
        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="7001",
            email="pair@example.com",
        )
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="m-pair",
            email="pair@example.com",
            link_key="",
        )
        identity = build_identity_snapshot(company=self.company)["identity"]
        missing = identity.get("missing_link_key") or []
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["shopify_customer_id"], "7001")

    def test_transform_skips_guest_and_builds_contact_id(self):
        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="8001",
            email="ok@example.com",
        )
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="m-ok",
            email="ok@example.com",
            link_key="",
        )
        rows = _ci05_evidence_rows(
            company=self.company,
            rows=[
                {
                    "side": "missing_link_key",
                    "person.email": "o***@example.com",
                    "manago_contact_id": "m-ok",
                    "shopify_customer_id": "8001",
                    "prior_external_id": "",
                },
                {
                    "side": "missing_link_key",
                    "person.email": "g@example.com",
                    "manago_contact_id": "m-g",
                    "shopify_customer_id": "email:g@example.com",
                    "prior_external_id": "",
                },
                {"side": "driver", "driver": "link_key_reused"},
            ],
            max_rows=10,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["person.email"], "ok@example.com")

        mapping = get_check_mapping("CI-05")
        intents = build_intents_from_mapping(
            company=self.company, mapping=mapping, evidence_rows=rows
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].payload.get("contactId"), "m-ok")
        self.assertEqual(str(intents[0].payload.get("externalId")), "8001")
        ok, _reason = rollback_supported(intents[0])
        self.assertTrue(ok)

    def test_live_rebuild_when_worklist_has_no_missing(self):
        """Stale DCS provenance (drivers only) still previews from live Contact DB."""
        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="9001",
            email="live@example.com",
        )
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="m-live",
            email="live@example.com",
            link_key="",
        )
        from dataruns.writebacks.transform import _ci05_evidence_rows

        rebuilt = _ci05_evidence_rows(
            company=self.company,
            rows=[{"side": "driver", "driver": "link_key_reused"}],
            max_rows=10,
        )
        self.assertEqual(len(rebuilt), 1)
        self.assertEqual(rebuilt[0]["shopify_customer_id"], "9001")
        self.assertEqual(rebuilt[0]["manago_contact_id"], "m-live")
        # Even without a worklist detail, collect_evidence_rows rebuilds live.
        rows = collect_evidence_rows(
            company=self.company,
            check_id="CI-05",
            max_rows=10,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["shopify_customer_id"], "9001")

    def test_no_sandbox_when_empty_mismatches(self):
        rows = collect_evidence_rows(
            company=self.company, check_id="CI-05", max_rows=10
        )
        self.assertEqual(rows, [])


class Ci05RegistryAllowlistTests(TestCase):
    def test_registry_and_migration_seed(self):
        by_id = {
            str(row.get("check_id") or "").upper(): row
            for row in list_mapping_entries()
        }
        self.assertTrue(by_id["CI-05"].get("enabled"))
        self.assertTrue(by_id["CI-01"].get("enabled"))
        mapping = get_check_mapping("CI-05")
        self.assertEqual(mapping.get("approval_tier"), "batch")
        self.assertEqual(mapping.get("template_id"), "T2")
        self.assertFalse(mapping.get("irreversible"))

        mod = importlib.import_module(
            "dataruns.migrations.0042_writeback_allowed_ci05"
        )
        WritebackAllowedCheck.objects.filter(check_id="CI-05").delete()
        mod.seed_wb15_allowlist(django_apps, None)
        self.assertTrue(
            WritebackAllowedCheck.objects.filter(
                check_id="CI-05", enabled=True
            ).exists()
        )


class Ci05PipelineDefaultCapTests(TestCase):
    """WB-20 regression: nested capability_batch_max import must not shadow other checks."""

    # Branches that call capability_batch_max when Fix omits max_rows (same UnboundLocal path).
    CHECKS_USING_CAPABILITY_BATCH_MAX = (
        "CI-05",
        "LE-02",
        "LE-05",
        "LE-09",
        "SP-07",
        "PT-04",
        "PT-03",
    )

    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB15Cap", slug="wb15-cap")
        self.company = Company.objects.create(
            tenant=self.tenant, name="WB15 Cap", domain="wb15-cap.test"
        )

    def test_preview_default_max_rows_does_not_unbound_capability_batch_max(self):
        from dataruns.writebacks.pipeline import run_writeback_pipeline

        # Must not raise UnboundLocalError on capability_batch_max (WB-20 shadow bug).
        result = run_writeback_pipeline(
            company=self.company,
            check_id="CI-05",
            mode="preview",
            max_rows=None,
        )
        self.assertEqual(result.check_id, "CI-05")
        self.assertIsInstance(result.intents, list)

    def test_all_capability_capped_checks_preview_without_unbound(self):
        from dataruns.writebacks.pipeline import run_writeback_pipeline

        for check_id in self.CHECKS_USING_CAPABILITY_BATCH_MAX:
            with self.subTest(check_id=check_id):
                result = run_writeback_pipeline(
                    company=self.company,
                    check_id=check_id,
                    mode="preview",
                    max_rows=None,
                )
                self.assertEqual(result.check_id, check_id)
                self.assertIsInstance(result.intents, list)