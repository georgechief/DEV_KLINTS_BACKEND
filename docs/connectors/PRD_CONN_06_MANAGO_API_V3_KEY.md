# PRD-CONN-06 — Manago API v3 key on Connected stack

**Status:** Ready for implementation  
**Module:** see folder path  
**Depends on:** Manago connect (API v2 client id + api secret) already on `/integrations`; connector encrypt/mask helpers; DCS catalog ingest that reads `api_v3_key`  
**Surface:** **Connected stack only** (`/integrations`) — Manago.ai card, when connector is linked (`connected` / `degraded`)  
**Scope:** Let the operator paste a Manago **API v3** key (created in Manago → API access details → API v3), store it encrypted, and show it **masked** with a show/hide control after save

---

## 1. Context (what the merchant copies)

In Manago’s own UI (**API access details → API v3**), the merchant creates a key (often named like `SHOPIFY_…`). That screen shows:

- Key name  
- Token owner  
- **API key** with an eye / crossed-eye control to reveal or mask  
- Expiry / status  

Klints does **not** recreate Manago’s full key-admin table. We only need:

1. A place on **Connected stack** to paste that **API v3 key**.  
2. After save, show the stored key **masked** (same pattern as API Secret on connect), with optional reveal in the session UI.  
3. Backend stores it so DCS catalog calls (`catalogList` / PT-01 / PT-03) can use `API-KEY` without staying `UNKNOWN`.

This is **Manago API v3**, not a Shopify Admin token. Shopify OAuth remains separate on the Shopify card.

---

## 2. What exists today

### Frontend (`integrations.tsx`)

| State | Manago card |
|-------|-------------|
| Not connected | Form: Endpoint, Client ID, API Secret (`PasswordInput`) → connect |
| Connected / degraded | Stats + Remove — **no v3 key field** |

### Backend

| Piece | Today |
|-------|--------|
| Connect body | `endpoint`, `client_id`, `api_secret` → stored (secret encrypted as `api_key`) |
| Catalog client | Reads `config.api_v3_key` / `apiV3Key` for Manago v3 `API-KEY` header |
| `SECRET_CONFIG_FIELDS` | `api_key`, `access_token`, `refresh_token` — **`api_v3_key` not listed yet** |
| List/detail serializer | `masked_config(connector.config)` — will not mask v3 until field is secret-listed |
| Update API | No dedicated “set Manago v3 key” endpoint |

Without `api_v3_key`, PT-01/PT-03 Manago-catalog paths correctly stay `MISSING_INPUT` / `UNKNOWN`.

---

## 3. Goal

1. On Connected stack, **Manago card only**, when linked: show an **API v3 key** section.  
2. Empty state: input + **Save** to add the key.  
3. Saved state: show **masked** value + eye toggle (show/hide) + **Replace** / **Remove key**.  
4. Persist encrypted on `Connector.config["api_v3_key"]`.  
5. Never return the full plaintext key from list/GET APIs (mask only).  
6. Optional light validation (non-empty trim); full Manago v3 probe can be v1.1.

**Out of v1:** Managing multiple Manago v3 keys; syncing key list from Manago; Frontend SDK tab; Shopify card changes; `product_feed_url` UI (separate follow-up if needed).

---

## 4. UX (Connected stack — Manago card)

Show this block **only** when Manago connector `status ∈ {connected, degraded}` (same “linked” notion as CONN-04).

### 4.1 Empty (no v3 key stored)

```text
API v3 key
Optional — required for Manago product catalog checks (PT-01 / PT-03).
Create a key in Manago → API access details → API v3, then paste it here.

[ ••••••••••••••••••••          ]   ← PasswordInput / masked entry while typing
[ Save key ]
```

Helper copy (muted, short):

> Copy the API key from Manago **API v3** (not API v2 Client ID / Secret).

### 4.2 Saved (key present)

```text
API v3 key
[ shprt_****····  or  ****···· ]  [👁]   ← masked by default; eye toggles local reveal
[ Replace ]  [ Remove ]
```

| Control | Behavior |
|---------|----------|
| Masked display | Default. Use same mask style as `mask_api_key` (prefix + `****` when `_` present, else `****`) |
| Eye / crossed-eye | Client-only toggle between masked string from API and last plaintext the user typed **or** a one-shot reveal from a dedicated endpoint — **v1 locked:** no plaintext from GET; eye only reveals while user is **replacing** (typing new value) OR shows the **masked** server value only. Prefer: saved state shows masked from API; “Replace” opens password field; do **not** ship a “return full secret” API in v1. |
| Replace | Opens password field + Save (overwrites encrypted value) |
| Remove | Clears `api_v3_key` from config (confirm optional) |

**v1 reveal policy (locked, safest):**

- After save, UI shows **server masked** value only (no full reveal of stored secret).  
- Eye on the **input while typing** (add/replace) works like existing `PasswordInput` for API Secret.  
- Matches “show masked key as we have an option” without exposing decrypt-to-browser of the stored secret.

If product later wants true reveal-of-stored-secret, add `POST …/reveal/` with audit — **not v1**.

### 4.3 Placement

- Inside Manago card only, below bootstrap stats / health row, above Remove connector.  
- Do **not** put on Shopify card or Settings.  
- Hidden when Manago not linked.

### 4.4 Roles

Same as connect: `admin` (and `analyst` if they can manage connectors today — match existing connect permissions). Viewers: read masked presence only, no Save/Remove.

---

## 5. Data model / config

On Manago `Connector.config` (encrypted dict):

| Key | Type | Secret? | Notes |
|-----|------|---------|--------|
| `api_v3_key` | string | **Yes** | Fernet via `encrypt_config` |
| existing | `base_url`, `client_id`, `api_key` (v2 secret), … | unchanged | |

### 5.1 Crypto changes (required)

Extend `tenants/crypto.py`:

```python
SECRET_CONFIG_FIELDS = ("api_key", "access_token", "refresh_token", "api_v3_key")
```

So `encrypt_config` / `masked_config` treat `api_v3_key` like other secrets.

List/detail responses then include e.g.:

```json
"config": {
  "base_url": "https://app.manago.ai",
  "client_id": "…",
  "api_key": "****",
  "api_v3_key": "SHOPIFY_****"
}
```

Presence flag for FE (optional convenience):

```json
"has_api_v3_key": true
```

Derive as `bool(config.get("api_v3_key"))` after decrypt check, or from masked non-empty. Prefer explicit boolean on Manago connector serializer so FE does not parse mask strings.

---

## 6. API

### 6.1 Set / replace key

```http
PUT /api/v1/connectors/manago_ai/api-v3-key/
Authorization: Bearer …
Content-Type: application/json

{ "api_v3_key": "<plaintext from Manago UI>" }
```

**Behavior:**

1. Require Manago connector exists and `status ∈ {connected, degraded}` (or allow `error` so they can still attach key — **locked:** allow any status except missing connector).  
2. Trim key; reject empty → `400`.  
3. Merge into config; `encrypt_config`; save.  
4. Return masked connector slice:

```json
{
  "platform": "manago_ai",
  "has_api_v3_key": true,
  "api_v3_key_masked": "SHOPIFY_****"
}
```

5. Optional audit: `connector.updated` / `connector.manago_api_v3_key_set` (no secret in meta).

### 6.2 Remove key

```http
DELETE /api/v1/connectors/manago_ai/api-v3-key/
```

Clears `api_v3_key` from config; `has_api_v3_key: false`.

### 6.3 Read

No new GET required if connector list already returns `has_api_v3_key` + masked config. FE uses list/bootstrap card data after mutate (invalidate query).

**Never** return decrypted `api_v3_key` on GET/list.

### 6.4 Validation (v1)

| Check | Result |
|-------|--------|
| Missing / whitespace-only | `400` |
| Length absurdly short (&lt; 8) | `400` optional |
| Live Manago catalogList probe | **v1.1** — skip in v1 (store opaque; DCS will fail/UNKNOWN if bad) |

---

## 7. Frontend wiring

| File | Change |
|------|--------|
| `src/routes/integrations.tsx` | Manago linked card: API v3 key section (§4) |
| `src/lib/connectors.ts` | `setManagoApiV3Key(key)`, `removeManagoApiV3Key()` |
| Password / eye | Reuse existing password input component used for API Secret |

Flow:

1. Load connectors → if Manago linked and `!has_api_v3_key` → empty form.  
2. Save → PUT → toast success → show masked.  
3. Replace → local password field → PUT.  
4. Remove → DELETE → confirm → empty form.

Do not ask for v3 key on **initial** connect form (v2 Client ID / Secret stay as today). Add only after connected — keeps connect simple; matches “on Connected stack only” for the v3 field.

---

## 8. Downstream (no extra work in this PRD)

Existing ingest already:

```text
config.api_v3_key → Manago catalogList API-KEY
```

After key is saved, next DCS fresh-import / bootstrap that pulls catalog can use it. This PRD does **not** require auto-re-bootstrap on save; optional “Refresh data” if a fetch button already exists.

---

## 9. Acceptance

1. Connected Manago card shows API v3 key block; Shopify card does not.  
2. Disconnected Manago card does not show the block.  
3. Save non-empty key → encrypted in DB; list API shows masked / `has_api_v3_key: true`; plaintext never in list JSON.  
4. UI after save shows masked value; typing field uses show/hide like API Secret.  
5. Replace overwrites previous key.  
6. Remove clears key; FE returns to empty state.  
7. `SECRET_CONFIG_FIELDS` includes `api_v3_key`; unit tests for encrypt/mask.  
8. Viewer cannot PUT/DELETE (match connector permission rules).  
9. Audit/meta never logs full key.

---

## 10. Files to change

| Area | File |
|------|------|
| BE | `tenants/crypto.py` — add `api_v3_key` to secrets |
| BE | `tenants/connector_views.py` (+ urls) — PUT/DELETE api-v3-key |
| BE | Connector list serializer — `has_api_v3_key` |
| BE | `tenants/tests/test_manago_api_v3_key.py` |
| FE | `integrations.tsx` — Manago card UI |
| FE | `lib/connectors.ts` — API helpers |
| Audit | Register action if emitting `connector.manago_api_v3_key_set` |

---

## 11. Copy reference (short)

| Element | Copy |
|---------|------|
| Section title | API v3 key |
| Helper | Create a key in Manago → API access details → API v3, then paste it here. |
| Empty CTA | Save key |
| Saved actions | Replace · Remove |
| Error empty | Enter an API v3 key. |

---

## 12. Handoff note for Engineering

1. Surface is **Connected stack / Manago only** — not Settings, not Shopify.  
2. Key comes from Manago’s **API v3** tab (screenshot reference); name may look like `SHOPIFY_…` — still a Manago key.  
3. Store as `api_v3_key`; mask like other secrets; no plaintext GET in v1.  
4. Eye control = password-field reveal while editing; saved state shows masked from API.  
5. Unblocks catalog DCS paths that already look for this config field.
