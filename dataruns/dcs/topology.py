"""FD-06 Manago topology — Excel sheet 02/03/05 account map.

Enumerate Manago accounts/sub-accounts (owners + endpoint), classify
relationships, and expose a registry for foundation gate FD-06 / RC-11.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from tenants.manago import list_users_by_client
from tenants.manago_fetch import ManagoFetchError, resolve_manago_credentials
from tenants.manago_topology_service import preferred_owner_from_config

TopologyClass = Literal[
    "geo_variant",
    "independent_business_line",
    "segment_variant",
    "single_account",
    "unknown",
]

VALID_MULTI_CLASSES = frozenset(
    {
        "geo_variant",
        "independent_business_line",
        "segment_variant",
    }
)


def empty_topology_registry() -> dict[str, Any]:
    """Canonical empty account map for run_snapshot / gate_inputs."""
    return {
        "schema_version": "1.0.0",
        "source": "manago_ai",
        "as_of": None,
        "client_id": None,
        "endpoint": None,
        "accounts": [],
        "classified": False,
        "topology_ok": False,
        "error": None,
    }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _normalize_class(value: Any) -> TopologyClass:
    if not isinstance(value, str):
        return "unknown"
    raw = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "geo": "geo_variant",
        "geo_variant": "geo_variant",
        "geovariant": "geo_variant",
        "independent": "independent_business_line",
        "independent_business_line": "independent_business_line",
        "business_line": "independent_business_line",
        "segment": "segment_variant",
        "segment_variant": "segment_variant",
        "single": "single_account",
        "single_account": "single_account",
    }
    return aliases.get(raw, "unknown")  # type: ignore[return-value]


def _config_topology_accounts(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Onboarding-supplied account map (Excel suggested fix)."""
    topology = config.get("topology")
    if isinstance(topology, dict):
        accounts = topology.get("accounts")
        if isinstance(accounts, list):
            return [a for a in accounts if isinstance(a, dict)]
    accounts = config.get("topology_accounts")
    if isinstance(accounts, list):
        return [a for a in accounts if isinstance(a, dict)]
    return []


_MULTI_OWNER_PRIMARY_REQUIRED = (
    "Multiple Manago owners — select a primary owner before scoring "
    "(Connected stack → Manago owners)."
)


def _configured_accounts_for_primary(
    *,
    unique_owners: list[str],
    configured: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """When only config.owner is set, scope FD-06 + fetch to that primary."""
    if configured:
        return configured
    preferred = preferred_owner_from_config(config)
    if not preferred or len(unique_owners) <= 1:
        return configured
    if not any(owner.lower() == preferred.lower() for owner in unique_owners):
        return configured
    return [
        {
            "owner": owner,
            "in_scope": owner.lower() == preferred.lower(),
            "classification": (
                "single_account"
                if owner.lower() == preferred.lower()
                else "unknown"
            ),
            "label": (
                "primary" if owner.lower() == preferred.lower() else "out_of_scope"
            ),
        }
        for owner in unique_owners
    ]


def _needs_primary_owner_selection(
    *,
    unique_owners: list[str],
    configured: list[dict[str, Any]],
    config: dict[str, Any],
) -> bool:
    if len(unique_owners) <= 1:
        return False
    if preferred_owner_from_config(config):
        return False
    in_scope = [row for row in configured if row.get("in_scope", True)]
    if configured and len(in_scope) == 1:
        return False
    return True


def _config_default_classification(config: dict[str, Any]) -> TopologyClass:
    topology = config.get("topology")
    if isinstance(topology, dict) and topology.get("classification"):
        return _normalize_class(topology.get("classification"))
    if config.get("topology_classification"):
        return _normalize_class(config.get("topology_classification"))
    return "unknown"


@dataclass
class TopologyLoadResult:
    registry: dict[str, Any]
    topology_ok: bool
    topology_accounts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "topology_ok": self.topology_ok,
            "topology_accounts": self.topology_accounts,
            "topology_registry": self.registry,
            "topology_error": self.error,
        }


def _account_node(
    *,
    account_id: str,
    owner: str | None,
    endpoint: str,
    parent_account_id: str | None = None,
    classification: TopologyClass = "unknown",
    label: str | None = None,
    locale: str | None = None,
    shop_domain: str | None = None,
    in_scope: bool = True,
    kind: str = "manago_owner",
) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "owner": owner,
        "endpoint": endpoint,
        "parent_account_id": parent_account_id,
        "classification": classification,
        "label": label,
        "locale": locale,
        "shop_domain": shop_domain,
        "in_scope": bool(in_scope),
        "kind": kind,
    }


def _merge_onboarding(
    *,
    enumerated: list[dict[str, Any]],
    configured: list[dict[str, Any]],
    default_class: TopologyClass,
    endpoint: str,
    client_id: str,
) -> list[dict[str, Any]]:
    """Overlay onboarding classification / labels onto enumerated owners."""
    by_owner: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for row in configured:
        owner = str(row.get("owner") or "").strip().lower()
        account_id = str(row.get("account_id") or "").strip()
        if owner:
            by_owner[owner] = row
        if account_id:
            by_id[account_id] = row

    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_owners: set[str] = set()
    for node in enumerated:
        owner_key = str(node.get("owner") or "").strip().lower()
        cfg = by_owner.get(owner_key) or by_id.get(str(node.get("account_id") or ""))
        if cfg:
            node = {
                **node,
                "classification": _normalize_class(
                    cfg.get("classification") or default_class
                ),
                "label": cfg.get("label") or node.get("label"),
                "locale": cfg.get("locale") or node.get("locale"),
                "shop_domain": cfg.get("shop_domain") or node.get("shop_domain"),
                "parent_account_id": cfg.get("parent_account_id", node.get("parent_account_id")),
                "in_scope": bool(cfg.get("in_scope", True)),
                "endpoint": str(cfg.get("endpoint") or node.get("endpoint") or endpoint),
            }
        elif default_class != "unknown":
            node = {**node, "classification": default_class}
        seen_ids.add(str(node["account_id"]))
        if owner_key:
            seen_owners.add(owner_key)
        merged.append(node)

    # Configured accounts not returned by API still count (Excel: sub-accounts in scope).
    for cfg in configured:
        owner = str(cfg.get("owner") or "").strip()
        owner_key = owner.lower()
        account_id = str(cfg.get("account_id") or "").strip() or owner
        if not account_id:
            continue
        # Already overlaid onto an enumerated owner/node — do not duplicate.
        if account_id in seen_ids or (owner_key and owner_key in seen_owners):
            continue
        merged.append(
            _account_node(
                account_id=account_id,
                owner=owner or None,
                endpoint=str(cfg.get("endpoint") or endpoint),
                parent_account_id=cfg.get("parent_account_id") or client_id,
                classification=_normalize_class(
                    cfg.get("classification") or default_class
                ),
                label=cfg.get("label"),
                locale=cfg.get("locale"),
                shop_domain=cfg.get("shop_domain"),
                in_scope=bool(cfg.get("in_scope", True)),
                kind="manago_sub_account",
            )
        )
        seen_ids.add(account_id)
        if owner_key:
            seen_owners.add(owner_key)
    return merged


def evaluate_topology_ok(accounts: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """
    Excel FD-06 / RC-11 rules.

    - Need ≥1 in-scope account with owner + endpoint.
    - Multiple in-scope accounts require an Excel relationship class on each
      (geo_variant / independent_business_line / segment_variant).
    - Single in-scope account is OK without multi-class (no cross-account mix).
    """
    in_scope = [a for a in accounts if a.get("in_scope", True)]
    if not in_scope:
        return False, "No Manago accounts are marked as in use for this company."

    for account in in_scope:
        if not str(account.get("owner") or "").strip():
            return False, "A Manago account is missing its owner email."
        if not str(account.get("endpoint") or "").strip():
            return False, "A Manago account is missing its connection endpoint."

    if len(in_scope) == 1:
        return True, None

    for account in in_scope:
        classification = _normalize_class(account.get("classification"))
        if classification not in VALID_MULTI_CLASSES:
            return (
                False,
                "Several Manago accounts are linked, but their relationship isn't "
                "set yet. Tell Klints how they relate (same brand in different "
                "regions, separate businesses, or audience segments) so data "
                "from each account stays separate.",
            )
    return True, None


def load_manago_topology(
    *,
    config: dict[str, Any],
    shopify_shop_domain: str | None = None,
    timeout: float = 15.0,
) -> TopologyLoadResult:
    """
    Enumerate Manago owners via ``api/user/listByClient``, merge onboarding
    classification, optionally attach Shopify storefront domain.
    """
    registry = empty_topology_registry()
    registry["as_of"] = _utcnow_iso()

    try:
        endpoint, client_id, api_secret = resolve_manago_credentials(config)
    except ManagoFetchError as exc:
        registry["error"] = str(exc)
        return TopologyLoadResult(
            registry=registry,
            topology_ok=False,
            error=str(exc),
        )

    registry["client_id"] = client_id
    registry["endpoint"] = endpoint
    default_class = _config_default_classification(config)
    configured = _config_topology_accounts(config)

    try:
        data = list_users_by_client(
            client_id=client_id,
            api_secret=api_secret,
            endpoint=endpoint,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 — surface as topology FAIL
        registry["error"] = f"Manago listByClient failed: {exc}"
        return TopologyLoadResult(
            registry=registry,
            topology_ok=False,
            error=registry["error"],
        )

    if data.get("success") is False:
        message = data.get("message") or "Manago listByClient rejected credentials."
        registry["error"] = str(message)
        return TopologyLoadResult(
            registry=registry,
            topology_ok=False,
            error=registry["error"],
        )

    owners: list[str] = []
    users = data.get("users")
    if isinstance(users, list):
        for user in users:
            if isinstance(user, str) and user.strip():
                owners.append(user.strip())
            elif isinstance(user, dict):
                email = user.get("email") or user.get("owner") or user.get("login")
                if isinstance(email, str) and email.strip():
                    owners.append(email.strip())

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_owners: list[str] = []
    for owner in owners:
        key = owner.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_owners.append(owner)

    if _needs_primary_owner_selection(
        unique_owners=unique_owners,
        configured=configured,
        config=config,
    ):
        registry["error"] = _MULTI_OWNER_PRIMARY_REQUIRED
        return TopologyLoadResult(
            registry=registry,
            topology_ok=False,
            error=_MULTI_OWNER_PRIMARY_REQUIRED,
        )

    configured = _configured_accounts_for_primary(
        unique_owners=unique_owners,
        configured=configured,
        config=config,
    )

    # Fallback: stored owner on connector config.
    if not unique_owners:
        for key in ("owner", "owner_email"):
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                unique_owners.append(value.strip())
                break

    enumerated: list[dict[str, Any]] = []
    for owner in unique_owners:
        enumerated.append(
            _account_node(
                account_id=f"{client_id}:{owner.lower()}",
                owner=owner,
                endpoint=endpoint,
                parent_account_id=client_id if len(unique_owners) > 1 else None,
                classification=(
                    "single_account"
                    if len(unique_owners) == 1 and default_class == "unknown"
                    else default_class
                ),
                kind="manago_owner",
            )
        )

    # Root client node when we have owners (parent for sub-accounts).
    if unique_owners:
        root = _account_node(
            account_id=client_id,
            owner=unique_owners[0],
            endpoint=endpoint,
            parent_account_id=None,
            classification=(
                "single_account"
                if len(unique_owners) == 1 and default_class == "unknown"
                else default_class
            ),
            label="client",
            kind="manago_client",
            in_scope=len(unique_owners) == 1,  # multi-owner: score via owner nodes
        )
        # Prefer owner nodes as in-scope leaves; root only when single owner.
        if len(unique_owners) == 1:
            enumerated = [root]
        else:
            enumerated = [root, *enumerated]

    accounts = _merge_onboarding(
        enumerated=enumerated,
        configured=configured,
        default_class=default_class,
        endpoint=endpoint,
        client_id=client_id,
    )

    if shopify_shop_domain and accounts:
        # Excel optional Shopify Plus surface — attach storefront to primary node.
        primary = next((a for a in accounts if a.get("in_scope")), accounts[0])
        if not primary.get("shop_domain"):
            primary["shop_domain"] = shopify_shop_domain

    ok, error = evaluate_topology_ok(accounts)
    registry["accounts"] = accounts
    registry["classified"] = ok and (
        len([a for a in accounts if a.get("in_scope", True)]) == 1
        or all(
            _normalize_class(a.get("classification")) in VALID_MULTI_CLASSES
            for a in accounts
            if a.get("in_scope", True)
        )
    )
    registry["topology_ok"] = ok
    registry["error"] = error

    return TopologyLoadResult(
        registry=registry,
        topology_ok=ok,
        topology_accounts=accounts,
        error=error,
    )
