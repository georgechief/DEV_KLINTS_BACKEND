"""
Assert DCS CheckMaster catalogue is seeded (empty-DB deploy recovery).

Run from klints_backend:
  python scripts/verify_dcs_master_catalogue.py

Post-deploy (Docker):
  docker compose exec -T web python scripts/verify_dcs_master_catalogue.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.dcs.master import CheckMasterNotSeededError, load_check_master
from dataruns.models import CheckMaster

_EXPECTED = 42


def main() -> int:
    print("\nOPS — verify DCS CheckMaster catalogue\n")
    count = CheckMaster.objects.filter(is_active=True).count()
    print(f"active CheckMaster rows: {count} (expect {_EXPECTED})")
    if count < _EXPECTED:
        print(
            f"\nFAIL — run: python manage.py ensure_runtime_catalogue\n"
            f"(or: python manage.py seed_dcs_master)\n",
            file=sys.stderr,
        )
        return 1
    try:
        master = load_check_master()
    except CheckMasterNotSeededError as exc:
        print(f"\nFAIL — {exc}\n", file=sys.stderr)
        return 1
    print(f"load_check_master OK — {len(master.checks)} checks")
    print("\nPASS — DCS master catalogue seeded correctly.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
