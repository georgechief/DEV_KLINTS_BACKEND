"""Read-only WF-01 backend verification — PRD-WF-01 §12 acceptance."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.architecture.constants import ARCHITECTURE_ASSESSMENT_KIND
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import DataRun
from dataruns.use_cases.build_package import generate_build_package, serialize_build_package
from dataruns.use_cases.constants import (
    DEFAULT_MANIFEST_REL,
    HANDOFF_PACKAGE_SPEC,
    MCP_ACTION_OBJECT_THEATER_FORMAT,
    MVP1_PILOT_COUNT,
    MVP1_PILOT_IDS,
)
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot
from dataruns.use_cases.serialize import serialize_pilot_detail
from tenants.models import Company, Tenant, User


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _seed_pilot_buildable(company: Company, use_case_id: str) -> None:
    pilot = (
        UseCasePilot.objects.select_related("blueprint")
        .prefetch_related("stage_maps")
        .get(use_case_id=use_case_id)
    )
    body = pilot.blueprint.body if pilot.blueprint else {}
    gates = body.get("gates") if isinstance(body.get("gates"), dict) else {}
    min_dcs = float(gates.get("min_dcs") or 70)
    check_ids = gates.get("gating_check_ids") or []
    checks = [{"check_id": cid, "status": "PASS"} for cid in check_ids]
    DataRun.objects.create(
        tenant=company.tenant,
        name=DCS_SCORE_DATA_RUN_NAME,
        status=DataRun.Status.SUCCEEDED,
        metadata={
            "kind": DCS_SCORE_KIND,
            "company_id": str(company.id),
            "headline_score": max(min_dcs, 75),
            "check_results": checks,
        },
    )
    allowed = gates.get("architecture_modes") or ["AUGMENT"]
    mode_key = str(allowed[0]).upper() if allowed else "AUGMENT"
    mode = getattr(
        ArchitectureAssessment.Mode,
        mode_key,
        ArchitectureAssessment.Mode.AUGMENT,
    )
    af_run = DataRun.objects.create(
        tenant=company.tenant,
        name="Architecture Assessment",
        status=DataRun.Status.SUCCEEDED,
        metadata={
            "kind": ARCHITECTURE_ASSESSMENT_KIND,
            "company_id": str(company.id),
        },
    )
    ArchitectureAssessment.objects.create(
        company=company,
        tenant=company.tenant,
        data_run=af_run,
        status=ArchitectureAssessment.Status.SUCCEEDED,
        mode=mode,
        probe_coverage={"lifecycle_gaps": []},
    )


def main() -> int:
    print("=== WF-01 BACKEND VERIFICATION ===")
    print("Bar: PRD-WF-01 §12 — 16 pilots, build package, human fallback\n")

    base = Path(ROOT)
    result = load_use_case_pilots_from_pack(
        manifest_path=base / DEFAULT_MANIFEST_REL,
        blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
    )
    _assert(result.pilots_upserted == MVP1_PILOT_COUNT, "16 pilots seeded")
    _assert(set(result.pilot_ids) == set(MVP1_PILOT_IDS), "pilot id set matches manifest")
    print(f"Pilot library: {MVP1_PILOT_COUNT} pilots loaded OK")

    tenant, _ = Tenant.objects.get_or_create(
        slug="wf01-verify",
        defaults={"name": "WF01 Verify"},
    )
    company, _ = Company.objects.get_or_create(
        tenant=tenant,
        domain="wf01-verify.example.com",
        defaults={"name": "WF01 Verify Co"},
    )
    analyst = User.objects.filter(email="wf01-verify@example.com").first()
    if analyst is None:
        analyst = User.objects.create_user(
            email="wf01-verify@example.com",
            password="pass",
            tenant=tenant,
            role=User.Role.ANALYST,
        )

    for use_case_id in sorted(MVP1_PILOT_IDS):
        pilot = UseCasePilot.objects.select_related("blueprint").get(use_case_id=use_case_id)
        detail = serialize_pilot_detail(pilot)
        summary = detail.get("workflow_summary") or {}
        _assert((summary.get("node_count") or 0) > 0, f"{use_case_id} workflow nodes")
        _assert(len(summary.get("nodes") or []) > 0, f"{use_case_id} node list")
    print("Detail API: all 16 pilots expose workflow_summary.nodes OK")

    for demo_id in ("UC-02", "UC-06B"):
        _seed_pilot_buildable(company, demo_id)
        pkg = generate_build_package(
            company=company,
            use_case_id=demo_id,
            generated_by=analyst,
        )
        payload = pkg.payload
        _assert(payload["route"] == "HUMAN_FALLBACK", f"{demo_id} human fallback route")
        _assert(payload.get("qa_requirements"), f"{demo_id} qa_requirements")
        _assert(payload.get("approval_requirements"), f"{demo_id} approval_requirements")
        _assert(payload.get("rollback"), f"{demo_id} rollback")
        _assert(payload.get("handoff_stub"), f"{demo_id} handoff_stub")
        _assert(
            payload["handoff_stub"]["activation_state"] == "STAGED_NOT_LIVE",
            f"{demo_id} STAGED_NOT_LIVE",
        )
        _assert(
            payload["handoff_stub"].get("format") == HANDOFF_PACKAGE_SPEC,
            f"{demo_id} handoff_stub.format HANDOFF_PACKAGE_SPEC",
        )
        _assert(
            payload["handoff_stub"].get("format") != MCP_ACTION_OBJECT_THEATER_FORMAT,
            f"{demo_id} no MCP_ACTION theater format",
        )
        serialized = serialize_build_package(pkg.package)
        _assert(
            serialized["handoff_stub"].get("format") == HANDOFF_PACKAGE_SPEC,
            f"{demo_id} serialize handoff_stub.format honest",
        )
        _assert(payload.get("hashes", {}).get("package_content_hash"), f"{demo_id} hash")
        print(f"Build package: {demo_id} OK (provisional={payload.get('provisional_supplemental')})")

    print("\nAll WF-01 backend checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\nFAILED: {exc}")
        raise SystemExit(1) from exc
