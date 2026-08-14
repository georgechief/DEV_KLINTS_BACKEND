# PRD-DCS-00 — Check master registry + score assembly engine

**Depends on:** nothing live (fixture-driven)  
**Blocks:** DCS-01 persistence of real scores  
**Scope:** pure scoring library + seeded master data; no connector I/O

## 1. Goal

1. Persist an immutable **master table of the 42 MVP1 checks** (IDs preserved forever).  
2. Implement **score assembly** exactly as sheet **08 Score Assembly**.  
3. Prove correctness against DataPack golden fixtures before any live check logic.

## 2. Source of truth

Workbook (local copy next to these PRDs):

`docs/dcs_scoring/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx`

| Need | Tab |
|------|-----|
| Exact 42 rows (ID, class, dimension, weight, role, cadence, phase) | **09 MVP1 Check Scope** |
| Detection logic, systems, surfaces, severity, root causes, fix hints | **02 Check Catalogue** (join on Check ID) |
| RC-01…RC-15 | **03 Root Cause Taxonomy** |
| Dimension weights, result factors, confidence factors, score_state bands | **07 Scoring Model** |
| Aggregation algorithm | **08 Score Assembly** |
| Worked example per check | **10 Lumera Scoring Example** |

Fixtures (local copies under `docs/dcs_scoring/reference/fixtures/`):

| File | Role |
|------|------|
| `lumera_expected_results/check_results.json` | 42 input `check_result` objects |
| `lumera_expected_results/dcs_score.json` | Expected assembly output |
| `scoring_golden_dataset.json` | Cases: `lumera`, `all_pass`, `gate_fail`, `partial_sweep` |
| `edge_cases/all_pass.json` | Edge |
| `edge_cases/gate_fail.json` | Edge |
| `edge_cases/partial_sweep.json` | Edge |
| `edge_cases/erp_not_connected.json` | BR exclusion |

Schemas (`docs/dcs_scoring/reference/schemas/`):

- `check_definition.schema.json`
- `check_result.schema.json`
- `dcs_run.schema.json`

Human-readable master copy in-repo: [`docs/dcs_scoring/CHECK_MASTER_42.md`](./CHECK_MASTER_42.md).

## 3. Master registry

### 3.1 Seed artifact

Commit JSON derived from sheets 09+02:

`dataruns/dcs/check_master_mvp1.json`

(or store in `ScoringModel.config` with `name=DCS`, `version=DCS-1.0.0`)

Each row **must** include:

```json
{
  "check_id": "CI-01",
  "mvp1_class": "RULE_BASED",
  "dimension": "01 Customer Identity",
  "check_name": "Contact count reconciliation",
  "check_type": "Cross-system reconciliation",
  "numeric_weight": 4,
  "role": "SCORED",
  "cadence": "Initial + Recurring",
  "build_phase": "MVP1-A",
  "entity": "Contact / Customer identity",
  "systems_compared": "Manago vs Shopify",
  "detection_logic": "... from sheet 02 ...",
  "manago_surface": "...",
  "shopify_surface": "...",
  "erp_surface": "—",
  "severity": "High",
  "root_cause_ids": ["RC-01", "RC-03", "RC-09"],
  "suggested_fix": "...",
  "fix_type": "...",
  "fix_owner": "..."
}
```

### 3.2 Rules

- **Never renumber or rename `check_id`.**
- Master count must be exactly **42**.
- Set equality with fixture IDs in `check_results.json` must pass in CI.
- Organize code by `dimension` → `check_type` → `check_id`; lookup always by ID.

### 3.3 Root cause master

Seed `dataruns/dcs/root_cause_taxonomy.json` from sheet **03** (RC-01…RC-15). Findings may only use these codes.

## 4. Result status → score factor (sheet 07)

| status | score_factor | Eligible for dimension score? |
|--------|-------------:|-------------------------------|
| `PASS` | 1.0 | yes |
| `WARN` | 0.5 | yes |
| `FAIL` | 0.0 | yes |
| `NOT_APPLICABLE` | null | no — requires `reason_code` |
| `NOT_CONNECTED` | null | no — requires `reason_code` |
| `UNKNOWN` | null | no — lowers coverage; requires `reason_code` |

Confidence (sheet 07):

| confidence | confidence_factor |
|------------|------------------:|
| `HIGH` | 1.0 |
| `MEDIUM` | 0.7 |
| `LOW` | 0.4 |

Gates (`role=GATE`, `numeric_weight=0`) never contribute to dimension numerators/denominators.

## 5. Score assembly algorithm (sheet 08) — implement exactly

Function signature:

```python
assemble_dcs_score(
    check_results: list[CheckResult],
    *,
    scoring_model_version: str = "DCS-1.0.0",
    erp_in_scope: bool = False,
    sweep_complete: bool = True,
) -> DcsRun
```

### Step 1 — Foundation gates

Blocking gates for MVP1 (when connector in scope):

- `FD-01` Manago auth — blocking if Manago connected/required  
- `FD-02` Shopify auth — blocking if Shopify connected/required  
- `FD-04` rate-limit — blocking if FAIL  
- `FD-05` historical depth — blocking if FAIL  
- `FD-06` topology — blocking if FAIL  
- `FD-07` tracking — blocking if FAIL  

`FD-03` ERP:

- If `erp_in_scope=False` → treat as `NOT_CONNECTED` (do not block headline).  
- If `erp_in_scope=True` and FAIL → blocking.

If any **blocking** gate FAIL →:

```text
run_state = BLOCKED
headline_score = null
blocking_gates_failed = <count>
# still return per-check results; do not invent dimension scores as if complete
```

### Step 2–3 — Per check factors

For each result:

- Map status → `score_factor`  
- Attach `numeric_weight` from master (gates = 0)  
- Exclusions (`NOT_APPLICABLE` / `NOT_CONNECTED` / `UNKNOWN`) must have `reason_code` — **no silent zero**

### Step 4 — Dimension score

For each dimension `01`…`07`:

```text
eligible = checks in dimension with status in {PASS, WARN, FAIL} AND numeric_weight > 0
earned  = Σ (numeric_weight × score_factor)
denom   = Σ numeric_weight          # eligible only
dimension_score = 100 * earned / denom
# store 4 decimal places; round for display only
```

### Step 5 — Coverage

```text
scoped_applicable_weight = Σ numeric_weight of checks in dimension that are in MVP1 scope
                           and not NOT_APPLICABLE (declared)
eligible_weight = denom from Step 4
dimension_coverage = eligible_weight / scoped_applicable_weight
```

`UNKNOWN` counts against coverage (in scoped weight, not in eligible).  
Required dimensions need `coverage >= 0.80` or → `INCOMPLETE` (sheet 07/08).

### Step 6 — Confidence

```text
dimension_confidence = Σ (numeric_weight × confidence_factor) / eligible_weight
```

Confidence does **not** change the numeric score.

### Step 7 — Headline

```text
included_dimensions = dimensions with a computed score
# If ERP out of scope: exclude 07 Business Reality from headline
headline = Σ (dimension_score × weight_percent) / Σ weight_percent(included)
```

Weights from sheet 07 (must sum 100 when all included):

```text
18+18+14+12+18+10+10 = 100
```

If BR excluded: re-normalize over remaining 90 weight points:

```text
headline = Σ (score_d × w_d) / Σ w_d   for d in included
```

Caps when BR excluded (sheet 08 step 7):

- `run_state` cannot be `READY` → max `CONDITIONALLY_READY`  
- overall confidence ≤ 0.85  

### Step 8 — Recommendation state (score_state / run_state)

Apply after gates + coverage (sheet 07):

| Condition | run_state |
|-----------|-----------|
| Blocking gate failed | `BLOCKED` |
| Sweep incomplete OR required dim coverage < 0.80 | `INCOMPLETE` |
| headline ≥ 90 | `READY` |
| 70 ≤ headline < 90 | `CONDITIONALLY_READY` |
| 50 ≤ headline < 70 | `REMEDIATE` |
| headline < 50 | `BLOCKED` |

`headline_score` null only when blocked by gates (or explicitly incomplete with no publishable score — follow golden `gate_fail` / `partial_sweep`).

### Step 9 — Provenance

Persist:

- `scoring_model_version = "DCS-1.0.0"`  
- `scope_model_version` / check catalog hash  
- Never recompute historical runs under a new model in place — new run only  

## 6. Worked calculation — Lumera golden

Input: `check_results.json` (42 rows)  
Expected: `dcs_score.json`

Verified from fixture aggregation:

| Dimension | Eligible weight | Earned | Score |
|-----------|----------------:|-------:|------:|
| 01 Customer Identity | 22 | 18 | 81.8182 |
| 02 Lifecycle Event | 32 | 26 | 81.25 |
| 03 Product & Transaction | 14 | 14 | 100 |
| 04 Segment & Property | 15 | 13 | 86.6667 |
| 05 Channel & Consent | 17 | 13 | 76.4706 |
| 06 Measurement | 8 | 7 | 87.5 |
| 07 Business Reality | 10 | 8 | 80 |

Headline:

```text
(81.8182*18 + 81.25*18 + 100*14 + 86.6667*12 + 76.4706*18 + 87.5*10 + 80*10) / 100
= 84.267
→ score_state = CONDITIONALLY_READY
blocking_gates_failed = 0
```

Engine unit test **must** assert `headline_score == 84.267` (± 0.001) for case `lumera`.

Other golden cases (`scoring_golden_dataset.json`):

| case_id | Expected |
|---------|----------|
| `all_pass` | headline 100, `READY` |
| `gate_fail` | headline null, `BLOCKED` |
| `partial_sweep` | `INCOMPLETE` |

## 7. Output object (`dcs_run`)

Align with `dcs_run.schema.json` + practical API fields:

```json
{
  "schema_version": "1.0.0",
  "tenant_id": "<uuid>",
  "run_id": "<dcs-run-id>",
  "run_state": "CONDITIONALLY_READY",
  "scope_model_version": "MVP1-42-v1.4.1",
  "scoring_model_version": "DCS-1.0.0",
  "blocking_gates_failed": 0,
  "headline_score": 84.267,
  "dimension_scores": {
    "01 Customer Identity": 81.8182,
    "02 Lifecycle Event": 81.25,
    "03 Product & Transaction": 100,
    "04 Segment & Property": 86.6667,
    "05 Channel & Consent": 76.4706,
    "06 Measurement": 87.5,
    "07 Business Reality": 80
  },
  "coverage": 1.0,
  "confidence": 0.99,
  "dimensions": {
    "01 Customer Identity": {
      "score": 81.8182,
      "coverage": 1.0,
      "confidence": 1.0,
      "weight_percent": 18
    }
  },
  "check_result_refs": ["FD-01", "FD-02"],
  "missing_required_inputs": [],
  "started_at": "...",
  "completed_at": "...",
  "provenance": {
    "source_versions": {
      "check_master": "1.0.0",
      "scoring_model": "DCS-1.0.0"
    },
    "created_at": "...",
    "created_by": "dcs.assemble"
  }
}
```

Match fixture field names in `dcs_score.json` for tests (`dimensions.*.weight_percent` etc.).

## 8. Code layout

```text
dataruns/dcs/
  __init__.py
  check_master_mvp1.json
  root_cause_taxonomy.json
  master.py          # load/validate 42
  assemble.py        # assemble_dcs_score
  types.py           # CheckResult, DcsRun dataclasses
  tests/
    test_assemble_lumera.py
    test_assemble_golden_cases.py
    test_master_ids.py
```

Copy fixtures into `dataruns/dcs/fixtures/` **or** read from DataPack path in tests via env `KLINTS_DATAPACK_ROOT`.

## 9. DB seed

| Model | Use |
|-------|-----|
| `ScoringModel` | `name="DCS"`, `version="DCS-1.0.0"`, `config` = master + weights |

Migration/data migration loads master once.

## 10. Files to add/change

| File | Change |
|------|--------|
| `dataruns/dcs/*` | New package (§8) |
| `dataruns/models.py` | Only if extra fields needed on `ScoringModel` (prefer JSON config) |
| `dataruns/migrations/*` | Seed `ScoringModel` |
| `dataruns/dcs/tests/*` | Golden tests |

## 11. Out of scope

- Executing checks against Shopify/Manago  
- Celery / email  
- HTTP APIs  

## 12. Acceptance

1. Master has 42 IDs; equals fixture ID set.  
2. `assemble(check_results.json)` → matches `dcs_score.json`.  
3. `all_pass` / `gate_fail` / `partial_sweep` match `scoring_golden_dataset.json`.  
4. Unknown status without `reason_code` rejected by validator.  
5. Sheet 08 formulas are the only scoring path (no alternate weights).
