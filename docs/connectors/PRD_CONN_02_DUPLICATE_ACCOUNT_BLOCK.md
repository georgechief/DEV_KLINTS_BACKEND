# PRD-CONN-02 — Block duplicate Shopify / Manago account connect

**Status:** Ready for implementation  
**Depends on:** existing Manago create + Shopify OAuth (`tenants/connector_views.py`)  
**Repos:** FE onboarding + integrations connect flows  
**Scope:** backend uniqueness checks + clear API errors; FE surfaces the message

## 1. Problem

Today uniqueness is only **per company + connector name**:

```text
UniqueConstraint(fields=["company", "name"])  # tenants.models.Connector
```

That means:

- Company A can connect `acme.myshopify.com`
- Company B can also connect `acme.myshopify.com` (same physical Shopify store)

Same risk for Manago: two Klints companies can store the same Manago `workspace_id` / `client_id`.

We need **global account ownership**: one Shopify shop (or Manago account) may belong to at most one Klints company at a time.

## 2. Goal

From **onboarding** or **integrations**, when a user tries to connect Shopify or Manago:

1. Detect if that external account is already connected to **any** company in Klints.
2. If yes → **block** the connect (do not create/update connector, do not enqueue bootstrap).
3. Return a clear error telling them to disconnect elsewhere or use a different account.

Same-company reconnect (Shopify OAuth refresh for the company’s own connector) remains allowed.

## 3. Identity keys (source of truth)

| Platform | Canonical external key | Where stored today |
|----------|------------------------|--------------------|
| Shopify | Normalized `shop_domain` (e.g. `acme.myshopify.com`) | Encrypted `Connector.config` + plaintext `ConnectorSnapshot.snapshot_data.shop_domain` / `shop_id` |
| Shopify (secondary) | `shop_id` (Shopify numeric id) | Same snapshot/config |
| Manago | `workspace_id` (primary) | Snapshot + encrypted config |
| Manago (secondary) | `client_id` if stored separately from workspace | Verify payload / config |

**Lookup rule**

- Prefer **snapshot plaintext** fields for search (avoid decrypting every connector).
- Fallback: decrypt `config` only if snapshot missing (legacy rows).

Normalize before compare:

- Shopify: `tenants.shopify.normalize_shop_domain(shop)`
- Manago: strip + case-sensitive as Manago returns (do not lowercase workspace ids unless product confirms)

## 4. When to check

### 4.1 Manago — `POST /api/v1/connectors/`

File: `tenants/connector_views.py` → `ConnectorListCreateView.post`

Current behavior already blocks **same company** second Manago:

```text
409 {"detail": "Connector already connected."}
```

Add **cross-company** check **before** `Connector.objects.create`:

```text
If any other company has name=manago_ai AND status in {connected, degraded}
   AND (snapshot.workspace_id == incoming OR config.workspace_id == incoming)
→ 409 ACCOUNT_ALREADY_CONNECTED
```

Also run the check in `POST /api/v1/connectors/verify/` optionally as soft warning; **hard block remains on create**.

### 4.2 Shopify — OAuth start + callback

**Start** `POST /api/v1/connectors/shopify/start/`

- After normalizing `shop`, check global ownership.
- If owned by **another** company → `409` (do not return authorize URL).
- If owned by **this** company → allow (reconnect).
- If unowned → allow.

**Callback** `GET /api/v1/connectors/shopify/callback/`

- Re-check after token exchange / `fetch_shop` (authoritative `shop` + `shop_id`).
- If another company owns it → redirect FE with error query params (callback is unauthenticated browser redirect):

```text
?shopify=error&reason=account_already_connected
```

- Do **not** `update_or_create` connector or enqueue bootstrap.

FE already maps `reason` via `shopifyErrorReasonMessage` (`klints_frontend/src/lib/connectors.ts`) — add the new reason string.

## 5. API error contract

### JSON endpoints (Manago create, Shopify start)

HTTP **409 Conflict**

```json
{
  "detail": "This Shopify account is already connected in Klints. Disconnect it from the other workspace, or connect a different store.",
  "code": "account_already_connected",
  "platform": "shopify",
  "external_key": "acme.myshopify.com"
}
```

Manago example:

```json
{
  "detail": "This Manago account is already connected in Klints. Disconnect it from the other workspace, or connect a different account.",
  "code": "account_already_connected",
  "platform": "manago_ai",
  "external_key": "<workspace_id>"
}
```

Do **not** leak the other company’s name, tenant slug, or user emails.

### Shopify callback redirect

```text
{FRONTEND_SHOPIFY_REDIRECT_URL or return_to}
  ?shopify=error
  &reason=account_already_connected
```

FE copy (suggested):

> This Shopify store is already connected to another Klints workspace. Disconnect it there, or connect a different store.

## 6. Allowed vs blocked matrix

| Scenario | Result |
|----------|--------|
| Company A connects shop X (first time) | Allow |
| Company A reconnects shop X (OAuth again) | Allow (own connector) |
| Company B tries shop X while A still connected | **Block 409 / callback error** |
| Company A disconnects shop X, then B connects X | Allow |
| Company A has `status=error` or deleted connector for X | Treat as free (only `connected` / `degraded` count as owners) |
| Same company tries second Manago row | Keep existing 409 “Connector already connected.” |

**Owner statuses that block others:** `connected`, `degraded`  
**Statuses that do not block:** `error`, missing row, or hard-deleted connector

## 7. Implementation guidance (backend)

### 7.1 Helper module

Add something like:

`tenants/connector_uniqueness.py`

```python
def find_shopify_owner(*, shop_domain: str, shop_id=None) -> Connector | None: ...
def find_manago_owner(*, workspace_id: str) -> Connector | None: ...

def assert_external_account_available(
    *,
    platform: str,
    external_key: str,
    company: Company,
    shop_id=None,
) -> None:
    """Raise AccountAlreadyConnectedError if owned by another company."""
```

Query strategy (efficient):

1. Filter `Connector` by `name=platform` and `status__in=["connected", "degraded"]`.
2. Join latest `ConnectorSnapshot` per connector (or filter `snapshot_data__shop_domain` / `snapshot_data__workspace_id` if Postgres JSON lookup is acceptable).
3. Exclude `company_id=current`.
4. If match → raise.

Index note (optional follow-up migration): if JSON lookups are slow, add denormalized columns:

- `Connector.external_account_key` (CharField, unique where not null)
- Set on create/update/disconnect clear

For MVP, snapshot JSON lookup + tests is enough if connector volume is low.

### 7.2 Wire into views

| View | Change |
|------|--------|
| `ConnectorListCreateView.post` | Call uniqueness before create |
| `ShopifyOAuthStartView.post` | Call uniqueness after normalize shop |
| `ShopifyOAuthCallbackView.get` | Call uniqueness after `fetch_shop`, before `update_or_create` |

### 7.3 Disconnect clears ownership

`DELETE /api/v1/connectors/{id}/` already deletes the row (`ConnectorDestroyView`). After delete, the external key is free. No extra work if ownership is derived from live rows.

## 8. Frontend guidance

| Surface | Behavior |
|---------|----------|
| Onboarding Manago submit | Show API `detail` toast / inline error on 409 |
| Onboarding Shopify start | Same |
| Integrations connect | Same |
| Shopify return `reason=account_already_connected` | Toast via `shopifyErrorReasonMessage` |

Files:

- `klints_frontend/src/routes/onboarding.tsx`
- `klints_frontend/src/routes/integrations.tsx`
- `klints_frontend/src/lib/connectors.ts`

## 9. Files to change

| File | Change |
|------|--------|
| `tenants/connector_uniqueness.py` | New helpers + exception |
| `tenants/connector_views.py` | Manago create, Shopify start/callback |
| `tenants/tests/test_connector_uniqueness.py` | New acceptance tests |
| `klints_frontend/src/lib/connectors.ts` | Map new Shopify reason |
| FE onboarding/integrations | Surface 409 detail |

## 10. Acceptance tests

1. Company A connects Shopify `acme.myshopify.com` → OK.  
2. Company B `shopify/start` with same shop → **409** `account_already_connected`.  
3. Company B completes OAuth somehow → callback redirects `reason=account_already_connected`, no connector created for B.  
4. Company A disconnects → Company B can connect.  
5. Company A reconnects own shop → OK (bootstrap supersede rules from CONN-01 still apply).  
6. Same for Manago `workspace_id` across two companies.  
7. Error body never includes other tenant/company identifiers.

## 11. Out of scope

- Transferring a shop between companies with admin approval UI  
- Multi-shop per company  
- Manago endpoint URL uniqueness (only workspace/client identity)
