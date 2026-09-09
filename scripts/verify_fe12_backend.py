"""PRD-FE-12 backend verification — evidence payload for Fix CSV export (read-only)."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("=== FE-12 BACKEND VERIFICATION ===\n")

    from django.conf import settings
    from dataruns.dcs_urls import urlpatterns
    from dataruns.writebacks.registry import MappingDisabled, get_check_mapping

    _assert(settings.WRITEBACKS_ENABLED is False, "WRITEBACKS_ENABLED must stay False")
    print(f"WRITEBACKS_ENABLED={settings.WRITEBACKS_ENABLED} — OK")

    names = {getattr(p, "name", None) for p in urlpatterns}
    _assert("dcs-worklist-detail" in names, "worklist detail route must exist for FE export source")
    print("route: GET /api/v1/dcs/worklist/{check_id}/ — OK")

    evidence_csv_routes = [
        p
        for p in urlpatterns
        if getattr(p, "name", None) and "evidence" in str(getattr(p, "name", "")).lower()
    ]
    _assert(len(evidence_csv_routes) == 0, "optional evidence.csv endpoint not required for FE-12 v1")
    print("no evidence.csv endpoint (FE builds CSV client-side) — OK")

    try:
        get_check_mapping("LE-04")
        raise AssertionError("LE-04 must stay disabled")
    except MappingDisabled:
        print("LE-04 MappingDisabled — OK")

    print("\nRunning worklist evidence detail tests …")
    proc = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "test",
            "dataruns.tests.test_dcs_worklist.DcsWorklistTests.test_detail_200_has_evidence_with_source_and_observed_at",
            "dataruns.tests.test_dcs_worklist.DcsWorklistTests.test_evidence_preview_prefers_mismatches",
            "--verbosity=1",
            "--keepdb",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode != 0:
        print("\nFE-12 backend verification: FAIL (worklist tests)")
        return proc.returncode

    print("\nFE-12 backend verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
