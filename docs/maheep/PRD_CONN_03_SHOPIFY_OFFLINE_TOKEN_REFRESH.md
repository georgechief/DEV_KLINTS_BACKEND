# PRD-CONN-03 — Shopify offline access token refresh in Celery jobs

**Status:** Implemented (happy path); failure-state patch in [PRD-CONN-05](./PRD_CONN_05_SHOPIFY_TOKEN_REFRESH_FAILURE_HANDLING.md)  
**Depends on:** Shopify OAuth connect (`tenants/shopify.py`, CONN-01 bootstrap)  
**Blocks:** Reliable daily DCS / long-running bootstrap once Shopify issues **expiring** offline tokens  
**Shopify docs:** [About offline access tokens](https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/offline-access-tokens)

## 1. Problem

Klints stores a Shopify Admin API token on `Connector.config` (Fernet-encrypted) after OAuth:

```text
access_token, shop_domain, shop_id, scopes, api_version, ...
```

Today `exchange_code_for_token` only persists `access_token` + `scope` — it does **not** request or store:

- `expires_in` / access token expiry  
- `refresh_token`  
- `refresh_token_expires_in`

Shopify now supports **expiring offline access tokens** (default path evolving for public apps). Background Celery jobs (bootstrap, daily DCS) must refresh expired tokens **without** a merchant in the browser, then **save** the new token so the rest of that run uses it.

Reference behavior ([Shopify offline tokens](https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/offline-access-tokens)):

- Access token short-lived (example response `expires_in: 3600`)  
- Refresh token ~90 days (`refresh_token_expires_in: 7776000`)  
- Refresh via `grant_type=refresh_token`  
- Persist new access + refresh tokens on each refresh  

## 2. Goal

1. On OAuth token exchange, request **expiring offline** tokens (`expiring=1`) and persist refresh metadata on the connector.  
2. At the start of Celery jobs that call Shopify (bootstrap today; DCS later), **ensure a valid access token** for that tenant’s Shopify connector.  
3. If expired / near expiry → refresh, encrypt+save to DB, continue the **same** run with the new token.  
4. If refresh fails → mark auth failure (same as CONN-01 `AUTH_FAILED` path); do not proceed with a dead token.

## 3. Important note on “async / await”

This codebase’s Celery workers are **sync prefork** (`celery -A core worker`), and Shopify helpers use **sync** `urllib` (`tenants/shopify.py`).

**Implementation rule (locked):**

- Implement token refresh as a **normal sync Python function** (same style as `exchange_code_for_token`).  
- Call it **synchronously** at the top of Celery tasks (before `run_import` / Shopify API use).  
- Do **not** require `async def` / `await` inside Celery tasks unless the project later migrates to asyncio workers.

If a contributor adds an `async def refresh_shopify_offline_token(...)` for reuse, the Celery entrypoint must call it via a single documented bridge (e.g. `asyncio.run(...)`) — preferred path is **sync-only** to match existing `tenants/shopify.py`.

“Async” in product language here means: **runs in Celery, not in the HTTP request.**

## 4. Config shape (encrypted `Connector.config`)

Extend Shopify connector config:

```json
{
  "shop_domain": "acme.myshopify.com",
  "shop_id": 123,
  "shop_name": "Acme",
  "scopes": "read_customers,read_orders,...",
  "api_version": "2026-01",
  "access_token": "shpat_...",
  "access_token_expires_at": "2026-07-29T12:00:00+00:00",
  "refresh_token": "shprt_...",
  "refresh_token_expires_at": "2026-10-27T12:00:00+00:00",
  "token_mode": "offline_expiring"
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `access_token` | yes | Current Admin API token |
| `access_token_expires_at` | when expiring | ISO-8601 UTC |
| `refresh_token` | when expiring | Store encrypted with config |
| `refresh_token_expires_at` | when expiring | ISO-8601 UTC |
| `token_mode` | yes | `offline_expiring` \| `offline_non_expiring` |

**Legacy connectors** with only `access_token` and no expiry → `token_mode=offline_non_expiring`; skip refresh until re-OAuth or migration exchange.

Snapshot (`ConnectorSnapshot.snapshot_data`) must **never** store raw `access_token` / `refresh_token` (keep current pattern: metadata only).

## 5. OAuth acquire (update existing exchange)

### 5.1 Authorization code → token

File: `tenants/shopify.py` → `exchange_code_for_token`

POST `https://{shop}/admin/oauth/access_token` body:

```text
client_id, client_secret, code
expiring=1
```

Parse response:

```json
{
  "access_token": "shpat_...",
  "expires_in": 3600,
  "refresh_token": "shprt_...",
  "refresh_token_expires_in": 7776000,
  "scope": "..."
}
```

Compute:

```text
access_token_expires_at = now + expires_in seconds
refresh_token_expires_at = now + refresh_token_expires_in seconds
token_mode = offline_expiring
```

If Shopify returns a non-expiring token (no `expires_in` / no refresh) → store as `offline_non_expiring` (backward compatible).

### 5.2 Callback persistence

`ShopifyOAuthCallbackView` already builds `config` dict — add the new fields before `encrypt_config`.

## 6. Refresh API helper

Add in `tenants/shopify.py`:

```python
def refresh_offline_access_token(
    *,
    shop: str,
    refresh_token: str,
    timeout: float = 15.0,
) -> ShopifyTokenBundle:
    """
    POST grant_type=refresh_token
    https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/offline-access-tokens
    """
```

Request form body:

```text
client_id={SHOPIFY_API_KEY}
client_secret={SHOPIFY_API_SECRET}
grant_type=refresh_token
refresh_token={refresh_token}
```

Return access_token, refresh_token, expires_in, refresh_token_expires_in, scope.

**Retry:** on network/`5xx`/`429`, retry same `refresh_token` (Shopify allows retry window). On definitive `401 invalid_request` / inactive refresh → raise `ShopifyOAuthError` → connector needs re-auth.

## 7. Ensure-fresh helper (called from Celery)

Add e.g. `dataruns/connectors/shopify_token.py` or `tenants/shopify_tokens.py`:

```python
def ensure_fresh_shopify_token(*, connector: Connector, skew_seconds: int = 120) -> dict:
    """
    Load encrypted config. If offline_expiring and access token expired
    (or expires within skew), refresh, save connector.config, return plain config.
    """
```

Algorithm:

```text
1. config = decrypt(connector.config)
2. if platform is not shopify → return config
3. if token_mode != offline_expiring or no refresh_token:
     return config  # legacy non-expiring
4. if refresh_token_expires_at <= now:
     raise AuthExpiredError  # merchant must reconnect
5. if access_token_expires_at > now + skew:
     return config  # still valid
6. call refresh_offline_access_token(shop, refresh_token)
7. update config fields; encrypt_config; connector.save(update_fields=["config", "updated_at"])
8. optional: ConnectorSnapshot metadata-only version bump (no secrets)
9. return new plain config
```

Use **select_for_update** / atomic update when refreshing to avoid two workers refreshing the same connector simultaneously (daily Beat + manual fetch).

## 8. Where to call (existing Celery jobs)

### 8.1 `dataruns.bootstrap_connector_fetch` (required)

File: `dataruns/tasks.py`

After loading connector for `platform == "shopify"`, **before** preflight / `run_import`:

```text
config = ensure_fresh_shopify_token(connector=connector)
# use returned config for preflight + pass through import
```

If refresh raises → `_fail_bootstrap_preflight` / `AUTH_FAILED` + email (existing path).

### 8.2 Future `dataruns.run_dcs_score` (required when DCS-01 lands)

At worker start, if company has Shopify connected → `ensure_fresh_shopify_token` before FD-02 live probe / any Shopify reads.

### 8.3 Manual fetch

Same bootstrap task path already covers `POST .../shopify/fetch/`.

## 9. Migration of existing installs (optional phase)

Per Shopify docs, non-expiring → expiring can use token exchange with `expiring=1`.  

**v1 of this PRD:**  

- New OAuth installs request `expiring=1`.  
- Legacy non-expiring keep working until merchant reconnects **or** a follow-up migration task runs.  

Do not silently revoke non-expiring tokens in v1 without a migration job.

## 10. Files to change

| File | Change |
|------|--------|
| `tenants/shopify.py` | `expiring=1` on code exchange; `refresh_offline_access_token`; richer token dataclass |
| `tenants/connector_views.py` | Persist expiry/refresh fields on callback |
| `dataruns/connectors/shopify_token.py` (new) | `ensure_fresh_shopify_token` |
| `dataruns/tasks.py` | Call ensure at start of Shopify bootstrap |
| `dataruns/dcs/...` / `run_dcs_score` | Call ensure when DCS worker exists |
| `tenants/tests/test_shopify_token_refresh.py` | Exchange parse, refresh, skew, legacy skip, save-to-DB |
| `tenants/tests/test_connector_bootstrap.py` | Bootstrap uses refreshed token when expired |

## 11. Acceptance

1. New Shopify OAuth stores `refresh_token` + expiry fields when Shopify returns them.  
2. Bootstrap with expired access token + valid refresh → refreshes, saves DB, import succeeds with new token.  
3. Bootstrap with expired refresh → failed bootstrap, `AUTH_FAILED`, connector `error`/`degraded` per existing rules, admin email.  
4. Legacy connector without refresh fields → no refresh attempted; existing token used.  
5. Two concurrent workers do not corrupt config (one refresh wins).  
6. Secrets never appear in snapshots, logs, or health_report.

## 12. Out of scope

- Online (session) access tokens  
- FE UI for “token expires in …”  
- Automatic migration of all legacy tokens via token exchange (phase 2)  
- Manago token refresh (different auth model)
