# Write-surface matrix — PRD-WB-01B §3

**Status:** Authoritative for WB-01B honesty claims · per-check/field sheet: [`WRITEBACK_POSSIBLE_NOT_SHEET.csv`](./WRITEBACK_POSSIBLE_NOT_SHEET.csv) (PRD-WB-01C)
**Source:** `docs/maheep/PRD_WB_01B_SANDBOX_PROOF_AND_LE04_FIX.md` §3
**Convention:** Klints Django `Contact` / `Order` are **canonical read models**. Writes go to **connector APIs**. Manago “transactions” import as Klints `Order` (`map.json` `raw_sources.transactions` → entity `order`). Shopify “orders” → same.

---

## Manago

| Business object | Connector object | Klints DB model (read) | Write via WB today? | `klints_` / `klints:` namespace? | Native field changes? | `op_kind` / API | Notes |
|-----------------|------------------|------------------------|---------------------|--------------------------------|----------------------|-----------------|-------|
| **Contact** | Contact | `Contact` | **Yes** | Optional marker `klints_backfill` on backfill | **Yes** — email, phone, externalId, etc. via upsert | `contact_upsert` · `api/contact/upsert` | Mapping **CI-01**. Prefer native only when Suggested Fix says so |
| **Contact details** | Contact properties / details | (on Contact / raw) | **Yes** | **Yes — preferred** `klints_*` | Allowed if mapping `namespace: native` | `detail_set` · upsert `properties` | Mapping **CC-03** (`klints_consent_evidence`). **PT-04** (`klints_net_ltv` from Shopify net; WB-11). **SP-07** renames foreign `klints_*` → `legacy_klints_*`. New “column” = new detail key, not Django migration |
| **Contact tags** | Tags | (raw / tags) | **Yes** | **Yes — preferred** `klints:` | Native tags allowed if mapping says so | `tag_add` / deleteTag rollback | **SP-01 disabled** (not in MVP1 42). **SP-07** renames foreign `klints:` → `legacy_klints:*`. LE-04 disabled (pack = Integration + Manual) |
| **Transaction / purchase event** | External event (`PURCHASE`, …) | Evidence → often shown as order-like | **Yes — LE-01** | Event payload (value, date, externalId) — contact `klints_backfill` stamp N/A for event_ingest | Event payload fields (value, date, externalId) | `event_ingest` · `batchAddContactExtEvent` | **LE-01 enabled** with irreversible disclosure; rollback limited/best-effort. **Not** a Shopify Order rewrite |
| **Return / cancellation event** | External event (`RETURN` / `CANCELLATION`) | Evidence → order-like | **Yes — LE-09** | Same as purchase events — no contact `klints_backfill` on event_ingest | `externalId`, `value`, `contactExtEventType` | `event_ingest` · `batchAddContactExtEvent` | **LE-09 enabled** (WB-10); match `shopify_only_return`; irreversible; rollback not supported |
| **Order** (commerce order object) | — | `Order` (normalized from Manago transactions) | **No dedicated order updater** | n/a | n/a | — | Manago side is **events/transactions**, not Shopify-style Order CRUD |
| Product / catalog | Product | — | Stub | — | — | `product_upsert` | Out of WB-01B |
| Merge contacts | Contact | `Contact` | Stub | — | — | `contact_merge` | Out of WB-01B |

## Shopify

| Business object | Connector object | Klints DB model (read) | Write via WB today? | `klints` namespace? | Native field changes? | `op_kind` / API | Notes |
|-----------------|------------------|------------------------|---------------------|--------------------|----------------------|-----------------|-------|
| **Customer (contact)** | Customer | `Contact` | **Yes (sandbox)** — mapping **WB-SHOP-01** | Prefer metafield `namespace=klints` (not yet execute) | **Yes** via customer update (note for sandbox proof) | `shopify_customer_update` · Admin `customers/{id}.json` PUT | Capability `SHOPIFY.CUSTOMER.UPDATE` · scope `write_customers` |
| **Customer metafield** | Metafield | — | **Stub** until implemented | **Yes** `namespace=klints`, key e.g. `wb_test` | n/a | `shopify_metafield_set` | Preferred hygienic test if execute is implemented later |
| **Order** | Order | `Order` | **No** | — | — | — | Not in adapter. Do **not** claim order writeback |
| **Transaction / payment** | Transaction (Shopify) | — | **No** | — | — | — | Not in adapter |
| **Checkout** | Checkout | raw only | **No** | — | — | — | Read/raw for LE-08 etc. |

## Namespace rules

| Platform | Klints-owned writes | Native repairs |
|----------|---------------------|----------------|
| Manago | Details `klints_*`, tags `klints:` | Only when check Suggested Fix requires (email, consent flags, externalId, …) |
| Shopify | Metafields `namespace=klints` (when implemented) | Sandbox customer field update OK for proof; prod still gated |
| Both | Never invent fields missing from mapping / `map.json` / extras | Unmapped required field → fail row |

## Klints Django models — write?

| Model | Written by writeback pipeline? |
|-------|--------------------------------|
| `Contact` / `Order` | **No** (read for evidence / before-state) |
| `WritebackJob` | **Yes** (job audit) |
| `WritebackApprovalToken` | **Yes** (early BL-017; unused on sandbox path) |
| Connector config | **No** (credentials only) |

## Enabled mappings (WB-01B + WB-08 + WB-09 + WB-10 + WB-11)

| Check | Platform | `op_kind` | Status |
|-------|----------|-----------|--------|
| CI-01 | Manago | `contact_upsert` | Enabled |
| CC-03 | Manago | `detail_set` | Enabled |
| WB-SHOP-01 | Shopify | `shopify_customer_update` | Enabled (sandbox proof) |
| SP-01 | Manago | `tag_add` | **Disabled stub** — not in MVP1 42; no DCS executor; `operations=[]` |
| LE-01 | Manago | `event_ingest` | **Enabled** (WB-08; irreversible disclosure; rollback limited) |
| SP-07 | Manago | `detail_set` + `tag_add` (rename off namespace) | **Enabled** (WB-09; reverse_rename_map; gate Fix) |
| LE-09 | Manago | `event_ingest` | **Enabled** (WB-10; RETURN/CANCELLATION; irreversible; rollback not supported) |
| PT-04 | Manago | `detail_set` | **Enabled** (WB-11+WB-12; `klints_net_ltv` = Shopify net; re-score PASSes when stamp ≈ net) |
| LE-04 | Manago | `tag_add` | **Disabled** — pack Fix Type is Integration build + Manual (T6) |
