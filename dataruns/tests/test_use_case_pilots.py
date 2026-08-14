"""Tests for PRD-UC-01 Phase A — pilot seed + catalogue API."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL, MVP1_PILOT_COUNT, MVP1_PILOT_IDS
from dataruns.use_cases.loader import (
    BlueprintValidationError,
    load_use_case_pilots_from_pack,
    validate_blueprint_payload,
)
from dataruns.use_cases.models import PilotStageMap, UseCaseBlueprint, UseCasePilot
from dataruns.use_cases.views import UseCaseCatalogueView, UseCaseDetailView
from tenants.models import Company, Tenant

User = get_user_model()


class UseCaseLoaderTests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        self.manifest_path = base / DEFAULT_MANIFEST_REL
        self.blueprints_dir = self.manifest_path.parent

    def test_load_all_sixteen_pilots_from_pack(self):
        result = load_use_case_pilots_from_pack(
            manifest_path=self.manifest_path,
            blueprints_dir=self.blueprints_dir,
        )
        self.assertEqual(result.pilots_upserted, MVP1_PILOT_COUNT)
        self.assertEqual(UseCasePilot.objects.count(), MVP1_PILOT_COUNT)
        self.assertEqual(UseCaseBlueprint.objects.count(), MVP1_PILOT_COUNT)
        self.assertIn("UC-06B", result.pilot_ids)
        self.assertNotIn("UC-06A", result.pilot_ids)
        self.assertEqual(set(result.pilot_ids), set(MVP1_PILOT_IDS))

    def test_load_is_idempotent(self):
        load_use_case_pilots_from_pack(
            manifest_path=self.manifest_path,
            blueprints_dir=self.blueprints_dir,
        )
        first_hash = UseCaseBlueprint.objects.get(pilot_id="UC-02").content_hash
        load_use_case_pilots_from_pack(
            manifest_path=self.manifest_path,
            blueprints_dir=self.blueprints_dir,
        )
        self.assertEqual(UseCasePilot.objects.count(), MVP1_PILOT_COUNT)
        self.assertEqual(
            UseCaseBlueprint.objects.get(pilot_id="UC-02").content_hash,
            first_hash,
        )

    def test_uc02_has_gates_and_stage_map(self):
        load_use_case_pilots_from_pack(
            manifest_path=self.manifest_path,
            blueprints_dir=self.blueprints_dir,
        )
        bp = UseCaseBlueprint.objects.get(pilot_id="UC-02")
        gates = bp.body.get("gates") or {}
        self.assertEqual(gates.get("min_dcs"), 70)
        self.assertIn("CC-03", gates.get("gating_check_ids") or [])
        stages = set(
            PilotStageMap.objects.filter(pilot_id="UC-02").values_list(
                "stage_id", flat=True
            )
        )
        self.assertEqual(stages, {"stage_02", "stage_04"})

    def test_validate_rejects_missing_gates(self):
        with self.assertRaises(BlueprintValidationError):
            validate_blueprint_payload(
                {
                    "schema_version": "1.0.1",
                    "blueprint_id": "bad",
                    "use_case_id": "UC-02",
                    "variant_id": "default",
                    "release": "MVP1",
                    "target_platform": ["MANAGO"],
                    "gates": {},
                    "audience": {},
                    "trigger": {},
                    "workflow": {"nodes": [{"node_id": "a"}, {"node_id": "b"}]},
                    "measurement": {},
                    "qa": {},
                    "approval": {},
                    "rollback": {},
                    "capability_dependencies": [],
                    "provenance": {},
                }
            )


class UseCaseCatalogueApiTests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="UC Tenant", slug="uc-tenant")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="UC Co",
            domain="uc.example.com",
        )
        self.viewer = User.objects.create_user(
            email="uc-viewer@example.com",
            password="pass",
            tenant=self.tenant,
            role=User.Role.VIEWER,
        )
        self.factory = APIRequestFactory()

    def test_catalogue_lists_sixteen_pilots(self):
        request = self.factory.get("/api/v1/use-cases/")
        force_authenticate(request, user=self.viewer)
        response = UseCaseCatalogueView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["pilot_count"], MVP1_PILOT_COUNT)
        self.assertEqual(len(response.data["pilots"]), MVP1_PILOT_COUNT)
        first = response.data["pilots"][0]
        self.assertEqual(first["use_case_id"], "UC-02")
        self.assertIn("gates", first)
        self.assertIn("execution", first)
        self.assertGreater(first.get("node_count") or 0, 0)

    def test_detail_returns_blueprint_summary(self):
        request = self.factory.get("/api/v1/use-cases/UC-02/")
        force_authenticate(request, user=self.viewer)
        response = UseCaseDetailView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["use_case_id"], "UC-02")
        self.assertIn("workflow_summary", response.data)
        self.assertIn("trigger", response.data)
        self.assertIn("business_objective", response.data)

    def test_detail_unknown_returns_404(self):
        request = self.factory.get("/api/v1/use-cases/UC-99/")
        force_authenticate(request, user=self.viewer)
        response = UseCaseDetailView.as_view()(request, use_case_id="UC-99")
        self.assertEqual(response.status_code, 404)

    def test_catalogue_empty_before_load(self):
        UseCasePilot.objects.all().delete()
        request = self.factory.get("/api/v1/use-cases/")
        force_authenticate(request, user=self.viewer)
        response = UseCaseCatalogueView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["pilot_count"], 0)
