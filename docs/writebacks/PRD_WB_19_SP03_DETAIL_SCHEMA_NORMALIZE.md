# PRD-WB-19 — SP-03 Standard detail schema consistency (format contract + normalise)

**Status:** **MVP shipped 2026-09-26** · Phase B (semantic key merge) optional · P0 M2 Catalogue · Sahil  

**Owner track:** Sahil — **BE primary · FE Approve allowlist + Fix honesty** (pack Fix Owner = **Klints (automated)**)  
**Surfaces:** Fix `/fix` Preview · Approve · FE-12 Download · Settings Allow writebacks · `WritebackAllowedCheck` · registry / mapping · possible sheet · Activity/audit · **DCS segment detail schema** · Manago `detail_set` / upsert **properties**  
**Milestone:** M2 Activation & Blueprint — Segment & Property  
**Depends on:** WB-09 (SP-07 gate) · WB-03…WB-18 · FE-08/09/12 · live `evaluate_sp_03` + `segment_join`  
**PRD path:** `docs/writebacks/`  
**Analysis SoT:** [`ANALYSIS_SP03_DETAIL_SCHEMA_NORMALIZE.md`](./ANALYSIS_SP03_DETAIL_SCHEMA_NORMALIZE.md)  
**Ownership SoT:** [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md) §6 #1  

**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02 Check Catalogue** row **SP-03** (seeded `CheckMaster` extract §3.1)  
- sheet **01 Overview** — **T4 Field normalisation** → `contact_upsert` / property writes  
- sheet **09 MVP1 Check Scope** · SCORED · MVP1-A · weight **4** · High · seq 21  
- `docs/dcs_scoring/CHECK_MASTER_42.md` row SP-03 — *Standard detail schema consistency* · RC-06, RC-08 · **High**  
- WB-01 §1b.2 — T4 → `contact_upsert` (property normalise); native details also writable via proven `detail_set`  
- Ownership §6 #1 — **first pure Klints Approve left**; needs per-key format contract  
- Live proof: DCS-486 one-off cleared SP-03 by rewriting `ORDER_NUMBER` `"1"`→`"1.0"`  

**Out of scope:**  
- **SP-07** reopen / versioned Klints prefix  
- **SP-01** tag consolidation (not in MVP1 42)  
- Silent **semantic key merge/delete** without product rename map (Phase B)  
- Shopify metafield writers  
- Changing SP-03 PASS/FAIL bands  
- Inventing Manago APIs beyond UPSERT properties  
- Stub_factory-generated mapping (wrong defaults)  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-19 — SP-03 detail schema normalise (format contract + Approve).

Read:
- docs/writebacks/PRD_WB_19_SP03_DETAIL_SCHEMA_NORMALIZE.md (this file)
- docs/writebacks/ANALYSIS_SP03_DETAIL_SCHEMA_NORMALIZE.md
- docs/writebacks/WRITEBACK_FIX_OWNERSHIP_MVP1_42.md (§6 #1)
- docs/writebacks/PRD_WB_09_SP07_NAMESPACE_CLEAN_WRITEBACK.md (expand + detail_set pattern)
- dataruns/dcs/executors/segment.py (evaluate_sp_03)
- dataruns/dcs/segment_join.py (_classify_value, inconsistent keys, semantic dupes)
- scripts/dcs_486_easy_fixes_sp03_le09.py (coerce lesson: "1"→"1.0")
- FE: src/lib/writebacks.ts — DO add SP-03 to WRITEBACK_APPROVE_EXECUTABLE

Ship Klints Approve (not plan-only). Owner is Klints.

CRITICAL:
- Fix Owner = Klints (automated) → normal Approve path; seed WritebackAllowedCheck; FE allowlist ON
- requires_consent_namespace_clean=true (SP-07 must PASS)
- Hand-author SP-03.detail_schema_normalize.v1.json — template_id T4; do NOT stub_factory
- Mapping MUST include format_contract (Part A). Transform must read format_contract from mapping JSON (custom top-level key)
- Never majority-win alone (boolean majority was wrong on ORDER_NUMBER)
- Expand key-level inconsistent_sample → per-contact intents (live rebuild from pins + Manago raw)
- Coerce numeric 0/1 / "0"/"1" → decimal string ("1.0") so Manago string round-trip still classifies numeric
- MVP Approve ONLY side=inconsistent_detail_format. Semantic_duplicate_keys = Download honesty only (not Ready)
- rollback.strategy must be revert_detail (detail_set) — NOT restore_prior_field
- entity_key via write_entity_key (email or contactId) — PT-04 pattern
- date. prefix migration only when contract.migrate_date_prefix=true (default off; no MVP op)
- SKIP_NEEDS_CONTRACT → status=skipped (never Ready)
- Update BOTH possible sheets; SURFACE; ownership after ship
- Tests + scripts/verify_wb19_sp03_detail_normalize.py
- Do NOT merge semantic keys; Do NOT touch SP-07/CC/LE mapping; Do NOT regress SP-07 gate

MVP ship:
1. format_contract in mapping (+ default ORDER_NUMBER numeric / decimal_string_if_01)
2. evaluate enrich optional; transform _sp03_evidence_rows expand to contacts
3. detail_set (native) normalise intents; rollback restore prior value
4. pipeline wires; FE allowlist; WritebackAllowedCheck migration
5. Possible sheet ×2 + SURFACE + ownership §3/§5
6. Tests + verify
```

---

## 1. Goal / user story

### 1.0 Problem → outcome

| Today | After WB-19 |
|-------|-------------|
| SP-03 FAILs on mixed detail formats; Fix has thin key-level evidence; ops used one-off scripts | Fix Preview shows per-contact normalise intents; Approve writes normalised Manago properties; re-score → PASS when formats consistent |
| Format contract not productised | Mapping `format_contract` is SoT for target format + coerce |
| Semantic dupes also FAIL | Download lists them; Approve does **not** claim to clear them in MVP |

### 1.1 Excel Suggested Fix = three products

| Part | Product | Ship |
|------|---------|------|
| **A. Format contract** | Per-key target format in mapping config | **MVP required** |
| **B. Approved batch** | Normalise via UPSERT/`detail_set` | **MVP Approve** |
| **C. `date.` prefix** | Migrate date-type keys when proximity wanted | **Contract-gated** (default off) |
| **D. Semantic key consolidate** | Collapse duplicate key names | **Out of MVP** (Phase B) |

### 1.2 Decision locks

| # | Lock | Value |
|---|------|-------|
| 1 | Fix Owner | **Klints (automated)** — Approve (not plan-only) |
| 2 | Do not treat like CC-01/02 | **Yes** — ownership differs |
| 3 | Template | **`template_id: "T4"`** |
| 4 | Op implementation | **`detail_set`** · namespace `native` · `RESTV2.CONTACT.UPSERT` (one property per intent; multi-key contact → multi intents). Excel says “upsert”; same Manago surface — lock `detail_set` for per-key audit/rollback like PT-04/SP-07 |
| 5 | SP-07 gate | **`requires_consent_namespace_clean: true`** |
| 6 | Match rule | **`side` const `inconsistent_detail_format`** — no oneOf |
| 7 | Preview sample | **`SP_SAMPLE` = 50** contact intents (Approve again after re-score if estate larger — same truncation honesty as other batch WBs) |
| 8 | Download | Fuller per-contact normalise list (`SP_DOWNLOAD_CONTACT_CAP=500`) + semantic_dupe groups |
| 9 | Ambiguous key | `SKIP_NEEDS_CONTRACT` → **skipped**, never Ready |
| 10 | Target picker | Explicit contract **first**; else safe heuristic §2; **never raw majority** |
| 11 | 0/1 coerce | Numeric target → `"1.0"` / `"0.0"` style when value is 0/1-like (DCS-486) |
| 12 | Semantic dupes | Download only in MVP |
| 13 | `date.` migrate | Only if `migrate_date_prefix: true` on that key — **no MVP op** until contract enables it |
| 14 | Rollback | **`revert_detail`** (detail_set-allowed strategy — **not** `restore_prior_field`, which is upsert/Shopify-only) |
| 15 | Entity key | **`write_entity_key`** = email if `@` present else `manago_contact_id` (PT-04 pattern; do not require email-only) |
| 16 | Same PR as PT-03 / CC Phase B | **No** |

---

## 2. Policy (format contract)

### 2.1 Mapping `format_contract` shape

```json
"format_contract": {
  "ORDER_NUMBER": {
    "target_format": "numeric",
    "coerce": "decimal_string_if_01"
  },
  "ORDER_AVG": {
    "target_format": "numeric",
    "coerce": "decimal_string_if_01"
  }
}
```

| Field | Meaning |
|-------|---------|
| `target_format` | One of `numeric` \| `boolean` \| `date_like` \| `text` |
| `coerce` | `decimal_string_if_01` \| `identity` \| (extend only with tests) |
| `migrate_date_prefix` | optional bool — if true and target `date_like`, rename key → `date.{key}` |

**Seed MVP contract** for keys seen in live FAIL estates (`ORDER_NUMBER`, and optionally `ORDER_AVG` / `ORDER_SUMMARY` if present). Unknown keys use §2.2 heuristic.

### 2.2 Heuristic when contract missing

1. Non-empty formats ⊆ `{numeric, boolean}` **and** every boolean-classified sample is 0/1-like → target **`numeric`**, coerce `decimal_string_if_01`.  
2. Else exactly one non-empty format → no write (already consistent at value level / skip).  
3. Else → **`SKIP_NEEDS_CONTRACT`**.

### 2.3 Coerce `decimal_string_if_01` (locked)

| Input | Output |
|-------|--------|
| `1`, `"1"`, `True` (if somehow), `1.0` | `"1.0"` |
| `0`, `"0"` | `"0.0"` |
| other numeric-parseable | canonical numeric string without forcing trailing `.0` unless needed for classification |
| non-numeric | do not coerce — skip / error |

After coerce, `_classify_value(after)` **must** equal `target_format` or intent is `error` / skipped (honest).

### 2.4 Proposed actions

| Condition | `proposed_action` | Intent status |
|-----------|-------------------|---------------|
| Value needs coerce to target | `NORMALIZE_DETAIL` | ready |
| Already at target format | — | skipped `already_at_target` |
| No contract + heuristic fail | `SKIP_NEEDS_CONTRACT` | skipped |
| Semantic dupe row only | — | **not an Approve op** (Download provenance only) |
| `migrate_date_prefix` (Part C) | `MIGRATE_DATE_PREFIX` | **Out of MVP mapping** until a second op is added |

---

## 3. Catalogue + live scoring

### 3.1 Catalogue (CheckMaster — seeded Excel SoT)

| Column | Value |
|--------|--------|
| Check ID | **SP-03** |
| Dimension | 04 Segment & Property |
| Check Name | Standard detail schema consistency |
| Check Type | Schema / format |
| Systems Compared | Manago |
| Root Causes | RC-06, RC-08 |
| Severity | **High** |
| DCS Weight | **4** |
| Suggested Fix | Per-key format contract in mapping config; normalisation batch via upsert (approved); date-type details migrated to date. prefix convention where proximity triggers are wanted. |
| Fix Type | Automated writeback (approved) |
| Fix Owner | **Klints (automated)** |
| Cadence | Initial |
| Phase | MVP1-A · SCORED · seq 21 |

Detection Logic empty on seed — live `segment_join` / `evaluate_sp_03` is SoT for PASS/FAIL.

### 3.2 Live scoring (do not change bands)

| Piece | Location |
|-------|----------|
| Join | `segment_join.build_segment_snapshot` |
| Score | `evaluate_sp_03` |
| FAIL if | `inconsistent_keys > 0` **or** `semantic_duplicate_groups > 0` |
| PASS if | no detail keys **or** both counters 0 |
| Sample | `SP_SAMPLE = 50` |

### 3.3 Evidence enrich (MVP required)

Score provenance is **key-level**. Writeback must emit **contact-level** rows:

| Field | Source |
|-------|--------|
| `side` | `inconsistent_detail_format` |
| `key` | detail key |
| `person.email` / `manago_contact_id` | contact |
| `write_entity_key` | email if `@` else contactId (transform-set) |
| `value_before` / `fmt_before` | current |
| `value_after` / `fmt_after` | after coerce |
| `proposed_action` / `evidence_gate` | contract id or `heuristic_numeric_from_01` / `needs_contract` |
| `target_format` | resolved |

**Also persist (honesty):** list of semantic_duplicate groups unchanged for Download.

Optional score-time: attach `inconsistent_contact_rows` uncapped (or rebuild live in transform from pins — prefer live rebuild like CI-05/CC-01 to avoid stale).

Evidence aggregate value keys (honesty):

| Key | Meaning |
|-----|---------|
| `inconsistent_keys` | count |
| `normalise_candidate_count` | contacts needing write |
| `skip_needs_contract_keys` | keys blocked |
| `preview_sample_cap` | `SP_SAMPLE` |
| `semantic_duplicate_groups` | count (Approve does not clear) |

---

## 4. Mapping (MVP)

**File:** `dataruns/writebacks/mappings/SP-03.detail_schema_normalize.v1.json`  
**Hand-authored.** Do **not** use `stub_factory`.

```json
{
  "schema_version": "1.0.0",
  "check_id": "SP-03",
  "template_id": "T4",
  "title": "Normalise Manago detail formats (per-key contract)",
  "enabled": true,
  "approval_tier": "batch",
  "requires_consent_namespace_clean": true,
  "irreversible": false,
  "fix_owner": "Klints (automated)",
  "operator_disclosure": "SP-03 normalises Manago contact detail property formats to a per-key contract (Excel T4). Catalogue Fix Owner is Klints (automated). Approve rewrites mixed-format keys (e.g. ORDER_NUMBER string 1/0 misclassified as boolean → numeric 1.0). Does not merge semantic duplicate key names in MVP — those remain Download-only. Requires SP-07 namespace clean. Re-run DCS after Approve.",
  "format_contract": {
    "ORDER_NUMBER": {
      "target_format": "numeric",
      "coerce": "decimal_string_if_01"
    },
    "ORDER_AVG": {
      "target_format": "numeric",
      "coerce": "decimal_string_if_01"
    },
    "ORDER_SUMMARY": {
      "target_format": "numeric",
      "coerce": "decimal_string_if_01"
    }
  },
  "rollback": {
    "strategy": "revert_detail",
    "note": "Restore prior property value from before-state (detail_set allowed strategy)."
  },
  "operations": [
    {
      "operation_id": "manago.detail_set.normalize_format",
      "op_kind": "detail_set",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.CONTACT.UPSERT",
      "entity_type": "contact",
      "from_evidence": {
        "match": { "path": "side", "const": "inconsistent_detail_format" },
        "entity_key": { "path": "write_entity_key" },
        "fields": {
          "contact_id": { "path": "manago_contact_id" },
          "detail_key": { "path": "key" },
          "detail_value": { "path": "value_after" },
          "email": { "path": "person.email" }
        }
      },
      "guards": ["entity_key_required", "email_format"]
    }
  ]
}
```

**Registry:**

```json
"SP-03": {
  "file": "SP-03.detail_schema_normalize.v1.json",
  "enabled": true,
  "template_id": "T4"
}
```

`SKIP_NEEDS_CONTRACT` / already_at_target → **skipped**, never Ready.

If Part C enabled later, add a second op matching `MIGRATE_DATE_PREFIX` (clear old key + set `date.{key}`) — **not** required for first green SP-03 on ORDER_NUMBER estates.

---

## 5. Transform + pipeline

### 5.0 Critical wires

| Wire | Action |
|------|--------|
| `transform.collect_evidence_rows` | `elif SP-03: _sp03_evidence_rows(...)` |
| `_sp03_evidence_rows` | Load inconsistent keys from worklist **or** live `build_segment_snapshot`; for each key, scan Manago contacts; emit contact rows with coerce |
| Target resolve | `format_contract` from mapping → heuristic §2.2 |
| Intent status | NORMALIZE → ready; SKIP_NEEDS_CONTRACT → skipped; already_at_target → skipped |
| `write_entity_key` | Set on each row before intent build (email or contactId) |
| Pipeline `effective_max` | `SP-03 → SP_SAMPLE` when `max_rows` unset |
| Truncation / empty notes | SP-03-specific honesty (formats vs semantic; Approve again if truncated) |
| Preflight | SP-07 clean required via mapping flag |
| Rollback | `revert_detail` — existing detail_set rollback restores prior value |
| `manago` execute | Existing `detail_set` path |

### 5.1 Denial / honesty copy (examples)

Empty after expand:  
`No mixed-format detail values to normalise in this sample. If SP-03 still FAILs, check semantic duplicate key names (Download) — Approve does not merge keys in MVP.`

Truncation:  
`Detail normalise sample capped at {N} contact writes. Download / Approve again after re-score if SP-03 still FAILs.`

### 5.2 Rollback

`rollback.strategy=revert_detail`. Adapter restores prior property value (empty string clears if prior was absent). Not irreversible. **Do not** use `restore_prior_field` — `rollback_strategy.py` only allows that for `contact_upsert` / Shopify.

---

## 6. Sheet / SURFACE / FE

### 6.1 Possible sheet (both CSVs)

| Column | Value |
|--------|--------|
| check_id | SP-03 |
| check_name | Standard detail schema consistency |
| pack_fix_type | Automated writeback (approved) |
| pack_fix_owner | Klints (automated) |
| pack_suggested_fix_summary | Per-key format contract + normalise Manago detail values via detail_set (T4) |
| platform | manago |
| op_kind | detail_set |
| entity | contact |
| field_or_key | native detail keys (ORDER_NUMBER, …) |
| namespace | native |
| write_possible_today | yes |
| rollback_possible_today | yes |
| mapping_file | SP-03.detail_schema_normalize.v1.json |
| registry_enabled | true |
| blocker | (empty) or `requires_sp07_pass` note in evidence |
| evidence_note | mixed formats only; semantic dupes Download-only; 0/1→1.0 coerce; SP-07 gated |
| last_verified | 2026-09-26 |

### 6.2 SURFACE

Add row: Detail schema normalise — **Approve live** (WB-19); Klints; T4/`detail_set`; format_contract; semantic merge deferred.

### 6.3 FE

| Item | MVP |
|------|-----|
| `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | **Add `"SP-03"`** |
| Honesty | Not needed as non-executable; ensure Fix copy mentions format contract + semantic Download limit |
| Friendly evidence | `inconsistent_detail_format` / `semantic_duplicate_keys` readable |

---

## 7. Allowlist / Settings / fix_owner

| Gate | MVP |
|------|-----|
| Settings Allow writebacks | Required for execute |
| `WritebackAllowedCheck` SP-03 | **Seed** (migration) |
| FE allowlist | **On** |
| CheckMaster `fix_owner=Klints (automated)` | Keep |

---

## 8. Tests + verify

| Item | Path |
|------|------|
| Django tests | `dataruns/tests/test_writeback_wb19.py` |
| Verify script | `scripts/verify_wb19_sp03_detail_normalize.py` |

**Must assert:**

- Registry enabled; mapping T4; `requires_consent_namespace_clean=true`; format_contract present  
- `rollback.strategy=revert_detail` (not restore_prior_field)  
- Coerce `"1"` → `"1.0"` classifies numeric  
- Majority-boolean key with 0/1 samples resolves to numeric via heuristic/contract  
- Ambiguous text+numeric without contract → SKIP_NEEDS_CONTRACT skipped  
- Semantic-only rows never Ready  
- Expand produces per-contact intents with `detail_set`  
- Contact without email but with contactId still Ready via `write_entity_key`  
- FE allowlist includes SP-03; WritebackAllowedCheck seeded  
- Possible sheet `write_possible_today=yes`  
- SP-07 still required / no self-regression  

---

## 9. Files to touch

| Area | Files |
|------|--------|
| Mapping / registry | `SP-03.detail_schema_normalize.v1.json`, `registry.json` |
| Transform / pipeline / messages | `transform.py`, `pipeline.py`, (+ messages if needed) |
| DCS (optional enrich) | `segment.py` / `segment_join.py` only if uncapped contact list persisted |
| Migration | `WritebackAllowedCheck` seed SP-03 |
| Sheet / SURFACE | both `WRITEBACK_POSSIBLE_NOT_SHEET.csv` + `WRITEBACK_SURFACE_MATRIX.md` |
| Ownership | §3 SP-03 → Correct Approve; §5 buckets; §6 next |
| FE | `writebacks.ts` allowlist (+ optional `dcs.ts` friendly) |
| Tests / verify | `test_writeback_wb19.py`, `verify_wb19_sp03_detail_normalize.py` |
| Docs | this PRD · ANALYSIS · README |

---

## 10. Acceptance

### MVP

- [x] Excel Suggested Fix language in disclosure + format_contract in mapping  
- [x] CheckMaster `fix_owner=Klints (automated)` confirmed  
- [x] Per-contact expand from inconsistent keys  
- [x] `"1"`→`"1.0"` coerce path covered by test  
- [x] No raw majority-only target picker  
- [x] Semantic dupes not written  
- [x] SP-07 gate on  
- [x] FE allowlist + WritebackAllowedCheck  
- [x] Possible sheet ×2 + SURFACE  
- [x] verify_wb19 green  
- [x] Re-score path documented (Approve → DCS → SP-03 PASS when formats clean)  
- [x] Download provenance includes fuller per-contact list (`SP_DOWNLOAD_CONTACT_CAP`) + semantic groups  

### Phase B (optional)

- [ ] Semantic key consolidation rename map + product rules  
- [ ] Broader `date.` prefix migrations  

---

## 11. Non-goals

SP-07 reopen · SP-01 · semantic silent merge · plan-only ownership dodge · Shopify metafield write · stub_factory · changing FAIL bands · CC/LE regress.

---

## 12. Risks

| Risk | Mitigation |
|------|------------|
| Boolean majority wrong | Contract + 0/1→numeric heuristic; DCS-486 |
| Manago stores strings | decimal_string coerce |
| Thin key-level evidence | Live per-contact expand |
| Operator expects semantic PASS from Approve | Honesty copy + Download |
| Writing under dirty SP-07 | requires_consent_namespace_clean |

---

## 13. Parents / next

| | |
|--|--|
| Parents | WB-09 · ownership §6 #1 · segment_join · DCS-486 proof |
| MVP1 · P0 order | After WB-18A — **first remaining Klints Approve** |
| Next code after MVP | **PT-03** (after catalog capability) **or** semantic Phase B |
| Unblocks | Schema honesty; headline points on mixed-format FAIL estates |

---

## 14. Open questions (product)

| # | Question | PRD default |
|---|----------|-------------|
| 1 | Op `detail_set` vs multi-prop `contact_upsert`? | **`detail_set`** (audited per key; T4 still; Excel “upsert” = same Manago UPSERT API) |
| 2 | Auto-merge semantic duplicate keys in MVP? | **No** |
| 3 | Seed contract keys beyond ORDER_*? | Start ORDER_NUMBER / AVG / SUMMARY; heuristic for others |
| 4 | `date.` migrate default? | **Off** unless contract says on |
| 5 | Preview cap 50 vs estates with 76+ contacts? | Cap + truncation honesty + re-Approve after re-score (existing batch pattern) |

**Sign-off log (Phase B semantic only):**

| Date | Who | Decision |
|------|-----|----------|
| | | |

---

## 15. Related

- [`ANALYSIS_SP03_DETAIL_SCHEMA_NORMALIZE.md`](./ANALYSIS_SP03_DETAIL_SCHEMA_NORMALIZE.md)  
- [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md)  
- [`PRD_WB_09_SP07_NAMESPACE_CLEAN_WRITEBACK.md`](./PRD_WB_09_SP07_NAMESPACE_CLEAN_WRITEBACK.md)  
- [`PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md`](./PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md)  
- `dataruns/dcs/segment_join.py` · `dataruns/dcs/executors/segment.py`  
- `scripts/dcs_486_easy_fixes_sp03_le09.py`  
