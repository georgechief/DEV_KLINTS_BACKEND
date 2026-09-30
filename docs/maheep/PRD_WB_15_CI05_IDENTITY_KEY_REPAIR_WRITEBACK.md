# PRD-WB-15 — CI-05 identity key repair writeback

**Status:** **Shipped** — P0 M2 Catalogue Automated writeback · Sahil  

**Owner track:** Sahil — **BE primary · FE Approve allowlist only** (pack Fix Owner = **Klints (automated)**)  
**Surfaces:** Fix `/fix` Approve · Settings Allow writebacks · `WritebackAllowedCheck` · registry / mapping · possible sheet · Activity/audit · **DCS identity mismatches (new)** · Manago `contact_upsert` (`externalId`)  
**Milestone:** M2 Activation & Blueprint — Customer Identity join spine  
**Depends on:** WB-03…WB-14 · FE-08/09 · live `evaluate_ci_05` + `identity_join` · Manago `RESTV2.CONTACT.UPSERT` (**CONFIRMED_LIVE** via CI-01)  
**PRD path:** `docs/maheep/`  
**Contract SoT:** Catalogue Automated writeback for CI-05; Writeback + Identity  
**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02 Check Catalogue** row **CI-05** (headers row 5 — full column map §3.1)  
- sheet **01 Overview** — **T2 Identity key repair** covers **CI-05, CI-16** (“Backfill externalId / klints_erp_id…”). **This PR = CI-05 Manago `externalId` only.** CI-16 / ERP `klints_erp_id` out of scope.  
- sheet **06 Field Mapping Reference** — `person.external_key` ↔ `contact externalId` ↔ `customers.id` (Preferred join spine CI-05; bijective)  
- sheet **09 MVP1 Check Scope** (Identity · SCORED · MVP1-A · weight 4)  
- `docs/dcs_scoring/CHECK_MASTER_42.md` row CI-05 — *External ID linkage integrity* · RC-01, RC-02 · **Critical**  
- WB-01 §1b.2 — T2 → `contact_upsert` (+ optional `detail_set`); stub_factory T2 default `approval_tier=individual` — **CI-05 overrides to `batch`** per Excel “approved batch” (§2 #9)  
- **MVP1 · P0 next list #5** — after LE-09 → LE-05 → LE-02 → PT-04 (all live) → **CI-05** → CI-03 → CC-01/02…  
- WB-02 §3.2 — CI-05 **removed** from “Approve OFF until built” (shipped WB-15)  
**Out of scope:**  
- Resolving **`reused`** link_key clusters (same Shopify id on ≥2 Manago contacts) — **CI-03 merge** / follow-on; see §2  
- Clearing or rewriting **`dangling`** link keys (Manago points at nonexistent Shopify id) without a clean email match  
- CI-16 / ERP `klints_erp_id` `detail_set`  
- Changing CI-05 FAIL bands (`CI05_PASS_LINK_COVERAGE` 0.80 / WARN 0.50)  
- Auto-merge / `contact_merge` (CI-03)  
- Creating new Manago contacts (that is **CI-01** `shopify_only`)  
- Shopify Customer writers  
- Handoff / Studio / QA / CAP product work (Approve allowlist only)  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-15 — CI-05 identity key repair Automated writeback.

Read:
- docs/maheep/PRD_WB_15_CI05_IDENTITY_KEY_REPAIR_WRITEBACK.md (this file)
- docs/maheep/PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md (T2 contact_upsert)
- docs/maheep/PRD_WB_08_CATALOGUE_WAVE2_SP01_LE01.md + `CI-01.identity_backfill.v1.json` (upsert + link_key → externalId)
- dataruns/dcs/executors/identity.py (evaluate_ci_05 — today aggregate-only evidence)
- dataruns/dcs/identity_join.py (link_key_reused / dangling; email sets)
- dataruns/connectors/manago_ai/map.json (link_key ↔ externalId)
- dataruns/writebacks/transform.py (_contact_upsert_payload)
- FE: src/lib/writebacks.ts WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS

Ship:
1. DCS: emit provenance mismatches side=missing_link_key for clean email-matched pairs on FAIL/WARN **and UNKNOWN(with_link=0)** (§3.2); retain driver tags for reused/dangling.
2. Mapping CI-05.identity_key_repair.v1.json — contact_upsert; match missing_link_key; approval_tier=batch; restore_prior_field rollback (§4).
3. Transform: extend _contact_upsert_payload for contactId + prior externalId; bijection guard (§5).
4. Adapter: contact_upsert rollback restore_prior_field for externalId (not only klints_backfill clear) (§5.1).
5. Capability RESTV2.CONTACT.UPSERT already CONFIRMED_LIVE — reuse (§5.2).
6. Pipeline: CI-05 UPSERT ceiling + truncation probe (batch tier — not individual max_rows=1) (§5.3).
7. Enable registry + seed WritebackAllowedCheck CI-05 (§6).
8. Possible sheet (docs + dataruns copies) + SURFACE + FE allowlist (§7–8).
9. Tests + verify_wb15_ci05_identity_key_repair.py (§10).
10. Migration 0042_writeback_allowed_ci05 (after 0041 LE-02).

Do NOT write for reused / dangling / ambiguous email matches.
Do NOT implement CI-03 contact_merge.
Do NOT invent sandbox missing_link_key rows.
Do NOT change CI-05 FAIL bands / coverage thresholds.
Do NOT use approval_tier=individual for CI-05 (Excel approved batch; avoids single-intent trap).
Do NOT add CI-05 to suppressFixProceedToStudio.
Acceptance: §12.
```

---

## 1. Why (simple)

| Before WB-15 | After WB-15 |
|--------------|-------------|
| CI-05 detects broken / thin Manago↔Shopify `externalId` spine (reused, dangling, low coverage) | Catalogue Fix Type AW · T2 · **`contact_upsert` sets `externalId`** — Fix Approve live for **clean missing-link backfills** |
| Evidence is aggregate only (no per-contact provenance) | DCS emits `side=missing_link_key` rows (+ driver tags) |
| Approve OFF (WB-02 §3.2) | FE allowlist + Settings gate |
| Operators rely on fuzzy email for joins | Clean 1:1 email matches get Shopify `customers.id` written as Manago `externalId` |

```text
CI-05 FAIL / WARN / UNKNOWN(with_link=0)
  → If FAIL driven by reused clusters only (no missing_link_key): prefer CI-03 — Preview 0
  → If clean missing_link_key rows exist:
       Fix Preview (contact_upsert — externalId = Shopify customers.id)
    → Approve (Settings ON; batch tier; reversible prior externalId)
    → Manago api/contact/upsert
    → Re-run DCS → coverage / UNKNOWN(with_link=0) improve; reused FAIL may remain
```

---

## 2. Product decisions (locked)

| # | Decision | Lock |
|---|----------|------|
| 1 | Ship **`contact_upsert`** setting native Manago **`externalId`** (= Klints `link_key`) | **Yes** — catalogue T2 + Suggested Fix; map.json `link_key` ↔ `externalId` |
| 2 | Correction target = Shopify **`customers.id`** (string) | **Yes** — sheet Shopify Surface |
| 3 | Match evidence **`side=missing_link_key` only** for writes | **Yes** — never invent from aggregates alone |
| 4 | **MVP1 scope = missing backfill only** (Excel: “from email-matched pairs”) | **Yes** — **reused** / **dangling rewrite** out of this PR |
| 5 | Email match rule for emit | **Exactly one** Manago contact (no link_key) ↔ **exactly one** Shopify customer by normalized email; Shopify id **not** already held as `link_key` by any Manago contact |
| 6 | Ambiguous matches (multi email / multi Shopify) | **Quarantine** — no write; Download / manual (Excel: quarantine ambiguous) |
| 7 | `reused` clusters | **Out of scope** — driver tag + honesty; prefer **CI-03** merge | 
| 8 | `dangling` keys | **Out of scope** this PR (no blind clear); may still FAIL until ops / follow-on |
| 9 | `approval_tier` = **`batch`** | **Yes** — Excel Suggested Fix: “contact upsert **(approved batch)**”. Overrides stub_factory T2 default `individual` so one Approve can clear a sample (≤50). Native `externalId` risk stays in disclosure. Do **not** use `individual` (would force max_rows=1 + `individual_tier_single_intent_required`) |
| 10 | `irreversible` = **false**; rollback = **`restore_prior_field`** for `externalId` | **Yes** — sheet Rollback Note. **Ship work:** today’s `contact_upsert` rollback only clears `klints_backfill` on *created* contacts — extend adapter + snapshot to restore prior `externalId` (§5.1) |
| 11 | `requires_consent_namespace_clean: false` | **Yes** — native field |
| 12 | **No sandbox invent** | **Yes** |
| 13 | Capability = existing **`RESTV2.CONTACT.UPSERT`** CONFIRMED_LIVE | **Yes** — no new capability id |
| 14 | Entity key = Manago **`contactId`** when known; else email | **Yes** — existing contact update, not CI-01 create. **Ship:** `_contact_upsert_payload` must pass `contactId` (today CI-01 path is email-only) |
| 15 | Bijection precheck at enrich / execute | **Yes** — skip intent if Shopify id already used as another contact’s `link_key` |
| 16 | Do **not** add CI-05 to `suppressFixProceedToStudio` | **Yes** |
| 17 | Sample cap | **`CI_MISMATCH_SAMPLE` = 50**; emit from identity/DB — do not rely on capped `link_key_reused[:50]` for writes |
| 18 | Eng owner = **Sahil**; pack Fix Owner = **Klints (automated)** | **Yes** |
| 19 | Optional `detail_set` `klints_erp_id` (T2 overview CI-16) | **Out of scope** — CI-16 not in MVP1-42 |
| 20 | Interaction with CI-01 | CI-01 creates Shopify-only contacts **with** link_key; CI-05 sets link_key on **existing** Manago contacts. Prefer clear CI-01 gaps first when both FAIL — disclosure honesty |
| 21 | Writeback when score is **UNKNOWN** (`with_link=0`) | **Yes** — attach `missing_link_key` on that path so first-time estates can Approve; scoring UNKNOWN unchanged |

### 2.1 Why missing-only (honest FAIL story)

Live estates (e.g. DCS 486) often **FAIL on `reused`**, not on missing keys. Excel Suggested Fix still starts with **backfill from email-matched pairs** + quarantine ambiguous.

| Driver | This PR writes? | Clears CI-05 alone? |
|--------|-----------------|---------------------|
| `missing_link_key` (clean 1:1 email) | **Yes** | Helps coverage / UNKNOWN→scored; improves join spine |
| `reused` | **No** | Need CI-03 (or dedicated dedup PRD) |
| `dangling` | **No** | Follow-on / manual |
| Ambiguous email | **No** | Quarantine |

**Disclosure must say:** Approve CI-05 only backfills **missing** `externalId` on clean matches. Duplicate `externalId` clusters stay FAIL until CI-03.

### 2.2 Lane wall

```text
Sahil WB-15   =  DCS missing_link_key rows + CI-05 mapping + allowlist + FE
Do not regress =  CI-01 / CC-03 / LE-* / PT-04 / SP-07 live writebacks
Out of this PR =  CI-03 merge · CI-16 ERP · dangling rewrite · coverage threshold changes
```

---

## 3. Excel / executor contract (do not invent)

### 3.1 Catalogue (sheet 02 — headers row 5) + CHECK_MASTER

Exact Excel CI-05 row (v1.4.1):

| Column | Value |
|--------|--------|
| Check ID | **CI-05** |
| DCS Dimension | 01 Customer Identity |
| Check Name | External ID linkage integrity |
| Entity | **Contact / Customer** |
| Systems Compared | Manago vs Shopify |
| Check Type | Referential integrity |
| Detection Logic | Manago contact **externalId** populated with Shopify customer ID; verify **bijective** mapping (no externalId reused across contacts, no contact linked to a nonexistent customer) |
| Manago Surface | contact **externalId** |
| Shopify Surface | **customers.id** |
| ERP Surface | ERP customer number (if mapped) |
| Inconsistency Type | Link key missing, duplicated, or dangling |
| Root Causes | RC-01, RC-02 |
| Business Impact | Without a stable join key every future reconciliation degrades to fuzzy email matching; writeback targeting becomes risky |
| Affected Workflows | All cross-system checks and writebacks |
| Severity | **Critical** |
| DCS Weight | High |
| Suggested Fix | Backfill **externalId** from **email-matched pairs** via **contact upsert** (approved batch); enforce the key on all future syncs; **quarantine ambiguous matches** for manual review |
| Fix Type | **Automated writeback (approved)** |
| Fix Owner | Klints (automated) |
| Rollback Note | externalId writes logged per contact; previous value (usually empty) **restorable** from audit log |
| Cadence | Initial + Recurring |
| MVP1 Fix Blueprint | **Y** |
| Fix Template | **T2 Identity key repair** |
| Build Priority | **P0** |

CHECK_MASTER_42: RULE_BASED · SCORED · MVP1-A · weight 4 · Critical · RC-01, RC-02.

**Suggested Fix split (normative for this PR):**

| Part | Catalogue text | WB-15 |
|------|----------------|-------|
| **A** | Backfill externalId from email-matched pairs via contact upsert | **In scope** — `missing_link_key` |
| **B** | Enforce key on future syncs | **Partial** — writeback + existing import map; no new sync pipeline in this PR |
| **C** | Quarantine ambiguous matches | **In scope** — no write (Preview skips) |
| **D** | Bijective repair of reused / dangling | **Out of scope** — CI-03 / follow-on |

### 3.2 Executor SoT (`evaluate_ci_05`) + WB-15 mismatches

```text
UNKNOWN  ⇔  missing connectors / identity / manago_n=0 / with_link=0
FAIL     ⇔  reused OR dangling OR coverage < 0.50
WARN     ⇔  0.50 ≤ coverage < 0.80 (and no reused/dangling)
PASS     ⇔  coverage ≥ 0.80 and no reused/dangling
```

Thresholds (do not change): `CI05_PASS_LINK_COVERAGE = 0.80`, `CI05_WARN_LINK_COVERAGE = 0.50`.

**Today:** aggregate evidence only (`identity.external_id_linkage`) — **no** `provenance.mismatches` list → insufficient for transform bind.

**Provenance mismatches (ship):** actionable `missing_link_key` rows **first**, then driver tags:

```json
{ "side": "missing_link_key", "person.email": "<email>", "manago_contact_id": "<manago uuid>", "shopify_customer_id": "<customers.id>", "prior_external_id": "" }
{ "side": "driver", "driver": "link_key_reused" }
{ "side": "driver", "driver": "link_key_dangling" }
{ "side": "driver", "driver": "low_link_coverage" }
```

**Emit rule (normative) for `missing_link_key`:**

1. From identity join / Contact DB: Manago contacts with **empty** `link_key`.  
2. Normalize email; require **exactly one** Shopify customer with that email.  
3. Require **exactly one** Manago contact with that email (no CI-03 email dup).  
4. Shopify `customers.id` **not** already present as any Manago `link_key` (bijection precheck).  
5. Cap at 50, stable order (email ASC).  
6. Do **not** emit writeable rows for reused / dangling / ambiguous.  

`evaluate_ci_05` attaches these to `provenance.mismatches` on **FAIL**, **WARN**, and **UNKNOWN** when `with_link=0` (MISSING_INPUT:person.external_key) so Fix can backfill a cold estate. Empty actionable list when no clean pairs.

### 3.3 Does Approve clear CI-05?

| Outcome | Honest claim |
|---------|----------------|
| After Approve on `missing_link_key` | Those Manago contacts now carry Shopify `customers.id` as `externalId` (sample capped) |
| After re-score | May move UNKNOWN→scored or improve coverage; **PASS only if** no reused/dangling and coverage ≥ 80% |
| If reused still dominate | Still **FAIL** — Fix CI-03 next |
| Truncated sample | Re-Approve after re-score |

Toast OK: “Writeback applied · CI-05 · N updates · re-run DCS to clear CI-05.”  
Do **not** toast PASS until score returns PASS.

### 3.4 When Fix preview is empty

| CI-05 outcome | Actionable `missing_link_key`? | Fix Approve |
|---------------|--------------------------------|-------------|
| FAIL/WARN/UNKNOWN(with_link=0) with clean missing sample | **Yes** | Preview intents |
| FAIL only reused / dangling / no clean email pairs | **No** | Preview **0** — Download; prefer CI-03 / manual quarantine |
| PASS / NOT_CONNECTED / other UNKNOWN | **No** | N/A |

---

## 4. Mapping — `CI-05.identity_key_repair.v1.json`

### 4.1 Target shape

```json
{
  "schema_version": "1.0.0",
  "check_id": "CI-05",
  "template_id": "T2",
  "title": "Identity key repair (Manago externalId backfill)",
  "enabled": true,
  "approval_tier": "batch",
  "requires_consent_namespace_clean": false,
  "irreversible": false,
  "operator_disclosure": "Sets Manago contact.externalId to the matched Shopify customers.id via contact upsert (native identity key — T2). Approved batch of clean 1:1 email matches with no existing link_key and no bijection conflict. Does not merge duplicate contacts (use CI-03 for reused externalId clusters) and does not rewrite dangling keys. Ambiguous email matches are skipped. Prior externalId (usually empty) is restorable via writeback rollback. Prefer clear CI-01 Shopify-only gaps first when both FAIL. Re-run DCS after Approve.",
  "rollback": { "strategy": "restore_prior_field" },
  "operations": [
    {
      "operation_id": "manago.contact_upsert.external_id_ci05",
      "op_kind": "contact_upsert",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.CONTACT.UPSERT",
      "entity_type": "contact",
      "from_evidence": {
        "match": { "path": "side", "const": "missing_link_key" },
        "entity_key": { "path": "manago_contact_id" },
        "fields": {
          "email": { "path": "person.email" },
          "contact_id": { "path": "manago_contact_id" },
          "link_key": { "path": "shopify_customer_id" },
          "prior_external_id": { "path": "prior_external_id" }
        }
      },
      "guards": ["entity_key_required", "email_format"],
      "mark_klints_backfill": true
    }
  ]
}
```

### 4.2 Registry

```json
"CI-05": {
  "file": "CI-05.identity_key_repair.v1.json",
  "enabled": true,
  "template_id": "T2"
}
```

Remove **CI-05** from WB-02 §3.2 Approve-OFF list when shipping.

---

## 5. Adapter / transport / transform

### 5.1 Reuse CI-01 upsert path — **extend for update + restore**

| Piece | Lock |
|-------|------|
| Catalogue API | Contact upsert — Manago `api/contact/upsert` |
| Field map | Klints `link_key` → Manago `externalId` (`map.json`) |
| Adapter execute | Existing `contact_upsert` — **no new op_kind** |
| Payload | `email` + **`contactId`** (when known) + `externalId` = Shopify customers.id |
| Transform today | `_contact_upsert_payload` is CI-01-shaped (email + link_key; find by email). **Must extend** to set `payload.contactId` from `fields.contact_id` and capture `before.externalId` / `prior_external_id` |
| Dry_run | Validate email + link_key (+ contactId when required); no HTTP write |
| Validate | Missing email / shopify id / bijection conflict → skip / error |
| Rollback strategy | `restore_prior_field` allowed for `contact_upsert` in `rollback_strategy.py` |
| Rollback **today** | Adapter only clears `klints_backfill` when contact was **created** (`existed=False`); skips if pre-existed — **insufficient for CI-05** |
| Rollback **ship** | When strategy=`restore_prior_field`: upsert prior `externalId` (empty string clears) using email/contactId from snapshot |
| **Forbidden** | `contact_merge`; writing reused / dangling / ambiguous rows |

### 5.2 Capability

Reuse existing:

```json
"RESTV2.CONTACT.UPSERT": {
  "status": "CONFIRMED_LIVE",
  "batch_max": 1000
}
```

No new capability key. Execute gate unchanged.

### 5.3 Transform enrich

| Rule | Behavior |
|------|----------|
| Flatten worklist | Same as other checks |
| Re-resolve PII | Never write masked emails |
| Target `link_key` | Always `shopify_customer_id` from mismatch — never invent |
| Contact ref | Prefer `manago_contact_id` on wire as `contactId` |
| Bijection | Drop row if any other Manago contact already has that `link_key` |
| Ambiguous | Already excluded at emit; double-check email uniqueness |
| Empty / no `missing_link_key` in score | Rebuild from **live** `build_identity_snapshot` (same emit rules). Still **0 intents** when live also has no clean pairs — no sandbox invent |
| Reused-only FAIL | **0 intents** + disclosure → CI-03 / Download |

### 5.4 Pipeline

| Rule | Lock |
|------|------|
| Default `max_rows` | Like **SP-07 / PT-04**: `capability_batch_max("RESTV2.CONTACT.UPSERT")` capped ≤1000 (sample emit is 50). **Batch tier** — do not hit individual max_rows=1 path |
| Truncation probe | Include **CI-05** with SP-07/PT-04/LE-02 family: capped at N — Approve again after re-score |
| Sandbox invent | **Never** |
| Once-per-run | Existing WB-04/07 per `(company, CI-05, data_run_id)` |

---

## 6. Allowlist / migration

```text
get_or_create check_id=CI-05, enabled=True, note="PRD-WB-15 CI-05 identity key repair"
```

Migration: **`0042_writeback_allowed_ci05`** (after `0041_writeback_allowed_le02`).

---

## 7. Possible sheet + SURFACE

### 7.1 Possible sheet row (both CSV copies)

| Column | Value |
|--------|--------|
| `check_id` | `CI-05` |
| `check_name` | External ID linkage integrity |
| `pack_fix_type` | Automated writeback (approved) |
| `fix_owner` | Klints (automated) |
| `suggested_fix` | Backfill Manago externalId from clean email-matched Shopify customers.id; quarantine ambiguous; reused → CI-03 |
| `platform` | manago |
| `op_kind` | `contact_upsert` |
| `entity` | contact |
| `field_or_key` | contact externalId (Shopify customers.id) |
| `namespace` | native |
| `creates_new` | no |
| `updates_existing` | yes |
| `write_possible_today` | yes |
| `rollback_possible_today` | yes |
| `mapping_file` | `CI-05.identity_key_repair.v1.json` |
| `evidence_note` | missing_link_key only; bijection guard; no reused/dangling rewrite; prefer CI-01 gaps first when both FAIL |

### 7.2 SURFACE matrix

Update **Contact / identity** row — note **CI-05** externalId backfill via `contact_upsert` (matched missing only; not CI-01 create; not CI-03 merge).  

Enabled-mappings table: add **CI-05** · `contact_upsert` · Enabled (WB-15).

---

## 8. Frontend

| Item | Lock |
|------|------|
| `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | Add **`CI-05`** |
| Honesty blurb | Identity key repair; reused clusters need CI-03; ambiguous skipped |
| Toast | Re-run DCS to clear CI-05 |
| `suppressFixProceedToStudio` | **Do not** add CI-05 |
| `verify-wb02-frontend.mjs` | Assert CI-05 allowlisted |
| WB-02 §3.2 | Remove CI-05 from OFF list |

No new Fix chrome. Deep-link: `/fix?issue=CI-05`.

---

## 9. Gates / settings

Unchanged: Settings Allow writebacks · sandbox company rules · ADMIN execute · once-per-run · capability CONFIRMED · operator disclosure before Approve.

---

## 10. Tests + verify

| Case | Expect |
|------|--------|
| Registry CI-05 enabled; match `missing_link_key`; op_kind `contact_upsert`; T2; **batch** | |
| `evaluate_ci_05` emits `missing_link_key` on FAIL/WARN and UNKNOWN(with_link=0) | |
| Ambiguous / reused / dangling do **not** emit writeable missing rows | |
| Transform builds intent with contactId + link_key=shopify_customer_id; bijection skip | |
| Empty mismatches → 0 intents (no sandbox) | |
| Adapter upsert; rollback restores prior externalId (`restore_prior_field`) | |
| Allowlist migration seeds CI-05 | |
| FE allowlist includes CI-05 | |
| CI-01 unchanged | |

Script: `scripts/verify_wb15_ci05_identity_key_repair.py` — registry, mapping (`approval_tier=batch`, `restore_prior_field`), allowlist, both sheet copies, FE string, DCS mismatch helper, adapter rollback path present, no CI-03 merge on CI-05 path.

---

## 11. PR / branch

- **Base:** tip with WB-13/14 merged  
- BE: `feat(WB-15): CI-05 identity key repair writeback`  
- FE: `feat(WB-15): enable CI-05 Fix Approve`  
- PR body: link this PRD · “T2 contact_upsert externalId; missing_link_key only; approved batch; quarantine ambiguous; reused → CI-03; restore_prior_field”

---

## 12. Acceptance checklist

- [x] DCS emits `side=missing_link_key` per §3.2 on FAIL/WARN/**UNKNOWN(with_link=0)**; driver tags retained  
- [x] Mapping `CI-05.identity_key_repair.v1.json` enabled; registry live; template T2; **`approval_tier=batch`**  
- [x] Transform passes `contactId` + bijection + ambiguous guards; no sandbox invent  
- [x] Adapter **`restore_prior_field`** restores prior `externalId` on contact_upsert  
- [x] Uses `RESTV2.CONTACT.UPSERT` CONFIRMED_LIVE (no new capability)  
- [x] Pipeline truncation probe for CI-05; UPSERT ceiling (batch — not individual max_rows=1)  
- [x] `0042_writeback_allowed_ci05` seeds CI-05  
- [x] Possible sheet (docs + runtime) + SURFACE synced; rollback=yes  
- [x] FE Approve allowlist includes CI-05; honesty + toast; **not** in Proceed suppress list  
- [x] Settings OFF → no execute  
- [x] Tests + `verify_wb15_ci05_identity_key_repair.py` green  
- [x] WB-02 §3.2 CI-05 removed from OFF list; no merge op; reused not written  
- [x] CI-05 FAIL bands / coverage thresholds untouched  

---

## 13. Explicitly not in this PR

- CI-03 `contact_merge` / resolving reused clusters  
- Rewriting or nulling dangling `externalId` without clean email match  
- CI-16 / `klints_erp_id`  
- Changing 80% / 50% coverage thresholds  
- Raising identity_join `link_key_reused[:50]` cap for write completeness of reused (irrelevant to missing-only writes)  
- Shopify Customer metafield / note writers  

---

## 14. Code reference map

| Path | Role |
|------|------|
| `dataruns/dcs/executors/identity.py` | `evaluate_ci_05` + **new** mismatch rows |
| `dataruns/dcs/identity_join.py` | Emit candidates for missing_link_key |
| `dataruns/writebacks/mappings/CI-05.identity_key_repair.v1.json` | **New** |
| `dataruns/writebacks/mappings/registry.json` | Enable CI-05 |
| `dataruns/writebacks/transform.py` | `_ci05_evidence_rows` / enrich / bijection |
| `dataruns/writebacks/adapters/manago.py` | Existing `contact_upsert` |
| `dataruns/connectors/manago_ai/map.json` | `link_key` ↔ `externalId` |
| `dataruns/writebacks/pipeline.py` | CI-05 ceiling + truncation |
| `dataruns/writebacks/rollback_strategy.py` | `restore_prior_field` for CI-05 |
| FE `src/lib/writebacks.ts` | Approve allowlist + honesty |

---

## 15. Traceability

| Field | Value |
|-------|--------|
| Milestone | M2 — Catalogue Automated writeback |
| Pack | Catalogue CI-05 P0 T2 |
| MVP1 · P0 order | **#5** after LE-09 / LE-05 / LE-02 / PT-04 |
| Parents | WB-01…14 · DCS identity · catalogue Suggested Fix |
| Unblocks | Stable join spine for later checks / writebacks |
| Next | **CI-03** (T3 Contact merge) per MVP1 list |

---

## 16. Decision log (deep-check + Excel)

| # | Question | Answer |
|---|----------|--------|
| 1 | Ship CI-05 with aggregate-only evidence? | **No** — must emit `missing_link_key` rows |
| 2 | Include reused repair in same PR? | **No** — Excel starts with email-matched backfill; reused → CI-03 |
| 3 | New op_kind? | **No** — reuse `contact_upsert` + UPSERT capability |
| 4 | `approval_tier` batch or individual? | **`batch`** — Excel “approved batch”; overrides T2 stub `individual` (avoids max_rows=1 + single-intent block) |
| 5 | Irreversible? | **No** — sheet: prior value restorable; **extend** upsert rollback for `externalId` |
| 6 | Ambiguous email? | **Quarantine** — no write |
| 7 | Overview T2 also CI-16? | ERP `klints_erp_id` out of scope (not MVP1-42) |
| 8 | After this? | **CI-03** on MVP1 list |
| 9 | Will Approve always PASS CI-05? | **No** — honest if reused remain |
| 10 | UNKNOWN with_link=0 writeable? | **Yes** — emit mismatches so cold estates can Approve |
| 11 | Does CI-01 upsert payload already set contactId? | **No** — extend for CI-05 |

---

## 17. Deep-check evidence (2026-09-24; draft recheck same day)

| Source | Finding |
|--------|---------|
| Excel §02 CI-05 (all cols) | AW · T2 · P0 · Blueprint Y · Critical · upsert externalId · **approved batch** · quarantine ambiguous · restorable |
| Excel §01 T2 | CI-05 + CI-16 — only CI-05 in this PR; CI-16 not in MVP1-42 |
| Excel §06 | `person.external_key` preferred join spine; bijective |
| CHECK_MASTER_42 | External ID linkage · RC-01/02 · Critical · weight 4 |
| `evaluate_ci_05` | Provenance `missing_link_key` + drivers; UNKNOWN(with_link=0) attaches mismatches |
| `identity_join` | Emits `missing_link_key` (guest Shopify ids excluded); `link_key_reused` / `dangling` capped 50 |
| map.json | `link_key` ↔ Manago `externalId` |
| CI-01 mapping | Upsert + link_key **create** path; email entity_key; rollback tagged_backfill_delete |
| `_contact_upsert_payload` / adapter rollback | **Shipped:** contactId on wire; `restore_prior_field` restores externalId |
| Pipeline | CI-05 UPSERT ceiling + truncation (batch tier) |
| Registry / mapping | `CI-05.identity_key_repair.v1.json` enabled · T2 · batch |
| Capability | `RESTV2.CONTACT.UPSERT` CONFIRMED_LIVE |
| Worklist | CI-05 cold UNKNOWN (`MISSING_INPUT:person.external_key`) included for Fix |
| FE / WB-02 OFF | CI-05 allowlisted; removed from OFF list |
| M3 DEMO gaps | CI-05 Live (WB-15) |
| Live DCS 486 | FAIL reused (cap 50 / real ~201) — reinforces reused out of WB-15 write scope |

### Draft recheck fixes applied
1. `approval_tier` → **batch** (Excel + avoid individual trap).  
2. Emit / Preview on **UNKNOWN(with_link=0)**.  
3. Explicit ship work: extend upsert payload (`contactId` + prior) + **restore_prior_field** rollback for `externalId`.  
4. Pipeline = UPSERT ceiling family (SP-07/PT-04), not contradictory “individual but not max_rows=1”.

### Post-ship deep-check fixes (2026-09-24)
1. **Worklist:** CI-05 `UNKNOWN` + `MISSING_INPUT:person.external_key` now Fix-actionable (scoring still UNKNOWN).  
2. **Emit:** Shopify guest `email:` ids excluded; real customer preferred when guest coexists.  
3. **Provenance cap:** driver tags no longer dropped when missing sample is full (50).  
4. **Transform enrich:** resolve email via `manago_contact_id` + `normalize_email`; skip guests; no PII masks on wire.  
5. Evidence element label for `missing_link_key`.  
6. **Empty preview root cause (live probe):** estates often hold clean `missing_link_key` pairs in Contact DB while the latest `dcs-score` predates WB-15 (snap has no `missing_link_key` → provenance mismatches empty → “Nothing ready to write”). **Fix:** preview rebuilds candidates from live `build_identity_snapshot` when worklist lacks `missing_link_key` (same emit rules — not sandbox invent).  
7. **Reused-only FAIL (e.g. localhost / DCS-486 style):** live `missing_link_key_count=0` → Preview 0 is **honest**; Excel Part D (reused repair) is **CI-03**, not WB-15. Empty-preview disclosure now says so.  
8. **Operator action:** re-run Data Consistency Score after deploy so worklist evidence matches writeback.
