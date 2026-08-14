# PRD-CONN-05 — Patch: Shopify offline token refresh failure handling

**Status:** Ready for implementation  
**Module:** see folder path  
**Depends on:** [PRD-CONN-03](./PRD_CONN_03_SHOPIFY_OFFLINE_TOKEN_REFRESH.md) (shipped: `ensure_fresh_shopify_token`, `refresh_offline_access_token`, OAuth `expiring=1`)  
**Related:** CONN-01 bootstrap `AUTH_FAILED`; DCS-07 daily beat eligibility; AUDIT-01 `connector.*` events; CONN-04 Integrations card status  
**Scope:** improve **existing** refresh helpers — do **not** rebuild OAuth or the happy-path refresh algorithm  
**Shopify docs:** [About offline access tokens](https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/offline-access-tokens)

## 1. What already works (CONN-03 — keep)

For `token_mode=offline_expiring`, Celery jobs already call `ensure_fresh_shopify_token`:

```text
access expired (or within 120s skew)
  + refresh_token present
  + refresh_token_expires_at > now
  → POST grant_type=refresh_token
  → save new access_token + refresh_token (+ expiries)
  → continue same job
```

**Expected happy path (must keep passing):**

| Input | Outcome |
|-------|---------|
| Access expired, refresh still valid at Shopify | Refresh succeeds; config updated; import/DCS continues |
| Access still valid (outside skew) | No network refresh; return current config |
| Legacy `offline_non_expiring` / no refresh fields | Skip refresh; use stored access token |

This is correct and already implemented in:

- `tenants/shopify.py` → `refresh_offline_access_token`, inactive-401 detection  
- `dataruns/connectors/shopify_token.py` → `ensure_fresh_shopify_token` (`select_for_update`)  
- Bootstrap: `dataruns/tasks.py` → `_ensure_shopify_token_for_bootstrap`  
- DCS: `dataruns/dcs/fresh_import.py` → `_ensure_shopify_token` before re-import  

**Do not rewrite these.** Patch call-site failure handling and connector state.

## 2. Problem (production gap)

Observed on Lumera / `klints-dev.myshopify.com` (daily beat 2026-08-02 15:00 IST, DataRun #66):

```json
{
  "token_mode": "offline_expiring",
  "access_token_expires_at": "2026-08-01T05:54:58.559891+00:00",
  "refresh_token_expires_at": "2026-10-30T04:54:58.559891+00:00",
  "shop_domain": "klints-dev.myshopify.com"
}
```

- Access token is **expired** → refresh path correctly runs.  
- Refresh token is **not** past our stored `refresh_token_expires_at`.  
- Shopify returns **401** `invalid_request` / refresh_token **inactive** (revoked, rotated-and-lost, app reinstall, merchant revoke, etc.).  
- We raise `ShopifyAuthExpiredError` / `ShopifyOAuthError` → DCS DataRun **failed**.  

**Gap:** connector `status` stays `connected`. Daily beat (DCS-07) still treats the company as eligible → every 15:00 IST re-fails the same way. Integrations UI still looks connected (CONN-04). No durable “reconnect Shopify” signal.

CONN-03 §2.4 / §11.3 already said: on refresh failure → `AUTH_FAILED` and connector `error`/`degraded`. **Bootstrap roughly does this; DCS fresh-import does not.**

## 3. Goal

1. Keep happy-path refresh unchanged for expired access + **live** refresh token.  
2. On **terminal** auth failures (inactive/expired refresh, definitive 401), **persist connector failure state** so beat stops looping and UI shows reconnect.  
3. Align DCS and bootstrap: same terminal classification + same connector update helper.  
4. Emit an audit event when Shopify auth dies so Activity / notifications (AUDIT-01/02) surface it.  
5. **Email the account owner(s)** that Shopify must be reconnected (same Mailer path as bootstrap/DCS emails).  
6. Optional small hardening: after a successful refresh, assert new `refresh_token` was persisted (rotation); never leave old refresh in DB if Shopify returned a new one.

**Out of v1:** FE “token expires in…” countdown; automatic OAuth without merchant; Manago token refresh; migrating non-expiring tokens.

## 4. Terminal vs retryable failures

Classify inside / next to existing helpers (prefer extending `tenants/shopify.py` / `shopify_token.py`):

| Class | Examples | Behavior |
|-------|----------|----------|
| **Retryable** | network, timeout, HTTP 429 / 5xx | Keep today’s retry in `_post_form_with_retry`; do **not** flip connector status |
| **Terminal — reconnect required** | refresh_token inactive; refresh_token expired locally; HTTP 401 that is not retryable; missing `shop_domain` when refresh needed | Fail the job **and** mark connector auth-dead (below) |

Reuse existing message detection:

- `_is_inactive_refresh_token_response`  
- `ShopifyAuthExpiredError` for local `refresh_token_expires_at <= now`

## 5. Patch: shared “mark Shopify auth expired” helper

Add one sync helper (name flexible), e.g. in `dataruns/connectors/shopify_token.py` or `tenants/shopify.py`:

```python
def mark_shopify_auth_expired(
    *,
    connector: Connector,
    reason: str,
    source: str,  # "bootstrap" | "dcs_fresh_import" | ...
) -> None:
    ...
```

### 5.1 Connector updates (required)

| Field | Change |
|-------|--------|
| `Connector.status` | Set to **`error`** (not `connected` / `degraded`) so DCS-07 eligibility drops |
| `Connector.config` | Keep encrypted tokens (do not wipe — useful for support); optional non-secret flags below |
| Non-secret config metadata (optional) | e.g. `auth_failure_at` (ISO UTC), `auth_failure_reason` (short safe string, **no** token values) |

Do **not** store raw tokens or Shopify response bodies with secrets in metadata / audit `meta`.

### 5.2 Audit (required if AUDIT-01 present)

Emit one company audit event, e.g.:

| Field | Value |
|-------|--------|
| `action` | `connector.auth_expired` (or reuse `connector.disconnected` if product prefers fewer action names — pick one and document) |
| `tone` | `risk` |
| `summary` | Human: “Shopify connection requires reconnect (refresh token inactive).” |
| `meta` | `{ "platform": "shopify", "reason_code": "REFRESH_INACTIVE" \| "REFRESH_EXPIRED" \| "AUTH_FAILED", "source": "dcs_fresh_import" \| "bootstrap", "shop_domain": "…" }` |

Bell / Activity will pick this up via existing AUDIT pipelines. Prefer a dedicated `connector.auth_expired` so reconnect copy is clear.

### 5.3 Email account owner (required)

When `mark_shopify_auth_expired` runs (terminal refresh failure), **send an email** telling the account to reconnect Shopify.

| Item | Spec |
|------|------|
| Recipients | **Account owners** = verified active company **admins** for that tenant — reuse `_bootstrap_admin_recipient_emails` / same set as CONN-01 bootstrap failure mail (not every team member) |
| Transport | `tenants/emails.py` → `send_email` (existing Mailer) |
| New helper | e.g. `send_shopify_auth_expired_email(*, company, shop_domain, reason_code, source)` |
| Subject | e.g. `Klints: Shopify connection needs reconnect` |
| Body | Shopify shop domain (safe); short reason (“refresh token inactive / expired”); CTA to Integrations / Connected stack reconnect URL (same pattern as bootstrap failure email) |
| Secrets | Never include access/refresh tokens or raw Shopify error bodies with credentials |
| When | Once per `mark_shopify_auth_expired` call that **newly** flips status to `error` (or first terminal failure after a successful connect). Do **not** email on every retryable 503. |
| Dedup | If connector is **already** `error` with the same auth-failure reason from a prior run, **skip** a second email on the next daily beat (avoid daily spam). Email again only after a successful reconnect later fails again, or if `auth_failure_at` was cleared on reconnect. |
| Bootstrap overlap | Bootstrap already sends `send_connector_bootstrap_failure_email` on AUTH_FAILED. Prefer: either (a) dedicated auth-expired email from `mark_*` and suppress duplicate wording in bootstrap for this reason only, or (b) let bootstrap keep its failure email and have `mark_*` email only when `source=dcs_fresh_import` / non-bootstrap. **Locked v1:** always send the dedicated auth-expired email from `mark_shopify_auth_expired` when status transitions `connected\|degraded → error`; bootstrap may still send its own failure email in the same job (acceptable once); subsequent daily DCS failures must **not** re-mail while still `error`. |

Mailer failures must **not** roll back connector status / audit — log and continue (same pattern as DCS notify).

### 5.4 Job outcomes (keep failing the run)

| Caller | On terminal refresh failure |
|--------|-----------------------------|
| Bootstrap | Keep `_fail_bootstrap_preflight` / `AUTH_FAILED` + admin email; **also** call `mark_shopify_auth_expired` |
| DCS `fresh_import` / `run_dcs_score` | Keep failing DataRun with clear `metadata.error`; **also** call `mark_shopify_auth_expired` **before** or as part of failure finalize |

After status=`error`, next `dispatch_daily_dcs_scores` must **skip** this company (already true if eligibility is `connected|degraded` only — verify tests).

## 6. Call-site changes (minimal)

| File | Change |
|------|--------|
| `dataruns/connectors/shopify_token.py` | Optionally wrap raise path to return a typed terminal error; or export `mark_shopify_auth_expired` |
| `dataruns/dcs/fresh_import.py` → `_ensure_shopify_token` | On `ShopifyAuthExpiredError` / terminal `ShopifyOAuthError`: mark connector, then re-raise `DcsFreshImportError` |
| `dataruns/tasks.py` → bootstrap ensure | On same errors: mark connector (if not already done inside ensure), then existing AUTH_FAILED path |
| `dataruns/dcs/enqueue.py` / DCS-07 tests | Confirm `status=error` is not eligible for daily beat |
| Integrations FE (CONN-04) | Already shows Error for `error` — no change if status flips correctly; optional copy “Reconnect required” when `auth_failure_reason` present |

## 7. Happy-path hardening (small, optional in same PR)

Shopify **rotates** refresh tokens on successful refresh. Confirm `apply_token_bundle_to_config` always writes the **new** `refresh_token` when present (already intended). Add/extend a unit test:

1. Mock refresh response with new access + **new** refresh.  
2. Assert DB config decrypts to the **new** refresh (old refresh must not remain).  
3. Second refresh with old token must not be what we send after a successful save.

This prevents a class of “inactive refresh” bugs from lost rotation under races (mitigated by existing `select_for_update`).

## 8. What not to change

- OAuth `expiring=1` exchange  
- Skew default (120s) unless product asks  
- Retry policy for 429/5xx  
- Manago auth  
- Requiring FE work beyond what CONN-04 already does for `error` status  

## 9. Acceptance

1. **Happy path unchanged:** expired access + Shopify-accepted refresh → tokens saved → bootstrap/DCS continues.  
2. **Inactive refresh (DCS):** DataRun fails with clear error **and** `Connector.status=error` for that Shopify connector.  
3. **Inactive refresh (bootstrap):** `AUTH_FAILED` health path **and** `Connector.status=error`.  
4. Next daily beat: company **not** enqueued solely for that dead Shopify connector (unless Manago-only eligibility still applies — follow DCS-07 rules; if eligibility is “any connected Shopify **or** Manago”, document whether auth-dead Shopify alone should still enqueue Manago-only score; **default for this patch:** if Shopify is `error` but Manago still `connected|degraded`, beat may still enqueue — DCS must not call Shopify refresh as if connected, or must treat Shopify as not connected in fresh-import).  
5. Audit event created once per terminal failure (no spam loop inside a single job).  
6. **Email:** verified company admins receive reconnect email when status first flips to `error`; no daily re-mail while still `error`.  
7. Reconnect OAuth (same company, CONN-02 allow) restores `connected`/`degraded` via existing callback + bootstrap and clears failure metadata (so a later failure can email again).  
8. Secrets never appear in audit `meta`, logs, email body, or health issues detail beyond safe reason codes.  
9. Unit tests: terminal inactive 401 → status `error` + email once; second mark while already `error` → no second email; retryable 503 → status unchanged + no email; refresh rotation persists new refresh_token.

### 9.1 Eligibility clarification (locked for this patch)

In `refresh_connected_platforms_for_dcs` / `_connected_connectors`, only platforms with status in `{connected, degraded}` are refreshed. After mark → `error`, Shopify is **skipped** on later DCS runs.  

If beat eligibility is “Shopify **or** Manago connected”, a company with Manago OK + Shopify `error` may still get a DCS run — that is OK; Shopify side should report `NOT_CONNECTED` / auth-failed gates, not crash the whole pipeline on refresh.  

**Additional requirement:** `DcsFreshImportError` from Shopify auth must not leave the parent DCS run without marking Shopify `error` first. Prefer: auth mark → then fail DCS **or** (stretch) continue Manago-only fresh import and let FD-02 fail cleanly.  

**v1 locked choice:** mark Shopify `error`, fail the DCS DataRun (same as today), stop silent `connected` lie. Stretch (phase 2): degrade to Manago-only continue.

## 10. Files to change

| File | Change |
|------|--------|
| `dataruns/connectors/shopify_token.py` | `mark_shopify_auth_expired` (+ optional reason_code helper); trigger email on `connected\|degraded → error` |
| `dataruns/dcs/fresh_import.py` | Call mark on terminal refresh failure |
| `dataruns/tasks.py` | Call mark on bootstrap terminal refresh failure (if not centralized inside ensure) |
| `dataruns/audit.py` / action registry | Register `connector.auth_expired` (or chosen action) |
| `tenants/emails.py` | `send_shopify_auth_expired_email` (+ tests) |
| `tenants/tests/test_shopify_token_refresh.py` | Terminal → status `error` + email once; no spam while still `error`; rotation persistence |
| `dataruns/tests/test_daily_dcs_beat.py` | Shopify `error` not treated as Shopify-eligible |
| `docs/PRD_CONN_03_...md` | Status note: patched by CONN-05 (optional one-liner) |

## 11. Ops note (current Lumera)

Until this patch ships, **manual reconnect** of Shopify for `klints-dev.myshopify.com` is required. After reconnect, access/refresh pair is new and daily refresh works again. This PRD makes the next inactive-token incident self-describing instead of a silent daily fail loop.
