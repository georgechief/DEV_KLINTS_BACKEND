# Write-surface matrix — PRD-WB-01B §3

**Status:** Authoritative for WB-01B honesty claims · per-check/field sheet: [`WRITEBACK_POSSIBLE_NOT_SHEET.csv`](./WRITEBACK_POSSIBLE_NOT_SHEET.csv) (PRD-WB-01C)
**Source:** `docs/maheep/PRD_WB_01B_SANDBOX_PROOF_AND_LE04_FIX.md` §3
**Convention:** Klints Django `Contact` / `Order` are **canonical read models**. Writes go to **connector APIs**. Manago “transactions” import as Klints `Order` (`map.json` `raw_sources.transactions` → entity `order`). Shopify “orders” → same.

---

## Manago

| Business object | Connector object | Klints DB model (read) | Write via WB today? | `klints_` / `klints:` namespace? | Native field changes? | `op_kind` / API | Notes |
|-----------------|------------------|------------------------|---------------------|--------------------------------|----------------------|-----------------|-------|
| **Contact** | Contact | `Contact` | **Yes** | Optional marker `klints_backfill` on backfill | **Yes** — email, phone, externalId, etc. via upsert | `contact_upsert` · `api/contact/upsert` | Mapping **CI-01** (create Shopify-only). **CI-05** (WB-15) backfills `externalId` on existing Manago contacts from clean email matches (`missing_link_key` only — not reused/dangling; not CI-03 merge). Prefer native only when Suggested Fix says so |
| **Contact details** | Contact properties / details | (on Contact / raw) | **Yes** | **Yes — preferred** `klints_*` | Allowed if mapping `namespace: native` | `detail_set` · upsert `properties` | Mapping **CC-03** (`klints_consent_evidence`). **PT-04** (`klints_net_ltv` from Shopify net; WB-11). **SP-07** renames foreign `klints_*` → `legacy_klints_*`. New “column” = new detail key, not Django migration |
| **Contact tags** | Tags | (raw / tags) | **Yes** | **Yes — preferred** `klints:` | Native tags allowed if mapping says so | `tag_add` / deleteTag rollback | **SP-01 disabled** (not in MVP1 42). **SP-07** renames foreign `klints:` → `legacy_klints:*`. LE-04 disabled (pack = Integration + Manual) |
| **Transaction / purchase event** | External event (`PURCHASE`, …) | Evidence → often shown as order-like | **Yes — LE-01 + LE-05 + LE-02** | Event payload (value, date, externalId) — contact `klints_backfill` stamp N/A for event ops | Event payload fields (value, date, externalId) | `event_ingest` · `batchAddContactExtEvent` · **`event_correct` · `updateContactExtEvent`** | **LE-01** count parity (WB-08). **LE-05** order-level gaps (WB-13; match `shopify_only`; no manago_only delete). **LE-02** matched value correct (WB-14; match `value_mismatch`; full resend; irreversible; rollback no). **Not** a Shopify Order rewrite |
| **Return / cancellation event** | External event (`RETURN` / `CANCELLATION`) | Evidence → order-like | **Yes — LE-09** | Same as purchase events — no contact `klints_backfill` on event_ingest | `externalId`, `value`, `contactExtEventType` | `event_ingest` · `batchAddContactExtEvent` | **LE-09 enabled** (WB-10); match `shopify_only_return`; irreversible; rollback not supported |
| **Order** (commerce order object) | — | `Order` (normalized from Manago transactions) | **No dedicated order updater** | n/a | n/a | — | Manago side is **events/transactions**, not Shopify-style Order CRUD |
| Product / catalog | Product | — | **Preview live — PT-03** (WB-20); execute after Loom | — | **Yes** (upsert / archive) | `product_upsert` · v3 `product/upsert` | Mapping **PT-03** T7; PRODUCT.IMPORT DISCOVERY_REQUIRED; surplus scoring excludes inactive; attribute_empty Download-only; irreversible; webhooks deferred |
| Merge contacts | Contact | `Contact` | **Phase A plan live** (WB-16) | — | — | `contact_merge` | Preview/Download merge plan only (`execute_mode=plan_only`); not auto-merged; CRM manager; Phase B SAFE `batchDelete` CONTACT_ID after Loom |
| Email consent reconcile | Contact | `Contact` | **Phase A plan live** (WB-17) | Native `forceOpt*` (Phase B) | Phase B only | `contact_upsert` plan | Preview/Download FORCE_OPT_OUT/IN/SKIP (`execute_mode=plan_only`); Data lead; Phase B forceOpt after Loom; opt-out not rolled back |
| SMS consent reconcile | Contact | `Contact` | **Phase A plan live** (WB-18) | Native `forcePhoneOpt*` (Phase B) | Phase B only | `contact_upsert` plan | Preview/Download FORCE_PHONE_OPT_OUT/IN/SKIP + unreachable Download-only (`execute_mode=plan_only`); Data lead; Phase B forcePhoneOpt after Loom; opt-out not rolled back |
| Detail schema normalise | Contact | `Contact` | **Yes — SP-03** (WB-19) | Native detail properties | **Yes** (format coerce) | `detail_set` | Approve LIVE; format_contract; mixed formats only; semantic dupes Download-only; SP-07 gated; `revert_detail` |

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

## Enabled mappings (WB-01B + WB-08 + WB-09 + WB-10 + WB-11 + WB-13 + WB-14 + WB-15 + WB-16 + WB-17 + WB-18 + WB-19 + WB-20)

| Check | Platform | `op_kind` | Status |
|-------|----------|-----------|--------|
| CI-01 | Manago | `contact_upsert` | Enabled |
| CI-05 | Manago | `contact_upsert` | **Enabled** (WB-15; `externalId` from `missing_link_key`; batch; restore_prior_field; reused → CI-03) |
| CI-03 | Manago | `contact_merge` | **Enabled plan-only** (WB-16 Phase A; `merge_candidate`; not auto-merged; CRM manager; execute → `ci03_plan_only`) |
| CC-01 | Manago | `contact_upsert` (plan) | **Enabled plan-only** (WB-17 Phase A; T8; `out_in`/`in_out`; Data lead; execute → `cc01_plan_only`; forceOpt Phase B gated) |
| CC-02 | Manago | `contact_upsert` (plan) | **Enabled plan-only** (WB-18 Phase A; T8; SMS `out_in`/`in_out` + unreachable Download-only; Data lead; execute → `cc02_plan_only`; forcePhoneOpt Phase B gated) |
| CC-03 | Manago | `detail_set` | Enabled |
| WB-SHOP-01 | Shopify | `shopify_customer_update` | Enabled (sandbox proof) |
| SP-01 | Manago | `tag_add` | **Disabled stub** — not in MVP1 42; no DCS executor; `operations=[]` |
| SP-03 | Manago | `detail_set` | **Enabled** (WB-19; format_contract + normalise; mixed formats only; semantic Download-only; SP-07 gated; revert_detail) |
| PT-03 | Manago | `product_upsert` | **Enabled Preview** (WB-20; T7; PRODUCT.IMPORT DISCOVERY_REQUIRED — execute blocked until Loom; archive_enabled=false; attribute_empty Download-only) |
| LE-01 | Manago | `event_ingest` | **Enabled** (WB-08; irreversible disclosure; rollback limited) |
| LE-05 | Manago | `event_ingest` | **Enabled** (WB-13; PURCHASE from `shopify_only`; no sandbox; EVENT.INGEST ceiling; irreversible) |
| LE-02 | Manago | `event_correct` | **Enabled** (WB-14; PURCHASE value from `value_mismatch`; full resend; EVENT.UPDATE; irreversible; rollback no) |
| SP-07 | Manago | `detail_set` + `tag_add` (rename off namespace) | **Enabled** (WB-09; reverse_rename_map; gate Fix) |
| LE-09 | Manago | `event_ingest` | **Enabled** (WB-10; RETURN/CANCELLATION; irreversible; rollback not supported) |
| PT-04 | Manago | `detail_set` | **Enabled** (WB-11+WB-12; `klints_net_ltv` = Shopify net; re-score PASSes when stamp ≈ net) |
| LE-04 | Manago | `tag_add` | **Disabled** — pack Fix Type is Integration build + Manual (T6) |
