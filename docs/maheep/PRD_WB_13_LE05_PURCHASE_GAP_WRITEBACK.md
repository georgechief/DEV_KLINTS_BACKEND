# PRD-WB-13 — LE-05 order-level PURCHASE gap writeback

**Status:** **Shipped (impl landed)** — P0 M2 Catalogue Automated writeback · Sahil  

**Owner track:** Sahil — **BE primary · FE Approve allowlist only**  
**Surfaces:** Fix `/fix` Approve · Settings Allow writebacks · `WritebackAllowedCheck` · registry / mapping · possible sheet · Activity/audit  
**Milestone:** M2 Activation & Blueprint (T2) — Lifecycle event depth  
**Depends on:** WB-03…WB-12 · FE-08/09 · live `evaluate_le_05` + `lifecycle_join` · Manago `RESTV2.EVENT.INGEST` (CONFIRMED_LIVE via LE-01 / LE-09)  
**PRD path:** `docs/maheep/`  
**Contract SoT:** Catalogue Automated writeback for LE-05; Writeback + Lifecycle live  
**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02 Check Catalogue** row **LE-05**  
- sheet **09 MVP1 Check Scope** (Lifecycle · SCORED · MVP1-A)  
- `docs/dcs_scoring/CHECK_MASTER_42.md` row LE-05 — *Order-level event gap list*  
- Manago Execution Capability · `RESTV2.EVENT.INGEST` / `batchAddContactExtEvent`  
- MVP1 · P0 next list: **#2 LE-05** (after LE-09; before LE-02) — T5 Event backfill  
- WB-02 §3.2 — LE-05 removed from “Approve OFF until built” (shipped)  
**Out of scope:**  
- Changing LE-05 FAIL bands / gap join formulas / `LE_GAP_SAMPLE`  
- Auto-deleting Manago-only extra PURCHASE events (`manago_only` side)  
- Implementing `event_correct` / `event_update` (that is **LE-02**, next after LE-05)  
- Disabling or replacing **LE-01** (count parity) — both may stay live; see §2.1  
- Adding LE-05 to `suppressFixProceedToStudio` (PT-04-only; LE-05 stays Studio-eligible UC-06B)  
- Shopify Order writers  
- Handoff / Studio / QA / CAP product work (Approve allowlist only)  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-13 — LE-05 order-level PURCHASE gap Automated writeback.

Read:
- docs/maheep/PRD_WB_13_LE05_PURCHASE_GAP_WRITEBACK.md (this file)
- docs/maheep/PRD_WB_08_CATALOGUE_WAVE2_SP01_LE01.md (LE-01 event_ingest pattern)
- docs/maheep/PRD_WB_10_LE09_RETURN_EVENT_WRITEBACK.md (T5 irreversible + no-sandbox pattern)
- dataruns/dcs/executors/lifecycle.py (evaluate_le_05 / _gap_mismatch_rows)
- dataruns/dcs/lifecycle_join.py (shopify_only / manago_only; LE_GAP_SAMPLE=50)
- dataruns/writebacks/mappings/LE-01.event_backfill.v1.json
- dataruns/writebacks/transform.py (_le01_evidence_rows / _enrich_le01_row)
- dataruns/writebacks/pipeline.py (LE-09 EVENT.INGEST ceiling — copy for LE-05)
- FE: src/lib/writebacks.ts WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS

Ship:
1. Mapping LE-05.purchase_gap.v1.json — event_ingest PURCHASE; match side=shopify_only (§4).
2. Transform: _le05_evidence_rows — reuse _enrich_le01_row; NO sandbox (§5).
3. Pipeline: LE-05 uses RESTV2.EVENT.INGEST batch ceiling + truncation probe (LE-09 style — NOT WRITEBACK_SANDBOX_MAX_ROWS=10) (§5.1).
4. Enable registry + seed WritebackAllowedCheck LE-05 (§6).
5. Possible sheet (docs + dataruns/writebacks copies) + SURFACE + FE allowlist (§7–8).
6. Tests + verify_wb13_le05_purchase_gap_writeback.py (§10).
7. Migration 0040_writeback_allowed_le05 (after 0039 PT-04).

Do NOT auto-delete manago_only events.
Do NOT implement event_correct (LE-02).
Do NOT change LE-05 FAIL bands / LE_GAP_SAMPLE.
Do NOT disable LE-01.
Do NOT add LE-05 to suppressFixProceedToStudio.
Do NOT default LE-05 max_rows to WRITEBACK_SANDBOX_MAX_ROWS (LE-01 trap).
Acceptance: §12.
```

---

## 1. Why (simple)

| Today | Gap |
|-------|-----|
| LE-05 **detects** Shopify paid orders missing Manago PURCHASE by `externalId` (order-level list) | Catalogue Fix Type = **Automated writeback (approved)** — Fix Approve live (WB-13) |
| LE-01 already backfills `shopify_only` PURCHASE (WB-08) | LE-05 is the **canonical order-gap** check (FAIL on any gap); Fix `/fix?issue=LE-05` still not executable |
| MVP1 · P0 order: LE-09 done → **LE-05 next** → LE-02 | Product sequence blocked without LE-05 Approve |

**WB-13** ships Fix Approve on LE-05 so operators clear **order-level** PURCHASE gaps via Manago `event_ingest`, then re-score → LE-05 PASS when `shopify_only=0` and `manago_only=0`.

```text
LE-05 FAIL (shopify_only > 0)
  → Fix Preview (event_ingest PURCHASE from side=shopify_only)
  → Approve (Settings ON; irreversible disclosure)
  → Manago batchAddContactExtEvent
  → Re-run DCS → LE-05 PASS if no remaining gaps
```

---

## 2. Product decisions (locked)

| # | Decision | Lock |
|---|----------|------|
| 1 | Ship **`event_ingest` PURCHASE** (same op_kind as LE-01) | **Yes** — T5 Event backfill; adapter live |
| 2 | Match evidence `side=shopify_only` | **Yes** — `evaluate_le_05` / `_gap_mismatch_rows` SoT |
| 3 | Entity key = `order.id` (Shopify order id → Manago event `externalId`) | **Yes** |
| 4 | `irreversible: true`; sheet rollback = **limited**; runtime `event_ingest` + `tagged_backfill_delete` → **`rollback_not_supported`** | **Yes** — same as LE-01 / LE-09 |
| 5 | `requires_consent_namespace_clean: false` | **Yes** — native event payload, not `klints_` detail |
| 6 | **No sandbox invent** (empty worklist or no `shopify_only`) | **Yes** — mirror LE-09; stricter than LE-01 |
| 7 | **Do not write** for `manago_only` | **Yes** — Download / manual; no delete adapter |
| 8 | Keep **LE-01 enabled**; prefer Fix **LE-05** for order gaps; **do not dual-Approve** same `shopify_only` ids before re-score | **Yes** — see §2.1 |
| 9 | FE allowlist add **LE-05** only (no new Fix chrome) | **Yes** |
| 10 | Approval tier = **batch** | **Yes** |
| 11 | Owner = **Sahil** | **Yes** |
| 12 | Approve **can** clear LE-05 PASS on re-score when **both** gap counts = 0 | **Yes** — executor counts gaps (not a stamp trap) |
| 13 | Pipeline ceiling = **`RESTV2.EVENT.INGEST` batch_max** (LE-09 style), **not** `WRITEBACK_SANDBOX_MAX_ROWS` | **Yes** — LE-01 still uses sandbox default 10; LE-05 must not |
| 14 | Omit event `date` / `currency` on wire (LE-01 parity); enrich may keep currency on evidence only | **Yes** |
| 15 | No contact `klints_backfill` stamp on `event_ingest` | **Yes** — same as LE-01 / LE-09 |
| 16 | Do **not** add LE-05 to `suppressFixProceedToStudio` | **Yes** — PT-04-only; LE-05 remains UC-06B Studio-eligible |

### 2.1 Overlap with LE-01 (honest)

| | LE-01 | LE-05 |
|---|--------|--------|
| What it scores | Purchase **count** parity (monthly / overall **>2%**) | **Any** order-level gap (`shopify_only` or `manago_only` > 0) |
| Write surface | `event_ingest` PURCHASE · `side=shopify_only` | **Same** write surface |
| Pipeline default `max_rows` | `WRITEBACK_SANDBOX_MAX_ROWS` (**10**) | **EVENT.INGEST ceiling** (LE-09 style) |
| Sandbox when empty worklist | Yes (if Settings execute ON) | **Never** |
| When FAIL with empty shopify_only sample | Possible (aggregate month fail) | Rare — counts > 0 but sample truncated / only `manago_only` in sample |

**Duplicate-event risk (lock):** `batchAddContactExtEvent` is **additive**. Approving **LE-01 and LE-05** on the **same** `data_run_id` for the same `order.id` can create **duplicate PURCHASE** events → LE-04 risk. Once-per-run is per `check_id`, so both can execute.

**Operator path:** Prefer **Fix LE-05** for order gaps → re-run DCS → only Approve LE-01 if count parity still FAILs. Disclosure must say LE-05 does not remove Manago-only extras and does not replace LE-01. Do **not** remove LE-01 in WB-13.

### 2.2 Lane wall

```text
Sahil WB-13   =  LE-05 mapping + transform + pipeline ceiling + allowlist + FE Approve list
Do not regress =  LE-01 / LE-09 / PT-04 / SP-07 / CI-01 / CC-03 live writebacks
Out of this PR =  LE-02 event_correct · CI-05 · Handoff / Studio product · raising LE_GAP_SAMPLE
```

---

## 3. Excel / executor contract (do not invent)

### 3.1 Catalogue (sheet 02 / CHECK_MASTER)

| Field | Value |
|-------|--------|
| Check | Order-level event gap list |
| Dimension | 02 Lifecycle Event |
| Fix Type | **Automated writeback (approved)** (MVP1 · P0 T5) |
| Suggested Fix | Backfill missing Manago **PURCHASE** events from Shopify paid orders missing by externalId |
| Severity | Critical |

### 3.2 Executor SoT (`evaluate_le_05`)

```text
FAIL     ⇔  shopify_only_count > 0 OR manago_only_count > 0
PASS     ⇔  both counts == 0 AND (shopify_paid_orders > 0 OR manago_purchase_events > 0)
UNKNOWN  ⇔  missing connectors / lifecycle / both order+event counts 0
```

Provenance mismatches (`_gap_mismatch_rows` — **shopify_only listed first**, then manago_only; cap `LE_MISMATCH_SAMPLE` = **50**). Lifecycle lists also truncated at `LE_GAP_SAMPLE` = **50**:

```json
{ "side": "shopify_only", "order.id": "<shopify_order_id>", "amount_gross": <optional>, "currency": <optional> }
{ "side": "manago_only", "order.id": "<id>" }
```

DCS mismatches carry **`order.id` (+ amount/currency for shopify_only)**. They do **not** carry `person.email` / `manago_contact_id` — transform enrich must resolve those (same as LE-01). Worklist may PII-mask emails; enrich must re-resolve from Order/Contact, never write masks.

Join spine (lifecycle): `event.externalId ↔ orders.id` (fallback email+date+value heuristic — **do not invent** new join keys in writeback). Heuristic-matched orders are **not** in `shopify_only` — writeback correctly skips them.

### 3.3 Does Approve clear LE-05?

| Outcome | Honest claim |
|---------|----------------|
| After Approve on `shopify_only` | Manago has PURCHASE events for those order ids (sample / batch capped) |
| After re-score | LE-05 **PASS** if `shopify_only_count=0` **and** `manago_only_count=0` |
| If only `manago_only` remains | Still **FAIL** — writeback does not delete extras |
| Truncated sample (`gaps_truncated` / batch cap) | Re-Approve after re-score (same as LE-09 / PT-04) |

Toast OK: “PURCHASE events backfilled — re-run DCS to clear LE-05.”  
Do **not** toast PASS until score returns PASS.

### 3.4 When Fix preview is empty

| LE-05 outcome | Actionable `shopify_only` rows? | Fix Approve |
|---------------|---------------------------------|-------------|
| FAIL with shopify_only sample | **Yes** | Preview intents |
| FAIL with only manago_only (in sample) | **No** | Preview **0** — Download evidence; manual |
| FAIL with empty mismatch sample | **No** | Download; re-score |
| PASS / UNKNOWN / NOT_CONNECTED | **No** | N/A |

---

## 4. Mapping — `LE-05.purchase_gap.v1.json`

### 4.1 Target shape

```json
{
  "schema_version": "1.0.0",
  "check_id": "LE-05",
  "template_id": "T5",
  "title": "Order-level PURCHASE gap backfill",
  "enabled": true,
  "approval_tier": "batch",
  "requires_consent_namespace_clean": false,
  "irreversible": true,
  "operator_disclosure": "Bulk PURCHASE event backfill for order-level gaps may not be fully reversible. Does not remove extra Manago-only events. Prefer Fix LE-05 (not also LE-01) for the same orders before re-running DCS — dual Approve can duplicate PURCHASE events. Rollback is not supported as a full reverse. Re-run DCS after Approve to clear LE-05.",
  "rollback": { "strategy": "tagged_backfill_delete" },
  "operations": [
    {
      "operation_id": "manago.event_ingest.purchase_le05",
      "op_kind": "event_ingest",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.EVENT.INGEST",
      "entity_type": "event",
      "from_evidence": {
        "match": { "path": "side", "const": "shopify_only" },
        "entity_key": { "path": "order.id" },
        "fields": {
          "order_id": { "path": "order.id" },
          "email": { "path": "person.email" },
          "contact_id": { "path": "manago_contact_id" },
          "value": { "path": "amount_gross" }
        }
      },
      "guards": ["entity_key_required"]
    }
  ]
}
```

### 4.2 Registry

```json
"LE-05": {
  "file": "LE-05.purchase_gap.v1.json",
  "enabled": true
}
```

Event type on wire = **PURCHASE** (adapter default for this op / same as LE-01 — do **not** require evidence `event_type` path; LE-09 needs it, LE-05 does not).

Adapter validate: `externalId` + (`email` or `contactId`) required on execute — enrich must supply contact reference or intent errors `missing_contact_reference`.

---

## 5. Transform

```text
elif normalized == "LE-05":
    rows = _le05_evidence_rows(company=company, rows=rows, max_rows=max_rows)
```

| Rule | Lock |
|------|------|
| Match | `side == shopify_only` only (ignore `manago_only`, nested non-gap rows) |
| Flatten | Flatten nested worklist `value` before enrich (same as LE-01 / LE-09) |
| Enrich | Reuse `_enrich_le01_row` (or shared `_enrich_purchase_gap_row`) — resolve email / contactId / amount_gross from Order + Manago contact; never write PII masks |
| Cap (transform) | Honor pipeline `max_rows` |
| Empty | If rows present but no shopify_only → **[]** (no sandbox) |
| Empty worklist | **[]** — do **not** call `_le01_sandbox_evidence_rows` |

### 5.1 Pipeline ceiling (critical — do not copy LE-01)

Today in `pipeline.py`:

| Check | Default `effective_max` when Fix omits `max_rows` |
|-------|--------------------------------------------------|
| LE-01 | `WRITEBACK_SANDBOX_MAX_ROWS` (**10**) |
| LE-09 | `capability_batch_max("RESTV2.EVENT.INGEST")` capped ≤1000 |
| PT-04 / SP-07 | UPSERT ceiling |

**Lock for LE-05:** treat like **LE-09**:

1. `elif normalized_check in ("LE-09", "LE-05"):` → EVENT.INGEST ceiling  
2. Add **`LE-05`** to truncation probe set `{SP-07, LE-09, PT-04, LE-05}` with note: *“capped at N purchase events… Approve again after re-running DCS if LE-05 still FAILs.”*  
3. DCS sample still ≤50 — one Approve may not clear a large FAIL; re-score + re-Approve  

**Do not** leave LE-05 on the sandbox-10 default — that silently truncates a 50-row gap sample.

---

## 6. Allowlist / migration

After latest writeback allowlist migration → **`0040_writeback_allowed_le05`**:

```text
get_or_create check_id=LE-05, enabled=True, note="PRD-WB-13 LE-05 purchase gap"
```

Settings Allow writebacks still master kill-switch.

---

## 7. Possible sheet + SURFACE

Add **new** LE-05 row (absent from sheet today). Sync **both**:

- `docs/maheep/WRITEBACK_POSSIBLE_NOT_SHEET.csv`
- `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` (runtime / Docker)

| Field | Value |
|-------|--------|
| `check_id` | `LE-05` |
| `check_name` | Order-level event gap list |
| `pack_fix_type` | Automated writeback (approved) |
| `pack_suggested_fix_summary` | Backfill missing Manago PURCHASE from Shopify-only orders |
| `op_kind` | `event_ingest` |
| `field_or_key` | `PURCHASE` |
| `write_possible_today` | `yes` |
| `rollback_possible_today` | `limited` |
| `mapping_file` | `LE-05.purchase_gap.v1.json` |
| `evidence_note` | event_ingest PURCHASE from side=shopify_only; irreversible; manago_only not written; prefer Fix LE-05 over dual LE-01 Approve; prefer after identity link |

SURFACE matrix: update **Transaction / purchase event** row — **Yes — LE-01 + LE-05**; note LE-05 order-gap path + no manago_only delete.

Enabled-mappings table: add **LE-05** · `event_ingest` · Enabled (WB-13).

---

## 8. FE

| Path | Change |
|------|--------|
| `src/lib/writebacks.ts` | Add **`LE-05`** to `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` |
| Honesty blurb | Extend “Event ingest (LE-01 / LE-09)” → include **LE-05** |
| Irreversible / limited rollback helpers | Confirm LE-05 picks up same honesty via mapping `irreversible` + `event_ingest` |
| `suppressFixProceedToStudio` | **Do not** add LE-05 (PT-04 only) |
| `scripts/verify-wb02-frontend.mjs` | Assert LE-05 allowlisted |
| WB-02 §3.2 list | Remove LE-05 from “Approve OFF until built” when shipping |

No new Fix chrome. Deep-link: `/fix?issue=LE-05`. Primary treating path = Approve → re-score; Studio Proceed may still show when UC-06B-eligible.

---

## 9. Gates / order

| Gate | Rule |
|------|------|
| Settings OFF | No execute |
| Once-per-run (WB-04/07) | One successful execute per `(company, LE-05, data_run_id)` |
| Claim-before-write + PII mask (WB-07) | Unchanged |
| LE-01 | Independent once-per-run key — **can** both execute same run; operator must avoid dual Approve on same order ids (§2.1) |
| Identity | Prefer contacts already linked (CI-01); enrich may yield intents that fail validate without email/contactId |

---

## 10. Tests + verify

| Case | Expect |
|------|--------|
| Registry LE-05 enabled; match `shopify_only`; event_ingest PURCHASE | |
| Enrich attaches email / amount / contactId from Order | |
| manago_only-only FAIL → 0 intents | |
| No sandbox when empty / non-shopify_only rows | |
| Pipeline default max for LE-05 = EVENT.INGEST ceiling (not sandbox 10) | |
| Truncation disclosure when sample ≥ ceiling | |
| Irreversible disclosure present; rollback_not_supported for event_ingest | |
| Settings OFF → blocked | |
| Allowlist migration seeds LE-05 | |
| FE allowlist includes LE-05 | |
| LE-01 still enabled / tests green | |
| Match does not fire on LE-09 `shopify_only_return` | |

`scripts/verify_wb13_le05_purchase_gap_writeback.py` — registry, mapping, allowlist, both sheet copies, FE string, pipeline LE-05 ceiling branch, no sandbox path for LE-05.

---

## 11. Branch / PR

- Branch: `feature/wb-13-le05-purchase-gap`  
- **Base:** tip with WB-10/11/12 merged  
- BE: `feat(WB-13): LE-05 order-level PURCHASE gap writeback`  
- FE: `feat(WB-13): enable LE-05 Fix Approve`  
- PR body: link this PRD · “T5 event_ingest; LE-09-style batch ceiling; overlap with LE-01 honest; no manago_only delete”

---

## 12. Acceptance checklist

- [x] Mapping `LE-05.purchase_gap.v1.json` enabled; registry live  
- [x] Match **`shopify_only`**; entity_key **`order.id`**; PURCHASE ingest  
- [x] Irreversible disclosure; sheet rollback limited; runtime `rollback_not_supported`  
- [x] Transform enrich reuse; **no sandbox invent**  
- [x] Pipeline: EVENT.INGEST ceiling + truncation probe for LE-05 (**not** sandbox 10)  
- [x] manago_only never produces write intents  
- [x] `0040_writeback_allowed_le05` seeds LE-05  
- [x] Possible sheet (docs + `dataruns/writebacks`) + SURFACE + enabled-mappings synced  
- [x] FE Approve allowlist includes LE-05; honesty blurb updated; **not** in Proceed suppress list  
- [x] Settings OFF → no execute  
- [x] Tests + `verify_wb13_le05_purchase_gap_writeback.py` green  
- [x] LE-01 not disabled; no LE-02 / event_correct; WB-02 §3.2 LE-05 removed from OFF list  

---

## 13. Explicitly not in this PR

- `event_correct` / LE-02 value correction  
- Deleting or merging `manago_only` PURCHASE events  
- Changing LE-05 / LE-01 FAIL bands  
- Raising `LE_GAP_SAMPLE` / `LE_MISMATCH_SAMPLE`  
- Changing LE-01 pipeline ceiling / removing LE-01 sandbox  
- CI-05 / CI-03 / consent writebacks  
- `suppressFixProceedToStudio` for LE-05  

---

## 14. Code reference map

| Path | Role |
|------|------|
| `dataruns/dcs/executors/lifecycle.py` | `evaluate_le_05` + `_gap_mismatch_rows` |
| `dataruns/dcs/lifecycle_join.py` | `shopify_only` / `manago_only`; `LE_GAP_SAMPLE` |
| `dataruns/writebacks/mappings/LE-01.event_backfill.v1.json` | Pattern to mirror |
| `dataruns/writebacks/mappings/LE-05.purchase_gap.v1.json` | **New** |
| `dataruns/writebacks/transform.py` | `_le05_evidence_rows` |
| `dataruns/writebacks/pipeline.py` | EVENT.INGEST ceiling + truncation for LE-05 |
| `dataruns/writebacks/adapters/manago.py` | `event_ingest` (existing) |
| `dataruns/writebacks/rollback_strategy.py` | event_ingest → `rollback_not_supported` |
| FE `src/lib/writebacks.ts` | Approve allowlist + honesty blurb |

---

## 15. Traceability

| Field | Value |
|-------|--------|
| Milestone | M2 — Catalogue Automated writeback |
| Pack | Catalogue LE-05 P0 T5 |
| MVP1 · P0 order | **#2** after LE-09; before LE-02 |
| Parents | WB-01…12 · WB-08 LE-01 · WB-10 LE-09 pattern · DCS lifecycle |
| Unblocks | Order-level PURCHASE honesty · LE-02 readiness |
| Next | **LE-02** (T6 event correction) per MVP1 list |

---

## 16. Decision log

| # | Question | Answer |
|---|----------|--------|
| 1 | Same write as LE-01? | **Yes** for `shopify_only` PURCHASE — keep both; prefer Fix LE-05; avoid dual Approve before re-score |
| 2 | Sandbox like LE-01? | **No** — live FAIL gaps only (LE-09 style) |
| 3 | Clear LE-05 PASS? | **Yes** on re-score when both gap counts 0 |
| 4 | manago_only? | **No write** — Download / later PRD |
| 5 | Template? | **T5** event_ingest (not T6 event_correct) |
| 6 | Batch ceiling? | **EVENT.INGEST** like LE-09 — **not** LE-01 sandbox 10 |
| 7 | Suppress Proceed to Studio? | **No** — PT-04 only; LE-05 stays UC-06B-eligible |
| 8 | Event date/currency on wire? | **Omit** (LE-01 parity) |
| 9 | After this? | **LE-02** on MVP1 list |
