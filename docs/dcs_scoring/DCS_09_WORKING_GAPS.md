# DCS-09 Working / Gaps (PRD-DCS-09)

**PRD:** `PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md`  
**Branch intent:** `feature/dcs-09-pilot-supplemental-gates`  
**Scope:** Evaluate 12 pack supplemental preflight gates; persist `scope=pilot_supplemental`; merge into `recommend.py` so pilots can become **`ready`** (not forever **`ready_provisional`**). **Never touch headline 42.**

**Backlog:** Pack **BL-003**  
**Depends on:** DCS 42-check path + snapshot · UC-01 / WF-01 recommend + Studio · OPS-UC-01 pilots seeded  
**Out of scope:** Changing `EXPECTED_CHECK_COUNT=42` / `assemble_dcs_score()` · HO-02 Send · CAP-01B · Engineering writeback mappings for these 12 · inventing PASS

---

## Step progress

| Step | Status | Notes |
|------|--------|-------|
| 0 Preconditions | **Done** | Pack inventory + sheet 11 opened; 12 IDs locked; zero 42 overlap; gap baseline |
| 1 Static mapping + contract | **Done** | supplemental master JSON (12) + UC gate map + `pilot_gates` contract/loader |
| 2 Persistence | **Done** | `DataRun` `pilot_gate_eval` save/load + merge; company-scoped |
| 3 Supplemental executor framework | **Done** | Isolated registry + context + ERP stubs; 42 isolation proven |
| 4 Slice A executors | **Done** | **CI-08 + CC-06** registered; PASS/FAIL/UNKNOWN/NOT_CONNECTED |
| 5 Evaluate orchestration | **Done** | `evaluate_pilot_gates` resolve → run → persist + readiness |
| 6 Wire `recommend.py` | **Done** | Store merge + audit: early-path `supplemental_status`; build seed uses store |
| 7 APIs | **Done** | master / evaluate / latest / readiness; bool parse + company isolation audited |
| 8 Slice B executors | **Done** | Audited twice: email capture, zero-join, malformed inject, connector honesty |
| 9 QA + build_package regression | **Done** | provisional clear; Generate lock; QA engine FAIL path; UNKNOWN/WARN honesty |
| 10 BE acceptance matrix | **Done** | PRD §10 locked in `test_pilot_gates_step10` |
| 11 FE light | **Done** | Opportunities + Studio supplemental blockers; provisional banner; no DCS pollution |
| 12 Verify + PR prep | **Done** | `verify_dcs09_backend.py` (+ `--run-tests`); audited locks; PRD §10 verify checked |
| 13 PR | **Ready** | Manual commit/PR — see §Step 13 (BE + FE split; you commit) |

**Optional P1 (post-M2 or late Step 11):** FE “Evaluate pilot gates” CTA (Slice C) — not required for §10 acceptance.

---

## Step 0 — Preconditions

**Goal:** Confirm pack SoT, code gap, and non-negotiable locks before mapping.  
**Tests:** `dataruns.tests.test_pilot_gates_step0`

### 0.0 Pack inventory (verified)

#### A — DCS workbook (sheet 11 + 02 + 09)

| File | Role for DCS-09 | Status |
|------|-----------------|--------|
| `Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx` | Sheet **11** Pilot Supplemental Gates · sheet **02** Check Catalogue (detection) · sheet **09** MVP1 scope (**42 only**) | **Found** (84 297 bytes) · sheets opened via openpyxl |

Path: `Klints_MVP1_…/01_Specifications/`

**Sheets confirmed on workbook:** `02 Check Catalogue` · `09 MVP1 Check Scope` · `11 Pilot Supplemental Gates` (among 11 total sheets).

#### Sheet 11 — Pilot Supplemental Gates (read)

| Metric | Value |
|--------|-------|
| Data rows | **12** (Check ID → Required By) |
| Failure Behavior (all rows) | PASS required; FAIL blocks **dependent pilot only**; excluded from headline DCS |
| Governance (sheet header) | Pilot cannot plan/build/activate until headline **and** supplemental gates PASS |

**Sheet 11 check IDs = constants = manifest** (asserted in `test_pilot_gates_step0`).

#### B — Pilot pack

| File | Role | Status |
|------|------|--------|
| `pilot_manifest.json` | `supplemental_preflight_checks` (12 IDs) | **Found** — matches `constants.py` |
| `UC-*_blueprint.json` (**16**) | `gates.gating_check_ids` — UC↔supplemental map | **Found** — matches PRD §3.1 **and** sheet 11 Required By |

MVP1 pilot IDs in pack: UC-02, UC-04, UC-05, UC-06B, UC-08, UC-09, UC-10, UC-11, UC-12, UC-13, UC-16, UC-17, UC-21, UC-23, UC-28, UC-36.

#### C — Repo docs / archive

| Path | Role | Status |
|------|------|--------|
| `docs/engineering/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md` | Implementation SoT | Present |
| `docs/engineering/DCS_09_WORKING_GAPS.md` | Step tracker | Present |
| `docs/dcs_scoring/PRD_DCS_09_…-FUTURE-PRD.md` | Long appendix (per-check notes) | Present |

### 0.1 The 12 — quadruple lock verified

| Source | Count | Match |
|--------|-------|-------|
| Sheet **11** Check ID column | 12 | BR-03 … SP-10 |
| `SUPPLEMENTAL_PREFLIGHT_CHECKS` | 12 | **Identical set** |
| `pilot_manifest.json` | 12 | **Identical set** |
| Headline `check_master_mvp1.json` overlap | 0 | **No supplemental ID in 42** |

### 0.2 UC ↔ supplemental map (sheet 11 = blueprints = PRD §3.1)

| UC | Supplemental gates |
|----|-------------------|
| UC-02 | CC-06, CI-08 |
| UC-04 | PT-13 |
| UC-05 | CC-06 |
| UC-06B | SP-10 |
| UC-08 | BR-09 |
| UC-09 | LE-10 |
| UC-11 | BR-09, SP-04 |
| UC-12 | PT-06 |
| UC-13 | PT-05 |
| UC-21 | LE-07, PT-06 |
| UC-28 | BR-03, PT-11 |

**Recheck:** Sheet 11 Required By · blueprint `gating_check_ids` · PRD §3.1 — **Pass** (automated).

**Pilots with no supplemental in gates (5 of 16):** UC-10, UC-16, UC-17, UC-23, UC-36 — supplemental side N/A for readiness until they declare supplemental gates (expected).

### 0.3 Dependencies

| Dep | Status | Evidence |
|-----|--------|----------|
| **DCS 42 path** | Present | `dataruns/dcs/orchestrate.py`, `assemble.py`, `_EXPECTED_CHECK_COUNT=42` |
| **UC-01 / recommend** | Present | `recommend.py` — provisional policy shipped |
| **WF-01 / Studio** | Present | `build_package.py`, provisional banner policy §3.2 |
| **OPS-UC-01** | Present | `scripts/verify_use_case_pilots.py` — 16 pilots seeded |
| **CAP-01 / HO-01** | Shipped | Independent — DCS-09 does not touch route/handoff |

### 0.4 Code gap confirmed (today)

| Surface | Behavior |
|---------|----------|
| `recommend._raw_gate_status` | Supplemental from **store only**; missing → **`not_evaluated`** → provisional |
| `RecommendationContext.check_results` | Still **42-scoped DCS score only** |
| `RecommendationContext.supplemental_results` | **Step 6:** `get_latest_supplemental_status_map` |
| Unit tests | Store PASS for UC-02 ready; DCS-injected CI-08/CC-06 ignored |

**M2 pain (pre-Step 6):** Real UC-02 with CC-03 PASS stayed **`ready_provisional`** until CI-08 + CC-06 evaluated.

### 0.5 UC-02 sample (do not edit blueprint)

| check_id | Scope | In headline 42? |
|----------|-------|-----------------|
| CC-03 | Hard gate | **Yes** |
| CC-06 | Supplemental | **No** |
| CI-08 | Supplemental | **No** |

**Expected after DCS-09 Slice A:** evaluate CI-08+CC-06 PASS + hard gates PASS → **`ready`**, `provisional_supplemental=false`.

### 0.6 Product locks (carry into Step 1)

| Lock | Value |
|------|--------|
| Headline count | **42** — never feed supplementals into `assemble_dcs_score()` |
| Supplemental FAIL | Blocks **dependent pilot only** — must **not** set DCS `run_state=BLOCKED` |
| Strict readiness | Supplemental **PASS** required; WARN/UNKNOWN/NOT_CONNECTED/FAIL ⇒ not ready |
| Unevaluated | → `not_evaluated` → `ready_provisional` (WF-01 until evaluated) |
| ERP-out | BR-09, PT-06 → `NOT_CONNECTED` when `erp_in_scope=false` |
| Thresholds | Catalogue 02 — `STOP_AND_FLAG` if contested |
| Branch / PR title | Per PRD §12 |

### 0.7 Explicitly not this PRD (§11)

| Later | Why |
|-------|-----|
| E2E-01 | Loom after Ready path works |
| Engineering fix/writeback for supplemental IDs | Download + human fix OK for M2 |
| Auto-eval after every DCS | Convenience |
| HO-02 | MCP Send |

### 0.8 Gaps / risks noted

| Gap | Impact | Mitigation |
|-----|--------|------------|
| No supplemental executors | Forever provisional | Steps 3–5 + 6 (Slice A first) |
| Recommend reads DCS ctx only | ~~Supplemental never merges~~ | **Done** — store-only merge in `recommend.py` |
| Tests mock supplementals in DCS payload | ~~False confidence on `ready`~~ | **Done** — store-backed tests |
| 10 executors in Slice B | Large Step 8 | Ship A first for M2 demo |

---

## Step 1 — Static mapping + contract

**Goal:** Committed SoT for the 12 checks and UC↔gate map (**first implementation step**).  
**Code:** `dataruns/dcs/pilot_gates/contract.py` · `master.py`  
**Files:** `dataruns/dcs/check_master_supplemental_mvp1.json` · `pilot_supplemental_gate_map.json`  
**Tests:** `dataruns.tests.test_pilot_gates_step1`

| Deliverable | Status |
|-------------|--------|
| Supplemental master (12 defs from sheet 11) | **Done** |
| UC↔gate map | **Done** |
| Contract + loader (file-only) | **Done** |
| Zero overlap with headline 42 | **Pass** |
| Strict readiness helpers | **Done** (`PASS` only) |
| Evaluate id resolution helper | **Done** (for Step 5/7) — empty list ≠ all 12 |

### 1.1 The 12 (locked — sheet 11)

| Check ID | Required by (pilot) | ERP-sensitive |
|----------|---------------------|---------------|
| BR-03 | UC-28 | no |
| BR-09 | UC-08, UC-11 | **yes** |
| CC-06 | UC-02, UC-05 | no |
| CI-08 | UC-02 | no |
| LE-07 | UC-21 | no |
| LE-10 | UC-09 | no |
| PT-05 | UC-13 | no |
| PT-06 | UC-12, UC-21 | **yes** |
| PT-11 | UC-28 | no |
| PT-13 | UC-04 | no |
| SP-04 | UC-11 | no |
| SP-10 | UC-06B | no |

Must equal `SUPPLEMENTAL_PREFLIGHT_CHECKS` and `pilot_manifest.json` — asserted.

### 1.2 Inverse map (UC → gates)

Same as Step 0 §0.2 — loaded via `get_supplemental_checks_for_use_case` / `list_supplemental_checks()["use_case_map"]`.

### 1.3 Result status contract

| Status | Meaning for recommend merge |
|--------|----------------------------|
| `PASS` | Contributes to **`ready`** |
| `FAIL` / `WARN` / `UNKNOWN` / `NOT_CONNECTED` | Not ready → **`blocked_checks`** when stored |
| (no result) | `not_evaluated` → **`ready_provisional`** |

**Catalog version:** `MVP1-SUPP-12-v1.4.1`

### Deep-check (Step 1)

| Check | Result |
|-------|--------|
| Master count 12 + catalog version | OK |
| IDs = constants = manifest; zero 42 overlap | OK |
| Gate map ↔ master `required_by` | OK |
| ERP flags BR-09 / PT-06 (JSON + contract) | OK |
| Slice A = CI-08 + CC-06 | OK |
| `resolve(check_ids=[])` → `[]` not all 12 | OK |
| Case-insensitive id helpers | OK |
| No bleed into 42 executor registry | OK |

---

## Step 2 — Persistence

**Goal:** Store and load latest supplemental evaluation per company.  
**Code:** `dataruns/dcs/pilot_gates/store.py`  
**Tests:** `dataruns.tests.test_pilot_gates_step2`

| Lock | Behavior |
|------|----------|
| Storage | `DataRun` `name=pilot-gate-eval`, `metadata.kind=pilot_gate_eval`, `scope=pilot_supplemental` |
| Company scope | `metadata.company_id` (same pattern as DCS score) |
| Latest | Latest **succeeded** eval per company |
| Partial eval | Default **merge** onto previous results by `check_id` |
| Metadata preserve | Omitted `data_run_id_score` / `erp_in_scope` keep prior values on merge |
| Envelope | `results[]` + `data_run_id_score` + `gate_catalog_version` + `erp_in_scope` |
| Isolation | Does **not** change DCS score latest / worklist |

### Deep-check (Step 2)

| Check | Result |
|-------|--------|
| Save + load latest envelope | OK |
| Merge partial eval preserves prior checks | OK |
| Merge preserves `data_run_id_score` + `erp_in_scope` | OK |
| Company isolation | OK |
| Reject empty / unknown check / bad status / bad severity | OK |
| FAILED eval ignored for latest | OK |
| No pollution of DCS score latest | OK |
| Master fills `required_by` / severity | OK |

**Non-goal:** Do not add supplemental rows to DCS worklist / ranked issues.

---

## Step 3 — Supplemental executor framework

**Goal:** Isolated runner — reuses snapshot/`db_context`, **never** registers in main 42 executor registry used by `assemble`.  
**Code:** `dataruns/dcs/pilot_gates/context.py` · `executors.py`  
**Tests:** `dataruns.tests.test_pilot_gates_step3`

| Lock | Behavior |
|------|----------|
| Separate registry | `register_supplemental_executor` — **not** in `dcs.executors.registry` |
| Snapshot source | Latest **succeeded** DCS score `run_snapshot` (or explicit **succeeded** `data_run_id`) |
| Batch ids | `run_supplemental_checks(None)` → all 12; `[]` → none |
| Missing inputs | `UNKNOWN` + `MISSING_INPUT` / `MISSING_INPUT:executor_pending` |
| ERP out of scope | BR-09, PT-06 → `NOT_CONNECTED` when `erp_in_scope=false` |
| Isolation | `assemble_dcs_score` + headline master stay **42** |

### Deep-check (Step 3)

| Check | Result |
|-------|--------|
| Supplemental IDs absent from 42 executor registry | OK |
| Headline master count 42; no supplemental overlap | OK |
| Assemble refs stay 42; supplemental id → AssembleValidationError | OK |
| ERP-out → NOT_CONNECTED for BR-09/PT-06 | OK |
| ERP-in → UNKNOWN pending (until Slice B) | OK |
| Unimplemented → UNKNOWN pending | OK |
| Stub register + run + persist via store | OK |
| Wrong-company / wrong-tenant / failed / wrong-name score id rejected | OK |
| Explicit snapshot override still links latest score run | OK |
| `run_supplemental_checks(None)` → all 12; `[]` → none | OK |

---

## Step 4 — Slice A executors (M2 demo)

**Priority A — UC-02:**

| ID | Focus (Catalogue 02) |
|----|----------------------|
| **CI-08** | Email format validity (Manago) |
| **CC-06** | Double opt-in state integrity |

**Code:** `dataruns/dcs/pilot_gates/slice_a.py` (registered from `executors.py`)  
**Tests:** `dataruns.tests.test_pilot_gates_step4`

| Lock | Behavior |
|------|----------|
| Isolation | Not in headline 42 executor registry / assemble |
| CI-08 | RFC-lite + typo (`gmial.com`…) + disposable + Manago `invalid` → any hit **FAIL** (Catalogue Suggested Fix: “Flag invalid set”; **no %** in sheet 02) |
| CC-06 | Not-confirmed stuck beyond **2d** — **pack SoT:** Use Case Library sheet 03 UC-05 Wait (“initial confirmation window”); provisional stuck-share **5%** (Catalogue silent on %) |
| No invented PASS | Missing DOI vocabulary / contacts → **UNKNOWN**; Manago down → **NOT_CONNECTED** |
| STOP_AND_FLAG | Catalogue 02 has no numeric cutovers — bands documented in `slice_a.py` |
| Deferred | Confirmation-email deliverability + multi-source DOI policy (Catalogue text; need email/list + signup-source inputs) |
| Snapshot vs DB | Prefer injected/`gate_inputs` contacts; else **ConnectorSnapshot** raw (DOI `state` not on frozen consent summary yet). Optional later: surface `doi_state_summary` in `consent_join` so CC-06 can read score `run_snapshot` alone |
| Related docs checked | Engineering PRD + WORKING_GAPS · FUTURE appendix · DCS-04 threshold rule · pack sheets **02/11** · UC Library **03** · UC-02/05 blueprints · BL-003 / AT-004 — **no conflicting numeric cutovers found** |

### Deep-check (Step 4)

| Check | Result |
|-------|--------|
| Slice A registered; absent from 42 registry | OK |
| CI-08 PASS / FAIL (typo, RFC, disposable, invalid flag) | OK |
| CI-08 NOT_CONNECTED without Manago/contacts | OK |
| CI-08 empty `gate_inputs.manago_contacts=[]` → UNKNOWN (no DB fallthrough) | OK |
| CI-08 identity fallback includes `source=both` | OK |
| CC-06 PASS within band / FAIL stuck share | OK |
| CC-06 UNKNOWN without DOI vocabulary or identity-only emails | OK |
| CC-06 UNKNOWN when Not-confirmed lacks timestamps (no invented FAIL/PASS) | OK |
| CC-06 loads Manago state from ConnectorSnapshot raw | OK |
| Run + persist via store | OK |

**Exit criteria:** Can evaluate CI-08 + CC-06 and persist real statuses. ✅

---

## Step 5 — Evaluate orchestration

**Goal:** Core pipeline: resolve check set → run executors → persist.  
**Code:** `dataruns/dcs/pilot_gates/evaluate.py`  
**Tests:** `dataruns.tests.test_pilot_gates_step5`

| Input | Resolution |
|-------|------------|
| `use_case_ids` | Union of supplemental gates for those UCs |
| `check_ids` | Exact subset of the 12 |
| both null | All 12 |
| `data_run_id` | Optional; default = latest succeeded DCS score run |
| `erp_in_scope` | Affects BR-09 / PT-06 (even before Slice B, stub honestly) |

| Lock | Behavior |
|------|----------|
| Empty `check_ids=[]` / `use_case_ids=[]` | Skip persist (`skipped=true`) — no wipe |
| Explicit bad `data_run_id` | `PilotGateEvaluateError` (no silent empty snapshot) |
| Partial eval | Merge onto previous bundle (store default) |
| Isolation | Does not change headline DCS score / assemble / worklist |
| Readiness | `supplemental_ready` + `blocked_by` + `not_evaluated` (for API Step 7) |
| Readiness map | `status_by_check_id=None` → load store; `{}` → empty (no fallthrough) |

### Deep-check (Step 5)

| Check | Result |
|-------|--------|
| UC-02 → CI-08+CC-06 persist + readiness ready | OK |
| `check_ids` subset / empty skip | OK |
| Both null → all 12 | OK |
| Partial merge preserves prior | OK |
| No DCS score / assemble pollution | OK |
| Readiness blocked / not_evaluated / UNKNOWN | OK |
| Invalid / wrong-company `data_run_id` raises | OK |
| Company isolation | OK |
| Explicit `{}` readiness map does not reload DB | OK |
| This-pass `results` store-normalized + `merged_count` | OK |

---

## Step 6 — Wire `recommend.py` (critical) — **Done**

**Shipped:**

1. `resolve_recommendation_context` loads `get_latest_supplemental_status_map`.  
2. `_raw_gate_status` — supplemental IDs from store only; 42 gates from DCS.  
3. PASS → ready; ≠ PASS → `blocked_checks`; missing → `not_evaluated` → provisional.  
4. Tests: `test_pilot_gates_step6.py` + updated `test_use_case_recommendations.py`.

---

## Step 7 — APIs — **Done**

**Shipped** under `/api/v1/dcs/`:

| Method | Path | Roles |
|--------|------|-------|
| GET | `pilot-gates/master/` | Admin / Analyst / Viewer |
| POST | `pilot-gates/evaluate/` | Admin / Analyst |
| GET | `pilot-gates/latest/` | Admin / Analyst / Viewer |
| GET | `pilots/{use_case_id}/readiness/` | Admin / Analyst / Viewer |

**Code:** `dataruns/dcs/pilot_gates/views.py` · wired in `dataruns/dcs_urls.py`  
**Tests:** `dataruns.tests.test_pilot_gates_step7`

**Non-goal:** Auto-eval after every DCS score (optional later).

---

## Step 8 — Slice B executors (remaining 10) — **Done**

**Code:** `dataruns/dcs/pilot_gates/slice_b.py` · registered in `executors._register_framework_defaults`  
**Contract:** `SLICE_B_CHECK_IDS` (10)  
**Tests:** `dataruns.tests.test_pilot_gates_step8`

| ID | Notes |
|----|-------|
| SP-10 | RFM among purchasers; provisional missing share 10% |
| PT-13 | Manago coupons vs Shopify discount codes |
| LE-07 | Abandoned checkout → CART capture rate |
| LE-10 | Event type discipline (OTHER / type_changed) |
| PT-05 | Catalog vs Shopify price parity |
| PT-06 | Stock parity; ERP-out → `NOT_CONNECTED` |
| PT-11 | Product attribute completeness |
| BR-03 | OOS on active surfaces |
| BR-09 | Replenishment inputs; ERP-out → `NOT_CONNECTED` |
| SP-04 | `date.*` detail validity |

**Exit criteria:** All 16 pilots can clear supplemental side when data supports PASS.

---

## Step 9 — QA + build_package regression — **Done**

**Surfaces:** `qa_normalize.py`, `build_package.py`, `qa_evaluators` / `qa_run` (honesty fix + regression lock).

| Check | Expect | Result |
|-------|--------|--------|
| `not_evaluated` under provisional | Still allowed (WF-01 §3.2) | OK |
| All supplementals PASS | `provisional_supplemental=false` on new package | OK |
| Supplemental FAIL | Generate locked (`blocked_checks`) | OK |
| `data_gates_pass` | Hard gates unchanged; supplemental FAIL blocks even if provisional flag true | OK |
| QA engine | `run_qa_for_package` fails `data_gates_pass` on supplemental FAIL; passes under provisional | OK |
| Honesty | `UNKNOWN` ≠ `not_evaluated`; supplemental `WARN`/`NOT_CONNECTED`/`UNKNOWN` block | OK |

### Deep-check (Step 9)

| Check | Result |
|-------|--------|
| Generate provisional + QA `data_gates_pass` PASS | OK |
| Store FAIL → Generate 409 `blocked_checks` | OK |
| Store PASS → package `provisional_supplemental=false` | OK |
| Crafted package CC-06=FAIL → QA FAIL via `run_qa_for_package` | OK |
| Evaluator + normalize supplemental FAIL under provisional | OK |
| `normalize_gate_label(UNKNOWN)` stays UNKNOWN | OK |

**Tests:** `dataruns.tests.test_pilot_gates_step9` · `test_qa_normalize_step2` · `test_qa_evaluators_step3` · `test_qa_run_step4` · `test_use_case_build_package`

---

## Step 10 — BE acceptance matrix (PRD §8 / §10) — **Done**

| §10 item | Expect | Result |
|----------|--------|--------|
| Static 12 IDs | Match pack + constants | OK |
| Evaluate isolation | No change to headline 42 / worklist pointer / snapshot | OK |
| UC-02 ready path | CI-08+CC-06 PASS + hard PASS → **`ready`** | OK |
| Supplemental FAIL | `blocked_checks`, Generate locked | OK |
| Unevaluated regression | Still `ready_provisional` | OK |
| ERP-out | BR-09 / PT-06 → `NOT_CONNECTED` (executor + evaluate persist) | OK |
| Tests | assemble isolation; recommend merge; evaluate API | OK |

### Deep-check (Step 10)

| Check | Result |
|-------|--------|
| Manifest via `DEFAULT_MANIFEST_REL` + API routes reverse | OK |
| Worklist payload has zero supplemental issue IDs after evaluate | OK |
| Eval bundle `data_run_id_score` links score; eval run ≠ score | OK |
| DCS-injected CI-08/CC-06 cannot unlock `ready` (store-only) | OK |
| Evaluate API → readiness → recommend → Generate (provisional false) | OK |
| ERP-out via `evaluate_pilot_gates(check_ids=[BR-09,PT-06])` | OK |

**Tests:** `dataruns.tests.test_pilot_gates_step10` (authoritative BE gate)

**Note:** Verify script (`scripts/verify_dcs09_backend.py`) remains Step 12.

---

## Step 11 — FE light — **Done**

| Surface | Change | Result |
|---------|--------|--------|
| Opportunities | Show supplemental FAIL from `blockers` / `supplemental_status`; provisional chip | OK |
| Workflow Studio | Same; provisional banner when `ready_provisional`; drop when `ready` | OK |
| No Data Center pollution | Supplemental blockers / check rows do **not** deep-link to score tiles | OK |

**Optional Slice C (P1):** “Evaluate pilot gates” CTA — not shipped (still optional).

**Verify:** `klints_frontend` → `npm run verify:dcs09` (`scripts/verify-dcs09-frontend.mjs`)

**BE companion:** `recommend.py` omits `href` for supplemental blockers / check_results (store FAIL ≠ DCS worklist).

### Deep-check (Step 11)

| Check | Result |
|-------|--------|
| Opportunities / Studio blockers labeled supplemental; no DCS deep-link | OK |
| `WorkflowReadyList` common blockers: supplemental not linked to score tiles | OK |
| Empty studio CTA → Opportunities when only supplemental blockers | OK |
| Provisional chip/banner only when `ready_provisional` (not on `ready`) | OK |
| `blockerCheckId` also reads `?issue=` so stale hrefs cannot pollute | OK |
| Data Center page has no supplemental pilot UI | OK |

---

## Step 12 — Verify + PR prep — **Done**

**Backend:** `scripts/verify_dcs09_backend.py`

| Check | Result |
|-------|--------|
| Docs / branch / PR right+gap / 42 lock | OK |
| Supplemental master JSON + gate map on disk; count=12 | OK |
| Constants / contract / pack / locked 12 IDs | OK |
| `SLICE_A \| SLICE_B` covers 12; slices disjoint | OK |
| Zero overlap with headline 42 + executor registry | OK |
| Recommend store-only `_raw_gate_status`; DCS inject ignored | OK |
| Supplemental gating_check blockers omit DCS href | OK |
| `core.urls` + `dcs_urls` + `reverse()` for 4 APIs | OK |
| evaluate / store / slice_a / slice_b / views present | OK |
| `assemble_dcs_score` stays 42; rejects supplemental CI-08 | OK |
| Step0–10 test modules present | OK |
| Sibling FE `verify-dcs09-frontend.mjs` | OK |
| Optional `--run-tests` (step0–step10); skipped if static failed | OK (164) |

**Audit fixes (Step 12 recheck):** skip `--run-tests` on static failure; live assemble reject; store-only status; master JSON + slice union; `reverse()`; FE sibling check; Windows utf-8 stdout.

**Docs:** PRD §10 verify script acceptance `[x]`.

**FE (already Step 11):** `npm run verify:dcs09` in `klints_frontend`.

---

## Step 13 — PR (manual) — **Ready**

DCS-09 spans **two git repos** (`klints_backend`, `klints_frontend`). Do **not** commit from the parent `Klints/` folder. Agent does **not** commit — you do.

### Pre-flight (already green when Step 13 opened)

```bash
# Backend (klints_backend) — use project venv
python scripts/verify_dcs09_backend.py
python scripts/verify_dcs09_backend.py --run-tests   # 164 OK

# Frontend (klints_frontend)
npm run verify:dcs09   # 25 checks OK
```

### Branch (both repos)

`feature/dcs-09-pilot-supplemental-gates` → base **`main`**

**Upstream warning (local as of Step 13 start):**

| Repo | Local branch | Currently tracks (wrong for PR) | Fix when pushing |
|------|--------------|----------------------------------|------------------|
| BE | `feature/dcs-09-pilot-supplemental-gates` | `origin/feature/wf-02-journey-stages-routing` | `git push -u origin HEAD` |
| FE | `feature/dcs-09-pilot-supplemental-gates` | `origin/WF-02` | `git push -u origin HEAD` |

Uncommitted DCS-09 work is on these local branches; first push should create/update the **same-named** remote branch off `main`, not push into WF-02.

### What to commit

| Repo | Paths (DCS-09 only) |
|------|---------------------|
| **klints_backend** | `dataruns/dcs/pilot_gates/` · `dataruns/dcs/check_master_supplemental_mvp1.json` · `dataruns/dcs/pilot_supplemental_gate_map.json` · `dataruns/dcs_urls.py` · `dataruns/use_cases/recommend.py` · `dataruns/use_cases/qa_normalize.py` · `dataruns/tests/test_pilot_gates_step0.py` … `step10.py` · `dataruns/tests/test_qa_*.py` / `test_use_case_*.py` (DCS-09 deltas) · `scripts/verify_dcs09_backend.py` · `docs/engineering/DCS_09_WORKING_GAPS.md` · `docs/engineering/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md` · `docs/engineering/README.md` |
| **klints_frontend** | `src/lib/use-cases.ts` · `src/routes/opportunities.tsx` · `src/components/workflow/WorkflowStudio.tsx` · `scripts/verify-dcs09-frontend.mjs` · `package.json` (`verify:dcs09`) |

Do **not** include unrelated WF/CAP/HO files. Headline `assemble` / CheckMaster 42 must stay untouched (verify script enforces).

### Suggested commit messages

**Backend:**
```text
feat(DCS-09): pilot supplemental gates + recommend Ready (UC-02 first)

Evaluate/persist 12 pack gates (scope=pilot_supplemental); merge into
recommend so PASS→ready, FAIL→blocked, missing→provisional; APIs +
verify; headline 42 unchanged.
```

**Frontend:**
```text
feat(DCS-09): supplemental gate blockers + provisional banner

Studio/Opportunities label supplemental blockers without DCS score-tile
deep-links; provisional chip/banner only for ready_provisional.
```

### Suggested PR titles

| Repo | Title |
|------|-------|
| Backend | `feat(DCS-09): pilot supplemental gates + recommend Ready (UC-02 first)` |
| Frontend | `feat(DCS-09): supplemental gate blockers + provisional banner (Studio/Opportunities)` |

### BE PR body (copy)

```markdown
## Summary
- 12 pack supplemental preflight gates: isolated evaluate + persist `scope=pilot_supplemental`
- `recommend.py` merge: PASS → `ready`; FAIL → `blocked_checks`; missing → `ready_provisional`
- APIs: master / evaluate / latest / readiness
- Headline 42 / `assemble_dcs_score` unchanged; supplemental FAIL does not block DCS run
- QA normalize honesty for supplemental UNKNOWN/WARN; Slice A+B executors

## Test plan
- [ ] `python scripts/verify_dcs09_backend.py`
- [ ] `python scripts/verify_dcs09_backend.py --run-tests` (step0–10)
- [ ] UC-02: CI-08+CC-06 PASS (+ hard gates) → recommendation `ready`
- [ ] Supplemental FAIL → Generate locked; missing → still provisional
```

### FE PR body (copy)

```markdown
## Summary
- Opportunities + Workflow Studio surface supplemental blockers (no Data Center score-tile deep-links)
- Provisional chip/banner only when status is `ready_provisional`; clears on `ready`
- Helpers: `SUPPLEMENTAL_PREFLIGHT_CHECKS`, `isSupplementalGate`, `isSupplementalBlocker`

## Test plan
- [ ] `npm run verify:dcs09`
- [ ] Studio/Opportunities: supplemental FAIL labeled; no DCS tile link for those IDs
- [ ] Provisional banner only for `ready_provisional`
```

### After you push

```bash
# From each repo (after commit)
git push -u origin HEAD
gh pr create --base main --title "…"   # use bodies above
```

---

## Gaps / defer (running)

| Item | Status |
|------|--------|
| FE evaluate CTA (Slice C) | P1 — optional Step 11+ |
| Auto-eval after DCS | Later |
| Engineering fix/writeback for supplemental IDs | Later |
| HO-02 Send | Out of scope |

---

## PR note (draft)

**Right:** 12 supplemental gates (evaluate/store/recommend/APIs); UC-02 ready path; Slice A+B executors; FE Opportunities/Studio blockers + provisional banner; no DCS score-tile pollution; `verify_dcs09_backend.py` + `npm run verify:dcs09` green.  
**Gap:** Slice C CTA; auto-eval; Engineering supplemental fix paths; HO-02.  
**PR:** Manual — BE + FE on `feature/dcs-09-pilot-supplemental-gates` → `main` (fix upstream before push).
