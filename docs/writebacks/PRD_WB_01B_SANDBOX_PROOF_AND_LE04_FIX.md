# PRD-WB-01B — Sandbox proof (Shopify + Manago), LE-04 fix, Loom + write-surface matrix

**Status:** Ready for implementation  
**Module:** see folder path  
**Depends on:** WB-01 ([PR #37](https://github.com/Rohan070/klints_backend/pull/37)) — merge after LE-04 fix or land WB-01B on same branch  
**FE:** If [FE #25](https://github.com/Rohan070/klints_frontend/pull/25) hardcodes LE-04, drop it when BE disables LE-04  
**Out of scope:** Prod `WRITEBACKS_ENABLED=True` · FE Approve live · MCP · catalog/product write · contact merge · claiming order/transaction writes that are not implemented

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-01B — sandbox proof + LE-04 fix + Loom evidence (BE).

Read: docs/writebacks/PRD_WB_01B_SANDBOX_PROOF_AND_LE04_FIX.md

Goal: (1) fix LE-04, (2) prove sandbox writebacks on Manago AND Shopify,
(3) ship a Loom walking through tests + honest write-surface matrix.

1. LE-04: registry enabled=false (pack = Integration build + Manual).
2. Shopify sandbox mapping WB-SHOP-01 (customer note or klints metafield).
3. Manago sandbox: CC-03 (klints_ detail) and/or CI-01 (contact upsert).
4. Keep WRITEBACKS_ENABLED=False; sandbox company + check allowlist only.
5. Add docs/writebacks/WRITEBACK_SURFACE_MATRIX.md (or §3 of this PRD kept current)
   listing Contacts / Orders / Transactions for Manago + Shopify:
   writeable? klints_ namespace? native allowed? status.
6. RECORD A LOOM (required PR deliverable) — see §7 script.
   MUST show writeback via Postman (preview → execute → rollback),
   then the same fields reflecting in Manago UI and Shopify Admin
   (approval evidence — not FE-only).
7. Unit tests + optional live sandbox pytest when env set.

Acceptance: §8.
```

---

## 1. Why this follow-up

| Gap | Need |
|-----|------|
| LE-04 enabled as writeback | Pack: **not** automated writeback |
| Shopify unused | Must **sandbox-pass** commerce writes too |
| Unclear what we can change | Matrix for contacts / orders / transactions × platform × `klints_` |
| No demo evidence | **Loom** with running tests + UI verify |

Rohan’s bar: sandbox pass + honest matrix + Loom — not prod.

---

## 2. Fix LE-04 (must)

| Check | Pack Fix Type | Action |
|-------|---------------|--------|
| **LE-04** | Integration build + Manual (guided) · T6 | `registry.json` → `"enabled": false` |

Also: FE stop advertising LE-04 preview; fix stub `template_id` → `T6` if file kept.

Optional third Manago enabled mapping: **SP-01** (tag) or **CI-06** (`klints_cohort`) — not LE-04.

---

## 3. Write-surface matrix (must document + keep honest)

> **Convention:** Klints Django `Contact` / `Order` are **canonical read models**. Writes go to **connector APIs**. Manago “transactions” import as Klints `Order` (`map.json` `raw_sources.transactions` → entity `order`). Shopify “orders” → same.

Ship this table in the PR (copy into `docs/writebacks/WRITEBACK_SURFACE_MATRIX.md` **or** keep this section authoritative and link from README).

### 3.1 Manago

| Business object | Connector object | Klints DB model (read) | Write via WB today? | `klints_` / `klints:` namespace? | Native field changes? | `op_kind` / API | Notes |
|-----------------|------------------|------------------------|---------------------|--------------------------------|----------------------|-----------------|-------|
| **Contact** | Contact | `Contact` | **Yes** | Optional marker `klints_backfill` on backfill | **Yes** — email, phone, externalId, etc. via upsert | `contact_upsert` · `api/contact/upsert` | Mapping **CI-01**. Prefer native only when Suggested Fix says so |
| **Contact details** | Contact properties / details | (on Contact / raw) | **Yes** | **Yes — preferred** `klints_*` | Allowed if mapping `namespace: native` | `detail_set` · upsert `properties` | Mapping **CC-03** (`klints_consent_evidence`). New “column” = new detail key, not Django migration |
| **Contact tags** | Tags | (raw / tags) | **Yes** | **Yes — preferred** `klints:` | Native tags allowed if mapping says so | `tag_add` / deleteTag rollback | Enable **SP-01** for third proof |
| **Transaction / purchase event** | External event (`PURCHASE`, …) | Evidence → often shown as order-like | **Code yes · mapping mostly off** | Can stamp `klints_backfill` in detail20 per pack | Event payload fields (value, date, externalId) | `event_ingest` · `batchAddContactExtEvent` | **Not** a Shopify Order rewrite. Rollback often limited → `irreversible` disclosure |
| **Order** (commerce order object) | — | `Order` (normalized from Manago transactions) | **No dedicated order updater** | n/a | n/a | — | Manago side is **events/transactions**, not Shopify-style Order CRUD |
| Product / catalog | Product | — | Stub | — | — | `product_upsert` | Out of WB-01B |
| Merge contacts | Contact | `Contact` | Stub | — | — | `contact_merge` | Out of WB-01B |

### 3.2 Shopify

| Business object | Connector object | Klints DB model (read) | Write via WB today? | `klints` namespace? | Native field changes? | `op_kind` / API | Notes |
|-----------------|------------------|------------------------|---------------------|--------------------|----------------------|-----------------|-------|
| **Customer (contact)** | Customer | `Contact` | **Partial** — adapter exists, **no enabled mapping until WB-01B** | Prefer metafield `namespace=klints` | **Yes** via customer update (e.g. note, phone) for sandbox | `shopify_customer_update` · Admin `customers/{id}.json` PUT | **WB-01B must enable + sandbox-prove** |
| **Customer metafield** | Metafield | — | **Stub** until implemented | **Yes** `namespace=klints`, key e.g. `wb_test` | n/a | `shopify_metafield_set` | Preferred hygienic test if you implement execute |
| **Order** | Order | `Order` | **No** | — | — | — | Not in adapter. Do **not** claim order writeback |
| **Transaction / payment** | Transaction (Shopify) | — | **No** | — | — | — | Not in adapter |
| **Checkout** | Checkout | raw only | **No** | — | — | — | Read/raw for LE-08 etc. |

### 3.3 Namespace rules (say this in the Loom)

| Platform | Klints-owned writes | Native repairs |
|----------|---------------------|----------------|
| Manago | Details `klints_*`, tags `klints:` | Only when check Suggested Fix requires (email, consent flags, externalId, …) |
| Shopify | Metafields `namespace=klints` (when implemented) | Sandbox customer field update OK for proof; prod still gated |
| Both | Never invent fields missing from mapping / `map.json` / extras | Unmapped required field → fail row |

### 3.4 Klints Django models — write?

| Model | Written by writeback pipeline? |
|-------|--------------------------------|
| `Contact` / `Order` | **No** (read for evidence / before-state) |
| `WritebackJob` | **Yes** (job audit) |
| `WritebackApprovalToken` | **Yes** (early BL-017; unused on sandbox path) |
| Connector config | **No** (credentials only) |

---

## 4. Shopify sandbox proof (must)

| Option | Prefer | Payload |
|--------|--------|---------|
| A | Yes if fastest | `shopify_customer_update` — one test customer `note` = `klints_wb_test` then rollback |
| B | Better hygiene | Implement `shopify_metafield_set` — `klints` / `wb_test` = `1` then delete |

Registry: `WB-SHOP-01` enabled · `max_rows=1` · rollback required · mark op implemented only after it works · add `SHOPIFY.CUSTOMER.UPDATE` (or metafield) to capabilities as `CONFIRMED_LIVE` with scope note `write_customers`.

---

## 5. Manago sandbox proof (must)

At least one of:

| Check | What it proves |
|-------|----------------|
| **CC-03** | New **`klints_` detail** on Contact + `revert_detail` |
| **CI-01** | **Contact** upsert (native fields) + backfill marker story |

Optional: **SP-01** tag with `klints:` prefix.

---

## 6. Sandbox runbook

```bash
WRITEBACKS_ENABLED=False
WRITEBACK_SANDBOX_COMPANY_IDS=<test_company_uuid>
WRITEBACK_CHECK_ALLOWLIST=CI-01,CC-03,WB-SHOP-01
WRITEBACK_SANDBOX_MAX_ROWS=1
```

Preview → execute (`diff_hash`) → verify in Manago / Shopify Admin → rollback → verify clean. Prod company execute must still **403**.

---

## 7. Loom video (required PR deliverable)

Post the Loom link in the GitHub PR description (BE follow-up PR or updated #37).

### 7.1 Length / structure (~8–12 min)

**Primary proof path for approval:** **Postman (or equivalent HTTP client) → platform UI.**  
Do not rely on FE Fix page alone for the Loom — Rohan needs to see the API contract and then the same fields live in Manago / Shopify.

| Segment | Show |
|---------|------|
| 1. Setup (30–45s) | Sandbox company id, JWT for that tenant, `WRITEBACKS_ENABLED=False`, allowlist; confirm **not** prod |
| 2. Matrix (1–2 min) | Screen-share §3: Contacts / Orders / Transactions × Manago × Shopify; `klints_` vs native; say what is **not** writeable |
| 3. Automated tests (~1 min) | Pytest / verify subset; LE-04 disabled |
| 4. **Manago via Postman** (3–4 min) | See §7.2 — required |
| 5. **Shopify via Postman** (3–4 min) | Same pattern for `WB-SHOP-01` |
| 6. Close (30s) | Prod still off; FE Approve not required for this proof |

### 7.2 Postman → platform UI (required for each connector)

For **Manago** (CC-03 and/or CI-01) and **Shopify** (WB-SHOP-01), record this sequence on camera:

| Step | Postman / API | Then show in platform |
|------|---------------|------------------------|
| A Auth | `Authorization: Bearer <sandbox JWT>` | — |
| B Preview | `POST /api/v1/writebacks/preview/` body `{ "check_id": "…", "max_rows": 1 }` | Response: intents, **before/after**, `diff_hash`, `op_kind`, `klints_` keys if any |
| C Execute | `POST /api/v1/writebacks/execute/` body `{ "check_id", "diff_hash", "max_rows": 1 }` (sandbox company only) | Response: `executed` / job id; **no** fake success |
| D **Reflect** | — | **Open Manago / Shopify Admin** on the **same** contact/customer and show the written field live (e.g. Manago detail `klints_consent_evidence`, Shopify customer note or `klints` metafield) |
| E Rollback | `POST /api/v1/writebacks/rollback/` with job id | Platform UI: value restored / removed |
| F Re-check | Optional second GET/preview or refresh UI | Clean state |

**Approval bar:** reviewer must see **API response fields match what appears in the platform UI** (same email/contact id, same detail key / metafield / note).

Collection tip: save a Postman collection in the PR or attach export (`writebacks_sandbox.postman_collection.json`) with preview/execute/rollback examples (secrets redacted).

### 7.3 Must say on camera

- “This is sandbox only — `WRITEBACKS_ENABLED` is false for prod.”  
- “Proof is **Postman writeback API**, then **details reflecting in Manago / Shopify**.”  
- “`klints_` / `klints:` preferred for Klints-owned Manago writes.”  
- “Shopify order and transaction writeback is **not** implemented.”  
- “Manago purchase/transaction write = **event ingest**, not Shopify Order.”  

### 7.4 Attachments with Loom

- Loom URL (in GitHub PR description)  
- Postman collection export (redacted) **or** screenshots of the three calls + platform UI  
- Matrix file committed in repo  

---

## 8. Acceptance checklist

- [ ] LE-04 disabled; FE not advertising it  
- [ ] Write-surface matrix committed (§3 / `WRITEBACK_SURFACE_MATRIX.md`) — contacts, orders, transactions, both platforms, `klints_` called out  
- [ ] Manago sandbox: execute + rollback proven  
- [ ] Shopify sandbox: execute + rollback proven  
- [ ] `WRITEBACKS_ENABLED` default False  
- [ ] **Loom link in PR** covering §7 (matrix + tests + **Postman API** + **platform UI reflect** for Manago and Shopify)  
- [ ] Loom clearly shows preview/execute(/rollback) responses and matching fields in Manago + Shopify Admin  
- [ ] No claim of Shopify order/transaction writeback  

---

## 9. One-page summary

| Question | Answer |
|----------|--------|
| What? | LE-04 fix + dual-connector sandbox proof + Loom + matrix |
| Manago writeables? | Contact, `klints_` details, tags; events in code |
| Shopify writeables? | Customer (sandbox); metafield if implemented; **not** orders/transactions |
| Evidence? | **Loom required** |

**PRD:** WB-01B · **Track:** delivery · **Bar:** sandbox pass + Loom + honest matrix  
