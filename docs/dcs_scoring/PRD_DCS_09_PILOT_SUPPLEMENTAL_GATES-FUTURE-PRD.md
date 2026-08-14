# PRD-DCS-09 — Pilot supplemental preflight gates (BL-003)

**Status:** Ready for implementation  
**Backlog:** `BL-003` (P0, MVP1-A)  
**Depends on:** DCS-00…06 (42-check score path + snapshot + executors pattern), CONN fresh import  
**Does not depend on:** MCP, Architecture (BL-008), Orchestration waves, Assessment Report  
**Unblocks:** BL-010 (16-pilot registry readiness), later Build / Handoff gating  

---

## 0. Original references (authoritative)

| Artifact | Path / location | Use for |
|----------|-----------------|--------|
| Backlog row BL-003 | Build Pack `06_Implementation/implementation_backlog_v1.2.xlsx` → sheet **01 Backlog** | Acceptance: “Every pilot gate resolves; supplemental FAIL blocks dependent pilot only” |
| Gate inventory + UC map | Build Pack / DataPack `01_Specifications/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx` → sheet **11 Pilot Supplemental Gates** | IDs, detection summary, Required By, Failure Behavior, MVP1 Role = `ON_DEMAND_PREFLIGHT` |
| Detection + fix detail | Same workbook → sheet **02 Check Catalogue** (rows for the 12 IDs) | Full detection logic, Suggested Fix, Fix Type, Fix Owner |
| Headline scope (do not mix) | Same workbook → sheet **09 MVP1 Check Scope** | The **42** only; these 12 are **outside** that list |
| Pilot list | Build Pack `04_MVP1_Pilot_Blueprints/pilot_manifest.json` | UC titles / rank |
| Blueprint gating (later) | Each `UC-*_blueprint.json` `gating_check_ids` | Headline + supplemental IDs a pilot declares |
| Capability / MCP (deferred) | Build Pack `02_Execution_Capabilities/…` | Out of scope for this PRD |
| Existing DCS overview | `docs/dcs_scoring/PRD_00_OVERVIEW.md` | Series context (listed these gates as later — this PRD implements them) |
| Executor pattern | `docs/dcs_scoring/PRD_DCS_04_RULE_BASED_CHECKS.md` | How to build checks against snapshot |
| Machine finding shape | Build Pack `03_Machine_Contracts/finding.schema.json` | Optional finding records for FAIL |

Copies of the DCS workbook also live under:

- `docs/dcs_scoring/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx`
- `Klints_MVP1_Rohan_Build_Pack_v1.2_20260718/01_Specifications/…` (backend tree)
- `DataPack/Klints_MVP1_Rohan_Build_Pack_v1.2_20260718/…`

**Stop-and-flag:** If code or tenant data disagrees with sheet **11** / **02**, do not invent thresholds silently — record expected vs observed and escalate (Build Pack stop-and-flag rule).

---

## 1. Vision (what / why)

### 1.1 Plain language

The **42-check DCS** answers: *“Is the data healthy enough?”* → headline score + scored worklist.

The **12 supplemental gates** answer a different question:

> *“Is it safe to plan / build / activate this specific pilot workflow?”*

They are **on-demand preflights**:

- **Not** part of the 42  
- **Do not** change `headline_score` or dimension scores  
- On **FAIL**: block **only** the dependent pilot(s)  
- On **PASS**: that pilot may proceed (subject to its other headline gating checks later)

### 1.2 Why this exists

Sheet **11** governance rule:

> A pilot cannot be planned, built or activated until all of its headline-scope **and** supplemental gating Check IDs have a current PASS result.

Without BL-003, pilot registry (BL-010) cannot enforce real readiness. Building UC-11 while `SP-04` is broken would ship a replenishment flow that never fires correctly.

### 1.3 What “on-demand” means

| Term | Meaning for MVP1 |
|------|------------------|
| On-demand | Evaluate when **pilot readiness** is requested (or when explicitly batching readiness for the 16 UCs) |
| Not on-demand | Do **not** treat them as inputs to every headline score assembly |
| Allowed convenience | May reuse the **latest DCS snapshot / DB state** from the last successful score run so you do not re-import |

**Do not** pass supplemental results into `assemble_dcs_score()`.

---

## 2. Scope

### 2.1 In scope (this PRD)

1. Registry of exactly **12** checks with role `ON_DEMAND_PREFLIGHT` / `PILOT_GATE`  
2. Static map **Check ID → Required By (UC-*)** from sheet 11  
3. Executors for each check (snapshot / DB context — same pattern as DCS-04)  
4. On-demand evaluation service + API  
5. Persistence of results **scoped separately** from the 42  
6. Readiness helper: `use_case_id → { ready, blocked_by[] }`  
7. Tests proving score isolation + pilot blocking  

### 2.2 Out of scope (future stages)

| Item | When |
|------|------|
| Showing these in the main DCS “ranked by impact” worklist as score issues | FE / FE-06 — **do not** by default |
| Full Fix-flow / writeback execution for these IDs | Pilot / Fix / Orchestration stages |
| Architecture assessment (BL-008/009) | After BL-003 |
| Loading 16 blueprints into runtime (BL-010) | Consumes this PRD’s readiness API |
| MCP discovery | Explicitly deferred |
| ERP product connector | BR-09 / PT-06 degrade to `NOT_CONNECTED` when ERP out of scope |
| Assessment Report PDF | Later; may *mention* blocked pilots, not as DCS score rows |

### 2.3 Non-negotiable rules

1. `EXPECTED_CHECK_COUNT` for headline master stays **42**.  
2. Supplemental FAIL must **not** set DCS `run_state = BLOCKED` by itself.  
3. Foundation gate FAIL (FD-*) still blocks scoring as today.  
4. Missing inputs → `UNKNOWN` + `MISSING_INPUT:…` (not fake FAIL/PASS).  
5. ERP-dependent checks with `erp_in_scope=false` → `NOT_CONNECTED` / `ERP_OUT_OF_SCOPE` (same convention as BR-01 today).  

---

## 3. When it runs (triggers)

| Trigger | Who | Behavior |
|---------|-----|----------|
| `GET/POST` pilot readiness for one UC | API / future FE | Evaluate only gates required by that UC (union with optional “also require headline gating IDs” when blueprints loaded) |
| Batch readiness for all 16 | Admin / job | Evaluate unique set of the 12 (or subset needed) once; attach per-UC blocked_by |
| After fresh DCS score (optional hook) | Worker flag | **Not required** for v1; if enabled, store supplemental results but **exclude from assemble** |
| Manual re-run gates | Admin | Re-evaluate using latest snapshot / optional refresh |

**Default v1:** explicit readiness API only (true on-demand).

---

## 4. Inventory (the 12)

### 4.1 Master table (from sheet 11)

| Check ID | Dimension | Name | Systems | Severity | Required By | Failure behavior |
|----------|-----------|------|---------|----------|-------------|------------------|
| BR-03 | 07 Business Reality | Out-of-stock exposure in active surfaces | Manago | High | UC-28 | FAIL → block UC only; excluded from headline DCS |
| BR-09 | 07 Business Reality | Replenishment input completeness | ERP vs Manago | Medium | UC-08, UC-11 | same |
| CC-06 | 05 Channel & Consent | Double opt-in state integrity | Manago | Medium | UC-02, UC-05 | same |
| CI-08 | 01 Customer Identity | Email format validity | Manago | Medium | UC-02 | same |
| LE-07 | 02 Lifecycle Event | Cart event coverage | Shopify vs Manago | High | UC-21 | same |
| LE-10 | 02 Lifecycle Event | Event type discipline | Manago | Medium | UC-09 | same |
| PT-05 | 03 Product & Transaction | Price parity catalog vs commerce | Manago vs Shopify | High | UC-13 | same |
| PT-06 | 03 Product & Transaction | Stock quantity parity | Manago vs Shopify vs ERP | High | UC-12, UC-21 | same |
| PT-11 | 03 Product & Transaction | Product attribute completeness | Manago vs Shopify | Medium | UC-28 | same |
| PT-13 | 03 Product & Transaction | Coupon and discount consistency | Manago vs Shopify | High | UC-04 | same |
| SP-04 | 04 Segment & Property | Date-prefixed detail validity | Manago | High | UC-11 | same |
| SP-10 | 04 Segment & Property | RFM computability coverage | Manago | High | UC-06B | same |

**MVP1 Role (sheet 11):** `ON_DEMAND_PREFLIGHT`  
**Numeric weight for scoring:** `0` (never scored)

### 4.2 UC → supplemental gates (invert of sheet 11)

| Use case | Title (pilot_manifest) | Supplemental gates |
|----------|------------------------|--------------------|
| UC-02 | Welcome series continuity | CI-08, CC-06 |
| UC-04 | First-purchase incentive delivery | PT-13 |
| UC-05 | Double opt-in completion nudge | CC-06 |
| UC-06B | Second Purchase Accelerator | SP-10 |
| UC-08 | Post-purchase education / product usage | BR-09 |
| UC-09 | Review & UGC request | LE-10 |
| UC-11 | Replenishment reminder | BR-09, SP-04 |
| UC-12 | Back-in-stock notification | PT-06 |
| UC-13 | Price-drop alert | PT-05 |
| UC-21 | Cart abandonment recovery | LE-07, PT-06 |
| UC-28 | Complementary product cross-sell | BR-03, PT-11 |

**Pilots with no sheet-11 supplemental row** (UC-10, UC-16, UC-17, UC-23, UC-36, …): readiness for *this* PRD is vacuously OK on supplemental side; they still need **headline** `gating_check_ids` from their blueprint when BL-010 lands.

---

## 5. How it connects to what we already built

```text
[Existing]
Connect → fresh import (every DCS run) → snapshot → 42 executors → assemble → score/worklist/API

[This PRD]
                    latest snapshot / company DB
                              ↓
              on-demand: run subset of 12 executors
                              ↓
              persist scope=pilot_supplemental
                              ↓
              readiness(UC) → ready | blocked_by[]

[Later]
BL-010 pilots + orchestration consume readiness
Architecture (BL-008) is parallel stream — not a dependency
```

Reuse:

| Existing | Reuse how |
|----------|-----------|
| `dataruns/dcs/fresh_import.py` + snapshot | Data as-of for evaluation |
| `dataruns/dcs/db_context.py` / snapshot builders | Same reads as scored checks |
| `dataruns/dcs/executors/*` + `registry.py` | New executor functions / register IDs |
| `CheckResult` type | Identical status enum |
| Worklist / status APIs | **Do not** auto-merge into scored issues |

Do **not** change:

- `check_master_mvp1.json` 42 count / `EXPECTED_CHECK_COUNT`  
- `assemble.py` scoring inputs  
- FE Data Center ranked issues (unless a separate “Pilot gates” surface is added later)  

---

## 6. What to store

### 6.1 Static config (versioned in repo)

1. `check_master_supplemental_mvp1.json` (or DB seed table)  
   - `check_id`, `dimension`, `role: ON_DEMAND_PREFLIGHT`, `numeric_weight: 0`, `severity`  
2. `pilot_supplemental_gate_map.json`  
   - `check_id → [UC-…]` and/or `UC → [check_id]`  

### 6.2 Runtime results (per evaluation)

Store each result with an explicit scope so they never pollute headline refs:

```json
{
  "scope": "pilot_supplemental",
  "check_id": "SP-04",
  "status": "FAIL",
  "confidence": "HIGH",
  "reason_code": null,
  "evidence": [],
  "evaluated_at": "2026-08-07T10:00:00Z",
  "data_run_id": 1234,
  "snapshot_as_of": "2026-08-07T09:55:00Z",
  "requested_for": ["UC-11"],
  "scoring_model_version": "DCS-1.0.0",
  "gate_catalog_version": "MVP1-SUPP-12-v1.4.1"
}
```

**Persistence options (pick one in impl; prefer A):**

| Option | Approach |
|--------|----------|
| **A (recommended)** | New model or `DataRun.metadata["pilot_supplemental_results"]` on a small `kind=pilot_gate_eval` DataRun |
| B | Reuse `RunIssue` / check result rows with `is_optional` or `scope` flag — **must** filter out of DCS worklist queries |

### 6.3 What not to store as “DCS issues”

- Do **not** emit default worklist issues that sort into “Ranked by projected impact” for these 12.  
- Optional: store `finding`-shaped records for FAIL for later Fix UI (`finding.schema.json`), tagged `blocks: ["pilot:UC-11"]`.  

---

## 7. API (v1)

Base: `/api/v1/` · JWT · company from user (same as DCS-06).

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/dcs/pilot-gates/master/` | List 12 definitions + UC map |
| `POST` | `/dcs/pilot-gates/evaluate/` | On-demand evaluate |
| `GET` | `/dcs/pilot-gates/latest/` | Latest evaluation bundle for company |
| `GET` | `/dcs/pilots/{use_case_id}/readiness/` | Convenience readiness |

### 7.1 POST `/dcs/pilot-gates/evaluate/`

**Roles:** admin (analyst optional read-eval — lock: admin mutate, analyst+viewer read latest).

**Request:**

```json
{
  "use_case_ids": ["UC-11"],
  "check_ids": null,
  "data_run_id": null,
  "erp_in_scope": false
}
```

| Field | Rules |
|-------|--------|
| `use_case_ids` | If set, evaluate union of gates required by those UCs |
| `check_ids` | If set, evaluate exactly these (must be ⊂ 12) |
| Both null | Evaluate all 12 |
| `data_run_id` | Optional pin to a SUCCEEDED DCS score DataRun snapshot; default = latest succeeded |
| `erp_in_scope` | Same meaning as DCS runs |

**Response (200):**

```json
{
  "evaluation_id": "...",
  "as_of": "...",
  "data_run_id": 1234,
  "results": [
    {
      "check_id": "SP-04",
      "status": "FAIL",
      "severity": "High",
      "required_by": ["UC-11"],
      "evidence": [],
      "suggested_fix": "from sheet 02"
    }
  ],
  "readiness": [
    {
      "use_case_id": "UC-11",
      "supplemental_ready": false,
      "blocked_by": ["SP-04", "BR-09"]
    }
  ]
}
```

**Readiness rule (this PRD):**

```text
supplemental_ready = every required supplemental check for that UC has status == PASS
```

`NOT_CONNECTED` / `UNKNOWN` / `WARN` / `FAIL` ⇒ **not ready** (strict PASS).  
If product later allows WARN with approval, that is a separate decision — **v1 = PASS only** (matches sheet 11 “PASS required”).

---

## 8. How to build each check (conditions, what / why / when)

Shared executor contract (align DCS-04):

```python
def execute(check_id: str, ctx: ScoringContext) -> CheckResult:
    """
    Read-only vs snapshot/DB.
    Missing inputs → UNKNOWN + MISSING_INPUT
    ERP out of scope where applicable → NOT_CONNECTED
    """
```

**When (per check):** only when that `check_id` is in the on-demand evaluation set.  
**Why:** sheet 11 Required By + business impact from sheet 02.  
**Fix (future):** sheet 02 Suggested Fix / Fix Type / Fix Owner — surface in readiness payload; do not auto-execute in BL-003.

Provisional numeric thresholds: if sheet 02 is qualitative only, implement measurable metrics in `evidence.value`, choose MVP1 cutovers in the appendix below, comment `STOP_AND_FLAG` if contested.

---

### CI-08 — Email format validity

| | |
|--|--|
| **Why** | Bad emails inflate bounces; junk identities break match rates; blocks welcome (UC-02) |
| **When** | Readiness for UC-02 (or explicit CI-08) |
| **Systems** | Manago contacts |
| **Detect** | RFC-lite syntax; disposable domains; obvious typo domains (`gmial.com`, etc.) |
| **PASS** | Invalid/typo/disposable rate below MVP1 threshold (appendix) **or** zero material violations if threshold TBD |
| **FAIL** | Material invalid set above threshold |
| **UNKNOWN** | No contact sample in snapshot |
| **Fix (later)** | Flag invalid; suppression tag (not delete); typo corrections with approval — CRM manager / approved writeback |
| **Code** | `executors/identity.py` |

---

### CC-06 — Double opt-in state integrity

| | |
|--|--|
| **Why** | Stuck Not-confirmed cohort is unreachable in DOI markets; caps list growth (UC-02, UC-05) |
| **When** | UC-02 / UC-05 readiness |
| **Systems** | Manago consent / DOI state |
| **Detect** | Share stuck in Not-confirmed beyond confirmation-window norms; DOI policy consistency across signup sources; confirmation deliverability signals if available |
| **PASS** | Stuck share within norms; no systemic DOI break |
| **FAIL** | Stuck cohort or broken DOI flow beyond threshold |
| **UNKNOWN** | DOI fields not present in snapshot |
| **Fix (later)** | Manual (guided) — CRM manager: audit DOI per source, fix template/link, re-confirm nudge |
| **Code** | `executors/consent.py` |

---

### LE-07 — Cart event coverage

| | |
|--|--|
| **Why** | Cart abandonment is top revenue flow; uncaptured carts = lost recovery (UC-21) |
| **When** | UC-21 readiness |
| **Systems** | Shopify abandoned checkouts vs Manago CART events |
| **Detect** | Capture rate in window; identity linkage (email present at abandonment) |
| **PASS** | Capture rate ≥ MVP1 threshold; linkage acceptable |
| **FAIL** | Material gap Shopify carts vs Manago CART |
| **UNKNOWN** | Either side missing checkout/cart stream |
| **Fix (later)** | Integration build — CART pipe add/update via eventId; guest-without-email is capture UX, not silent backfill |
| **Code** | `executors/lifecycle.py` |

---

### LE-10 — Event type discipline

| | |
|--|--|
| **Why** | Polluting PURCHASE/CART/OTHER breaks automations + platform analytics (UC-09) |
| **When** | UC-09 readiness |
| **Systems** | Manago events |
| **Detect** | Event type distribution; misuse (PURCHASE for reservations, OTHER dumping ground); type-changed events |
| **PASS** | Vocabulary matches mapping config; no material misuse |
| **FAIL** | Misuse / type-change patterns above threshold |
| **UNKNOWN** | Events not in snapshot |
| **Fix (later)** | Integration build — re-route streams; never change type on existing events |
| **Code** | `executors/lifecycle.py` |

---

### PT-05 — Price parity catalog vs commerce

| | |
|--|--|
| **Why** | Wrong prices in messages = trust/legal risk; price-drop pilot (UC-13) |
| **When** | UC-13 readiness |
| **Systems** | Manago catalog vs Shopify price |
| **Detect** | price/discountPrice vs Shopify; staleness; discount flags |
| **PASS** | Mismatch rate / staleness within threshold |
| **FAIL** | Material price drift |
| **UNKNOWN** | Catalog or products missing |
| **Fix (later)** | Webhook → product/updatePrice; reconciliation; approved writeback |
| **Code** | `executors/product.py` |

---

### PT-06 — Stock quantity parity

| | |
|--|--|
| **Why** | OOS promoted / in-stock suppressed; back-in-stock + cart (UC-12, UC-21) |
| **When** | UC-12 / UC-21 readiness |
| **Systems** | Manago vs Shopify vs ERP (if in scope) |
| **Detect** | Quantity parity; negative / frozen / stale |
| **PASS** | Parity within SLA |
| **FAIL** | Material mismatch or negative stock exposed |
| **NOT_CONNECTED** | ERP leg when `erp_in_scope=false` — still compare Manago↔Shopify; do not require ERP |
| **UNKNOWN** | Inventory fields missing |
| **Fix (later)** | Authoritative source + sync chain; Data lead |
| **Code** | `executors/product.py` |

---

### PT-11 — Product attribute completeness

| | |
|--|--|
| **Why** | Recommendations / cross-sell need category, brand, image, URL (UC-28) |
| **When** | UC-28 readiness |
| **Systems** | Manago vs Shopify |
| **Detect** | Coverage of category, brand, image URL, product URL; parity with Shopify |
| **PASS** | Coverage ≥ threshold on active catalog |
| **FAIL** | Material gaps |
| **UNKNOWN** | No catalog |
| **Fix (later)** | Enrichment upsert; mapping contract — Klints automated |
| **Code** | `executors/product.py` |

---

### PT-13 — Coupon and discount consistency

| | |
|--|--|
| **Why** | Dead codes in incentive emails destroy trust (UC-04) |
| **When** | UC-04 readiness |
| **Systems** | Manago coupons vs Shopify discount codes |
| **Detect** | Issued codes exist/valid in Shopify; redemption feedback; expired codes still sent |
| **PASS** | No material invalid/expired-in-flight codes |
| **FAIL** | Invalid or expired codes still referenced |
| **UNKNOWN** | Coupon objects not in snapshot |
| **Fix (later)** | Integration lifecycle sync; preflight block — external integrator |
| **Code** | `executors/product.py` |

---

### SP-04 — Date-prefixed detail validity

| | |
|--|--|
| **Why** | Replenishment proximity triggers depend on valid dates (UC-11); wrong type ⇒ never/daily fire |
| **When** | UC-11 readiness |
| **Systems** | Manago details (`date.*` / dictionary date — **verify Manago docs**) |
| **Detect** | Parse validity; plausibility window; coverage for proximity-critical fields (incl. `klints_next_refill` type contract) |
| **PASS** | Critical date fields valid + typed correctly for trigger |
| **FAIL** | Invalid/missing critical dates or wrong detail type for proximity |
| **UNKNOWN** | Details not available |
| **STOP_AND_FLAG** | Confirm whether proximity trigger needs standard `date.` detail vs dictionary detail before writeback later |
| **Fix (later)** | Normalize batch (approved); blank invalid with incident list |
| **Code** | `executors/segment.py` |

---

### SP-10 — RFM computability coverage

| | |
|--|--|
| **Why** | Flagship UC-06B needs RFM; “no data” Champions get worst treatment |
| **When** | UC-06B readiness |
| **Systems** | Manago RFM segments |
| **Detect** | Share with RFM assigned; unassigned = no-purchase-history (OK) vs missing-events (LE damage) |
| **PASS** | Purchasers have RFM coverage ≥ threshold; residual unassigned explained as no-history |
| **FAIL** | Material purchaser cohort without RFM attributable to event gaps |
| **UNKNOWN** | RFM not readable |
| **Fix (later)** | Upstream event repair (LE-05 etc.); this check verifies convergence |
| **Code** | `executors/segment.py` |

---

### BR-03 — Out-of-stock exposure in active surfaces

| | |
|--|--|
| **Why** | OOS in recommendations/campaigns = dead clicks (UC-28) |
| **When** | UC-28 readiness |
| **Systems** | Manago catalog + active surfaces / collections / scheduled content |
| **Detect** | Zero/negative stock still present on active surfaces |
| **PASS** | No material OOS exposure on active surfaces |
| **FAIL** | OOS SKUs actively exposed |
| **UNKNOWN** | Cannot resolve surface membership or stock |
| **Fix (later)** | Availability gate / flags via product upsert — Klints automated |
| **Code** | `executors/business.py` |

---

### BR-09 — Replenishment input completeness

| | |
|--|--|
| **Why** | UC-08 / UC-11 need usage-cycle inputs (pack size, consumption days) |
| **When** | UC-08 / UC-11 readiness |
| **Systems** | ERP vs Manago (consumption model may be Klints-computed later) |
| **Detect** | Coverage of replenishment-eligible assortment with pack size / expected consumption days (or governed `klints_` equivalents) |
| **PASS** | Coverage ≥ threshold |
| **FAIL** | Material gaps on replenishment candidates |
| **NOT_CONNECTED** | If detection *requires* ERP and `erp_in_scope=false` — do not fake PASS; readiness stays blocked **or** allow Manago-only `klints_` coverage path if snapshot has it (document chosen path in impl) |
| **Fix (later)** | Category consumption model + write `klints_` fields — Klints automated |
| **Code** | `executors/business.py` |

---

## 9. Show as issues? Fixes? (product rules)

| Surface | BL-003 (now) | Future |
|---------|--------------|--------|
| DCS score / arc / dimensions | No | No |
| Data Center ranked issues (42 FAIL/WARN) | **No** (default) | Optional filter “Pilot blockers” — separate |
| Pilot / Opportunity readiness card | Return `blocked_by` in API | FE shows “Blocked by SP-04” |
| Fix this issue CTA | Not required | Route by Fix Type from sheet 02; approval for writebacks |
| Assessment Report | N/A | May list blocked pilots under remediation (paid) |

**Fix ownership remains sheet 02** — BL-003 only **evaluates and reports**; it does not execute writebacks.

---

## 10. Implementation plan (ordered)

| Step | Deliverable | Notes |
|------|-------------|--------|
| 1 | Supplemental master JSON + UC map | Exact 12 IDs from sheet 11 |
| 2 | Seed / load helpers | Separate from `EXPECTED_CHECK_COUNT = 42` |
| 3 | Register executor stubs | Return UNKNOWN until logic lands |
| 4 | Evaluate service | Union gates by UC; persist scoped results |
| 5 | API endpoints | §7 |
| 6 | Implement executors in batches | See §11 |
| 7 | Tests | Score isolation + readiness matrix |
| 8 | (Optional) FE readiness | After API stable |

### 10.1 Suggested executor batches

| Batch | IDs | Rationale |
|-------|-----|-----------|
| A | CI-08, LE-10, SP-10 | Mostly Manago contact/event/RFM already in DB |
| B | LE-07, PT-05, PT-11 | Shopify↔Manago parity patterns exist |
| C | PT-06, PT-13, CC-06 | Needs inventory/coupons/DOI fields — UNKNOWN until ingest enough |
| D | SP-04, BR-03, BR-09 | Trigger-type confirmation + surfaces/ERP — stop-and-flag SP-04 type |

---

## 11. Files to touch

| File / area | Change |
|-------------|--------|
| `dataruns/dcs/check_master_supplemental_mvp1.json` | **New** — 12 defs |
| `dataruns/dcs/pilot_supplemental_gate_map.json` | **New** — UC ↔ gates |
| `dataruns/dcs/supplemental.py` (or `pilot_gates.py`) | Load map, evaluate, readiness |
| `dataruns/dcs/executors/{identity,lifecycle,product,segment,consent,business}.py` | Executors |
| `dataruns/dcs/executors/registry.py` | Register 12 IDs |
| `dataruns/dcs/views.py` + urls | API |
| `dataruns/models.py` | Optional dedicated model / metadata kind |
| `dataruns/tests/test_dcs_pilot_gates.py` | **New** |
| `docs/dcs_scoring/PRD_00_OVERVIEW.md` | Move “12 pilot supplemental gates” from out-of-scope to pointer here (follow-up edit) |

**Do not** add these 12 into `check_master_mvp1.json` as SCORED rows.

---

## 12. Acceptance criteria (maps to BL-003)

- [ ] Exactly **12** supplemental check IDs match sheet 11  
- [ ] Role / weight ensures **zero** effect on `headline_score` (test: assemble 42-only == assemble when supplemental also evaluated)  
- [ ] FAIL on supplemental **does not** force DCS `BLOCKED`  
- [ ] FAIL on supplemental **does** set `supplemental_ready=false` for Required By UCs  
- [ ] On-demand evaluate runs **without** requiring a new score assembly  
- [ ] Results stored with `scope=pilot_supplemental` (or equivalent) and excluded from DCS worklist default query  
- [ ] ERP out-of-scope behavior documented and tested for BR-09 / PT-06  
- [ ] SP-04 Manago date/dictionary type question recorded (resolved or STOP_AND_FLAG)  
- [ ] Golden / unit fixtures for at least batches A–B  

---

## 13. MVP1 thresholds appendix (fill during impl)

| Check | Provisional MVP1 rule | Source |
|-------|----------------------|--------|
| CI-08 | FAIL if invalid+typo+disposable ≥ 2% of contacts with email (or ≥ 50 rows) | Qualitative sheet 02 — confirm |
| CC-06 | FAIL if Not-confirmed older than 7d ≥ 5% of DOI cohort | Norms TBD — confirm |
| LE-07 | FAIL if CART capture rate vs abandoned checkouts < 70% | TBD |
| LE-10 | FAIL if OTHER share > 15% or type-changed events > 0 in window | TBD |
| PT-05 | FAIL if price mismatch > 2% of active SKUs | TBD |
| PT-06 | FAIL if qty mismatch > 2% or any negative exposed on active | TBD |
| PT-11 | FAIL if any of category/brand/image/url missing on > 10% active | TBD |
| PT-13 | FAIL if any in-flight send references invalid/expired code | Binary |
| SP-04 | FAIL if any proximity-critical date invalid/unparseable | Binary on critical set |
| SP-10 | FAIL if purchasers without RFM > 10% | TBD |
| BR-03 | FAIL if any OOS SKU on active surface | Binary |
| BR-09 | FAIL if replenishment-candidate coverage < 80% | TBD |

Replace with sheet-exact cutovers when George confirms.

---

## 14. Future stage handoff

| Stage | Consumes BL-003 how |
|-------|---------------------|
| **BL-010 Pilot registry** | Call readiness; refuse plan/build if not `supplemental_ready` (+ blueprint headline gates) |
| **Orchestration** | Emit FIX tasks for `blocked_by` check IDs; priority formula later |
| **Architecture** | Independent; may cross-check (e.g. WF on broken dates) but not required to ship BL-003 |
| **Report** | Optional “pilots blocked” section from latest readiness |
| **Fix / writeback** | Execute sheet 02 fixes under approval model — not part of evaluate |

---

## 15. One-page summary

| Question | Answer |
|----------|--------|
| What? | 12 on-demand pilot preflight checks |
| Why? | Don’t plan/build pilots on broken prerequisites |
| When? | When readiness is asked — not inside score assembly |
| Store? | Scoped results + UC map; not scored worklist |
| Show as DCS issues? | No (default) |
| Fixes now? | Return suggested_fix text only |
| Score impact? | None |

**Backlog ID:** BL-003 · **PRD ID:** DCS-09
