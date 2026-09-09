"""
OPS-UC-01 — assert MVP1 pilot catalogue is seeded (PRD-OPS-UC-01 §4).

Run from klints_backend (after migrate + load_use_case_pilots):
  python scripts/verify_use_case_pilots.py

Post-deploy (Docker):
  docker compose exec -T web python scripts/verify_use_case_pilots.py
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

from dataruns.use_cases.verify_catalogue import verify_pilot_catalogue


def main() -> int:
    print("\nOPS-UC-01 — verify MVP1 pilot catalogue\n")
    ok, messages = verify_pilot_catalogue(verbose=True)
    for line in messages:
        print(line)

    if ok:
        print("\nPASS — MVP1 pilot catalogue seeded correctly.\n")
        return 0

    print(
        "\nFAIL — run: python manage.py load_use_case_pilots\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
