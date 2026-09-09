"""GAP-01 Slice F demo seed package (offline ``seed_demo_tenant``)."""

from dataruns.demo_seed.constants import (
    DEFAULT_CONTACTS,
    DEFAULT_VERTICAL,
    SUPPORTED_VERTICALS,
)
from dataruns.demo_seed.corpus import build_skincare_corpus
from dataruns.demo_seed.identity import (
    assert_email_available_for_slug,
    create_demo_identity,
    demo_tenant_slug,
    ensure_stub_connectors,
    reset_demo_tenant,
)
from dataruns.demo_seed.offline_dcs import run_offline_demo_dcs

__all__ = [
    "DEFAULT_CONTACTS",
    "DEFAULT_VERTICAL",
    "SUPPORTED_VERTICALS",
    "assert_email_available_for_slug",
    "build_skincare_corpus",
    "create_demo_identity",
    "demo_tenant_slug",
    "ensure_stub_connectors",
    "reset_demo_tenant",
    "run_offline_demo_dcs",
]
