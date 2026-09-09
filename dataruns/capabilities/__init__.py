"""Capability Matrix registry (PRD-CAP-01).

v1: file seed + registry loader. Writebacks stay separate (option B).
"""

from dataruns.capabilities.contract import (  # noqa: F401
    CAP_ID_HUMAN_WORKFLOW_BUILD,
    CAP_ID_MCP_WORKFLOW_PUBLISH,
    CAP_ID_MCP_WORKFLOW_UPSERT,
    CAP_ID_RESTV2_WORKFLOW_LIST,
    PACKAGE_ROUTE_HUMAN_FALLBACK,
    PACKAGE_ROUTE_MCP,
    status_allows_mcp_write,
    upsert_is_execute_eligible,
)
from dataruns.capabilities.registry import (  # noqa: F401
    clear_matrix_registry_cache,
    get_capability,
    get_matrix_source,
    list_capabilities,
    matrix_seed_path,
)
from dataruns.capabilities.resolver import (  # noqa: F401
    CapabilityResolveOutcome,
    resolve_blueprint_capabilities,
    resolve_capabilities,
    resolve_dependency,
    resolve_package_route,
)
