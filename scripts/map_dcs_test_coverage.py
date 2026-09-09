#!/usr/bin/env python
"""Map MVP1 check IDs to executor modules and test file references."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django

django.setup()

from dataruns.dcs.executors.registry import get_executor, registered_check_ids

CHECK_RE = re.compile(r"""['"]([A-Z]{2}-\d{2}[A-Z]?)['"]""")


def main() -> None:
    tests_dir = BACKEND / "dataruns" / "tests"
    coverage: dict[str, set[str]] = {
        cid: set() for cid in sorted(registered_check_ids())
    }
    for test_file in tests_dir.glob("test_*.py"):
        text = test_file.read_text(encoding="utf-8", errors="ignore")
        for cid in CHECK_RE.findall(text):
            if cid in coverage:
                coverage[cid].add(test_file.name)

    print("check_id,executor_module,direct_test_files")
    for cid in sorted(registered_check_ids()):
        fn = get_executor(cid)
        mod = fn.__module__.rsplit(".", 1)[-1]
        tests = ";".join(sorted(coverage[cid])) or "lumera_or_orchestrate"
        print(f"{cid},{mod},{tests}")

    no_direct = [cid for cid, refs in coverage.items() if not refs]
    print(f"\n# checks without direct test file string refs: {len(no_direct)}")
    print(",".join(no_direct))


if __name__ == "__main__":
    main()
