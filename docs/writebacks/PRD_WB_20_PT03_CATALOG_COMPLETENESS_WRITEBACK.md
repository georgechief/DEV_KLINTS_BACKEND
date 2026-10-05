# PRD-WB-20 — PT-03 Catalog completeness reconcile (T7 product_upsert)

**Status:** **Preview live 2026-09-26** · execute gated on PRODUCT.IMPORT Loom · P0 M2 Catalogue · Sahil  
**Owner track:** Sahil — **BE primary · FE Approve allowlist + Fix honesty** (pack Fix Owner = **Klints (automated)**)  
**Surfaces:** Fix `/fix` Preview · Approve · FE-12 Download · Settings Allow writebacks · `WritebackAllowedCheck` · registry / mapping · possible sheet · Activity/audit · **DCS catalog join** · Manago **`product_upsert`** / `RESTV2.PRODUCT.IMPORT`  
**Milestone:** M2 Activation & Blueprint — Product & Transaction  
**Depends on:** WB-01…WB-19 · FE-08/09/12 · live `evaluate_pt_03` + `catalog_join` · **sandbox Loom** for product upsert (+ archive field)  
**PRD path:** `docs/writebacks/`  
**Analysis SoT:** [`ANALYSIS_PT03_CATALOG_COMPLETENESS.md`](./ANALYSIS_PT03_CATALOG_COMPLETENESS.md)  
**Ownership SoT:** [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md) §6 #1  
**Draft review:** Folded critical gaps — surplus archive must **teach scoring** (inactive/archived excluded from `surplus_in_manago`); attribute_empty does not auto-PASS; wire payload ≠ Klints `proposed_action`; `namespace: native`; LE-02-style capability ship sequence.  

**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02** row **PT-03** (seeded `CheckMaster`)  
- sheet **01 Overview** — **T7 Catalog sync** → `product_upsert`  
- sheet **09 MVP1 Check Scope** · SCORED · MVP1-A · weight **4** · High · seq 19  
- `docs/dcs_scoring/CHECK_MASTER_42.md` row PT-03 — *Catalog completeness vs commerce* · RC-01, RC-05, RC-10 · **High**  
- WB-01 §1b.2 — T7 → `product_upsert` / `RESTV2.PRODUCT.IMPORT`  
- Ownership §6 #1 — **remaining Klints Approve candidate** after SP-03  

**Out of scope:**  
- **PT-01** dangling event IDs / External ID convention work  
- Shopify **product webhooks** continuous sync (Integration half of Excel — separate ops/integration)  
- **BR-01** margin feed  
- Hard-**delete** surplus products  
- Inventing a Manago product-list API beyond feed / catalogList  
- Changing PT-03 PASS/FAIL bands  
- Stub_factory-generated mapping (wrong irreversible/defaults)  
- Same PR as CI-03B / CC Phase B / SP-03 semantic  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-20 — PT-03 catalog completeness reconcile (T7 product_upsert).

Read:
- docs/writebacks/PRD_WB_20_PT03_CATALOG_COMPLETENESS_WRITEBACK.md (this file)
- docs/writebacks/ANALYSIS_PT03_CATALOG_COMPLETENESS.md
- docs/writebacks/WRITEBACK_FIX_OWNERSHIP_MVP1_42.md (§6 #1)
- docs/writebacks/PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md (T7 / product_upsert)
- dataruns/dcs/executors/product.py (evaluate_pt_03)
- dataruns/dcs/catalog_join.py (missing / surplus / attribute_empty)
- dataruns/writebacks/capabilities.json (RESTV2.PRODUCT.IMPORT)
- FE: src/lib/writebacks.ts — add PT-03 to WRITEBACK_APPROVE_EXECUTABLE only when capability allows execute

Ship Klints Approve (not plan-only). Owner is Klints.

CRITICAL:
- Fix Owner = Klints (automated) → Approve path; seed WritebackAllowedCheck; FE allowlist ON only after capability CONFIRMED_LIVE or CONFIRMED_LIMITED
- RESTV2.PRODUCT.IMPORT is DISCOVERY_REQUIRED today — Loom sandbox upsert (+ archive) BEFORE enabling execute
- Hand-author PT-03.catalog_reconcile.v1.json — template_id T7; do NOT stub_factory
- Implement product_upsert in Manago adapter; add to _IMPLEMENTED_OP_KINDS
- Expand thin score mismatches → Shopify-enriched intents (pins + raw); title/sku best-effort (Ready on product_id even if sku empty)
- MVP Approve sides: missing_in_manago (UPSERT_FROM_SHOPIFY) + surplus_in_manago (ARCHIVE_FLAG when Loom proves field; else skipped Download honesty)
- CRITICAL scoring teach (WB-12-class): after archive, surplus_in_manago MUST exclude inactive/archived Manago products — today surplus uses ALL catalog keys, so active:false alone will NOT clear FAIL
- attribute_empty: Download-only by default (optional ENRICH later) — never invent fake names; MVP may leave FAIL if only attribute_empty remains
- ID convention default: Shopify product.id → Manago productId (scoring SoT). Do not invent SKU maps
- irreversible: true; rollback.strategy=none (LE-02 pattern); operator_disclosure required
- Preview cap PT_SAMPLE=50; capability batch_max (100 today)
- Ship sequence like LE-02: adapter+mapping OK while DISCOVERY_REQUIRED; FE execute allowlist ONLY after CONFIRMED_*
- Update BOTH possible sheets; SURFACE; ownership after ship
- Tests + scripts/verify_wb20_pt03_catalog_reconcile.py
- Do NOT ship webhooks; Do NOT touch PT-01/BR-01; Do NOT hard-delete surplus; Do NOT send proposed_action on Manago wire

MVP ship:
1. Loom → upgrade capabilities.json status (+ document archive field)
2. Adapter product_upsert + mapping T7 (namespace native)
3. catalog_join teach: surplus excludes inactive/archived (§3.2a)
4. Transform expand + pipeline notes
5. FE allowlist + WritebackAllowedCheck (after CONFIRMED_*)
6. Provenance honesty (attribute_empty mismatches + Shopify fields)
7. Possible sheet ×2 + SURFACE + ownership
8. Tests + verify
```

---

## 1. Goal / user story

### 1.0 Problem → outcome

| Today | After WB-20 |
|-------|-------------|
| PT-03 FAILs on missing/surplus/empty; Fix has thin `product_id` samples; no Approve | Fix Preview shows reconcile intents; Approve upserts missing + archive-flags surplus; re-score → PASS when **missing=0 and surplus=0** (and attribute_empty=0, or attribute_empty cleared separately) |
| Archive-flag would not clear FAIL (surplus counts all Manago keys) | Scoring teaches surplus = active/non-archived Manago ∩ complement of Shopify active |
| `product_upsert` stub / capability discovery | Adapter live; capability CONFIRMED_* |
| Continuous webhook sync promised in Excel | Documented as Integration follow-on — not blocking Approve one-time reconcile |

### 1.1 Excel Suggested Fix = three products

| Part | Product | Ship |
|------|---------|------|
| **A. Webhook catalog sync** | Upsert on Shopify product change | **Out of MVP** (Integration) |
| **B. One-time reconcile load** | Upsert active Shopify → Manago for `missing_in_manago` | **MVP Approve** |
| **C. Archive-flag surplus** | Flag Manago-only IDs | **MVP Approve** after Loom + **§3.2a scoring teach**; else Download / skipped |
| **D. Attribute empty** | Fill name/sku from Shopify when ID matches | **Out of MVP Approve** (Download honesty); optional Phase B |

### 1.2 Decision locks

| # | Lock | Value |
|---|------|-------|
| 1 | Fix Owner | **Klints (automated)** — Approve (not plan-only) |
| 2 | Do not treat like PT-01 / CC-01 | **Yes** — PT-01 is External; CC is Data lead |
| 3 | Template | **`template_id: "T7"`** |
| 4 | Op | **`product_upsert`** · `RESTV2.PRODUCT.IMPORT` · mapping `namespace: "native"` |
| 5 | Capability gate | Execute only if `capability_allows_execute` (CONFIRMED_LIVE \| CONFIRMED_LIMITED) |
| 6 | Match — missing | `side` const `missing_in_manago` |
| 7 | Match — surplus | `side` const `surplus_in_manago` |
| 8 | Preview sample | **`PT_SAMPLE` = 50**; execute ceiling `min(PT_SAMPLE, capability_batch_max or 100)` |
| 9 | ID convention | Shopify **`product.id`** → Manago **`productId`** (scoring SoT) unless product overrides |
| 10 | Surplus | **Archive-flag** — never hard-delete in MVP |
| 11 | Archive → PASS | **Scoring teach required** — `surplus_in_manago` counts only **active / non-archived** Manago products (§3.2a). FAIL bands unchanged. |
| 12 | Attribute empty | **Download-only by default** in MVP (optional `ENRICH_ATTRIBUTES` later) |
| 13 | Irreversible | **`true`**; `rollback.strategy: "none"` (LE-02) |
| 14 | Webhooks | **Out of MVP** |
| 15 | Same PR as PT-01 | **No** |
| 16 | Wire payload | Do **not** send `proposed_action` / `_proposed_action` to Manago — Klints evidence field only |

---

## 2. Policy (reconcile)

### 2.1 Proposed actions

| Condition | `proposed_action` | Intent status |
|-----------|-------------------|---------------|
| Shopify active product missing in Manago | `UPSERT_FROM_SHOPIFY` | ready when capability allows + `product_id` present (title/sku best-effort) |
| Manago ID not in Shopify active + archive Loom OK | `ARCHIVE_FLAG` | ready |
| Manago ID not in Shopify active + archive unknown | `ARCHIVE_FLAG` | **skipped** `archive_semantics_unknown` (Download still lists row) |
| Manago attribute_empty | — | **Download only** in MVP (no Ready unless optional enrich op added) |
| Capability DISCOVERY_REQUIRED | — | Preview may show plan; execute **blocked** |

### 2.2 Payload shapes

**Klints evidence / intent fields** (transform sets; not all go on the wire):

| Field | Role |
|-------|------|
| `side` / `product_id` / `write_entity_key` | Match + entity |
| `shopify_title` / `shopify_sku` | Enrich missing upsert |
| `proposed_action` | Gate Ready vs skipped (SP-03/CC pattern) |
| `evidence_gate` | `contract` N/A — use `pins_rebuild` / `archive_loom` / `needs_catalog_id` |

**Manago wire body** (normative sketch — **Loom wins**; do not invent beyond discovery):

```json
{
  "productId": "<shopify product.id>",
  "name": "<title or empty>",
  "sku": "<primary variant sku or empty>",
  "active": true,
  "catalogId": "<default manago catalogId when required>"
}
```

Archive surplus (Loom-confirmed field names win):

```json
{
  "productId": "<manago product_id>",
  "active": false
}
```

Never put `proposed_action` / `_proposed_action` / `_archive` on the Manago HTTP body unless Loom proves those fields exist. Use adapter-local flags from intent metadata instead.

Update this PRD §2.2 after Loom with exact path/body.

### 2.3 ID / catalog selection

1. Prefer Manago **default** catalog from `product_catalogs` (`setAsDefault`) when upsert requires `catalogId`.  
2. If multiple catalogs and none default → **skipped** `needs_catalog_id` (Download lists options).  
3. Never write SKU-as-productId unless product signs a convention override logged in ownership.

---

## 3. Catalogue + live scoring

### 3.1 Catalogue (CheckMaster — seeded Excel SoT)

| Column | Value |
|--------|--------|
| Check ID | **PT-03** |
| Dimension | 03 Product & Transaction |
| Check Name | Catalog completeness vs commerce |
| Check Type | Cross-system reconciliation |
| Systems Compared | Manago vs Shopify |
| Root Causes | RC-01, RC-05, RC-10 |
| Severity | **High** |
| DCS Weight | **4** |
| Suggested Fix | Establish catalog sync (v3 product/upsert on product change webhooks); one-time reconciliation load; archive-flag surplus entries. |
| Fix Type | Integration build + Automated writeback (approved) |
| Fix Owner | **Klints (automated)** |
| Cadence | Initial + Recurring |
| Phase | MVP1-A · SCORED · seq 19 |

Detection Logic empty on seed — live `catalog_join` / `evaluate_pt_03` is SoT for PASS/FAIL.

### 3.2 Live scoring (FAIL bands unchanged; surplus membership taught)

| Piece | Location |
|-------|----------|
| Join | `catalog_join.build_catalog_snapshot` |
| Score | `evaluate_pt_03` |
| FAIL if | `missing_in_manago > 0` **or** `surplus_in_manago > 0` **or** `attribute_empty > 0` |
| UNKNOWN if | Manago catalog not ingested |
| Sample | `PT_SAMPLE = 50` |

**Do not change** the three FAIL drivers or RC codes. **Do teach** surplus membership (§3.2a) so archive-flag Approve can clear surplus the way WB-12 taught PT-04 PASS after stamp.

#### 3.2a Scoring teach (MVP required — archive honesty)

**Today:** `surplus_in_manago = manago_ids − shopify_active` where `manago_ids` is **every** catalog key (active flag ignored).

**After WB-20:** when computing surplus, count only Manago products that are **in-assortment for compare**:

| Treat as in-assortment | Treat as out (not surplus) |
|------------------------|----------------------------|
| `active` is true / missing (default true today) | `active` is false |
| not archive-flagged | Loom-proven archive marker (if distinct from `active`) |

`missing_in_manago` still uses full Shopify **active** set vs Manago keys that are in-assortment (archived Manago row must not satisfy “present” for an active Shopify product — if Shopify active and Manago only has archived twin, still **missing** → upsert).

Document in `catalog_join` + tests. Without this teach, surplus ARCHIVE_FLAG cannot make PT-03 PASS.

### 3.3 Evidence enrich (MVP required)

Score provenance is **thin** (`product_id` only; attribute_empty not in mismatches). Writeback / Download must emit richer rows:

| Field | Source |
|-------|--------|
| `side` | `missing_in_manago` \| `surplus_in_manago` \| `attribute_empty` |
| `product_id` | shared key |
| `shopify_title` / `shopify_sku` | Shopify active product (pins) |
| `manago_name` / `manago_sku` / `manago_active` | Manago catalog row |
| `proposed_action` / `evidence_gate` | policy §2 |
| `write_entity_key` | `product_id` |

**Also (score-time honesty):** append `attribute_empty` mismatches; attach title/sku on missing samples when cheap.

Optional: live rebuild in transform from pins (prefer — avoid stale).

Evidence aggregate value keys:

| Key | Meaning |
|-----|---------|
| `missing_in_manago` | count |
| `surplus_in_manago` | count |
| `attribute_empty` | count |
| `reconcile_candidate_count` | ready-ish intents |
| `preview_sample_cap` | `PT_SAMPLE` |
| `capability_status` | PRODUCT.IMPORT status |

---

## 4. Mapping (MVP)

**File:** `dataruns/writebacks/mappings/PT-03.catalog_reconcile.v1.json`  
**Hand-authored.** Do **not** use `stub_factory`.

```json
{
  "schema_version": "1.0.0",
  "check_id": "PT-03",
  "template_id": "T7",
  "title": "Reconcile Manago catalog vs Shopify active assortment",
  "enabled": true,
  "approval_tier": "batch",
  "requires_consent_namespace_clean": false,
  "irreversible": true,
  "fix_owner": "Klints (automated)",
  "operator_disclosure": "PT-03 reconciles Manago product catalog to Shopify active products (Excel T7). Catalogue Fix Owner is Klints (automated). Approve upserts missing products and archive-flags surplus entries when Manago semantics allow. Does not run continuous Shopify webhooks (Integration follow-on). Does not hard-delete products. Product ID convention defaults to Shopify product.id = Manago productId. Requires RESTV2.PRODUCT.IMPORT capability confirmed. Re-run DCS after Approve.",
  "rollback": {
    "strategy": "none",
    "note": "product_upsert / archive treated irreversible until reverse archive Loom-proven."
  },
  "operations": [
    {
      "operation_id": "manago.product_upsert.from_shopify",
      "op_kind": "product_upsert",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.PRODUCT.IMPORT",
      "entity_type": "product",
      "from_evidence": {
        "match": { "path": "side", "const": "missing_in_manago" },
        "entity_key": { "path": "write_entity_key" },
        "fields": {
          "product_id": { "path": "product_id" },
          "name": { "path": "shopify_title" },
          "sku": { "path": "shopify_sku" },
          "proposed_action": { "path": "proposed_action" }
        }
      },
      "guards": ["entity_key_required"]
    },
    {
      "operation_id": "manago.product_upsert.archive_surplus",
      "op_kind": "product_upsert",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.PRODUCT.IMPORT",
      "entity_type": "product",
      "from_evidence": {
        "match": { "path": "side", "const": "surplus_in_manago" },
        "entity_key": { "path": "write_entity_key" },
        "fields": {
          "product_id": { "path": "product_id" },
          "proposed_action": { "path": "proposed_action" }
        }
      },
      "guards": ["entity_key_required"]
    }
  ]
}
```

**Registry:**

```json
"PT-03": {
  "file": "PT-03.catalog_reconcile.v1.json",
  "enabled": true,
  "template_id": "T7"
}
```

If archive Loom fails, keep surplus op in mapping but transform marks `ARCHIVE_FLAG` → skipped (honesty) — do not enable Ready surplus without field proof.

Optional third op for `attribute_empty` / `ENRICH_ATTRIBUTES` — **Phase B only** (not default MVP mapping).

---

## 5. Transform + pipeline + adapter

### 5.0 Critical wires

| Wire | Action |
|------|--------|
| `transform.collect_evidence_rows` | `elif PT-03: _pt03_evidence_rows(...)` |
| `_pt03_evidence_rows` | Prefer live `build_catalog_snapshot` from pins; enrich Shopify/Manago fields; set `proposed_action`; cap at effective_max |
| `ARCHIVE_FLAG` without Loom | status skipped `archive_semantics_unknown` (never Ready) |
| Adapter / pipeline dry_run | **Must preserve** incoming `skipped` (do not flip → ready) — honesty gates + archive_enabled |
| Adapter | `ManagoWriteAdapter._execute_intent` → `product_upsert` → discovered HTTP (v3 product/upsert or REST v2 import) |
| `_IMPLEMENTED_OP_KINDS` | Add `product_upsert` |
| Pipeline `effective_max` | `PT-03 → min(PT_SAMPLE, capability_batch_max(PRODUCT.IMPORT) or 100)` |
| Truncation / empty notes | PT-03-specific (missing vs surplus vs attribute_empty vs UNKNOWN catalog) |
| Preflight | Capability must allow execute for Approve; Settings writebacks on |
| Rollback | `strategy=none` → `rollback_not_supported`; irreversible disclosure |
| DCS | `catalog_join` §3.2a surplus teach + `attribute_empty` provenance mismatches |

### 5.1 Denial / honesty copy (examples)

Empty:  
`No catalog reconcile rows in this sample. If PT-03 is UNKNOWN, connect Manago catalog ingest (API v3 key / product feed). If FAIL remains from attribute_empty only, Download lists empty Manago rows — Approve may not fill them in MVP.`

Truncation:  
`Catalog reconcile sample capped at {N} products. Download / Approve again after re-score if PT-03 still FAILs.`

Capability blocked:  
`Manago PRODUCT.IMPORT is not confirmed for execute on this environment — Preview only until Loom upgrades capability status.`

### 5.2 Adapter Loom checklist (blocking)

| Step | Pass criteria |
|------|----------------|
| Auth | API v3 key and/or REST credentials that product upsert accepts |
| Upsert missing | Create/update product with Shopify product.id; appears in next catalog ingest as in-assortment |
| Archive surplus | Document field (`active:false` or archive flag); **and** verify re-score surplus count drops (§3.2a teach) |
| Batch | Confirm `batch_max` (start 100) |
| Errors | Map Manago errors to intent `error` honestly |
| Ship sequence | Mapping+Preview may land while DISCOVERY_REQUIRED; **do not** FE-allowlist execute until CONFIRMED_* (LE-02 pattern) |

After Loom: set `capabilities.json` → `CONFIRMED_LIMITED` or `CONFIRMED_LIVE` + scope_note.

---

## 6. Sheet / SURFACE / FE

### 6.1 Possible sheet (both CSVs)

| Column | Value |
|--------|--------|
| check_id | PT-03 |
| check_name | Catalog completeness vs commerce |
| pack_fix_type | Integration build + Automated writeback (approved) |
| pack_fix_owner | Klints (automated) |
| pack_suggested_fix_summary | One-time T7 product_upsert reconcile + archive surplus (webhooks Integration follow-on) |
| platform | manago |
| op_kind | product_upsert |
| entity | product |
| field_or_key | productId |
| namespace | native |
| write_possible_today | **yes** only after capability CONFIRMED_*; else **no** + blocker note |
| rollback_possible_today | no |
| mapping_file | PT-03.catalog_reconcile.v1.json |
| registry_enabled | true (Preview OK while discovery; execute still gated) |
| blocker | `requires_product_import_confirmed` until Loom |
| evidence_note | missing upsert + surplus archive; scoring excludes archived from surplus; attribute_empty Download-only MVP; no hard-delete; webhooks out; ID=Shopify product.id |
| last_verified | *(ship date)* |

### 6.2 SURFACE

Add row: Catalog reconcile — **Approve after Loom** (WB-20); Klints; T7/`product_upsert`; missing+surplus; irreversible; webhooks deferred.

### 6.3 FE

| Item | MVP |
|------|-----|
| `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | **Add `"PT-03"`** when capability allows execute |
| Honesty | Irreversible + “webhooks not included” + ID convention |
| Friendly evidence | `missing_in_manago` / `surplus_in_manago` / `attribute_empty` readable |

---

## 7. Allowlist / Settings / fix_owner

| Gate | MVP |
|------|-----|
| Settings Allow writebacks | Required for execute |
| `WritebackAllowedCheck` PT-03 | **Seed** (migration) when enabling execute |
| FE allowlist | **On** after capability confirm |
| CheckMaster `fix_owner=Klints (automated)` | Keep |
| Capability `RESTV2.PRODUCT.IMPORT` | **Upgrade** after Loom |

---

## 8. Tests + verify

| Item | Path |
|------|------|
| Django tests | `dataruns/tests/test_writeback_wb20.py` |
| Verify script | `scripts/verify_wb20_pt03_catalog_reconcile.py` |

**Must assert:**

- Registry enabled; mapping T7; `irreversible: true`; two ops (missing + surplus)  
- Capability status documented; execute blocked while DISCOVERY_REQUIRED  
- Expand missing → UPSERT_FROM_SHOPIFY with title/sku when present  
- Surplus without archive Loom → skipped not Ready  
- After archive + §3.2a teach, surplus count excludes inactive products (unit test)  
- attribute_empty never Ready in default MVP mapping  
- PT-01 dangling never written  
- FE allowlist + WritebackAllowedCheck when execute enabled  
- Possible sheet honesty matches capability  
- No stub_factory mapping  
- `rollback.strategy=none` → rollback_not_supported 

---

## 9. Files to touch

| Area | Files |
|------|--------|
| Mapping / registry | `PT-03.catalog_reconcile.v1.json`, `registry.json` |
| Capabilities | `capabilities.json` (after Loom) |
| Adapter / transport | `adapters/manago.py`, `manago_transport.py`, `capabilities.py` (`_IMPLEMENTED_OP_KINDS`) |
| Transform / pipeline / messages | `transform.py`, `pipeline.py` |
| DCS teach + honesty | `catalog_join.py` (§3.2a), `product.py` provenance (`attribute_empty` mismatches) |
| Migration | `WritebackAllowedCheck` seed PT-03 |
| Sheet / SURFACE | both possible CSVs + `WRITEBACK_SURFACE_MATRIX.md` |
| Ownership | §3 PT-03 → Correct Approve; §5 buckets; §6 next |
| FE | `writebacks.ts` allowlist (+ `dcs.ts` friendly) |
| Tests / verify | `test_writeback_wb20.py`, `verify_wb20_pt03_catalog_reconcile.py` |
| Docs | this PRD · ANALYSIS · README |

---

## 10. Acceptance

### Loom gate (before execute)

- [ ] Sandbox upsert missing product succeeds and re-score moves missing count  
- [ ] Archive surplus semantics documented + proven **and** surplus count drops after §3.2a teach  
- [ ] `capabilities.json` → CONFIRMED_LIMITED or CONFIRMED_LIVE  

### MVP

- [x] Excel Suggested Fix language in disclosure (reconcile + archive; webhooks called out as follow-on)  
- [x] CheckMaster `fix_owner=Klints (automated)` confirmed  
- [x] `product_upsert` implemented + `_IMPLEMENTED_OP_KINDS`  
- [x] `catalog_join` surplus excludes inactive/archived (§3.2a) + tests  
- [x] Per-product expand from pins  
- [x] Missing → Ready upsert; surplus → archive Ready or honest skip *(dry_run preserves skipped — 2026-09-26 recheck fix)*  
- [x] attribute_empty not Ready by default; provenance lists it for Download *(attribute_empty scoped to in-assortment with §3.2a)*  
- [x] No hard-delete; no `proposed_action` on Manago wire  
- [x] FE allowlist + WritebackAllowedCheck only after CONFIRMED_* *(omitted until Loom — correct)*  
- [x] Possible sheet ×2 + SURFACE  
- [x] verify_wb20 green  
- [x] Re-score path documented (Approve → DCS → PASS when missing+surplus clear; attribute_empty may remain)  
- [x] Multi-catalog no-default → `needs_catalog_id` skip (PRD §2.3)  

### Phase B (optional / Integration)

- [ ] Shopify product webhooks → continuous upsert  
- [ ] Reverse archive / rollback if Manago supports  
- [ ] `ENRICH_ATTRIBUTES` for attribute_empty Approve  
- [ ] Broader catalogId multi-catalog UX  

---

## 11. Non-goals

PT-01 reopen · BR-01 · hard-delete surplus · webhook MVP · stub_factory · changing FAIL bands · inventing SKU↔product maps · CC/LE/SP regress.

---

## 12. Risks

| Risk | Mitigation |
|------|------------|
| DISCOVERY_REQUIRED forever | Block allowlist; Preview-only until Loom |
| Archive write without scoring teach | §3.2a mandatory; test surplus excludes inactive |
| Wrong ID convention | Scoring SoT + ownership open Q; Download shows both |
| Archive field unknown | Surplus skipped + Download |
| attribute_empty left FAIL | Honesty copy; optional Phase B enrich |
| Irreversible writes | Disclosure + Settings gate + rollback none |
| UNKNOWN without catalog ingest | Honesty copy — fix connector config first |
| Operator expects webhooks | Disclosure + Phase B |
| Invented wire fields | Loom-first; no `_proposed_action` on HTTP |

---

## 13. Parents / next

| | |
|--|--|
| Parents | WB-01 T7 · ownership §6 #1 · catalog_join · connector catalog ingest |
| MVP1 · P0 order | After WB-19 — **last remaining Klints Approve candidate** in MVP1-42 |
| Next after MVP | CI-03 Phase B (optional) · CC Phase B (product) · Integration webhooks · or non-writeback work |
| Unblocks | Catalog honesty; PT-03 FAIL estates with missing/surplus |

---

## 14. Open questions (product)

| # | Question | PRD default |
|---|----------|-------------|
| 1 | Product ID = Shopify product.id or SKU/variant? | **product.id** (matches live scoring) |
| 2 | Archive field name? | **Discover on Loom** (`active:false` candidate) |
| 3 | Ship Preview before Loom? | **Yes** (mapping + expand); **No** FE execute allowlist until CONFIRMED_* |
| 4 | Attribute_empty in MVP Approve? | **No** (Download-only); optional Phase B enrich |
| 5 | Webhooks in same PR? | **No** |
| 6 | `catalogId` required on upsert? | Use default catalog; else skip `needs_catalog_id` |
| 7 | Must scoring exclude archived from surplus? | **Yes — locked** (§3.2a); otherwise archive cannot PASS |

**Sign-off log (Loom + ID convention):**

| Date | Who | Decision |
|------|-----|----------|
| | | |

---

## 15. Related

- [`ANALYSIS_PT03_CATALOG_COMPLETENESS.md`](./ANALYSIS_PT03_CATALOG_COMPLETENESS.md)  
- [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md)  
- [`PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md`](./PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md)  
- [`PRD_WB_19_SP03_DETAIL_SCHEMA_NORMALIZE.md`](./PRD_WB_19_SP03_DETAIL_SCHEMA_NORMALIZE.md)  
- `dataruns/dcs/catalog_join.py` · `dataruns/dcs/executors/product.py`  
- `dataruns/writebacks/capabilities.json` · `dataruns/connectors/manago_ai/client.py`  
