# Deep analysis — PT-03 Catalog completeness vs commerce (PRD-ready)

**Status:** **WB-20 Preview live 2026-09-26** — mapping + expand + `product_upsert` adapter + §3.2a surplus teach + provenance; execute still blocked (`RESTV2.PRODUCT.IMPORT` = `DISCOVERY_REQUIRED`; FE allowlist deferred). PRD: [`PRD_WB_20_PT03_CATALOG_COMPLETENESS_WRITEBACK.md`](./PRD_WB_20_PT03_CATALOG_COMPLETENESS_WRITEBACK.md).  
**Date:** 2026-09-26  
**Scope:** MVP1-42 check **PT-03** only. Do not conflate with **PT-01** (event product IDs resolve — External integrator) or **BR-01** (margin — Data lead).  
**Authority:** Excel sheet **02** row PT-03 (via seeded `CheckMaster`) · `CHECK_MASTER_42` · live `evaluate_pt_03` / `catalog_join` · ownership §6 · WB-01 T7 / `RESTV2.PRODUCT.IMPORT`.

---

## 0. One-line verdict

PT-03 **scoring is complete** when Manago product catalog is ingested; **Fix Preview is live** (WB-20). Excel Fix Owner = **Klints (automated)** — Approve execute waits on sandbox Loom for `RESTV2.PRODUCT.IMPORT` → CONFIRMED_* then FE allowlist. Excel Suggested Fix splits into (1) continuous webhook sync (integration follow-on), (2) **one-time reconcile upsert**, (3) **archive-flag surplus** — Preview ships plan for (2)+(3); (3) Ready only after `archive_enabled` Loom.

---

## 1. Excel catalogue (exact — SoT from CheckMaster)

| Column | PT-03 value |
|--------|-------------|
| Check ID | **PT-03** |
| Dimension | 03 Product & Transaction |
| Name | Catalog completeness vs commerce |
| Check Type | Cross-system reconciliation |
| Systems Compared | **Manago vs Shopify** |
| Root Causes | **RC-01, RC-05, RC-10** |
| Severity | **High** |
| DCS Weight | **4** (sheet 09 / CHECK_MASTER) |
| Suggested Fix | **Establish catalog sync (v3 product/upsert on product change webhooks); one-time reconciliation load; archive-flag surplus entries.** |
| Fix Type | **Integration build + Automated writeback (approved)** |
| Fix Owner | **Klints (automated)** |
| Cadence | Initial + Recurring |
| Phase | MVP1-A · SCORED · seq 19 |
| Fix Template (pack) | **T7 Catalog sync** → `product_upsert` |

**Do not confuse:**

| Check | Meaning | Owner | This PRD? |
|-------|---------|-------|-----------|
| **PT-03** | Active Shopify assortment ⊆↔ Manago catalog; surplus; attribute-empty | **Klints** | **Yes** |
| **PT-01** | Event product IDs resolve in catalog (dangling IDs) | **External integrator** | **No** — ID convention / historical map |
| **BR-01** | Margin coverage on catalog | Data lead | **No** |
| **PT-04** | Net vs gross truth | Klints | Already shipped (WB-11/12) |

---

## 2. What already works (DCS)

### 2.1 Pipeline

| Layer | Location | Status |
|-------|----------|--------|
| Join | `dataruns/dcs/catalog_join.py` → `build_catalog_snapshot()` | **Live** |
| Score | `dataruns/dcs/executors/product.py` → `evaluate_pt_03` | **Live** |
| Tests | `dataruns/tests/test_batch_4c_checks.py` | PASS / FAIL / UNKNOWN |
| Manago ingest | `catalogList` (v3 key) + optional `product_feed_url` XML | **Required** or PT-03 → UNKNOWN |
| Shopify ingest | Active `products` API (`status=active`) | Preferred; line-items alone are **not** PT-03 SoT when products API present |
| FE Approve allowlist | `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | **PT-03 absent** |
| Mapping / registry | — | **Absent** |
| Possible sheet | — | **No PT-03 row** |
| Adapter | `product_upsert` declared; **not** implemented | **Gap** |
| Capability (writebacks) | `RESTV2.PRODUCT.IMPORT` | **`DISCOVERY_REQUIRED`** (execute blocked) |

### 2.2 Detection contract (scoring)

**Shopify side:** active products from products API (`status=active`). When products API is present, line-item-only IDs are **not** added to the active set (comment in `catalog_join`: PT-03 must stay scoped to active catalog).

**Manago side:** product entries from XML feed / ingested `products` keyed by `productId` / `product_id` / `id` / `sku`.

**Comparisons (string ID equality):**

| Driver | Definition | FAIL? |
|--------|------------|-------|
| `missing_in_manago` | Shopify active IDs − Manago catalog IDs | **Yes** |
| `surplus_in_manago` | Manago IDs − Shopify active IDs | **Yes** |
| `attribute_empty` | Manago row missing name/title **and** sku | **Yes** (count) |

**PASS / FAIL / UNKNOWN:**

| Condition | Status |
|-----------|--------|
| Shopify or Manago not connected | NOT_CONNECTED / UNKNOWN |
| `manago_catalog_available` false | **UNKNOWN** (`MISSING_INPUT:manago_product_catalog`) |
| any of missing / surplus / attribute_empty > 0 | **FAIL** (RC-01) |
| else | **PASS** |

**Sample cap:** `PT_SAMPLE = 50`.

### 2.3 Provenance today (thin)

| `side` | Shape | In mismatches? |
|--------|--------|----------------|
| `missing_in_manago` | `{ product_id }` | **Yes** (≤50) |
| `surplus_in_manago` | `{ product_id }` | **Yes** (≤50) |
| `attribute_empty` | sample in `pt03.attribute_empty_sample` only | **No** — honesty gap for Download / Fix |

**PRD implication (shipped into draft):** Archive-flag alone does **not** clear FAIL today — `surplus_in_manago` uses all Manago keys. WB-20 must teach scoring to exclude inactive/archived (PRD §3.2a), same class as WB-12 teaching PT-04 PASS after stamp.

---

## 3. What Excel fix actually requires (decompose Suggested Fix)

| Part | Meaning | In first PRD? |
|------|---------|---------------|
| **A. Continuous catalog sync** | `v3 product/upsert` on Shopify **product change webhooks** | **Out of MVP writeback** — Integration build half; ops/integration PRD later |
| **B. One-time reconciliation load** | Upsert active Shopify products missing in Manago | **Yes — Approve** (`product_upsert`) |
| **C. Archive-flag surplus** | Flag Manago entries not in Shopify active set | **Yes — Approve** after Loom confirms archive field **+ scoring teach** (exclude inactive from surplus); else Download-only honesty |
| **D. Attribute fill** | Empty name/sku on Manago rows | **Download-only in MVP** — optional Phase B enrich from Shopify when ID matches |

If the PRD tries to ship webhooks in the same Approve PR, it will sprawl past Fix writebacks and block the remaining Klints candidate.

---

## 4. Capability / adapter gaps (critical)

| Surface | Today | Implication |
|---------|-------|-------------|
| Pack Capability Matrix | `RESTV2.PRODUCT.IMPORT` marked CONFIRMED_LIVE (docs) | **Not** the writeback execute SoT |
| `dataruns/writebacks/capabilities.json` | **`DISCOVERY_REQUIRED`**, `batch_max: 100` | Execute **blocked** until Loom → `CONFIRMED_LIVE` or `CONFIRMED_LIMITED` |
| Manago adapter | No `product_upsert` branch | Returns / raises not-implemented |
| `_IMPLEMENTED_OP_KINDS` | Omits `product_upsert` | Intent path incomplete |
| Manago public docs (connector note) | catalogList + **product upsert**; **no product-list** without feed/v3 | Read path already handled; write path needs sandbox discovery (path, body, catalogId, archive) |
| Rollback | stub_factory treats `product_upsert` as **irreversible** | Mapping should set `irreversible: true` + disclosure until reverse archive proven |

**PRD lock:** Do **not** FE-allowlist Approve execute until capability status is upgraded after sandbox Loom. Preview/mapping can land in the same PR behind the capability gate (same pattern as early LE-02 limited).

---

## 5. ID convention risk (PT-01 adjacency)

Live join uses **raw string equality** of Shopify `product.id` vs Manago product key.

| Risk | Effect |
|------|--------|
| Manago keyed by **SKU** / variant id / handle | Mass false `missing` + `surplus` |
| Events use **variant** ids (PT-01) | PT-03 still product-level — correct; do not “fix” PT-01 dangling via PT-03 |
| Integrator never agreed convention | Reconcile writes wrong catalog keys |

**Ownership §6:** Prefer PT-01 ID convention agreed with integrator **first**.  
**PRD default if unset:** Shopify **product.id** → Manago **productId** (matches current scoring). Document as open question; do not invent SKU↔product mapping in MVP.

---

## 6. Ownership / writeback posture

| Question | Answer |
|----------|--------|
| Fix Owner | **Klints (automated)** |
| Klints Approve? | **Yes** — after capability Loom |
| Plan-only escape? | **No** — unlike CC-01/02 / CI-03 |
| Copy CC-03 Data-lead exception? | **No** |
| Template | **T7** |
| Op | **`product_upsert`** · capability `RESTV2.PRODUCT.IMPORT` |
| Same PR as PT-01 / webhooks? | **No** |

---

## 7. Recommended MVP ship shape

1. **Hand-author** `PT-03.catalog_reconcile.v1.json` (T7) — do **not** stub_factory.  
2. Implement Manago **`product_upsert`** adapter after Loom (path/body/catalogId).  
3. Transform: expand `missing_in_manago` / `surplus_in_manago` (+ optional `attribute_empty`) from pins + Shopify/Manago raw.  
4. Preview cap `PT_SAMPLE` (50); truncation honesty; batch_max from capability (100 today).  
5. Match sides: `missing_in_manago` → UPSERT_FROM_SHOPIFY; `surplus_in_manago` → ARCHIVE_FLAG (or skip until archive field known).  
6. **Teach `catalog_join` surplus** to exclude inactive/archived Manago products (PRD §3.2a).  
7. FE allowlist + `WritebackAllowedCheck` **only when** `capability_allows_execute("RESTV2.PRODUCT.IMPORT")`.  
8. Possible sheet ×2 + SURFACE + ownership §3/§5/§6 update.  
9. Enrich score provenance: `attribute_empty` mismatches + Shopify title/sku on missing rows (honesty).  
10. Tests + `scripts/verify_wb20_pt03_catalog_reconcile.py`.

**Explicit non-goals for MVP:** Shopify product webhooks, PT-01 dangling repair, BR-01 margin, hard-delete surplus, inventing Manago list API.

---

## 8. Risks

| Risk | Mitigation |
|------|------------|
| Capability still DISCOVERY_REQUIRED | Hard gate; Loom before allowlist |
| Wrong productId convention | Lock scoring SoT; product sign-off; Download shows both IDs |
| Archive semantics unknown | Surplus Download-only until Loom; do not hard-delete |
| Archive without scoring teach | Surplus still FAILs — PRD §3.2a mandatory |
| Attribute_empty invisible in Fix Download | Add to provenance mismatches |
| Attribute_empty left after MVP Approve | Honesty — Download / Phase B enrich; do not claim full PASS |
| Irreversible upsert / archive | `irreversible: true` + operator disclosure |
| UNKNOWN estates (no feed / no v3 key) | Honesty: connect catalog ingest first — writeback cannot invent catalog read |
| Mixing PT-01 | Separate check; External owns ID convention |

---

## 9. Related

- [`PRD_WB_20_PT03_CATALOG_COMPLETENESS_WRITEBACK.md`](./PRD_WB_20_PT03_CATALOG_COMPLETENESS_WRITEBACK.md)  
- [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md) §6 #1  
- [`PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md`](./PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md) (T7 / product_upsert)  
- `dataruns/dcs/catalog_join.py` · `dataruns/dcs/executors/product.py`  
- `dataruns/writebacks/capabilities.json` · `dataruns/connectors/manago_ai/client.py` (catalogList / feed note)  
