"""Print DCS app status FD-02 for connected company."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.dcs.status import resolve_dcs_app_status
from tenants.models import Company, Connector, User


def main() -> None:
    connector = Connector.objects.filter(name="shopify", status="connected").first()
    if connector is None:
        print("No connected shopify")
        return
    company = connector.company
    user = User.objects.filter(company=company, role=User.Role.ADMIN).first()
    if user is None:
        user = User.objects.filter(company=company).first()
    status = resolve_dcs_app_status(company=company, user=user)
    issues = status.get("issues") or []
    fd02_issues = [i for i in issues if i.get("check_id") == "FD-02"]
    gates = status.get("foundation_gates") or []
    fd02_gate = next((g for g in gates if g.get("check_id") == "FD-02"), None)
    print("app_status:", status.get("app_status"))
    print("run_state:", status.get("run_state"))
    print("headline_score:", status.get("headline_score"))
    print("FD-02 gate:", json.dumps(fd02_gate, indent=2))
    print("FD-02 issues:", json.dumps(fd02_issues, indent=2))


if __name__ == "__main__":
    main()
