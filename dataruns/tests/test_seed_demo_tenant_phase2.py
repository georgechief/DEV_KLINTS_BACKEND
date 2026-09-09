"""GAP-01F Phase 2 — corpus + offline DCS REMEDIATE band."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from dataruns.demo_seed.corpus import build_skincare_corpus
from dataruns.demo_seed.identity import create_demo_identity, ensure_stub_connectors
from dataruns.demo_seed.offline_dcs import REMEDIATE_MAX, REMEDIATE_MIN, run_offline_demo_dcs
from dataruns.models import CheckMaster, Contact, DataRun
from tenants.models import Tenant


class SeedDemoTenantPhase2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if CheckMaster.objects.count() == 0:
            call_command("seed_dcs_master", verbosity=0)

    def test_corpus_mix_counts(self):
        corpus = build_skincare_corpus(contacts=100, seed=42)
        self.assertEqual(corpus.contact_count, 100)
        self.assertEqual(
            corpus.matched_count
            + corpus.shopify_only_count
            + corpus.manago_only_count
            + corpus.mismatch_count
            + corpus.manago_dup_count,
            100,
        )
        # Skewed toward Shopify-only so CI-01 relative delta fails.
        self.assertGreater(corpus.shopify_only_count, corpus.matched_count)
        self.assertGreater(corpus.manago_dup_count, 0)

    def test_corpus_default_scale_ratios_hold(self):
        """F0.4 default 5k uses same % mix as CI smoke sizes (multiples of 20)."""
        corpus = build_skincare_corpus(contacts=5000, seed=42)
        self.assertEqual(corpus.matched_count, 500)
        self.assertEqual(corpus.shopify_only_count, 2750)
        self.assertEqual(corpus.manago_only_count, 500)
        self.assertEqual(corpus.mismatch_count, 750)
        self.assertEqual(corpus.manago_dup_count, 500)

    def test_offline_dcs_lands_in_remediate_band(self):
        identity = create_demo_identity(
            vertical="skincare",
            slug="gap01f-p2-dcs",
            email="gap01f-p2@example.com",
            password="TestPass123!",
        )
        ensure_stub_connectors(company=identity.company, vertical="skincare")
        result = run_offline_demo_dcs(company=identity.company, contacts=100)
        self.assertTrue(result.ok, result.detail)
        self.assertIsNotNone(result.headline_score, result.detail)
        self.assertGreaterEqual(result.contact_count, 100)
        if not result.in_remediate_band:
            run = DataRun.objects.get(pk=result.data_run_id)
            checks = (run.metadata or {}).get("check_results") or []
            hist: dict[str, int] = {}
            fails = []
            for row in checks:
                st = str(row.get("status") or "?")
                hist[st] = hist.get(st, 0) + 1
                if st == "FAIL":
                    fails.append(row.get("check_id"))
            self.fail(
                f"expected REMEDIATE [{REMEDIATE_MIN},{REMEDIATE_MAX}] got "
                f"headline={result.headline_score} state={result.run_state} "
                f"hist={hist} fails={fails[:20]} ({result.detail})"
            )

    def test_offline_dcs_skips_website_http_scrape(self):
        identity = create_demo_identity(
            vertical="skincare",
            slug="gap01f-p2-noscrape",
            email="gap01f-p2-noscrape@example.com",
            password="TestPass123!",
        )
        ensure_stub_connectors(company=identity.company, vertical="skincare")
        with patch(
            "dataruns.dcs.scrapers.company_website.scrape_with_http_fallback"
        ) as scrape:
            result = run_offline_demo_dcs(company=identity.company, contacts=40)
        self.assertTrue(result.ok, result.detail)
        self.assertTrue(result.in_remediate_band, result.detail)
        scrape.assert_not_called()

    def test_command_require_remediate_rejects_skip_dcs(self):
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "seed_demo_tenant",
                "--vertical=skincare",
                "--slug=gap01f-p2-contradict",
                "--email=gap01f-p2-contradict@example.com",
                "--skip-masters",
                "--skip-dcs",
                "--require-remediate",
            )
        self.assertIn("--require-remediate", str(ctx.exception))
        self.assertIn("--skip-dcs", str(ctx.exception))
        self.assertFalse(
            Tenant.objects.filter(slug="gap01f-p2-contradict").exists()
        )

    def test_command_seeds_corpus_and_remediate_band(self):
        out = StringIO()
        call_command(
            "seed_demo_tenant",
            "--vertical=skincare",
            "--slug=gap01f-p2-cmd",
            "--email=gap01f-p2-cmd@example.com",
            "--password=TestPass123!",
            "--contacts=80",
            "--skip-masters",
            "--require-remediate",
            stdout=out,
        )
        text = out.getvalue()
        self.assertIn("REMEDIATE", text)
        self.assertIn("band:", text)
        self.assertIn("OK", text)
        tenant = Tenant.objects.get(slug="gap01f-p2-cmd")
        company = tenant.companies.first()
        self.assertIsNotNone(company)
        self.assertGreaterEqual(Contact.objects.filter(company=company).count(), 80)
        runs = DataRun.objects.filter(tenant=tenant)
        self.assertTrue(runs.exists())
        self.assertTrue(
            any((r.metadata or {}).get("gap01f_demo_seed") for r in runs)
        )
