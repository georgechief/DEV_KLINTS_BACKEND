# DCS-10 Working / Gaps (PRD-DCS-10)

**PRD:** `PRD_DCS_10_FRESH_IMPORT_BEFORE_SCORE.md`  
**Branch intent:** `feature/dcs-10-fresh-import-before-score` (create from `main` — do not mix with DCS-09)  
**Scope:** Fix-only — enforce existing `refresh_connected_platforms_for_dcs` (fail closed + status + test). **No** changes to 42 checks, bootstrap, triggers, or other tracks. **v1 = slices A+B+C only.**

---

## Step progress

| Step | Status | Notes |
|------|--------|-------|
| 0 Preconditions | **Done** | Repo audit + scope lock + v1 plan; see §Step 0 |
| 1 Slice A — fail closed | **Done** | `assert_fresh_imports_cover_connected` in `fresh_import.py` + orchestrate guard; tests in `test_dcs_fresh_import_before_score.py` |
| 2 Slice B — status API | **Done** | `fresh_imports` + `fresh_import_failed_platform` on run summaries |
| 3 Slice C — integration test | **Done** | Real `refresh_connected_platforms_for_dcs` in pipeline; mock import only |
| 4 Verify + PR (v1) | **Ready** | §Step 4 — verify script + manual QA checklist; **you commit / open PR** |
| 5 Slice D — FE copy | **Done** | Data Center import-phase honesty · `verify:dcs10-fresh-import` |
| 6 Slice E — pin joins | **Done** | Joins use this run's `source_runs` / `fresh_imports.snapshot_id`; fallback to latest when unresolvable |
| 7 Slice F — Integrations | **Optional P2** | `last_data_refresh` |
| 8 Slice G + full PRD | **Optional P2** | Refresh data button + doc pointer |

---

## Step 0 — Preconditions

**Goal:** Confirm pipeline exists, gap baseline locked, v1 scope clear — **no product code changes in Step 0.**  
**Tests:** None (doc + static repo audit only).

### 0.0 Docs inventory

| File | Role | Status |
|------|------|--------|
| `docs/engineering/PRD_DCS_10_FRESH_IMPORT_BEFORE_SCORE.md` | SoT | Present |
| `docs/engineering/DCS_10_WORKING_GAPS.md` | Step tracker | Present |
| `docs/engineering/README.md` | Index #17 | Present |
| `docs/dcs_scoring/PRD_DCS_01_ORCHESTRATION_AND_EMAIL.md` | Parent (§2 stale on bootstrap-only) | Present — pointer in DCS-10 §11 |

### 0.1 Code path inventory (verified in repo)

| Surface | Path | Step 0 finding |
|---------|------|----------------|
| Fresh import | `dataruns/dcs/fresh_import.py` | `refresh_connected_platforms_for_dcs` · `DcsFreshImportError` · `dcs-fresh-import:{platform}` · `triggered_by=dcs_score` |
| Pipeline hook | `dataruns/dcs/orchestrate.py` | Calls refresh **before** `build_dcs_run_snapshot`; sets `metadata.fresh_imports` on success; FAILED + `fresh_import_failed_platform` on `DcsFreshImportError` |
| Import body | `dataruns/connectors/import_data.py` | `run_import` → `client.fetch()` → upsert → `ConnectorSnapshot` |
| Manual enqueue | `dataruns/dcs/views.py` | `POST /dcs/runs/` · `live_revalidate=True` |
| Worker | `dataruns/tasks.py` | `run_dcs_score` → `run_dcs_pipeline` |
| Snapshot joins | `dataruns/dcs/lifecycle_join.py` | `_connector_raw_for_platform` pins to this run's import; falls back to `_latest_connector_raw` |
| Status API | `dataruns/dcs/status.py` | **`fresh_imports` + `fresh_import_failed_platform` on run summaries** (Slice B) |
| Integrations UI API | `tenants/connector_views.py` | `latest_bootstrap` only (`connector-bootstrap:*`) — not `dcs-fresh-import` |
| DCS-10 tests | `dataruns/tests/test_dcs_fresh_import_before_score.py` | **Present** (Slices A+C) · orchestrate unit tests still mock refresh (G9 doc note) |
| Orchestrate tests | `test_dcs_orchestrate.py` | Unit mocks refresh (fast path) · **G9 closed** by Slice C integration test |

### 0.2 Dependencies (must not break)

| Dep | Status | Evidence |
|-----|--------|----------|
| CONN-01 `run_import` | Present | Used by `fresh_import.py` |
| DCS-01 worker | Present | `run_dcs_pipeline` |
| PRD-FE-04 run progress | Present | `persist_import_stage_running` in orchestrate |
| CONN-05 Shopify auth | Present | `_ensure_shopify_token` in fresh_import; pre-pipeline fail in `run_dcs_score` when `live_revalidate` |
| Bootstrap unchanged | Lock | Out of scope — reconnect path untouched |

### 0.3 Gap baseline (why v1)

| ID | Gap | v1 slice |
|----|-----|----------|
| **G5–G6** | Connected platform skipped / empty `fresh_imports` → score may still succeed | **A** |
| **G9** | Tests mock away refresh | **C** |
| — | Status API hides import proof | **B** |
| G1, G2, G7 | UI / joins | **D–F optional** |

**Product rule (locked):** Each `connected|degraded` commerce connector must fresh-import in the **same** DCS run, or that run **FAILs** — no silent stale score.

### 0.4 v1 scope lock

| Ship in v1 (Steps 1–4) | Do **not** ship in v1 |
|------------------------|------------------------|
| Slice **A** fail closed | Slice **E** pin joins |
| Slice **B** status API | Slice **F** Integrations |
| Slice **C** integration test | Slice **G** Refresh data button |
| Verify + PR | Slice **D** FE (optional follow-up) |

**Unchanged:** 42 checks · assemble · worklist · bootstrap · daily beat · DCS-09 · HO-01 · CAP-01 · `BOOTSTRAP_DAYS`.

### 0.5 Branch / commit note (manual — you commit)

| Item | Note |
|------|------|
| **Branch** | Create `feature/dcs-10-fresh-import-before-score` from **`main`** (not from DCS-09 feature branch) |
| **Step 0 commit** | Docs only: `PRD_DCS_10_*` · `DCS_10_WORKING_GAPS.md` · `README.md` #17 |
| **Staging baseline** | Optional before Step 1: Re-run checks → inspect latest `dcs-score` `metadata.fresh_imports` (records whether gap is enforcement-only vs worker never runs) |

### 0.6 Step 0 exit criteria

| Criterion | Result |
|-----------|--------|
| PRD + WORKING_GAPS present | **Pass** |
| Pipeline + fresh_import code located | **Pass** |
| Gaps G1–G10 documented in PRD §2.4 | **Pass** |
| v1 = A+B+C locked | **Pass** |
| No Step 0 product code diff | **Pass** |

**Next:** Step 4 — verify + PR (see §Step 4 below).

---

## Step 4 — Verify + PR (v1 complete) — **Ready**

**Goal:** Static + automated sign-off for slices **A+B+C**; manual QA checklist for staging; **you** commit and open PR.

### 4.1 Verify script (BE)

```bash
cd klints_backend
python scripts/verify_dcs10_fresh_import_backend.py
python scripts/verify_dcs10_fresh_import_backend.py --run-tests
```

| Check | Covers |
|-------|--------|
| Slice A code | `assert_fresh_imports_cover_connected` · orchestrate guard · `fresh_import_failed_platform` |
| Slice B code | `_serialize_fresh_imports_for_status` · run summary fields |
| Slice C code | integration class · `wraps` refresh spy · dual-platform test |
| DCS-01 pointer | stale bootstrap note superseded |
| `--run-tests` | `test_dcs_fresh_import_before_score` · orchestrate · status fresh-import cases |

### 4.2 PRD §8 backend (CI / code)

| Criterion | v1 evidence |
|-----------|-------------|
| Both platforms in `fresh_imports` on success | Integration test `test_pipeline_fresh_imports_both_connected_platforms` |
| `dcs-fresh-import:*` sibling DataRuns | Same integration tests + `triggered_by=dcs_score` |
| Import failure → parent FAILED | Step 1 unit tests + `fresh_import_failed_platform` |
| Connected platform skipped → FAILED | Step 1 assert + orchestrate guard tests |
| Status API fresh import / failure | Step 2 status tests (7) |
| Integration without mocking refresh | Step 3 `wraps=refresh_connected_platforms_for_dcs` |

### 4.3 Manual QA §9 (staging — you)

1. Note Integrations bootstrap run ids (may stay old — **G1 expected**).  
2. Change a Manago field visible to a check.  
3. **Re-run checks** (Celery up) — do **not** reconnect.  
4. Inspect latest `dcs-score`: `metadata.fresh_imports` has new `data_run_id`s per connected platform.  
5. `GET /api/v1/dcs/status/` → `latest_run.fresh_imports` matches.  
6. Confirm worklist/score reflects change.  
7. Negative: Celery down → Re-run → 503/stuck; no false “updated” score.

### 4.4 PR checklist (manual — you)

| Item | Action |
|------|--------|
| **Branch** | `feature/dcs-10-fresh-import-before-score` from **`main`** |
| **Title** | `fix(DCS-10): mandatory fresh import before every DCS score; fail closed on stale data` |
| **Scope** | Slices A+B+C only — **no** D–G in this PR |
| **Files** | `fresh_import.py` · `orchestrate.py` · `status.py` · `views.py` · tests · `bootstrap_test_helpers.py` · docs · `verify_dcs10_fresh_import_backend.py` |
| **Do not mix** | DCS-09 · HO-01 · CAP-01 branches |

### 4.5 Regression (unchanged — spot-check)

| Track | Expect |
|-------|--------|
| 42 checks / assemble | Unchanged |
| Bootstrap / reconnect | Unchanged |
| DCS-09 supplemental | Unchanged |
| Daily beat / post-bootstrap DCS | Still calls `run_dcs_pipeline` → fresh import |

**v1 BE complete when:** verify script green + `--run-tests` green (26 tests) + manual §9 on staging (or documented deferral).

### 4.6 Verify run (Step 4 audit)

| Command | Expected |
|---------|----------|
| `python scripts/verify_dcs10_fresh_import_backend.py` | Static checks only — 0 failures |
| `python scripts/verify_dcs10_fresh_import_backend.py --run-tests` | Static + 26 Django tests — `ALL PASS` |

---

## Step 5 — Slice D (FE copy) — **Done**

**Goal:** Data Center honestly reflects connector import phase vs score calculation; surface fresh-import failure from status API.

| Change | Path |
|--------|------|
| Types + helpers | `klints_frontend/src/lib/dcs.ts` — `DcsFreshImportsSummary` · `isDcsFreshImportPhaseRunning` · `hasFreshImportsOnRun` · failure copy |
| Data Center UI | `klints_frontend/src/routes/data-consistency.tsx` — import banner · score arc · failure alert · re-run toast · poll-only Refresh status copy |
| Verify script | `klints_frontend/scripts/verify-dcs10-fresh-import-frontend.mjs` |

**Verify:**

```bash
cd klints_frontend
npm run verify:dcs10-fresh-import
```

**Ship:** Separate FE commit/PR or same branch as BE after v1 BE merges — your choice.

---

## Step 3 — Slice C (integration test) — **Done**

**Goal:** CI proves DCS pipeline runs real `refresh_connected_platforms_for_dcs` (not mocked away).

| Change | Path |
|--------|------|
| Pipeline integration tests (2) | `test_dcs_fresh_import_before_score.py` · `DcsFreshImportPipelineIntegrationTests` |
| Refresh spy | `wraps=refresh_connected_platforms_for_dcs` — proves orchestrate calls real refresh (G9) |
| Import mock boundary | `successful_run_import_side_effect` — simulates fetch + DB persist; **does not** replace refresh |
| Helper fix | `tenants/tests/bootstrap_test_helpers.py` — pass `platform=` to `persist_normalized_records` |

**Asserts:** `wraps` spy on refresh · single + dual-platform `dcs-fresh-import:*` child runs · `metadata.fresh_imports` (`data_run_id`, `window_end`) · status API.

**Tests:** `python manage.py test dataruns.tests.test_dcs_fresh_import_before_score.DcsFreshImportPipelineIntegrationTests` — **2 tests**.

---

## Step 2 — Slice B (status API) — **Done**

**Goal:** `GET /dcs/status/` exposes fresh-import proof on `latest_run` / `active_run`.

| Change | Path |
|--------|------|
| `_serialize_fresh_imports_for_status()` | `dataruns/dcs/status.py` — per-platform `data_run_id`, `window_end` |
| Run summary fields | `latest_run` / `active_run` — `fresh_imports`, `fresh_import_failed_platform` |
| View docstring | `dataruns/dcs/views.py` |
| Tests (7) | `dataruns/tests/test_dcs_app_status.py` |

**Tests:** `python manage.py test dataruns.tests.test_dcs_app_status.DcsAppStatusTests` — includes fresh-import cases.

---

## Step 1 — Slice A (fail closed) — **Done**

**Goal:** Each `connected|degraded` Shopify/Manago connector must appear in `fresh_imports` with a `data_run_id`, or the DCS run **FAILs**.

| Change | Path |
|--------|------|
| `assert_fresh_imports_cover_connected()` | `dataruns/dcs/fresh_import.py` — called after import loop |
| Orchestrate belt-and-suspenders guard | `dataruns/dcs/orchestrate.py` — after mocked/incomplete refresh |
| Unit tests (8) | `dataruns/tests/test_dcs_fresh_import_before_score.py` |
| Orchestrate regression | `test_dcs_orchestrate.py` — asserts guard invoked on success path |

**Tests:** `python scripts/verify_dcs10_fresh_import_backend.py --run-tests` — **26 passed** (static + Django).

**Manual commit (you):** product code + tests on branch `feature/dcs-10-fresh-import-before-score` from `main`.

---

## Confirmed gaps (reference)

See PRD §2.4 (G1–G10). v1 closes **G5–G6**, **G9**, and status visibility (**B**).

---

## Workaround until v1 shipped

1. Change data in Shopify/Manago.  
2. **Reconnect** (or save connector) → wait for bootstrap.  
3. **Re-run checks**.  

After v1: Re-run alone should suffice when Celery healthy.

---

## PR note (draft)

**Right (already in code):** `run_dcs_pipeline` calls `refresh_connected_platforms_for_dcs`; import failure marks DCS FAILED; status API exposes `fresh_imports` / `fresh_import_failed_platform` on run summaries (Slice B).  
**PR (v1):** DCS-10 slices **A+B+C** — `fix(DCS-10): mandatory fresh import before DCS score; fail closed`.  
**Verify:** `python scripts/verify_dcs10_fresh_import_backend.py --run-tests`  
**Manual:** §Step 4.3 staging QA before merge.
