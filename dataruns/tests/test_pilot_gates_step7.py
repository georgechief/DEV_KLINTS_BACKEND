"""DCS-09 Step 7 — pilot-gates HTTP APIs."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.pilot_gates.contract import (
    EXPECTED_SUPPLEMENTAL_CHECK_COUNT,
    GATE_CATALOG_VERSION,
    SLICE_A_CHECK_IDS,
)
from dataruns.dcs.pilot_gates.executors import clear_supplemental_executor_registry
from dataruns.dcs.pilot_gates.store import save_pilot_gate_eval
from dataruns.dcs.pilot_gates.views import (
    PilotGatesEvaluateView,
    PilotGatesLatestView,
    PilotGatesMasterView,
    PilotSupplementalReadinessView,
)
from dataruns.models import DataRun
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL, SUPPLEMENTAL_PREFLIGHT_CHECKS
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from tenants.models import Company, Tenant, User


class PilotGatesStep7ApiTests(TestCase):
    def setUp(self):
        clear_supplemental_executor_registry()
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="PG S7", slug="pg-s7")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="PG S7 Co",
            domain="pg-s7.example.com",
        )
        self.admin = User.objects.create_user(
            email="pg-s7-admin@example.com",
            password="pass",
            tenant=self.tenant,
            role=User.Role.ADMIN,
        )
        self.analyst = User.objects.create_user(
            email="pg-s7-analyst@example.com",
            password="pass",
            tenant=self.tenant,
            role=User.Role.ANALYST,
        )
        self.viewer = User.objects.create_user(
            email="pg-s7-viewer@example.com",
            password="pass",
            tenant=self.tenant,
            role=User.Role.VIEWER,
        )
        self.factory = APIRequestFactory()

    def tearDown(self):
        clear_supplemental_executor_registry()

    def _dcs_score(self) -> DataRun:
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 80,
            },
            run_snapshot={
                "as_of": "2026-06-01T00:00:00Z",
                "connectors": {"manago_ai": {"status": "connected"}},
                "gate_inputs": {
                    "manago_contacts": [
                        {
                            "email": "ok@example.com",
                            "contactId": "1",
                            "state": "CONFIRMED",
                            "createdOn": "2026-01-01T00:00:00Z",
                        },
                        {
                            "email": "ok2@example.com",
                            "contactId": "2",
                            "state": "CONFIRMED",
                            "createdOn": "2026-01-01T00:00:00Z",
                        },
                    ]
                },
            },
        )

    def test_master_viewer_ok(self):
        request = self.factory.get("/api/v1/dcs/pilot-gates/master/")
        force_authenticate(request, user=self.viewer)
        response = PilotGatesMasterView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], EXPECTED_SUPPLEMENTAL_CHECK_COUNT)
        self.assertEqual(response.data["gate_catalog_version"], GATE_CATALOG_VERSION)
        ids = {c["check_id"] for c in response.data["checks"]}
        self.assertEqual(ids, set(SUPPLEMENTAL_PREFLIGHT_CHECKS))
        self.assertIn("UC-02", response.data["use_case_map"])
        self.assertEqual(
            set(response.data["use_case_map"]["UC-02"]),
            set(SLICE_A_CHECK_IDS),
        )

    def test_latest_empty_then_populated(self):
        request = self.factory.get("/api/v1/dcs/pilot-gates/latest/")
        force_authenticate(request, user=self.viewer)
        empty = PilotGatesLatestView.as_view()(request)
        self.assertEqual(empty.status_code, 200)
        self.assertFalse(empty.data["evaluated"])
        self.assertEqual(empty.data["results"], [])
        self.assertEqual(empty.data["scope"], "pilot_supplemental")
        self.assertIsNone(empty.data["data_run_id"])
        self.assertEqual(empty.data["gate_catalog_version"], GATE_CATALOG_VERSION)

        save_pilot_gate_eval(
            company=self.company,
            results=[
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "FAIL"},
            ],
            erp_in_scope=False,
            merge_with_previous=False,
        )
        filled = PilotGatesLatestView.as_view()(request)
        self.assertEqual(filled.status_code, 200)
        self.assertTrue(filled.data["evaluated"])
        self.assertEqual(filled.data["status_by_check_id"]["CI-08"], "PASS")
        self.assertEqual(filled.data["status_by_check_id"]["CC-06"], "FAIL")

    def test_evaluate_analyst_uc02(self):
        score = self._dcs_score()
        request = self.factory.post(
            "/api/v1/dcs/pilot-gates/evaluate/",
            {
                "use_case_ids": ["UC-02"],
                "check_ids": None,
                "data_run_id": score.id,
                "erp_in_scope": False,
            },
            format="json",
        )
        force_authenticate(request, user=self.analyst)
        response = PilotGatesEvaluateView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["skipped"])
        self.assertEqual(set(response.data["check_ids"]), set(SLICE_A_CHECK_IDS))
        self.assertEqual(response.data["status_by_check_id"]["CI-08"], "PASS")
        self.assertEqual(response.data["status_by_check_id"]["CC-06"], "PASS")
        self.assertEqual(len(response.data["readiness"]), 1)
        ready = response.data["readiness"][0]
        self.assertEqual(ready["use_case_id"], "UC-02")
        self.assertTrue(ready["supplemental_ready"])
        self.assertEqual(ready["blocked_by"], [])
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 2)

    def test_evaluate_uses_latest_score_when_data_run_id_omitted(self):
        self._dcs_score()
        request = self.factory.post(
            "/api/v1/dcs/pilot-gates/evaluate/",
            {"use_case_ids": ["UC-02"], "erp_in_scope": False},
            format="json",
        )
        force_authenticate(request, user=self.analyst)
        response = PilotGatesEvaluateView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status_by_check_id"]["CI-08"], "PASS")
        self.assertIsNotNone(response.data["data_run_id_score"])

    def test_evaluate_erp_in_scope_string_false(self):
        self._dcs_score()
        request = self.factory.post(
            "/api/v1/dcs/pilot-gates/evaluate/",
            {
                "check_ids": ["BR-09"],
                "erp_in_scope": "false",
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = PilotGatesEvaluateView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["erp_in_scope"])
        self.assertEqual(
            response.data["status_by_check_id"]["BR-09"],
            "NOT_CONNECTED",
        )

    def test_evaluate_erp_in_scope_invalid(self):
        request = self.factory.post(
            "/api/v1/dcs/pilot-gates/evaluate/",
            {"check_ids": ["CI-08"], "erp_in_scope": "maybe"},
            format="json",
        )
        force_authenticate(request, user=self.analyst)
        response = PilotGatesEvaluateView.as_view()(request)
        self.assertEqual(response.status_code, 400)

    def test_evaluate_rejects_other_company_data_run(self):
        other_tenant = Tenant.objects.create(name="Other S7", slug="other-s7")
        other_company = Company.objects.create(
            tenant=other_tenant,
            name="Other S7 Co",
            domain="other-s7.example.com",
        )
        foreign = DataRun.objects.create(
            tenant=other_tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(other_company.id),
                "headline_score": 80,
            },
        )
        request = self.factory.post(
            "/api/v1/dcs/pilot-gates/evaluate/",
            {"use_case_ids": ["UC-02"], "data_run_id": foreign.id},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = PilotGatesEvaluateView.as_view()(request)
        self.assertEqual(response.status_code, 422)

    def test_evaluate_viewer_forbidden(self):
        request = self.factory.post(
            "/api/v1/dcs/pilot-gates/evaluate/",
            {"use_case_ids": ["UC-02"]},
            format="json",
        )
        force_authenticate(request, user=self.viewer)
        response = PilotGatesEvaluateView.as_view()(request)
        self.assertEqual(response.status_code, 403)

    def test_evaluate_bad_data_run_id(self):
        request = self.factory.post(
            "/api/v1/dcs/pilot-gates/evaluate/",
            {"use_case_ids": ["UC-02"], "data_run_id": 999999},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = PilotGatesEvaluateView.as_view()(request)
        self.assertEqual(response.status_code, 422)
        self.assertIn("data_run_id", response.data["detail"])

    def test_evaluate_bad_body_types(self):
        request = self.factory.post(
            "/api/v1/dcs/pilot-gates/evaluate/",
            {"use_case_ids": "UC-02"},
            format="json",
        )
        force_authenticate(request, user=self.analyst)
        response = PilotGatesEvaluateView.as_view()(request)
        self.assertEqual(response.status_code, 400)

    def test_readiness_uc02_not_evaluated(self):
        request = self.factory.get("/api/v1/dcs/pilots/UC-02/readiness/")
        force_authenticate(request, user=self.viewer)
        response = PilotSupplementalReadinessView.as_view()(
            request, use_case_id="UC-02"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["supplemental_ready"])
        self.assertEqual(
            set(response.data["not_evaluated"]),
            set(SLICE_A_CHECK_IDS),
        )

    def test_readiness_after_store_pass(self):
        save_pilot_gate_eval(
            company=self.company,
            results=[
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "PASS"},
            ],
            erp_in_scope=False,
            merge_with_previous=False,
        )
        request = self.factory.get("/api/v1/dcs/pilots/uc-02/readiness/")
        force_authenticate(request, user=self.viewer)
        response = PilotSupplementalReadinessView.as_view()(
            request, use_case_id="uc-02"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["supplemental_ready"])
        self.assertEqual(response.data["blocked_by"], [])
        self.assertEqual(response.data["not_evaluated"], [])

    def test_readiness_unknown_pilot_404(self):
        request = self.factory.get("/api/v1/dcs/pilots/UC-99/readiness/")
        force_authenticate(request, user=self.viewer)
        response = PilotSupplementalReadinessView.as_view()(
            request, use_case_id="UC-99"
        )
        self.assertEqual(response.status_code, 404)

    def test_latest_requires_company(self):
        orphan_tenant = Tenant.objects.create(name="Orphan S7", slug="orphan-s7")
        orphan = User.objects.create_user(
            email="orphan-s7@example.com",
            password="pass",
            tenant=orphan_tenant,
            role=User.Role.VIEWER,
        )
        request = self.factory.get("/api/v1/dcs/pilot-gates/latest/")
        force_authenticate(request, user=orphan)
        response = PilotGatesLatestView.as_view()(request)
        self.assertEqual(response.status_code, 400)

    def test_latest_isolated_by_company(self):
        other_tenant = Tenant.objects.create(name="Iso S7", slug="iso-s7")
        other_company = Company.objects.create(
            tenant=other_tenant,
            name="Iso S7 Co",
            domain="iso-s7.example.com",
        )
        save_pilot_gate_eval(
            company=other_company,
            results=[{"check_id": "CI-08", "status": "FAIL"}],
            erp_in_scope=False,
            merge_with_previous=False,
        )
        request = self.factory.get("/api/v1/dcs/pilot-gates/latest/")
        force_authenticate(request, user=self.viewer)
        response = PilotGatesLatestView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["evaluated"])
        self.assertEqual(response.data["status_by_check_id"], {})

    def test_readiness_blocked_by_fail(self):
        save_pilot_gate_eval(
            company=self.company,
            results=[
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "FAIL"},
            ],
            erp_in_scope=False,
            merge_with_previous=False,
        )
        request = self.factory.get("/api/v1/dcs/pilots/UC-02/readiness/")
        force_authenticate(request, user=self.viewer)
        response = PilotSupplementalReadinessView.as_view()(
            request, use_case_id="UC-02"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["supplemental_ready"])
        self.assertEqual(
            response.data["blocked_by"],
            [{"check_id": "CC-06", "status": "FAIL"}],
        )

    def test_urls_mounted_via_reverse(self):
        from django.urls import reverse
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=self.viewer)
        master = client.get(reverse("dcs-pilot-gates-master"))
        self.assertEqual(master.status_code, 200)
        latest = client.get(reverse("dcs-pilot-gates-latest"))
        self.assertEqual(latest.status_code, 200)
        ready = client.get(
            reverse(
                "dcs-pilot-supplemental-readiness",
                kwargs={"use_case_id": "UC-02"},
            )
        )
        self.assertEqual(ready.status_code, 200)

        client.force_authenticate(user=self.analyst)
        self._dcs_score()
        evaluate = client.post(
            reverse("dcs-pilot-gates-evaluate"),
            {"use_case_ids": ["UC-02"]},
            format="json",
        )
        self.assertEqual(evaluate.status_code, 200)

    def test_unauthenticated_401(self):
        from django.urls import reverse
        from rest_framework.test import APIClient

        client = APIClient()
        self.assertEqual(
            client.get(reverse("dcs-pilot-gates-master")).status_code,
            401,
        )
        self.assertEqual(
            client.post(
                reverse("dcs-pilot-gates-evaluate"),
                {},
                format="json",
            ).status_code,
            401,
        )
