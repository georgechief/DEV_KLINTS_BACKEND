"""Tests for PRD-UC-01 Phase C — stage map + gap_suggested."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import TestCase

from dataruns.architecture.constants import ARCHITECTURE_ASSESSMENT_KIND
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import DataRun
from dataruns.use_cases.constants import (
    DEFAULT_MANIFEST_REL,
    MVP1_PILOT_COUNT,
    MVP1_PILOT_IDS,
    PILOT_PRIMARY_STAGES,
)
from dataruns.use_cases.gaps import (
    assert_stage_map_complete,
    collect_gap_stage_ids,
    collect_gap_stage_ids_from_probe_coverage,
    is_gap_suggested,
    matched_gap_stages,
    pilots_suggested_for_gap,
)
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import PilotStageMap, UseCasePilot
from dataruns.use_cases.recommend import (
    build_recommendations_payload,
    resolve_recommendation_context,
)
from tenants.models import Company, Tenant


# Locked PRD §6 table — must stay in sync with constants.PILOT_PRIMARY_STAGES.
PRD_SECTION_6_MAP = {
    "UC-02": ("stage_02", "stage_04"),
    "UC-04": ("stage_03",),
    "UC-05": ("stage_02",),
    "UC-06B": ("stage_05",),
    "UC-08": ("stage_04",),
    "UC-09": ("stage_04",),
    "UC-10": ("stage_04",),
    "UC-11": ("stage_06",),
    "UC-12": ("stage_07",),
    "UC-13": ("stage_08",),
    "UC-16": ("stage_09",),
    "UC-17": ("stage_10",),
    "UC-21": ("stage_03",),
    "UC-23": ("stage_12",),
    "UC-28": ("stage_14",),
    "UC-36": ("stage_15",),
}


class UseCaseStageMapUnitTests(TestCase):
    def test_constants_match_prd_section_6(self):
        assert_stage_map_complete()
        self.assertEqual(set(PILOT_PRIMARY_STAGES.keys()), set(MVP1_PILOT_IDS))
        self.assertEqual(PILOT_PRIMARY_STAGES, PRD_SECTION_6_MAP)

    def test_seeded_db_stage_maps_match_prd(self):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.assertEqual(UseCasePilot.objects.count(), MVP1_PILOT_COUNT)
        for use_case_id, expected in PRD_SECTION_6_MAP.items():
            got = tuple(
                PilotStageMap.objects.filter(
                    pilot_id=use_case_id, is_primary=True
                )
                .order_by("stage_id")
                .values_list("stage_id", flat=True)
            )
            self.assertEqual(
                set(got),
                set(expected),
                msg=f"{use_case_id} stage map mismatch",
            )

    def test_normalize_messy_gap_tokens(self):
        raw = [
            {"stage_id": "stage_2", "stage": 2},
            {"stage": 9},
            "Stage 12",
            "stage-14",
            "stage_02",  # duplicate of stage_2
            15,
            {"stage_id": "bogus"},
        ]
        got = collect_gap_stage_ids(raw)
        self.assertEqual(
            got,
            ["stage_02", "stage_09", "stage_12", "stage_14", "stage_15"],
        )

    def test_probe_coverage_flat_and_nested(self):
        probe = {
            "lifecycle_gaps": [{"stage_id": "stage_05"}],
            "gap_stage_ids": ["stage_06", "6"],  # 6 normalizes to stage_06 dupe
        }
        got = collect_gap_stage_ids_from_probe_coverage(probe)
        self.assertEqual(got, ["stage_05", "stage_06"])

    def test_gap_suggested_flag_only(self):
        self.assertTrue(
            is_gap_suggested(
                primary_stages=("stage_02", "stage_04"),
                af_gap_stage_ids=["stage_02"],
            )
        )
        self.assertFalse(
            is_gap_suggested(
                primary_stages=("stage_02", "stage_04"),
                af_gap_stage_ids=["stage_09"],
            )
        )
        matched = matched_gap_stages(
            primary_stages=("stage_02", "stage_04"),
            af_gap_stage_ids=["stage_04", "stage_10"],
        )
        self.assertEqual(matched, ["stage_04"])

    def test_stage_02_suggests_uc02_and_uc05(self):
        self.assertEqual(
            pilots_suggested_for_gap("stage_02"),
            ["UC-02", "UC-05"],
        )

    def test_stage_03_suggests_uc04_and_uc21(self):
        self.assertEqual(
            pilots_suggested_for_gap("stage_03"),
            ["UC-04", "UC-21"],
        )


class UseCaseGapRecommendationIntegrationTests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="UC Gap", slug="uc-gap")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="UC Gap Co",
            domain="uc-gap.example.com",
        )

    def _seed_dcs_and_af(self, *, gaps: list):
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 50,  # blocked_dcs — gap flag must still work
                "check_results": [],
            },
        )
        af_run = DataRun.objects.create(
            tenant=self.tenant,
            name="AF",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": ARCHITECTURE_ASSESSMENT_KIND,
                "company_id": str(self.company.id),
            },
        )
        ArchitectureAssessment.objects.create(
            company=self.company,
            tenant=self.tenant,
            data_run=af_run,
            status=ArchitectureAssessment.Status.SUCCEEDED,
            mode=ArchitectureAssessment.Mode.INCOMPLETE,
            probe_coverage={"lifecycle_gaps": gaps},
        )

    def test_gap_suggested_independent_of_blocked_status(self):
        # Messy tokens still match UC-02 / UC-05
        self._seed_dcs_and_af(
            gaps=[
                {"stage_id": "stage_2", "job": "welcome"},
                {"stage": 10},
            ]
        )
        payload = build_recommendations_payload(company=self.company)
        by_id = {p["use_case_id"]: p for p in payload["pilots"]}

        self.assertTrue(by_id["UC-02"]["gap_suggested"])
        self.assertTrue(by_id["UC-05"]["gap_suggested"])
        self.assertTrue(by_id["UC-17"]["gap_suggested"])  # stage_10
        self.assertFalse(by_id["UC-06B"]["gap_suggested"])

        # Status stays blocked_* — gap_suggested is a flag, not a status
        self.assertEqual(by_id["UC-02"]["status"], "blocked_dcs_score")
        self.assertNotEqual(by_id["UC-02"]["status"], "gap_suggested")

        self.assertEqual(payload["summary"]["gap_suggested"], 3)
        self.assertIn("stage_02", payload["architecture"]["gap_stage_ids"])
        self.assertIn("stage_10", payload["architecture"]["gap_stage_ids"])

    def test_context_normalizes_gap_stage_ids(self):
        self._seed_dcs_and_af(gaps=[{"stage_id": "Stage 05"}])
        ctx = resolve_recommendation_context(company=self.company)
        self.assertEqual(ctx.gap_stage_ids, ["stage_05"])
