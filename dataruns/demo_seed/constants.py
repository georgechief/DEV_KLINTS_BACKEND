"""GAP-01 Slice F — offline demo tenant seed helpers."""

from __future__ import annotations

SUPPORTED_VERTICALS = frozenset({"skincare"})

DEFAULT_VERTICAL = "skincare"
DEFAULT_TENANT_SLUG = "klints-demo-skincare"
DEFAULT_TENANT_NAME = "Klints Demo - Skincare"
DEFAULT_COMPANY_NAME = "Klints Demo Skincare Co"
DEFAULT_COMPANY_DOMAIN = "demo-skincare.klints.local"
DEFAULT_ADMIN_EMAIL = "demo@example.com"
DEFAULT_ADMIN_PASSWORD = "DemoPass123!"
DEFAULT_ADMIN_NAME = "Demo Admin"
DEFAULT_CONTACTS = 5000

# Honest stub markers — not live OAuth credentials (F0.9).
DEMO_SEED_CONFIG_MARKER = "gap01f_demo_seed"
