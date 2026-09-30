# Deep analysis — SP-03 Standard detail schema consistency (PRD-ready)

**Status:** Analysis complete — **WB-19 MVP shipped**: [`PRD_WB_19_SP03_DETAIL_SCHEMA_NORMALIZE.md`](./PRD_WB_19_SP03_DETAIL_SCHEMA_NORMALIZE.md).  
**Date:** 2026-09-26  
**Scope:** MVP1-42 check **SP-03** only. Do not conflate with SP-07 (namespace collisions) or SP-01 (tag consolidation, not in 42).  
**Authority:** Excel sheet **02** row SP-03 (via seeded `CheckMaster`) · `CHECK_MASTER_42` · live `evaluate_sp_03` / `segment_join` · ownership §6 #1 · DCS-486 one-off proof (`scripts/dcs_486_easy_fixes_sp03_le09.py`).

---

## 0. One-line verdict

SP-03 **scoring is complete**; **WB-19 MVP Approve is shipped** (format contract + per-contact expand + `detail_set` + FE allowlist). Excel Fix Owner = **Klints (automated)**. Semantic duplicate keys still FAIL the check but remain **Download-only** (no silent merge in MVP).

---

## 1. Excel catalogue (SoT from CheckMaster seed)

| Column | SP-03 value |
|--------|-------------|
| Check ID | **SP-03** |
| Dimension | 04 Segment & Property |
| Name | Standard detail schema consistency |
| Check Type | Schema / format |
| Systems Compared | **Manago** |
| Root Causes | **RC-06, RC-08** |
| Severity | **High** |
| DCS Weight | **4** |
| Cadence | Initial |
| Phase | MVP1-A |
| Role | SCORED |
| Suggested Fix | **Per-key format contract in mapping config; normalisation batch via upsert (approved); date-type details migrated to `date.` prefix convention where proximity triggers are wanted.** |
| Fix Type | **Automated writeback (approved)** |
| Fix Owner | **Klints (automated)** |
| Sheet 09 / CHECK_MASTER | seq **21** · RULE_BASED · Manago · High |

**Fix Template (pack):** T4 Field normalisation → `contact_upsert` (WB-01 §1b.2 / template map). Native detail property writes may also use proven `detail_set` (same UPSERT surface) — PRD locks one.

**Do not confuse:**

| Check | Meaning | This PRD? |
|-------|---------|-----------|
| **SP-03** | Mixed formats / semantic key dupes on Manago details | **Yes** |
| **SP-07** | `klints_` / `klints:` namespace collisions | No — already WB-09; **dependency** (gate) |
| **SP-01** | Tag consolidation | No — not in MVP1 42 |

---

## 2. What already works (DCS)

### 2.1 Pipeline

| Layer | Location | Status |
|-------|----------|--------|
| Join | `dataruns/dcs/segment_join.py` → `build_segment_snapshot()` | **Live** (+ contact sample for Download) |
| Score | `dataruns/dcs/executors/segment.py` → `evaluate_sp_03` | **Live** |
| Tests | `dataruns/tests/test_batch_4c_checks.py` · `test_writeback_wb19.py` | PASS |
| FE Approve allowlist | `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | **SP-03 included** |
| Mapping / registry | `SP-03.detail_schema_normalize.v1.json` | **Enabled (T4)** |
| Possible sheet | both CSVs | **SP-03 yes** |
| One-off proof | `scripts/dcs_486_easy_fixes_sp03_le09.py` | Cleared SP-03 on estate (ORDER_NUMBER `"1"`→`"1.0"`) |

### 2.2 Detection contract (scoring)

**Sources scanned:** Manago contact `properties` / `dictionaryProperties` / `details` / `customFields`.

**Value formats** (`_classify_value`):

| Class | Rule |
|-------|------|
| `empty` | null / blank |
| `boolean` | bool type **or** token in `{true,false,yes,no,y,n,0,1,on,off}` |
| `numeric` | int/float **or** parseable number string |
| `date_like` | ISO / slash dates / epoch-ish digits |
| `text` | else |

**Inconsistent key:** >1 non-empty format class for the same key → FAIL contributor.

**Semantic duplicate groups:** keys that normalise to the same `_semantic_key` (lowercase, strip non-alnum, `average→avg`, `number→num`, `summary→sum`) with >1 distinct key name → FAIL contributor.

**Shopify metafield keys** are surfaced as comparison context only — **not** a FAIL driver alone.

### 2.3 PASS / FAIL

| Condition | Status |
|-----------|--------|
| Manago not connected | NOT_CONNECTED |
| No Manago contacts in raw | UNKNOWN |
| `detail_key_count == 0` | **PASS** (N/A) |
| `inconsistent_keys > 0` **or** `semantic_duplicate_groups > 0` | **FAIL** (RC-06) |
| else | PASS |

Provenance (WB-19):

| `side` | Shape |
|--------|--------|
| `inconsistent_detail_format` (key) | `key`, `format_distribution`, `samples` |
| `inconsistent_detail_format` (contact) | email / contactId / `value_before` / `fmt_before` — **Download fuller list** (cap `SP_DOWNLOAD_CONTACT_CAP`) |
| `semantic_duplicate_keys` | `normalized`, `keys[]` |

**PRD implication (shipped):** Transform expands inconsistent keys → per-contact intents from **pins + Manago raw**. Cap Preview at `SP_SAMPLE` (50); Download evidence includes contact rows up to download cap + semantic groups.

---

## 3. What Excel fix actually requires (decompose Suggested Fix)

| Part | Meaning | In first PRD? |
|------|---------|---------------|
| **A. Per-key format contract** | Mapping config declares target format (+ coerce) per detail key | **Yes — mandatory** |
| **B. Normalisation batch (approved)** | Upsert/detail write normalised values | **Yes — Approve** |
| **C. `date.` prefix migration** | Date-type details → `date.{key}` when proximity triggers wanted | **Phase-gated** (Part C) — only when contract says `migrate_date_prefix=true` |
| **D. Semantic key consolidation** | Collapse ORDER_AVG / orderAvg / … | **Not in Excel Suggested Fix wording** → **Download / Phase B** — do not silent-delete |

If the PRD tries to ship semantic key merges without a rename map, it will surprise operators and break workflows that read the old key.

---

## 4. Live proof lesson (DCS-486) — must lock in PRD

Estate FAIL was almost entirely **`ORDER_NUMBER`**: formats `boolean:55` + `numeric:21` because string `"1"` / `"0"` hit `_BOOL_TOKENS`.

| Attempt | Write | Result |
|---------|-------|--------|
| 1 | JSON number `1` | Manago re-stored as string `"1"` → still **boolean** in DCS |
| 2 | Decimal string `"1.0"` | Classified **numeric** → SP-03 **PASS** |

**Locks:**

1. **Never use raw majority-of-formats as the only target picker** — majority was boolean and wrong.
2. Coerce path for numeric target must produce values that **survive Manago string round-trip** and DCS `_classify_value` → `numeric` (prefer decimal string when value ∈ {0,1} / `"0"`/`"1"`).
3. Any mixed-format key fails the whole check — Fix must clear **all** inconsistent keys present, not only the largest.

---

## 5. Ownership / writeback posture

| Question | Answer |
|----------|--------|
| Fix Owner | **Klints (automated)** |
| Klints Approve? | **Yes** (after PRD + Settings + allowlist) |
| Plan-only? | **No** — not Data lead / CRM |
| Copy CC-03 exception? | N/A — owner already Klints |
| Dependency | **SP-07 PASS** (`requires_consent_namespace_clean=true`) |
| Next after ship | PT-03 (catalog) or product-gated consent Phase B |

---

## 6. Adapter / surface gaps

| Need | Status |
|------|--------|
| `RESTV2.CONTACT.UPSERT` | CONFIRMED_LIVE |
| Write `properties.{KEY}` | Proven via `contact_upsert` / `detail_set` |
| Format contract in mapping | **Shipped** — `format_contract` on SP-03 mapping |
| Per-contact expand from inconsistent keys | **Shipped** — `_sp03_evidence_rows` (pins) |
| Rollback prior property value | `revert_detail` |
| FE allowlist + `WritebackAllowedCheck` | **Shipped** for SP-03 |
| Possible sheet row | **Shipped** |

**Recommended op:** `detail_set` (namespace `native`) for single-key clarity + **`revert_detail`** rollback — **or** `contact_upsert` with `properties` bag when one contact has multiple keys. PRD prefers **`detail_set`** to match PT-04/SP-07 property writes; template_id still **T4**. Do **not** set `rollback.strategy=restore_prior_field` on `detail_set` (strategy mismatch).

---

## 7. Target-format resolution (must lock)

Priority order when building intents for key `K`:

1. **Explicit** `format_contract[K].target_format` in mapping (± `coerce`, `migrate_date_prefix`).
2. Else **safe heuristic** (documented):
   - If non-empty formats ⊆ `{numeric, boolean}` and all boolean-classified samples are 0/1-like → target **`numeric`** with coerce `decimal_string_if_01`.
   - Else if exactly one non-empty format after ignoring `empty` → that format (no-op / skip writes).
   - Else → **`SKIP_NEEDS_CONTRACT`** (Preview/Download only; never Ready).
3. Never coerce `text` ↔ `numeric` without explicit contract.
4. Never invent values for `empty`.

**`date.` migration (Part C):** only when contract sets `migrate_date_prefix: true` and target is `date_like` — write value under `date.{K}` and clear `K` (SP-07-style rename), with reverse_map rollback. Default **off** for MVP keys like ORDER_NUMBER.

---

## 8. Semantic duplicates (FAIL but out of MVP write)

| Option | Ship? |
|--------|-------|
| Surface in Download / provenance | **Yes** |
| Auto-merge / delete loser keys | **No** in WB-19 |
| Optional Phase B rename map | Only after product key-survival rules |

Honesty copy: Approve clears **mixed formats** only; if FAIL remains from semantic_dupes alone, operator must rename in Manago (or future Phase B).

---

## 9. Risks

| Risk | Mitigation |
|------|------------|
| Majority-win → wrong boolean target | Explicit contract + 0/1→numeric heuristic; DCS-486 lesson |
| Manago string round-trip | Coerce to `"1.0"` style for 0/1 numerics |
| Thin provenance | Live expand from pins + Manago raw |
| Semantic merge destroying keys | Out of MVP |
| Writing without SP-07 clean | `requires_consent_namespace_clean=true` |
| Stub_factory T4 | Hand-author mapping; do not stub_factory |
| Mixing SP-07 collisions | SP-03 never renames `klints_*` collisions — SP-07 owns that |

---

## 10. Recommended PRD shape (WB-19)

**Single phase MVP (Approve):** format contract + expand + normalise inconsistent keys + FE allowlist + sheet + tests + verify.

**Phase B (optional):** semantic key consolidation map; broader date-prefix migrations.

**Not optional the way CC Phase B was:** Klints owner means **Approve is the ship**. There is no “plan-only satisfies ownership” escape hatch here.

---

## 11. Related

- [`PRD_WB_19_SP03_DETAIL_SCHEMA_NORMALIZE.md`](./PRD_WB_19_SP03_DETAIL_SCHEMA_NORMALIZE.md)  
- [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md) §6 #1  
- [`PRD_WB_09_SP07_NAMESPACE_CLEAN_WRITEBACK.md`](./PRD_WB_09_SP07_NAMESPACE_CLEAN_WRITEBACK.md) (gate + rename pattern)  
- [`PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md`](./PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md) (T4)  
- `dataruns/dcs/segment_join.py` · `dataruns/dcs/executors/segment.py`  
- `scripts/dcs_486_easy_fixes_sp03_le09.py` · DCS-486 easy-fixes report  
