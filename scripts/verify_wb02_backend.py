"""PRD-WB-02 backend verification — sandbox token consume + approve chain tests."""

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


def _read(rel_path: str) -> str:
    path = os.path.join(ROOT, rel_path)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def main() -> int:
    print("=== WB-02 BACKEND VERIFICATION ===\n")

    pipeline = _read("dataruns/writebacks/pipeline.py")
    _assert("and not sandbox" not in pipeline, "pipeline must not skip sandbox token consume")
    print("pipeline: sandbox approval_id consumption — OK")

    from django.conf import settings

    _assert(settings.WRITEBACKS_ENABLED is False, "WRITEBACKS_ENABLED must stay False")
    print(f"WRITEBACKS_ENABLED={settings.WRITEBACKS_ENABLED} — OK")

    from dataruns.writebacks.registry import MappingDisabled, get_check_mapping

    try:
        get_check_mapping("LE-04")
        raise AssertionError("LE-04 must stay disabled in registry")
    except MappingDisabled:
        print("LE-04 MappingDisabled — OK")

    print("\nRunning test_writeback_wb02 …")
    proc = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "test",
            "dataruns.tests.test_writeback_wb02",
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
        print("\nWB-02 backend verification: FAIL (tests)")
        return proc.returncode

    print("\nWB-02 backend verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
