# PRD-WB-14 — LE-02 purchase value correction writeback

**Status:** **Shipped (impl landed)** — P0 M2 Catalogue Automated writeback · Sahil  

**Owner track:** Sahil — **BE primary · FE Approve allowlist only** (pack Fix Owner = **Klints (automated)**)  
**Surfaces:** Fix `/fix` Approve · Settings Allow writebacks · `WritebackAllowedCheck` · registry / mapping · possible sheet · Activity/audit · **DCS lifecycle mismatches (new)** · Manago adapter `event_correct` (**new**)  
**Milestone:** M2 Activation & Blueprint (T2) — Lifecycle value honesty  
**Depends on:** WB-03…WB-13 · FE-08/09 · live `evaluate_le_02` + `lifecycle_join` · LE-05/LE-01 treating path for gap-driven FAIL · Manago `updateContactExtEvent` (**capability discovery → CONFIRMED**)  
**PRD path:** `docs/maheep/`  
**Contract SoT:** Catalogue Automated writeback for LE-02; Writeback + Lifecycle  
**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02 Check Catalogue** row **LE-02** (headers row 5 — full column map §3.1)  
- sheet **01 Overview** — T6 Event correction covers **LE-02, LE-04, PT-04** (“Dedup and value correction; klints_net_ltv…”). **This PR = LE-02 value-correct AW only.** LE-04 stays Integration+Manual (WB-01B). PT-04 already shipped via `detail_set` (WB-11/12), not `event_correct`.  
- sheet **06 Field Mapping Reference** — `order.value_net` / event value vs `total_price`/`subtotal` composition rule (PT-08 note); MVP1 LE-02 FAIL still uses **gross**  
- sheet **09 MVP1 Check Scope** (Lifecycle · SCORED · MVP1-A)  
- `docs/dcs_scoring/CHECK_MASTER_42.md` row LE-02 — *Purchase value parity* · RC-02, RC-13, RC-14 · High  
- WB-01 §1b.2 — `event_correct` = value/date fix where `externalId` matches (T6 LE-02, LE-06); stub_factory T6 default `approval_tier=individual`  
- WB-13 / product sequence: LE-09 → LE-05 → **LE-02** (Excel lists all three P0; WB-13 locked LE-02 next)  
- WB-02 §3.2 — LE-02 **removed** from “Approve OFF until built” (shipped WB-14)  
**Out of scope:**  
- Catalogue Suggested Fix **Part A** — decide/document gross vs net in mapping config (explain / product config; not a Manago write)  
- Changing LE-02 FAIL band (`LE02_VALUE_DELTA_FAIL` = 2% gross)  
- Changing MVP1 **gross** compare to net (Part A); correction target stays Shopify **gross** — §2  
- Changing DCS-08 LE-02 `revenue_impact` alias / rollup exclusion  
- Auto-deleting Manago-only extra PURCHASE events (LE-04 deletion limited; not LE-02)  
- Using `event_ingest` / `batchAddContactExtEvent` for LE-02 (creates events → LE-04 risk)  
- LE-04 duplicate handling · LE-06 · LE-08 (`event_update` CART close)  
- PT-04 / `klints_net_ltv` (already WB-11/12)  
- Shopify Order writers  
- Handoff / Studio / QA / CAP product work (Approve allowlist only)  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-14 — LE-02 purchase value correction Automated writeback.

Read:
- docs/maheep/PRD_WB_14_LE02_PURCHASE_VALUE_CORRECT_WRITEBACK.md (this file)
- docs/maheep/PRD_WB_13_LE05_PURCHASE_GAP_WRITEBACK.md (operator path + no dual-write honesty)
- docs/maheep/PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md (§1b.2 event_correct)
- dataruns/dcs/executors/lifecycle.py (evaluate_le_02 — attach value_mismatch rows)
- dataruns/dcs/lifecycle_join.py (matched pairs; emit value_mismatches)
- dataruns/writebacks/adapters/manago.py + manago_transport.py (event_ingest pattern — NEW event_correct)
- dataruns/writebacks/capabilities.json (RESTV2.EVENT.UPDATE CONFIRMED_LIMITED)
- FE: src/lib/writebacks.ts WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS

Ship:
1. DCS: emit provenance mismatches side=value_mismatch for matched non-heuristic pairs (§3.2).
2. Mapping LE-02.value_correct.v1.json — event_correct; match side=value_mismatch; approval_tier=individual (§4).
3. Transport + ManagoWriteAdapter event_correct → updateContactExtEvent after path/body discovery; full field resend (§5).
4. Transform enrich: resolve email/contactId/date/currency from Manago event + Shopify gross (§5.1).
5. Capability RESTV2.EVENT.UPDATE — CONFIRMED_LIMITED batch_max 50 after sandbox proof (§5.2).
6. Pipeline: no sandbox invent; ceiling from capability batch_max (CONFIRMED_LIMITED = 50) (§5.3).
7. Enable registry + seed WritebackAllowedCheck LE-02 (§6).
8. Possible sheet (docs + dataruns copies) + SURFACE + FE allowlist (§7–8).
9. Tests + verify_wb14_le02_value_correct_writeback.py (§10).
10. Migration 0041_writeback_allowed_le02 (after 0040 LE-05).

Do NOT use event_ingest for LE-02.
Do NOT invent sandbox value_mismatch rows.
Do NOT invent Manago HTTP path/fields without sandbox discovery.
Do NOT implement Suggested Fix Part A (gross vs net mapping config).
Do NOT change LE-02 FAIL bands / switch MVP1 to net / change DCS-08 revenue alias.
Do NOT delete manago_only extras / implement LE-04 / LE-06 / LE-08.
Do NOT add LE-02 to suppressFixProceedToStudio.
Acceptance: §12.
```

---

## 1. Why (simple)

| Before WB-14 | After WB-14 |
|--------------|-------------|
| LE-02 detects Manago PURCHASE Σ vs Shopify totals (monthly / overall **>2%** gross) and decomposes drivers | Catalogue Fix Type AW · T6 · **`updateContactExtEvent`** — Fix Approve live |
| LE-05 / LE-01 clear gap-driven value miss | Residual matched wrong **value** cleared via `event_correct` |
| Mismatches were driver tags only | DCS emits `side=value_mismatch` (+ drivers) |
| `event_correct` adapter missing | Adapter + `RESTV2.EVENT.UPDATE` CONFIRMED_LIMITED |

```text
LE-02 FAIL
  → Prefer Fix LE-05 / LE-01 first if driver includes missing_or_extra_events
  → Re-score
  → If still FAIL with side=value_mismatch rows:
       Fix Preview (event_correct — full event resend, value=Shopify gross)
    → Approve (Settings ON; irreversible disclosure)
    → Manago updateContactExtEvent
    → Re-run DCS → LE-02 PASS if gross delta ≤ 2%
```

---

## 2. Product decisions (locked)

| # | Decision | Lock |
|---|----------|------|
| 1 | Ship **`event_correct`** via Manago **`updateContactExtEvent`** (not `event_ingest`) | **Yes** — catalogue T6 + Suggested Fix |
| 2 | Correction target value = Shopify order **`total_price` / `amount_gross`** (MVP1 LE-02 SoT) | **Yes** — do not switch FAIL band to net in this PR |
| 3 | Match evidence `side=value_mismatch` only | **Yes** — never invent from drivers alone |
| 4 | Entity key = Manago **`event_external_id`** (event spine); Shopify amount from `order.id` | **Yes** — skip heuristic-only; order_number matches may differ |
| 5 | **Full field resend** on update (catalogue: update ≠ upsert) | **Yes** — value + type + externalId + email/contactId + date (and currency if present on prior event) |
| 6 | `irreversible: true`; sheet Rollback Note → possible `rollback=no`; runtime **`rollback_not_supported`** | **Yes** — “prior values held in Klints raw… **not restorable in Manago**” |
| 7 | `requires_consent_namespace_clean: false` | **Yes** — native event payload (not `klints_`) |
| 8 | **No sandbox invent** (empty worklist / no `value_mismatch`) | **Yes** — LE-09 / LE-05 style |
| 9 | Prefer **LE-05 then LE-01** before LE-02 when gaps drive FAIL | **Yes** — Excel Detection Logic names missing events as **LE-01**; LE-05 is the order-gap list (WB-13). Prefer LE-05 for gaps, then LE-01 if count still FAILs, then LE-02 |
| 10 | Do **not** write for `manago_only` / `shopify_only` | **Yes** — LE-05/LE-01 or Download; LE-02 = matched wrong **value** only |
| 11 | Suggested Fix **Part A** (gross vs net mapping config) | **Out of scope** — if FAIL is only `gross_vs_net_definition` and **no** `value_mismatch` rows → Preview **0** + explain |
| 12 | FE allowlist add **LE-02** only (no new Fix chrome) | **Yes** |
| 13 | `approval_tier` = **`individual`** | **Yes** — matches `stub_factory` T6 default (native revenue overwrite; higher risk than `klints_` hygiene). One Fix Approve still may send up to sample cap of intents; tier echoed on preview |
| 14 | Eng owner track = **Sahil**; pack Fix Owner = **Klints (automated)** | **Yes** |
| 15 | Capability must be **`CONFIRMED_LIVE` or `CONFIRMED_LIMITED`** before execute | **Yes** — shipped `CONFIRMED_LIMITED` batch_max 50 |
| 16 | Do **not** add LE-02 to `suppressFixProceedToStudio` | **Yes** — PT-04 only |
| 17 | Absolute per-row money gate for emitting mismatch | **`abs(shopify_gross − manago_value) > 0.01`** (currency units) |
| 18 | Cap mismatch sample | **`LE_MISMATCH_SAMPLE` = 50** (same as other LE gap samples) |
| 19 | Manago HTTP path/body | **Discover on sandbox** — catalogue names API **`updateContactExtEvent`** only; do not invent fields beyond discovery + full-resend rule |

### 2.1 Overlap with LE-01 / LE-05 (honest)

| | LE-01 | LE-05 | LE-02 (this PR) |
|---|--------|--------|------------------|
| What it scores | Purchase **count** parity | Any order-level **gap** | Purchase **value** parity (gross) |
| Write surface | `event_ingest` PURCHASE | `event_ingest` PURCHASE | **`event_correct`** (update existing) |
| Actionable side | `shopify_only` | `shopify_only` | **`value_mismatch`** (matched only) |
| Fixes wrong value on existing event? | No (adds another → LE-04 risk) | No | **Yes** |

**Operator path:** Clear gaps with **LE-05** (prefer) / LE-01 → re-score → only then Approve **LE-02** for residual wrong values. Disclosure must say LE-02 does not backfill missing orders and does not delete Manago-only extras.

### 2.2 Lane wall

```text
Sahil WB-14   =  DCS value_mismatch rows + event_correct adapter + LE-02 mapping + allowlist + FE
Do not regress =  LE-01 / LE-05 / LE-09 / PT-04 / SP-07 / CI-01 / CC-03 live writebacks
Out of this PR =  LE-06 · LE-08 event_update · net definition flip · manago_only delete · CI-05
```

---

## 3. Excel / executor contract (do not invent)

### 3.1 Catalogue (sheet 02 — headers row 5) + CHECK_MASTER

Exact Excel LE-02 row (v1.4.1):

| Column | Value |
|--------|--------|
| Check ID | **LE-02** |
| DCS Dimension | 02 Lifecycle Event |
| Check Name | Purchase value parity |
| Entity | **Order / PURCHASE event** |
| Systems Compared | Manago vs Shopify |
| Check Type | Cross-system reconciliation |
| Detection Logic | Sum of PURCHASE event value vs sum of Shopify order totals **per month**; decompose into **missing events (LE-01)**, **value-field errors**, and **gross/net definition drift** |
| Manago Surface | PURCHASE event value (**float 7.2**) |
| Shopify Surface | `orders.total_price` / `subtotal_price` |
| ERP Surface | — |
| Inconsistency Type | Revenue totals disagree between systems |
| Root Causes | RC-02, RC-13, RC-14 |
| Business Impact | Marketing revenue reporting loses credibility with finance; value-based segments (VIP thresholds) mis-assign customers |
| Affected Workflows | VIP progression, value-tiered flows, reporting |
| Severity | High |
| DCS Weight | High |
| Suggested Fix | **(A)** Fix value-mapping definition (decide gross vs net incl. shipping/tax, document in mapping config); **(B)** correct systematically wrong events where **`updateContactExtEvent` is safe**; note **update is not upsert — all fields must be resent** |
| Fix Type | **Automated writeback (approved)** |
| Fix Owner | Klints (automated) |
| Rollback Note | Event updates overwrite; prior values held in Klints raw layer for reference, **not restorable in Manago** |
| Cadence | Initial + Recurring |
| MVP1 Fix Blueprint | **Y** |
| Fix Template | **T6 Event correction** |
| Build Priority | **P0** |

CHECK_MASTER_42: RULE_BASED · SCORED · MVP1-A · weight 4 · High · same RCs.

**Suggested Fix split (normative for this PR):**

| Part | Catalogue text | WB-14 |
|------|----------------|-------|
| **A** | Decide gross vs net; document in mapping config | **Out of scope** — product/config honesty; Preview 0 when only this driver |
| **B** | Correct systematically wrong events via `updateContactExtEvent`; full resend | **In scope** — `event_correct` writeback |

**Gross lock:** MVP1 executor compares **gross** (`total_price` → `amount_gross`). Sheet Shopify Surface also lists `subtotal_price` for net composition; **do not** retarget writeback to net without a separate product PR that also changes FAIL SoT.

### 3.2 Executor SoT (`evaluate_le_02`) + WB-14 mismatches

```text
FAIL     ⇔  any month value_delta > 2% OR overall gross delta > 2%
PASS     ⇔  no failing months AND overall_delta ≤ 2%
UNKNOWN  ⇔  missing connectors / lifecycle / both counts 0
```

**Evidence:** snapshot blob with `value_decomposition` + `drivers` + `monthly` + lifecycle `value_mismatches`.

**Provenance mismatches (shipped):** actionable `value_mismatch` rows **first** (so sample cap keeps writeable rows), then driver tags:

```json
{ "side": "value_mismatch", "order.id": "<shopify_order_id>", "event_external_id": "<manago_event_externalId>", "shopify_gross": <float 7.2>, "manago_value": <float 7.2>, "abs_delta": <float>, "currency": "<optional>", "person.email": "<optional>", "manago_contact_id": "<optional>", "occurred_at": "<optional>", "match_kind": "<non-heuristic>" }
{ "side": "driver", "driver": "missing_or_extra_events(LE-01/LE-05)" }
{ "side": "driver", "driver": "value_field_mapping" }
{ "side": "driver", "driver": "gross_vs_net_definition" }
```

**Emit rule (normative):**

1. From `lifecycle_join` matched pairs where `match_kind ≠ heuristic_email_date_value`.  
2. Manago event spine `event_external_id` = event `order.id` (externalId / join key); Shopify amount from `matched_order.id`.  
3. `abs(shopify amount_gross − manago event value) > 0.01`.  
4. **Dedupe** one row per Shopify `order.id` (largest `abs_delta`) — avoids LE-04 duplicate multi-write.  
5. Cap at `LE_GAP_SAMPLE` / `LE_MISMATCH_SAMPLE` (50), sorted by `abs_delta` descending.  
6. Do **not** emit rows for `shopify_only` / `manago_only` (other checks).  
7. Wire `value` rounds to **2 decimal places** (catalogue float 7.2).  

`evaluate_le_02` attaches these to `provenance.mismatches` on FAIL (and empty list on PASS).

### 3.3 Does Approve clear LE-02?

| Outcome | Honest claim |
|---------|----------------|
| After Approve on `value_mismatch` | Those Manago PURCHASE events now carry Shopify gross `value` (sample / batch capped) |
| After re-score | LE-02 **PASS** if overall + monthly gross deltas ≤ 2% |
| If gaps still dominate | Still **FAIL** — fix LE-05/LE-01 first |
| If only gross-vs-net definition drift remains | Still **FAIL** — not this writeback |
| Truncated sample | Re-Approve after re-score |

Toast OK: “Writeback applied · LE-02 · N updates · re-run DCS to clear LE-02” (same pattern as LE-05).  
Do **not** toast PASS until score returns PASS.

### 3.4 When Fix preview is empty

| LE-02 outcome | Actionable `value_mismatch`? | Fix Approve |
|---------------|------------------------------|-------------|
| FAIL with value_mismatch sample | **Yes** | Preview intents |
| FAIL only drivers / gaps / gross-net | **No** | Preview **0** — Download; prefer LE-05/LE-01 or mapping decision |
| PASS / UNKNOWN / NOT_CONNECTED | **No** | N/A |

---

## 4. Mapping — `LE-02.value_correct.v1.json`

### 4.1 Target shape

```json
{
  "schema_version": "1.0.0",
  "check_id": "LE-02",
  "template_id": "T6",
  "title": "Purchase value correction (matched PURCHASE)",
  "enabled": true,
  "approval_tier": "individual",
  "requires_consent_namespace_clean": false,
  "irreversible": true,
  "operator_disclosure": "Updates existing Manago PURCHASE events via updateContactExtEvent (full field resend — not upsert). Overwrites event value with Shopify order gross (total_price). Not reversible in Manago — prior values remain only in Klints raw/import. Does not decide gross vs net mapping (document that separately). Does not backfill missing orders (use LE-05/LE-01) and does not remove Manago-only extras. Prefer clear gaps first, then Approve LE-02. Re-run DCS after Approve to clear LE-02.",
  "rollback": { "strategy": "none" },
  "operations": [
    {
      "operation_id": "manago.event_correct.purchase_value_le02",
      "op_kind": "event_correct",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.EVENT.UPDATE",
      "entity_type": "event",
      "from_evidence": {
        "match": { "path": "side", "const": "value_mismatch" },
        "entity_key": { "path": "event_external_id" },
        "fields": {
          "order_id": { "path": "event_external_id" },
          "shopify_order_id": { "path": "order.id" },
          "email": { "path": "person.email" },
          "contact_id": { "path": "manago_contact_id" },
          "value": { "path": "shopify_gross" },
          "prior_value": { "path": "manago_value" },
          "occurred_at": { "path": "occurred_at" },
          "currency": { "path": "currency" }
        }
      },
      "guards": ["entity_key_required"]
    }
  ]
}
```

### 4.2 Registry

```json
"LE-02": {
  "file": "LE-02.value_correct.v1.json",
  "enabled": true,
  "template_id": "T6"
}
```

Remove **LE-02** from WB-02 §3.2 Approve-OFF list when shipping.

---

## 5. Adapter / transport / transform

### 5.1 `event_correct` (new)

| Piece | Lock |
|-------|------|
| Catalogue API name | **`updateContactExtEvent`** (sheet Suggested Fix) — singular update, not ingest |
| Transport | `update_contact_ext_event(ctx, event: dict) -> dict` — **exact path + body schema from sandbox discovery** (candidate to verify: `api/contact/updateContactExtEvent`, mirroring ingest’s `api/contact/batchAddContactExtEvent` family). Do not invent undocumented fields. |
| Adapter execute | `op_kind == "event_correct"` → build **full** event payload → transport |
| Adapter dry_run | Validate payload; no HTTP write |
| Payload minimum (until discovery expands) | `externalId`, `contactExtEventType=PURCHASE`, `value` (Shopify gross), and **`email` or `contactId`** |
| Full resend | Also send prior `date` (platform shape from enrich) and `currency` when known — catalogue: **all fields must be resent** |
| Validate | Missing externalId / contact ref / value → intent error; do not partial-write |
| Rollback | `rollback_not_supported` (sheet: not restorable in Manago) |
| **Forbidden** | Calling `batchAddContactExtEvent` / `event_ingest` from LE-02 path |

### 5.2 Capability

Shipped in `capabilities.json` (after sandbox path proof):

```json
"RESTV2.EVENT.UPDATE": {
  "status": "CONFIRMED_LIMITED",
  "batch_max": 50,
  "scope_note": "updateContactExtEvent — LE-02 value correct; path api/contact/updateContactExtEvent; full field resend (not upsert); batch_max=50 matches LE_MISMATCH_SAMPLE until Loom proves higher"
}
```

Execute gate (existing WB-01 rule): refuse execute while status ∉ `{CONFIRMED_LIVE, CONFIRMED_LIMITED}`.  
**Ship sequence:** implement adapter + mapping behind capability status; sandbox proof flips status to `CONFIRMED_LIMITED` (or `CONFIRMED_LIVE`) — do not leave Fix Approve advertising execute while `DISCOVERY_REQUIRED`.

### 5.3 Transform enrich

| Rule | Behavior |
|------|----------|
| Flatten worklist nested `value` | Same as LE-01 / LE-05 |
| Re-resolve PII | Never write masked emails; resolve from Order / Contact / Manago snapshot |
| Target value | Always `shopify_gross` from mismatch — re-read `Order.amount` **only when mismatch amount missing**; never overwrite a bound mismatch gross |
| Prior fields | Prefer mismatch `occurred_at` / `currency` / `manago_contact_id`; else reload matched Manago PURCHASE from snapshot by `externalId` when available |
| Empty / no `value_mismatch` | **0 intents** — no sandbox |

### 5.4 Pipeline

| Rule | Lock |
|------|------|
| Default `max_rows` | `capability_batch_max("RESTV2.EVENT.UPDATE")` capped ≤1000; **shipped = 50** (not individual-tier 1) |
| Truncation probe | Include **LE-02** with note: capped at N corrections — Approve again after re-score if LE-02 still FAILs |
| Sandbox invent | **Never** |
| Once-per-run | Existing WB-04/07 per `(company, LE-02, data_run_id)` |

---

## 6. Allowlist / migration

```text
get_or_create check_id=LE-02, enabled=True, note="PRD-WB-14 LE-02 purchase value correct"
```

Migration: **`0041_writeback_allowed_le02`** (after `0040_writeback_allowed_le05`).

---

## 7. Possible sheet + SURFACE

### 7.1 Possible sheet row (both CSV copies)

| Column | Value |
|--------|--------|
| `check_id` | `LE-02` |
| `check_name` | Purchase value parity |
| `pack_fix_type` | Automated writeback (approved) |
| `fix_owner` | Klints (automated) |
| `suggested_fix` | Correct matched Manago PURCHASE value → Shopify gross via updateContactExtEvent (full resend); mapping-definition Part A not this row |
| `platform` | manago |
| `op_kind` | `event_correct` |
| `entity` | event (catalogue Entity: Order / PURCHASE event) |
| `field_or_key` | PURCHASE event value (float 7.2) |
| `namespace` | native |
| `creates_new` | no |
| `updates_existing` | yes |
| `write_possible_today` | yes (capability CONFIRMED_LIMITED) |
| `rollback_possible_today` | no |
| `mapping_file` | `LE-02.value_correct.v1.json` |
| `evidence_note` | event_correct from side=value_mismatch; full resend; irreversible; prefer LE-05/LE-01 first; gross target; Part A gross/net config out of band |

### 7.2 SURFACE matrix

Update **Transaction / purchase event** row — note **LE-02** value correct via `event_correct` / `updateContactExtEvent` (matched only; not ingest).  

Enabled-mappings table: add **LE-02** · `event_correct` · Enabled (WB-14).

---

## 8. Frontend

| Item | Lock |
|------|------|
| `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | Add **`LE-02`** |
| Honesty blurb | Mention value correction / limited rollback (events overwrite; not restorable in Manago) |
| Toast | Re-run DCS to clear LE-02 |
| `suppressFixProceedToStudio` | **Do not** add LE-02 |
| `verify-wb02-frontend.mjs` | Assert LE-02 allowlisted |
| WB-02 §3.2 | Remove LE-02 from OFF list |

No new Fix chrome. Deep-link: `/fix?issue=LE-02`.

---

## 9. Gates / settings

Unchanged: Settings Allow writebacks · sandbox company rules · ADMIN execute · once-per-run · capability CONFIRMED · irreversible disclosure before Approve.

---

## 10. Tests + verify

| Case | Expect |
|------|--------|
| Registry LE-02 enabled; match `value_mismatch`; op_kind `event_correct` | |
| `evaluate_le_02` emits `value_mismatch` for fixture with wrong matched value | |
| Heuristic-only match does **not** emit value_mismatch | |
| Transform builds intent value=shopify_gross; full resend fields present | |
| Empty mismatches → 0 intents (no sandbox) | |
| Adapter calls update transport — **never** batchAddContactExtEvent | |
| Capability DISCOVERY → execute denied; CONFIRMED → execute OK (mocked) | |
| Allowlist migration seeds LE-02 | |
| FE allowlist includes LE-02 | |
| LE-05 / LE-01 unchanged | |

Script: `scripts/verify_wb14_le02_value_correct_writeback.py` — registry, mapping, allowlist, both sheet copies, FE string, no `event_ingest` in LE-02 mapping, DCS mismatch helper present, capability key exists.

---

## 11. PR / branch

- **Base:** tip with WB-13 merged  
- BE: `feat(WB-14): LE-02 purchase value correction writeback`  
- FE: `feat(WB-14): enable LE-02 Fix Approve`  
- PR body: link this PRD · “T6 event_correct / updateContactExtEvent; DCS value_mismatch rows; gross target; prefer LE-05 first; irreversible”

---

## 12. Acceptance checklist

- [x] DCS emits `side=value_mismatch` per §3.2; drivers retained  
- [x] Mapping `LE-02.value_correct.v1.json` enabled; registry live; template T6; **`approval_tier=individual`**  
- [x] Transport + adapter `event_correct` implemented after **path/body discovery**; validate full resend  
- [x] Capability `RESTV2.EVENT.UPDATE` present; execute only when CONFIRMED_*  
- [x] Sandbox/Loom proof flips capability to CONFIRMED_LIVE (or CONFIRMED_LIMITED with note)  
- [x] Pipeline: no sandbox invent; truncation probe for LE-02  
- [x] `0041_writeback_allowed_le02` seeds LE-02  
- [x] Possible sheet (docs + runtime) + SURFACE synced; rollback=no  
- [x] FE Approve allowlist includes LE-02; honesty + toast; **not** in Proceed suppress list  
- [x] Settings OFF → no execute  
- [x] Tests + `verify_wb14_le02_value_correct_writeback.py` green  
- [x] WB-02 §3.2 LE-02 removed from OFF list; no `event_ingest` on LE-02; Part A not implemented as write  
- [x] DCS-08 LE-02 revenue alias untouched 

---

## 13. Explicitly not in this PR

- Suggested Fix **Part A** (gross vs net mapping config documentation)  
- Switching LE-02 FAIL band to **net** / changing 2% threshold  
- DCS-08 LE-02 revenue_impact / rollup changes  
- `event_ingest` “correction” (duplicate risk)  
- Deleting `manago_only` PURCHASE events / LE-04 guided dedup  
- LE-06 / LE-08 `event_update`  
- CI-05 / CI-03 / consent writebacks  
- Raising `LE_MISMATCH_SAMPLE` beyond 50 without product ask  
- Inventing Manago update path/fields without sandbox discovery  

---

## 14. Code reference map

| Path | Role |
|------|------|
| `dataruns/dcs/executors/lifecycle.py` | `evaluate_le_02` + **new** mismatch rows |
| `dataruns/dcs/lifecycle_join.py` | Matched pairs / amounts for value_mismatch |
| `dataruns/writebacks/mappings/LE-02.value_correct.v1.json` | **New** |
| `dataruns/writebacks/mappings/registry.json` | Enable LE-02 |
| `dataruns/writebacks/transform.py` | `_le02_evidence_rows` / enrich |
| `dataruns/writebacks/adapters/manago_transport.py` | `update_contact_ext_event` |
| `dataruns/writebacks/adapters/manago.py` | `event_correct` branch |
| `dataruns/writebacks/capabilities.json` | `RESTV2.EVENT.UPDATE` |
| `dataruns/writebacks/pipeline.py` | LE-02 ceiling + truncation |
| `dataruns/writebacks/rollback_strategy.py` | event_correct → not supported |
| FE `src/lib/writebacks.ts` | Approve allowlist + honesty |

---

## 15. Traceability

| Field | Value |
|-------|--------|
| Milestone | M2 — Catalogue Automated writeback |
| Pack | Catalogue LE-02 P0 T6 |
| MVP1 · P0 order | After LE-05 (LE-09 → LE-05 → **LE-02**) |
| Parents | WB-01…13 · DCS lifecycle · catalogue Suggested Fix |
| Unblocks | Residual value-field honesty after gap clear |
| Next | Remaining catalogue AW (CI-03, CC-01/02, CI-05, …) as product prioritizes |

---

## 16. Decision log (deep-check + Excel recheck)

| # | Question | Answer |
|---|----------|--------|
| 1 | Can we ship LE-02 with **driver-only** mismatches? | **No** — must emit `value_mismatch` rows |
| 2 | Use `event_ingest` to “fix” value? | **No** — duplicates → LE-04; catalogue requires `updateContactExtEvent` |
| 3 | Gross or net correction target? | **Gross** (`total_price`) — matches MVP1 FAIL SoT; Part A net decision out of scope |
| 4 | Suggested Fix two sentences? | **Split** — Part A config / Part B writeback (this PR = B only) |
| 5 | Adapter exists today? | **Yes (shipped)** — `event_correct` + `update_contact_ext_event` |
| 6 | Exact Manago HTTP path in Excel? | **No** — only API **name**; path proved as `api/contact/updateContactExtEvent` |
| 7 | Capability CONFIRMED today? | **Yes** — `EVENT.UPDATE` **CONFIRMED_LIMITED** batch_max 50 |
| 8 | `approval_tier` batch or individual? | **`individual`** — stub_factory T6 default (PT-04 used batch for `detail_set`; different op) |
| 9 | Excel says missing events (LE-01) — where does LE-05 fit? | LE-05 = order-gap list (WB-13); prefer LE-05 then LE-01 then LE-02 |
| 10 | Overview T6 also LE-04 / PT-04? | LE-04 off; PT-04 already `detail_set`; this PR = LE-02 only |
| 11 | Rollback in Manago? | **No** — sheet Rollback Note + irreversible |
| 12 | After this? | Next open catalogue AW (CI-03 / CC-01/02 / CI-05) per priority |

---

## 17. Deep-check evidence (2026-09-23; rechecked same day — shipped)

| Source | Finding |
|--------|---------|
| Excel §02 LE-02 (all 24 cols) | AW approved · T6 · P0 · Blueprint Y · `updateContactExtEvent` · full resend · not restorable in Manago · Severity/Weight High |
| Excel §01 T6 | LE-02 + LE-04 + PT-04 — only LE-02 AW value-correct in this PR |
| Excel §06 Field Mapping | Composition rule mentions total_price/subtotal; MVP1 LE-02 fail = gross |
| CHECK_MASTER_42 | Purchase value parity · RC-02/13/14 · High · MVP1-A |
| `evaluate_le_02` | Attaches lifecycle `value_mismatches` first, then drivers |
| `lifecycle_join` | Emits `value_mismatch` (non-heuristic; `event_external_id`; dedupe per Shopify order; 2dp) |
| `stub_factory` | T6 → `event_correct` · `approval_tier=individual` · irreversible |
| Registry / mapping | `LE-02.value_correct.v1.json` enabled · match `value_mismatch` · entity_key=`event_external_id` |
| Adapter / transport | `event_correct` → `api/contact/updateContactExtEvent` (never ingest) |
| `capabilities.json` | `RESTV2.EVENT.UPDATE` **CONFIRMED_LIMITED** · batch_max **50** |
| FE allowlist / WB-02 OFF | LE-02 allowlisted; removed from OFF list; honesty for `event_correct` |
| DCS-08 | LE-02 revenue alias of missing GMV — **unchanged** in WB-14 |
