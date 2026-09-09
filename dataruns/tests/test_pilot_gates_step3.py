"""DCS-09 Step 3 — isolated supplemental executor framework."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from dataruns.dcs.assemble import AssembleValidationError, assemble_dcs_score
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.executors.registry import registered_check_ids
from dataruns.dcs.master import load_check_master_from_json
from dataruns.dcs.pilot_gates.context import (
    build_supplemental_gate_context,
    get_latest_succeeded_dcs_score_run,
    resolve_dcs_score_run,
)
from dataruns.dcs.pilot_gates.contract import (
    ERP_SENSITIVE_CHECK_IDS,
    EXPECTED_SUPPLEMENTAL_CHECK_COUNT,
    STATUS_NOT_CONNECTED,
    STATUS_PASS,
    STATUS_UNKNOWN,
    SUPPLEMENTAL_CHECK_IDS,
)
from dataruns.dcs.pilot_gates.executors import (
    REASON_ERP_OUT_OF_SCOPE,
    REASON_EXECUTOR_PENDING,
    REASON_MISSING_INPUT,
    check_result_to_store_row,
    clear_supplemental_executor_registry,
    get_supplemental_executor,
    make_supplemental_result,
    register_supplemental_executor,
    registered_supplemental_check_ids,
    run_supplemental_check,
    run_supplemental_checks,
)
from dataruns.dcs.pilot_gates.store import save_pilot_gate_eval
from dataruns.dcs.types import CheckResult, Evidence
from dataruns.models import DataRun
from tenants.models import Company, Tenant


class PilotGatesStep3IsolationTests(SimpleTestCase):
    def test_supplemental_ids_not_in_headline_executor_registry(self):
        overlap = registered_check_ids() & set(SUPPLEMENTAL_CHECK_IDS)
        self.assertEqual(overlap, set())

    def test_headline_master_still_42(self):
        master = load_check_master_from_json()
        self.assertEqual(len(master.checks), 42)
        self.assertEqual(master.check_ids() & set(SUPPLEMENTAL_CHECK_IDS), set())

    def test_assemble_rejects_supplemental_ids(self):
        """Headline assemble must not accept supplemental check_ids (stays 42)."""
        master = load_check_master_from_json()
        results = [
            CheckResult(check_id=c.check_id, status="PASS") for c in master.checks
        ]
        run = assemble_dcs_score(results, erp_in_scope=False, master=master)
        self.assertEqual(len(run.check_result_refs), 42)
        self.assertEqual(set(run.check_result_refs) & set(SUPPLEMENTAL_CHECK_IDS), set())

        with self.assertRaises(AssembleValidationError):
            assemble_dcs_score(
                results
                + [CheckResult(check_id="CI-08", status="PASS")],
                erp_in_scope=False,
                master=master,
            )


class PilotGatesStep3FrameworkTests(TestCase):
    def setUp(self):
        clear_supplemental_executor_registry()
        self.tenant = Tenant.objects.create(name="PG S3", slug="pg-s3")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="PG S3 Co",
            domain="pg-s3.example.com",
        )

    def tearDown(self):
        clear_supplemental_executor_registry()

    def _dcs_with_snapshot(
        self,
        *,
        company: Company | None = None,
        status: str = DataRun.Status.SUCCEEDED,
        snapshot: dict | None = None,
        name: str = DCS_SCORE_DATA_RUN_NAME,
    ) -> DataRun:
        company = company or self.company
        return DataRun.objects.create(
            tenant=company.tenant,
            name=name,
            status=status,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(company.id),
                "headline_score": 80,
            },
            run_snapshot=snapshot
            if snapshot is not None
            else {
                "as_of": "2026-01-01T00:00:00Z",
                "connectors": {"manago": {"status": "connected"}},
            },
        )

    def test_erp_out_of_scope_returns_not_connected(self):
        ctx = build_supplemental_gate_context(
            company=self.company,
            erp_in_scope=False,
        )
        for check_id in ("BR-09", "PT-06"):
            result = run_supplemental_check(check_id, context=ctx)
            self.assertEqual(result.status, STATUS_NOT_CONNECTED)
            self.assertEqual(result.reason_code, REASON_ERP_OUT_OF_SCOPE)

    def test_erp_in_scope_missing_inputs_unknown(self):
        ctx = build_supplemental_gate_context(
            company=self.company,
            erp_in_scope=True,
        )
        for check_id in sorted(ERP_SENSITIVE_CHECK_IDS):
            result = run_supplemental_check(check_id, context=ctx)
            # Missing inject: UNKNOWN, or NOT_CONNECTED if connector absent.
            self.assertIn(result.status, {STATUS_UNKNOWN, STATUS_NOT_CONNECTED})
            self.assertNotEqual(result.reason_code, REASON_EXECUTOR_PENDING)
            self.assertTrue(
                str(result.reason_code or "").startswith(REASON_MISSING_INPUT)
                or str(result.reason_code or "").startswith("NOT_CONNECTED")
            )

    def test_all_twelve_registered_no_pending_fallback(self):
        # Slice A + Slice B cover all 12 — pending fallback unused.
        self.assertEqual(
            registered_supplemental_check_ids(),
            set(SUPPLEMENTAL_CHECK_IDS),
        )
        ctx = build_supplemental_gate_context(company=self.company)
        result = run_supplemental_check("LE-07", context=ctx)
        self.assertIn(result.status, {STATUS_UNKNOWN, STATUS_NOT_CONNECTED})
        self.assertNotEqual(result.reason_code, REASON_EXECUTOR_PENDING)
        self.assertTrue(
            str(result.reason_code or "").startswith(REASON_MISSING_INPUT)
            or str(result.reason_code or "").startswith("NOT_CONNECTED")
        )

    def test_register_stub_executor_and_run(self):
        def _pass_ci08(ctx):
            return make_supplemental_result(
                check_id="CI-08",
                status=STATUS_PASS,
                ctx=ctx,
                message="stub pass",
            )

        register_supplemental_executor("CI-08", _pass_ci08)
        self.assertIn("CI-08", registered_supplemental_check_ids())
        ctx = build_supplemental_gate_context(company=self.company)
        result = run_supplemental_check("CI-08", context=ctx)
        self.assertEqual(result.status, STATUS_PASS)
        self.assertEqual(result.message, "stub pass")
        # Must not appear on headline registry.
        self.assertNotIn("CI-08", registered_check_ids())

    def test_framework_defaults_register_all_twelve(self):
        from dataruns.dcs.pilot_gates.contract import (
            SLICE_A_CHECK_IDS,
            SLICE_B_CHECK_IDS,
        )

        registered = registered_supplemental_check_ids()
        self.assertEqual(registered, set(SUPPLEMENTAL_CHECK_IDS))
        self.assertTrue(SLICE_A_CHECK_IDS <= registered)
        self.assertTrue(SLICE_B_CHECK_IDS <= registered)
        self.assertTrue(ERP_SENSITIVE_CHECK_IDS <= registered)

    def test_context_loads_snapshot_from_dcs_score_run(self):
        score = self._dcs_with_snapshot()
        ctx = build_supplemental_gate_context(company=self.company)
        self.assertEqual(ctx.data_run_id_score, score.pk)
        self.assertEqual(ctx.snapshot().get("as_of"), "2026-01-01T00:00:00Z")
        latest = get_latest_succeeded_dcs_score_run(company=self.company)
        self.assertEqual(latest.pk, score.pk)

    def test_explicit_snapshot_override_still_links_score_run(self):
        score = self._dcs_with_snapshot()
        ctx = build_supplemental_gate_context(
            company=self.company,
            scoring_snapshot={"as_of": "override"},
        )
        self.assertEqual(ctx.data_run_id_score, score.pk)
        self.assertEqual(ctx.snapshot(), {"as_of": "override"})

    def test_explicit_data_run_id_wrong_company_rejected(self):
        other = Company.objects.create(
            tenant=self.tenant,
            name="Other",
            domain="pg-s3-other.example.com",
        )
        score = self._dcs_with_snapshot(company=other)
        ctx = build_supplemental_gate_context(
            company=self.company,
            data_run_id=score.pk,
        )
        self.assertIsNone(ctx.data_run_id_score)
        self.assertEqual(ctx.snapshot(), {})

    def test_explicit_failed_score_run_rejected(self):
        failed = self._dcs_with_snapshot(status=DataRun.Status.FAILED)
        self.assertIsNone(
            resolve_dcs_score_run(company=self.company, data_run_id=failed.pk)
        )
        ctx = build_supplemental_gate_context(
            company=self.company,
            data_run_id=failed.pk,
        )
        self.assertIsNone(ctx.data_run_id_score)
        self.assertEqual(ctx.snapshot(), {})

    def test_wrong_tenant_score_run_rejected(self):
        other_tenant = Tenant.objects.create(name="PG S3 B", slug="pg-s3-b")
        other_company = Company.objects.create(
            tenant=other_tenant,
            name="Other T",
            domain="pg-s3-b.example.com",
        )
        # Forge metadata company_id to match caller company — tenant must still reject.
        score = DataRun.objects.create(
            tenant=other_tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
            },
            run_snapshot={"as_of": "forged"},
        )
        self.assertIsNone(
            resolve_dcs_score_run(company=self.company, data_run_id=score.pk)
        )
        # Sanity: other company resolves its own score when metadata matches.
        own = self._dcs_with_snapshot(company=other_company)
        self.assertEqual(
            resolve_dcs_score_run(
                company=other_company, data_run_id=own.pk
            ).pk,
            own.pk,
        )

    def test_non_score_name_rejected(self):
        run = self._dcs_with_snapshot(name="pilot-gate-eval")
        self.assertIsNone(
            resolve_dcs_score_run(company=self.company, data_run_id=run.pk)
        )

    def test_run_none_means_all_twelve_empty_means_none(self):
        ctx = build_supplemental_gate_context(
            company=self.company,
            erp_in_scope=False,
        )
        all_results = run_supplemental_checks(None, context=ctx)
        self.assertEqual(len(all_results), EXPECTED_SUPPLEMENTAL_CHECK_COUNT)
        self.assertEqual(
            {r.check_id for r in all_results},
            set(SUPPLEMENTAL_CHECK_IDS),
        )
        # ERP-out short-circuit; Slice A/B run real evaluators (missing → UNKNOWN /
        # NOT_CONNECTED — never invent PASS).
        by_id = {r.check_id: r for r in all_results}
        self.assertEqual(by_id["BR-09"].status, STATUS_NOT_CONNECTED)
        self.assertEqual(by_id["CI-08"].status, STATUS_NOT_CONNECTED)
        self.assertIn(by_id["LE-07"].status, {STATUS_UNKNOWN, STATUS_NOT_CONNECTED})
        self.assertNotEqual(by_id["LE-07"].reason_code, REASON_EXECUTOR_PENDING)

        self.assertEqual(run_supplemental_checks([], context=ctx), [])

    def test_run_many_and_persist_rows(self):
        def _pass_ci08(ctx):
            return make_supplemental_result(
                check_id="CI-08",
                status=STATUS_PASS,
                ctx=ctx,
                evidence=[
                    Evidence(
                        source="test",
                        observed_at="2026-01-01T00:00:00Z",
                        locator="email",
                        value=1,
                    )
                ],
            )

        register_supplemental_executor("CI-08", _pass_ci08)
        score = self._dcs_with_snapshot()
        ctx = build_supplemental_gate_context(
            company=self.company,
            erp_in_scope=False,
            data_run_id=score.pk,
        )
        results = run_supplemental_checks(
            ["CI-08", "BR-09", "bogus"],
            context=ctx,
        )
        self.assertEqual({r.check_id for r in results}, {"BR-09", "CI-08"})
        rows = [check_result_to_store_row(r) for r in results]
        bundle = save_pilot_gate_eval(
            company=self.company,
            results=rows,
            data_run_id_score=ctx.data_run_id_score,
            erp_in_scope=ctx.erp_in_scope,
        )
        self.assertEqual(bundle.status_by_check_id["CI-08"], STATUS_PASS)
        self.assertEqual(bundle.status_by_check_id["BR-09"], STATUS_NOT_CONNECTED)
        self.assertEqual(bundle.data_run_id_score, score.pk)

    def test_cannot_register_headline_check_on_supplemental_registry(self):
        with self.assertRaises(KeyError):
            register_supplemental_executor(
                "CC-03",
                lambda ctx: make_supplemental_result(
                    check_id="CC-03", status=STATUS_PASS, ctx=ctx
                ),
            )
        self.assertIsNone(get_supplemental_executor("CC-03"))

    def test_unknown_supplemental_id_raises(self):
        ctx = build_supplemental_gate_context(company=self.company)
        with self.assertRaises(KeyError):
            run_supplemental_check("CC-03", context=ctx)
