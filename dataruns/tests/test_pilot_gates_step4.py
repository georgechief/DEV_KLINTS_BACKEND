"""DCS-09 Step 4 — Slice A executors (CI-08, CC-06)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase, TestCase

from dataruns.dcs.executors.registry import registered_check_ids
from dataruns.dcs.pilot_gates.context import (
    build_supplemental_gate_context,
)
from dataruns.dcs.pilot_gates.contract import (
    SLICE_A_CHECK_IDS,
    STATUS_FAIL,
    STATUS_NOT_CONNECTED,
    STATUS_PASS,
    STATUS_UNKNOWN,
)
from dataruns.dcs.pilot_gates.executors import (
    check_result_to_store_row,
    clear_supplemental_executor_registry,
    registered_supplemental_check_ids,
    run_supplemental_check,
    run_supplemental_checks,
)
from dataruns.dcs.pilot_gates.slice_a import (
    CC06_CONFIRMATION_WINDOW_DAYS,
    CC06_FAIL_STUCK_SHARE,
    evaluate_cc06,
    evaluate_ci08,
)
from dataruns.dcs.pilot_gates.store import save_pilot_gate_eval
from tenants.models import Company, Tenant


def _as_of() -> str:
    return "2026-06-01T00:00:00Z"


def _ctx(
    company: Company,
    *,
    contacts: list[dict] | None = None,
    manago_connected: bool = True,
) -> SupplementalGateContext:
    snapshot: dict = {
        "as_of": _as_of(),
        "connectors": {
            "manago_ai": {
                "status": "connected" if manago_connected else "disconnected"
            }
        },
    }
    if contacts is not None:
        snapshot["gate_inputs"] = {"manago_contacts": contacts}
    return build_supplemental_gate_context(
        company=company,
        scoring_snapshot=snapshot,
    )


class PilotGatesStep4IsolationTests(SimpleTestCase):
    def test_slice_a_not_in_headline_registry(self):
        self.assertEqual(registered_check_ids() & set(SLICE_A_CHECK_IDS), set())


class PilotGatesStep4ExecutorTests(TestCase):
    def setUp(self):
        clear_supplemental_executor_registry()
        self.tenant = Tenant.objects.create(name="PG S4", slug="pg-s4")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="PG S4 Co",
            domain="pg-s4.example.com",
        )

    def tearDown(self):
        clear_supplemental_executor_registry()

    def test_slice_a_registered(self):
        self.assertTrue(SLICE_A_CHECK_IDS <= registered_supplemental_check_ids())

    def test_ci08_pass_clean_emails(self):
        ctx = _ctx(
            self.company,
            contacts=[
                {"email": "ada@example.com", "contactId": "1"},
                {"email": "bob@brand.co.uk", "contactId": "2"},
            ],
        )
        result = evaluate_ci08(ctx)
        self.assertEqual(result.status, STATUS_PASS)
        self.assertIsNone(result.reason_code)

    def test_ci08_fail_typo_domain(self):
        ctx = _ctx(
            self.company,
            contacts=[
                {"email": "ada@gmial.com", "contactId": "1"},
                {"email": "ok@example.com", "contactId": "2"},
            ],
        )
        result = evaluate_ci08(ctx)
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertEqual(result.reason_code, "CI08_INVALID_EMAIL_SET")

    def test_ci08_fail_rfc_and_disposable(self):
        ctx = _ctx(
            self.company,
            contacts=[
                {"email": "not-an-email", "contactId": "1"},
                {"email": "x@mailinator.com", "contactId": "2"},
            ],
        )
        result = evaluate_ci08(ctx)
        self.assertEqual(result.status, STATUS_FAIL)

    def test_ci08_fail_manago_invalid_flag(self):
        ctx = _ctx(
            self.company,
            contacts=[
                {
                    "email": "looks-ok@example.com",
                    "invalid": True,
                    "contactId": "1",
                }
            ],
        )
        result = evaluate_ci08(ctx)
        self.assertEqual(result.status, STATUS_FAIL)

    def test_ci08_not_connected_without_contacts(self):
        ctx = _ctx(self.company, contacts=None, manago_connected=False)
        result = evaluate_ci08(ctx)
        self.assertEqual(result.status, STATUS_NOT_CONNECTED)

    def test_ci08_unknown_when_connected_but_empty(self):
        ctx = _ctx(self.company, contacts=[], manago_connected=True)
        result = evaluate_ci08(ctx)
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("manago_contacts", result.reason_code or "")

    def test_ci08_identity_both_source_fallback(self):
        ctx = build_supplemental_gate_context(
            company=self.company,
            scoring_snapshot={
                "as_of": _as_of(),
                "connectors": {"manago_ai": {"status": "connected"}},
                "contacts": [
                    {
                        "source": "both",
                        "person.email": "bad@gmial.com",
                        "manago_contact_id": "1",
                    }
                ],
            },
        )
        result = evaluate_ci08(ctx)
        self.assertEqual(result.status, STATUS_FAIL)

    def test_cc06_pass_within_band(self):
        as_of = datetime(2026, 6, 1, tzinfo=timezone.utc)
        fresh = (as_of - timedelta(hours=12)).isoformat().replace("+00:00", "Z")
        # 1 stuck of 41 ≈ 0.024 <= 0.05 → PASS
        contacts = [
            {
                "email": f"c{i}@example.com",
                "state": "CONFIRMED",
                "contactId": str(i),
                "createdOn": "2026-01-01T00:00:00Z",
            }
            for i in range(39)
        ]
        contacts.append(
            {
                "email": "stuck@example.com",
                "state": "Not confirmed",
                "contactId": "stuck",
                "createdOn": "2026-01-01T00:00:00Z",
            }
        )
        # one fresh not-confirmed (inside window) should not count as stuck
        contacts.append(
            {
                "email": "fresh@example.com",
                "state": "NOT_CONFIRMED",
                "contactId": "fresh",
                "createdOn": fresh,
            }
        )
        ctx = _ctx(self.company, contacts=contacts)
        result = evaluate_cc06(ctx)
        self.assertEqual(result.status, STATUS_PASS)
        self.assertEqual(CC06_CONFIRMATION_WINDOW_DAYS, 2)
        self.assertEqual(CC06_FAIL_STUCK_SHARE, 0.05)

    def test_cc06_fail_stuck_share(self):
        # 3/10 stuck = 0.3 > 0.05
        contacts = []
        for i in range(7):
            contacts.append(
                {
                    "email": f"ok{i}@example.com",
                    "state": "CONFIRMED",
                    "contactId": f"ok{i}",
                    "createdOn": "2026-01-01T00:00:00Z",
                }
            )
        for i in range(3):
            contacts.append(
                {
                    "email": f"stuck{i}@example.com",
                    "state": "Not confirmed",
                    "contactId": f"stuck{i}",
                    "createdOn": "2026-01-01T00:00:00Z",
                }
            )
        ctx = _ctx(self.company, contacts=contacts)
        result = evaluate_cc06(ctx)
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertEqual(result.reason_code, "CC06_DOI_STUCK_SHARE")

    def test_cc06_unknown_without_doi_vocabulary(self):
        ctx = _ctx(
            self.company,
            contacts=[
                {
                    "email": "a@example.com",
                    "state": "CUSTOMER",
                    "contactId": "1",
                    "createdOn": "2026-01-01T00:00:00Z",
                }
            ],
        )
        result = evaluate_cc06(ctx)
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("doi_state", result.reason_code or "")

    def test_cc06_unknown_when_not_confirmed_missing_timestamps(self):
        ctx = _ctx(
            self.company,
            contacts=[
                {
                    "email": "ok@example.com",
                    "state": "CONFIRMED",
                    "contactId": "1",
                    "createdOn": "2026-01-01T00:00:00Z",
                },
                {
                    "email": "stuck@example.com",
                    "state": "Not confirmed",
                    "contactId": "2",
                    # no createdOn — cannot invent FAIL/PASS
                },
            ],
        )
        result = evaluate_cc06(ctx)
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("doi_timestamps", result.reason_code or "")

    def test_cc06_unknown_identity_snapshot_only(self):
        ctx = build_supplemental_gate_context(
            company=self.company,
            scoring_snapshot={
                "as_of": _as_of(),
                "connectors": {"manago_ai": {"status": "connected"}},
                "contacts": [
                    {
                        "source": "manago_ai",
                        "person.email": "a@example.com",
                        "manago_contact_id": "1",
                    }
                ],
            },
        )
        result = evaluate_cc06(ctx)
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("doi_state", result.reason_code or "")

    def test_cc06_loads_from_connector_snapshot(self):
        from tenants.models import Connector, ConnectorSnapshot

        connector = Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="crm",
            status="connected",
        )
        ConnectorSnapshot.objects.create(
            connector=connector,
            version=1,
            snapshot_data={
                "raw": {
                    "contacts": [
                        {
                            "email": "ok@example.com",
                            "state": "CONFIRMED",
                            "contactId": "1",
                            "createdOn": "2026-01-01T00:00:00Z",
                        }
                    ]
                }
            },
        )
        ctx = build_supplemental_gate_context(
            company=self.company,
            scoring_snapshot={
                "as_of": _as_of(),
                "connectors": {"manago_ai": {"status": "connected"}},
            },
        )
        result = evaluate_cc06(ctx)
        self.assertEqual(result.status, STATUS_PASS)

    def test_run_slice_a_and_persist(self):
        contacts = [
            {
                "email": "ok@example.com",
                "contactId": "1",
                "state": "CONFIRMED",
                "createdOn": "2026-01-01T00:00:00Z",
            },
            {
                "email": "bad@gmial.com",
                "contactId": "2",
                "state": "CONFIRMED",
                "createdOn": "2026-01-01T00:00:00Z",
            },
        ]
        ctx = _ctx(self.company, contacts=contacts)
        results = run_supplemental_checks(["CI-08", "CC-06"], context=ctx)
        by_id = {r.check_id: r for r in results}
        self.assertEqual(by_id["CI-08"].status, STATUS_FAIL)
        self.assertEqual(by_id["CC-06"].status, STATUS_PASS)
        self.assertNotIn("CI-08", registered_check_ids())
        rows = [check_result_to_store_row(r) for r in results]
        bundle = save_pilot_gate_eval(
            company=self.company,
            results=rows,
            erp_in_scope=False,
        )
        self.assertEqual(bundle.status_by_check_id["CI-08"], STATUS_FAIL)
        self.assertEqual(bundle.status_by_check_id["CC-06"], STATUS_PASS)

    def test_registry_run_matches_direct(self):
        ctx = _ctx(
            self.company,
            contacts=[{"email": "ok@example.com", "contactId": "1"}],
        )
        via_registry = run_supplemental_check("CI-08", context=ctx)
        direct = evaluate_ci08(ctx)
        self.assertEqual(via_registry.status, direct.status)
