# PRD-WB-11 — PT-04 `klints_net_ltv` writeback

**Status:** **Shipped (WB-11)** — P0 M2 Catalogue Automated writeback · Sahil  

**Owner track:** Sahil — **BE primary · FE Approve allowlist only**  
**Surfaces:** Fix `/fix` Approve · Settings Allow writebacks · `WritebackAllowedCheck` · registry / mapping · possible sheet · SP-07 owned-key allowlist · Activity/audit  
**Milestone:** M2 Activation & Blueprint (T2) — Product & Transaction depth after WB-10  
**Depends on:** WB-03…WB-10 · FE-08/09 · POLISH-01 · DCS `evaluate_pt_04` + `product_truth` live · SP-07 gate for `klints_*` writes  
**PRD path:** `docs/maheep/` (writeback series numbering only — **owner is Sahil**)  
**Parallel with:** Maheep WB-08/09/10 stack if unmerged — shares `dataruns/writebacks/**`; coordinate branch base  
**Contract SoT:** Catalogue Automated writeback for PT-04; Writeback + Lifecycle live  
**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02 Check Catalogue** row **PT-04**  
- sheet **09 MVP1 Check Scope** (Product & Transaction · SCORED · MVP1-A)  
- `docs/dcs_scoring/CHECK_MASTER_42.md`  
- Manago Execution Capability Matrix · `RESTV2.CONTACT.UPSERT` (CONFIRMED_LIVE)  
- Excel Suggested Fix: *Land LE-09 returns pipe, then recompute; where platform totals cannot net refunds, maintain `klints_net_ltv` detail as the governed value and point workflows at it.*  
**Out of scope:**  
- Implementing Manago `event_correct` / `event_update` adapters (pack T6 label ≠ required op_kind for this Suggested Fix)  
- Changing PT-04 DCS FAIL/PASS bands / `product_truth` formulas (provenance union §3.4 is allowed)  
- Re-running LE-09 inside this PR (WB-10 already ships returns pipe)  
- Teaching PT-04 to PASS when `klints_net_ltv` matches net → **WB-12**  
- ERP credit-note cross-check  
- Shopify Order writers  
- Turning global `WRITEBACKS_ENABLED=True` outside Settings gate  
- Handoff / Studio / QA / CAP  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-11 — PT-04 klints_net_ltv Automated writeback.

Read:
- docs/maheep/PRD_WB_11_PT04_NET_LTV_WRITEBACK.md (this file)
- docs/maheep/PRD_WB_10_LE09_RETURN_EVENT_WRITEBACK.md (dependency honesty)
- docs/maheep/WRITEBACK_SURFACE_MATRIX.md
- dataruns/dcs/executors/product.py (evaluate_pt_04)
- dataruns/dcs/product_truth.py
- dataruns/writebacks/mappings/CC-03.consent_provenance.v1.json (detail_set pattern)
- dataruns/writebacks/adapters/manago.py (detail_set)
- dataruns/dcs/segment_join.py (owned keys from enabled mappings)
- FE: src/lib/writebacks.ts WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS

Ship:
1. New mapping PT-04.net_ltv.v1.json — detail_set klints_net_ltv (§4).
2. Minimal evaluate_pt_04 provenance union: failing ∪ refund_blind (§3.4) — scores unchanged.
3. Transform: match side=net_overstatement; write_entity_key; shopify_net (§5).
4. Enable registry + seed WritebackAllowedCheck PT-04 (§6).
5. Update SP-07 owned-key expectations: klints_net_ltv becomes owned (§6.2). Re-score order.
6. Possible sheet + SURFACE matrix + FE allowlist (§7–8).
7. Tests + verify script (§10). Honest “may not PASS PT-04” disclosure.
8. Migration 0039 WritebackAllowedCheck PT-04.

Do NOT implement event_correct adapter.
Do NOT change PT-04 FAIL bands / revenue formula.
Do NOT claim Approve clears PT-04 PASS.
Do NOT touch handoff / Studio / QA / CAP.
Acceptance: §12.
```

---

## 1. Why (simple)

| Today | Gap |
|-------|-----|
| PT-04 **detects** Manago lifetime purchase value overstated vs Shopify net (orders − refunds) | Catalogue Fix Type = **Automated writeback (approved)** — **no mapping** |
| Excel Suggested Fix: LE-09 pipe **then** governed `klints_net_ltv` | LE-09 writeback shipped (WB-10); PT-04 Fix Approve still missing |
| VIP / loyalty / value-tier pilots gate on PT-04 | Gate without Fix = product trap (G10) |

**WB-11** ships Fix Approve so a tenant can **stamp `klints_net_ltv` = Shopify net** on overstated Manago contacts, then re-score / point workflows at the Klints-governed value.

```text
Prefer: LE-09 PASS (returns reflected) → re-run DCS
If PT-04 still FAIL (platform cannot net refunds in Manago totals):
  → Fix Preview (detail_set klints_net_ltv = shopify_net)
  → Approve (Settings ON; SP-07 PASS for klints_ writes)
  → Manago upsert properties
  → Workflows / VIP use klints_net_ltv (PT-04 check may still FAIL on re-score — honest)
```

---

## 2. Product decisions (locked)

| # | Decision | Lock |
|---|----------|------|
| 1 | Ship **detail_set** `klints_net_ltv` (not `event_correct`) | **Yes** — Excel Suggested Fix is the detail; T6 label is pack taxonomy only |
| 2 | Match evidence `side=net_overstatement` | **Yes** (executor SoT) |
| 3 | `detail_value` = evidence `shopify_net` (governed net LTV) | **Yes** |
| 4 | `requires_consent_namespace_clean: true` | **Yes** (same class as CC-03) |
| 5 | `irreversible: false`; rollback `revert_detail` | **Yes** (Excel: removable in bulk) |
| 6 | No hard execute-block on LE-09 status | **Yes** — disclosure prefers LE-09 first; writeback still allowed |
| 7 | Do not change PT-04 **FAIL/PASS bands** or revenue formula | **Yes** |
| 8 | Enabling PT-04 makes `klints_net_ltv` **owned** for SP-07 | **Yes** — update WB-09 tests/verify that asserted it foreign |
| 9 | FE = allowlist `PT-04` only | **Yes** |
| 10 | Approval tier = **batch** | **Yes** (multi-contact FAIL sample) |
| 11 | Owner = **Sahil** | **Yes** |
| 12 | Writeback does **not** make PT-04 PASS by itself | **Yes** — executor compares PURCHASE totals ↔ Shopify net; it does **not** read `klints_net_ltv`. Success = stamp + point workflows at it (Excel wording) |
| 13 | Provenance must expose actionable rows for refund_blind-only FAIL | **Yes** — minimal `evaluate_pt_04` mismatch union allowed (§3.4); scores unchanged |

**Lane wall:**

```text
Sahil WB-11   =  PT-04 mapping + transform + allowlist + FE Approve list
Do not regress =  live writebacks (CI-01 / CC-03 / LE-01 / SP-07 / LE-09 / WB-SHOP-01)
Out of this PR =  Studio / HO / QA / CAP unless required for PT-04 Fix path
```

---

## 3. Excel / executor contract (do not invent)

### 3.1 Catalogue (sheet 02)

| Field | Value |
|-------|--------|
| Check | Net vs gross transaction truth per contact |
| Surfaces | Manago transaction statistics (total spend) vs Shopify orders − refunds per customer |
| Depends on | LE-09 returns pipe |
| Suggested Fix | LE-09 first; else maintain **`klints_net_ltv`** as governed value |
| Fix Type | **Automated writeback (approved)** |
| Fix Owner | Klints (automated) |
| Template | **T6** Event correction *(pack name — implement via `detail_set`, see §2)* |
| Priority | **P0** |
| Rollback note | `klints_net_ltv` is Klints-namespaced detail; removable in bulk |

### 3.2 Live executor evidence (`evaluate_pt_04`)

Mismatch rows today:

```json
{
  "side": "net_overstatement",
  "person.email": "...",
  "shopify_customer_id": "...",
  "manago_contact_id": "...",
  "shopify_net": 123.45,
  "manago_purchase_value_deduped": 200.0,
  "delta_vs_net": 0.62,
  "refund_blind": true,
  "overstatement": 76.55
}
```

**Critical:** Match const is **`net_overstatement`**. Value to write is **`shopify_net`**.

### 3.3 Does Approve clear the PT-04 check?

**No — not with today’s executor.**

`evaluate_pt_04` compares Manago PURCHASE lifetime (deduped) vs Shopify net. It does **not** consult `klints_net_ltv`. Stamping the detail therefore:

| Outcome | Honest claim |
|---------|----------------|
| After Approve | Manago contact has `klints_net_ltv` = Shopify net |
| After re-score | PT-04 may **still FAIL** |
| Product intent (Excel) | Workflows / VIP / value tiers **point at `klints_net_ltv`**, not raw Manago lifetime |

Fix UI / disclosure must not toast “PT-04 fixed / PASS”. Prefer: “Governed net LTV stamped — point workflows at `klints_net_ltv`. Re-score may still show PT-04 FAIL until product truth uses the detail (future) or LE-09 clears refund blindness.”

Follow-on: **[PRD-WB-12](./PRD_WB_12_PT04_PASS_ON_KLINTS_NET_LTV.md)** — teach PT-04 to PASS when `klints_net_ltv` matches `shopify_net`.

### 3.4 Provenance gap — refund_blind-only FAIL

Today mismatches are built **only** from `failing_sample` (`delta_vs_net > PT04_DELTA_FAIL`).  
Status can still FAIL when `contacts_refund_blind > 0` with **empty** mismatches (absolute refund gap without relative fail).

`refund_blind_sample` rows in `product_truth` are the same shape as failing rows but **lack** `side`. Worklist bind reads **`provenance.mismatches` only** — evidence.value samples are not enough.

**WB-11 allows a minimal executor provenance fix (scores unchanged):**

```text
mismatches = project(failing_sample ∪ refund_blind_sample)
  - dedupe by manago_contact_id
  - each projected row stamps side=net_overstatement + same fields as today’s failing projection
  - cap PT_SAMPLE=50 (product.py / product_truth constant)
```

Do **not** change `PT04_DELTA_FAIL`, FAIL/PASS bands, or revenue formula.  
Evidence.value may still truncate samples to 20 — that is display only; mismatches drive writeback.

### 3.5 When Fix preview is empty (honest)

| PT-04 outcome | Actionable `net_overstatement` rows? | Fix Approve |
|---------------|--------------------------------------|-------------|
| FAIL with failing/refund_blind samples (after §3.4) | **Yes** (up to 50) | Preview intents |
| FAIL with aggregate only (no ids / no sample rows) | **No** | Preview **0** — Download evidence |
| PASS / UNKNOWN / NOT_CONNECTED | **No** | N/A |

PT-04 has **no WARN** band today — do not invent one.

### 3.6 Adapter already live

`ManagoWriteAdapter` `detail_set` → contact upsert `properties` (same as CC-03).  
Rollback strategy `revert_detail` already supported for `detail_set`.  
`_detail_set_payload` already resolves `email` **or** `contactId` from `entity_key` (contactId when no `@`).

`event_correct` / `event_update` remain **stubs** — do not build them in WB-11.

`email_format` guard only fires when `entity_key` contains `@` — contactId keys are OK.

---

## 4. Mapping — `PT-04.net_ltv.v1.json`

### 4.1 Target shape

```json
{
  "schema_version": "1.0.0",
  "check_id": "PT-04",
  "template_id": "T6",
  "title": "Governed net LTV detail (klints_net_ltv)",
  "enabled": true,
  "approval_tier": "batch",
  "requires_consent_namespace_clean": true,
  "irreversible": false,
  "operator_disclosure": "Prefer LE-09 PASS before stamping net LTV. Sets klints_net_ltv to Shopify net. After Approve, re-run DCS — PT-04 PASSes when stamped net matches Shopify net (see live mapping / WB-12).",
  "rollback": { "strategy": "revert_detail" },
  "operations": [
    {
      "operation_id": "manago.detail_set.klints_net_ltv",
      "op_kind": "detail_set",
      "target": "manago",
      "namespace": "klints_",
      "capability_id": "RESTV2.CONTACT.UPSERT",
      "entity_type": "contact",
      "from_evidence": {
        "match": { "path": "side", "const": "net_overstatement" },
        "entity_key": { "path": "write_entity_key" },
        "fields": {
          "detail_key": { "const": "klints_net_ltv" },
          "detail_value": { "path": "shopify_net" },
          "email": { "path": "person.email" },
          "contact_id": { "path": "manago_contact_id" }
        }
      },
      "guards": ["entity_key_required", "email_format", "klints_prefix"]
    }
  ]
}
```

`write_entity_key` is set by transform (§5): valid email if present, else `manago_contact_id`. Never invent emails.

### 4.2 Registry

```json
"PT-04": {
  "file": "PT-04.net_ltv.v1.json",
  "enabled": true,
  "template_id": "T6"
}
```

### 4.3 Honesty

- Preview exposes `operator_disclosure` (LE-09 preference + **may not PASS PT-04**).  
- Rollback supported via `revert_detail` (clear/restore prior `klints_net_ltv`).  
- Not irreversible — do not show LE-01-style irreversible modal.  
- Never toast “PT-04 PASS” / “check cleared” solely from this write.

---

## 5. Transform — evidence bind + enrich

### 5.1 Worklist bind

```text
elif normalized == "PT-04":
    rows = _pt04_evidence_rows(...)
```

### 5.2 `_pt04_evidence_rows`

| Rule | Behavior |
|------|----------|
| Match | `_evidence_side(row) == "net_overstatement"` only |
| Enrich | Flatten nested worklist `value` |
| Require | `shopify_net` numeric (incl. 0 / negative if commerce net is negative) |
| Identity | Need `person.email` **or** `manago_contact_id` |
| `write_entity_key` | `person.email` if `@` present; else `manago_contact_id` |
| Resolve | Fill missing email/contact from Manago snapshot / Contact DB — **no fake emails** |
| Cap | UPSERT batch_max (like SP-07/LE-09) + truncation disclosure; DCS mismatches ≤ `PT_SAMPLE` (50) — re-Approve after re-score if more contacts remain |
| Empty / non-actionable | No sandbox by default |
| Skip | No `shopify_net`; no email and no contact id |
| Already at target | Skip when prior `klints_net_ltv` equals `shopify_net` (`already_at_target`) — same pattern as CC-03 |

### 5.3 Payload after bind

```text
properties.klints_net_ltv = shopify_net   # string/number per detail_set coercion
email | contactId       = resolved identity
entity_key              = write_entity_key
```

---

## 6. Allowlist + SP-07 owned keys

### 6.1 Migration

After `0038_writeback_allowed_le09` → new **`0039_writeback_allowed_pt04`**:

```text
get_or_create check_id=PT-04, enabled=True, note="PRD-WB-11 PT-04 klints_net_ltv"
```

Do **not** remove other allowlisted checks.

### 6.2 SP-07 owned-key flip (required)

Today WB-09 tests/verify assert `klints_net_ltv` is a **foreign** collision.  
When PT-04 mapping is enabled with `namespace: klints_` + `detail_key: klints_net_ltv`, `segment_join._owned_keys_from_enabled_mappings` treats it as **owned**.

**Operational order (preflight):**

```text
1. Ship PT-04 mapping enabled in registry
2. Re-score DCS so SP-07 no longer flags klints_net_ltv as foreign
3. Then PT-04 Approve can pass requires_consent_namespace_clean
```

If other foreign `klints_*` collisions remain, SP-07 still FAIL → PT-04 execute stays blocked (correct).

**Must update in this PR:**

- `scripts/verify_wb09_sp07_namespace_clean.py` — stop requiring foreign `klints_net_ltv`; assert owned when PT-04 enabled  
- `dataruns/tests/test_writeback_wb09.py` cases that assert `is_klints_owned_detail("klints_net_ltv") is False`  
- `dataruns/tests/test_batch_4c_checks.py` (and any SP-07 fixture) that uses `klints_net_ltv` as the **foreign** example — switch fixture to a key that stays unowned (e.g. `klints_foreign_example`) **or** run with PT-04 registry disabled in that test  
- Prefer: assert `klints_net_ltv` owned **when PT-04 registry enabled**

---

## 7. Possible sheet + matrix

### 7.1 CSV row

| Column | Value |
|--------|--------|
| `check_id` | `PT-04` |
| `check_name` | Net vs gross transaction truth per contact |
| `pack_fix_type` | Automated writeback (approved) |
| `pack_fix_owner` | Klints (automated) |
| `pack_suggested_fix_summary` | Stamp klints_net_ltv = Shopify net on overstated Manago contacts |
| `platform` / `op_kind` | `manago` / `detail_set` |
| `field_or_key` | `klints_net_ltv` |
| `namespace` | `klints_` |
| `write_possible_today` | `yes` |
| `rollback_possible_today` | `yes` |
| `mapping_file` | `PT-04.net_ltv.v1.json` |
| `registry_enabled` | `true` |
| `evidence_note` | detail_set klints_net_ltv from side=net_overstatement; requires SP-07 PASS; prefer LE-09 first |

Sync both `dataruns/writebacks/` and `docs/maheep/` CSV copies.

### 7.2 SURFACE matrix

- Manago Contact details row: note **PT-04** writes `klints_net_ltv`.  
- Enabled mappings table: add **PT-04**.

### 7.3 WB-02 pending list

When shipping, remove `PT-04` from “Approve OFF until built”.

---

## 8. Frontend (minimal)

| File | Change |
|------|--------|
| `src/lib/writebacks.ts` | Add **`PT-04`** to `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` |
| same | Surface `operator_disclosure` (LE-09 preference) on Approve |
| `scripts/verify-wb02-frontend.mjs` | Assert PT-04 allowlisted |

No new Fix chrome.

---

## 9. Reuse existing harden

| PRD | Must still hold |
|-----|-----------------|
| WB-03 | Settings default OFF |
| WB-04 / WB-07 | Once-per-run + claim-before-write |
| WB-06 | Status / Written restore |
| WB-09 | SP-07 PASS required for `requires_consent_namespace_clean` |
| WB-10 | LE-09 path unchanged |
| POLISH-01 | Audit append-only |

Deep-link: `/fix?issue=PT-04`.

---

## 10. Tests + verify

| Case | Expect |
|------|--------|
| Registry PT-04 enabled; `detail_set` + `klints_net_ltv` | |
| Preview `side=net_overstatement` → intent with `shopify_net` value | |
| Missing identity → error, no fake email | |
| ContactId-only `write_entity_key` (no email) still ready when contactId present | |
| Prior `klints_net_ltv` == `shopify_net` → skipped `already_at_target` | |
| SP-07 FAIL (other foreign collisions) → PT-04 execute blocked | |
| Settings OFF → denied | |
| Rollback reverts detail | |
| `is_klints_owned_detail("klints_net_ltv")` True when PT-04 enabled | |
| Disclosure does not claim PT-04 PASS | |
| Provenance includes refund_blind-only contacts after §3.4 (not empty mismatches) | |
| Concurrent double Approve → 409 | |

```text
scripts/verify_wb11_pt04_net_ltv_writeback.py
```

---

## 11. Branch / PR

- Branch: `feature/wb-11-pt04-net-ltv`  
- **Base:** tip that includes WB-10 (LE-09) + WB-09  
- BE title: `feat(WB-11): PT-04 klints_net_ltv governed net writeback`  
- FE title (if split): `feat(WB-11): enable PT-04 Fix Approve`  
- PR body: link this PRD · “detail_set not event_correct; owns klints_net_ltv for SP-07”  

---

## 12. Acceptance checklist

- [x] Mapping `PT-04.net_ltv.v1.json` enabled; registry live  
- [x] Match const **`net_overstatement`**; value from **`shopify_net`**; entity_key via **`write_entity_key`**  
- [x] `detail_set` / `klints_net_ltv` / `namespace: klints_`  
- [x] `requires_consent_namespace_clean: true`  
- [x] Rollback `revert_detail` works; not irreversible  
- [x] Provenance union failing ∪ refund_blind with `side=net_overstatement` (§3.4); FAIL bands unchanged  
- [x] Disclosure: may **not** PASS PT-04 after stamp  
- [x] `0039_writeback_allowed_pt04` seeds PT-04  
- [x] SP-07 owned-key tests/fixtures updated (`klints_net_ltv` owned; foreign fixtures retargeted)  
- [x] Possible sheet + SURFACE matrix + docs CSV synced  
- [x] FE Approve allowlist includes PT-04  
- [x] Settings OFF → no execute; SP-07 FAIL → blocked  
- [x] Tests + `verify_wb11_pt04_net_ltv_writeback.py` green  
- [x] No `event_correct` adapter; no handoff / Studio / QA / CAP edits  

---

## 13. Explicitly not in this PR

- `event_correct` / `event_update` adapter implementation  
- Changing PT-04 FAIL bands or revenue formula  
- Teaching PT-04 to PASS when `klints_net_ltv` matches net → **WB-12**  
- Auto-chaining LE-09 execute inside PT-04 Approve  
- Claiming ERP credit notes  
- Versioned Klints prefix (WB-09B)  
- Raising `PT_SAMPLE` / evidence display caps beyond today’s 50 / 20  

---

## 14. Code reference map

| Path | Role |
|------|------|
| `dataruns/dcs/product_truth.py` | Net vs gross per contact |
| `dataruns/dcs/executors/product.py` | `evaluate_pt_04` + §3.4 mismatch union |
| `dataruns/writebacks/mappings/CC-03.consent_provenance.v1.json` | detail_set pattern |
| `dataruns/writebacks/mappings/PT-04.net_ltv.v1.json` | **New** |
| `dataruns/writebacks/transform.py` | `_pt04_evidence_rows` + `write_entity_key` |
| `dataruns/dcs/segment_join.py` | Owned keys after enable |
| FE `src/lib/writebacks.ts` | Approve allowlist |

---

## 15. Traceability

| Field | Value |
|-------|--------|
| Milestone | M2 — Catalogue Automated writeback |
| Pack | Catalogue PT-04 P0 T6 (implement as detail_set) |
| Parents | WB-01…10 · DCS-04 PT-04 · DCS-08 revenue (consume) |
| Unblocks | VIP / value-tier / loyalty honesty · G10 gap |
| Next | Remaining catalogue AW (CI-05, LE-02, …) as product prioritizes |
| Independent of | Handoff · Studio · Track B |

---

## 16. Open questions (resolved — do not reopen in impl)

| # | Question | Decision |
|---|----------|----------|
| 1 | T6 `event_correct` vs Suggested Fix detail? | **detail_set `klints_net_ltv`** |
| 2 | Match side? | **`net_overstatement`** |
| 3 | Value field? | **`shopify_net`** |
| 4 | Block if LE-09 FAIL? | **No hard block** — disclosure only |
| 5 | Namespace preflight? | **`requires_consent_namespace_clean: true`** |
| 6 | Is `klints_net_ltv` still SP-07 foreign? | **No after enable** — becomes owned |
| 7 | Irreversible? | **No** — `revert_detail` |
| 8 | Does stamp clear PT-04? | **No** — workflows use detail; check may stay FAIL |
| 9 | Empty email on mismatch? | **`write_entity_key`** = email or `manago_contact_id` |
| 10 | refund_blind-only FAIL? | Union into mismatches (§3.4); stamp `side`; scores unchanged |
| 11 | Migration? | **0039** after LE-09’s 0038 |
| 12 | SP-07 then PT-04 order? | Enable mapping → re-score → then Approve |
