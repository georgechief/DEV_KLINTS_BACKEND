# PRD-DCS-10 — Fresh import before every DCS score (mandatory)

**Status:** Step 4 ready · **v1 complete (BE)** · **Slice D (FE) done** — manual commit + PR · optional E+ later  
**Owner track:** Engineering  — **BE primary** (orchestrate + fresh_import + status API) · **FE light** (Data Center honesty)  
**Depends on:** CONN-01 import (`run_import`) · DCS-01 worker (`run_dcs_pipeline`) · PRD-FE-04 run progress  
**Parent:** [PRD_DCS_01_ORCHESTRATION_AND_EMAIL.md](../dcs_scoring/PRD_DCS_01_ORCHESTRATION_AND_EMAIL.md) (§2 source_run_ids is **stale** — superseded by this PRD)  
**Out of scope:** DCS-09 supplemental gates · changing BOOTSTRAP_DAYS window · incremental/delta sync · new connector types  

### Scope lock — fix fresh import only (do not change the rest)

This PRD **does not redesign DCS**. It enforces and surfaces behavior that **`run_dcs_pipeline` already calls** (`refresh_connected_platforms_for_dcs` → existing `run_import`).

| Unchanged (must stay as-is) | This PRD only fixes |
|----------------------------|---------------------|
| 42 checks, executors, assemble, worklist, gates | Runs that today **silently score on stale data** → **FAIL** when a connected platform did not fresh-import |
| Bootstrap / reconnect / `enqueue_connector_bootstrap` | Prove `fresh_imports` on succeeded runs + expose on status API |
| `POST /dcs/runs/` contract (202, roles, 409/503) | FE copy so Re-run ≠ Refresh status |
| Daily beat · post-bootstrap DCS triggers | Integration test (no mock on refresh) |
| `BOOTSTRAP_DAYS` rolling window | *(Optional P1)* pin joins to this run’s import snapshot |
| DCS-09 · HO-01 · CAP-01 · writebacks | *(Optional P2)* Integrations “last refresh” · standalone Refresh data button |

**v1 ship = slices A + B + C only.** Slices D–G are optional polish — not required to close the gap.

---

## 0. Cursor agent brief

```text
Implement PRD-DCS-10 — DCS must not score stale Shopify/Manago data.

Read:
- docs/engineering/PRD_DCS_10_FRESH_IMPORT_BEFORE_SCORE.md (§2 code audit)
- dataruns/dcs/fresh_import.py
- dataruns/dcs/orchestrate.py
- dataruns/dcs/lifecycle_join.py (_latest_connector_raw)
- dataruns/dcs/snapshot.py
- dataruns/dcs/views.py (POST /dcs/runs/)
- klints_frontend/src/routes/data-consistency.tsx

Goal: Re-run checks = fresh platform fetch for each connected commerce connector,
then score. Reconnect/bootstrap must NOT be the only reliable refresh path.

Ship P0 first: fail closed + prove fresh_imports on succeeded runs.
Acceptance: §8.
Verify: python scripts/verify_dcs10_fresh_import_backend.py --run-tests
```

---

## 1. Why (product)

Operators change data in **Shopify** and **Manago.ai** (consent, contacts, orders, catalog). Klints must reflect those changes on the next **Data Consistency Score** without forcing **Reconnect** on Integrations.

**Observed behavior (staging QA):**

- Reconnect → bootstrap import → counts/update visible → DCS reflects changes.
- **Re-run checks** alone often does **not** feel like a data refresh (Integrations `latest_bootstrap` unchanged; worklist/score unchanged until reconnect).

**Required product rule:**

> Every **successful** DCS score run for a company with connected commerce connectors must be backed by a **successful fresh import in that same run** for each such connector. Otherwise the run must **fail loudly** — never publish a “new” score on stale connector data.

---

## 2. Current code audit (deep — Aug 2026)

### 2.1 Intended pipeline (when worker completes)

```text
POST /api/v1/dcs/runs/  (Admin, live_revalidate=True)
  → enqueue_dcs_score → Celery run_dcs_score
    → run_dcs_pipeline
      → persist_import_stage_running (Foundation dim "00" = running)
      → refresh_connected_platforms_for_dcs   ← fresh import step
           for each connected|degraded shopify + manago_ai:
             run_import → API fetch → DB upsert → new ConnectorSnapshot
      → build_dcs_run_snapshot (joins)
      → evaluate 42 checks → assemble → persist
```

**Code references:**

| Step | Module | Lock |
|------|--------|------|
| Enqueue manual | `dataruns/dcs/views.py` | `live_revalidate=True`; requires eligible connector |
| Worker | `dataruns/tasks.py` `run_dcs_score` | Calls `run_dcs_pipeline`; may fail **before** pipeline if Shopify token dead (`live_revalidate`) |
| Fresh import | `dataruns/dcs/fresh_import.py` | Creates `DataRun` name `dcs-fresh-import:{platform}`; `metadata.triggered_by=dcs_score` |
| Orchestrate | `dataruns/dcs/orchestrate.py` | Docstring: “Always re-imports connected platforms”; on `DcsFreshImportError` → run **FAILED** + `fresh_import_failed_platform` |
| Import body | `dataruns/connectors/import_data.py` `run_import` | `client.fetch()` → `persist_normalized_records` (upsert) → `create_run_connector_snapshot` (version++) |

Fresh-import path landed in commit `5b88a5f` (“Harden DCS foundation gates with fresh import…”, Jul 2025). **DCS-01 PRD §2 still describes bootstrap-only source runs — documentation drift.**

### 2.2 What DCS checks actually read (two paths)

| Data path | Source | Updated by successful `run_import`? |
|-----------|--------|-------------------------------------|
| **Identity / CI-* spine** | `Contact` + `Order` DB tables (`identity_join.py`) | **Yes** — upsert on import |
| **Consent, lifecycle, catalog, drift, segment, workflow, product truth, supplemental CC-06/CI-08 raw** | `_latest_connector_raw()` → **latest** `ConnectorSnapshot.snapshot_data.raw` by `version` (`lifecycle_join.py`) | **Yes** — new snapshot per import |

If **no** successful import runs, both paths stay on **last bootstrap (or last DCS fresh import)** data.

### 2.3 Triggers and `live_revalidate`

| Trigger | `live_revalidate` | Fresh import in pipeline? |
|---------|-------------------|---------------------------|
| Manual `POST /dcs/runs/` | **true** | Yes (if worker runs) |
| Daily beat `dispatch_daily_dcs_scores` | false (default) | Yes (if worker runs) |
| `maybe_enqueue_dcs_after_bootstrap` | false (default) | Yes (if worker runs) |

`live_revalidate` only adds **Shopify token refresh + live auth probe** (`db_context._maybe_live_revalidate`) — **not** whether fresh import runs. Fresh import is unconditional inside `run_dcs_pipeline` (not gated on `live_revalidate`).

### 2.4 Confirmed gaps (why reconnect “works” but Re-run may not)

| # | Gap | Evidence | User impact |
|---|-----|----------|-------------|
| **G1** | **Integrations UI only surfaces bootstrap imports** | `connector_views._latest_bootstrap_for_connector` → `find_latest_bootstrap_data_run` only; name `connector-bootstrap:*` | After Re-run, **Integrations counts/run id unchanged** even when `dcs-fresh-import:*` succeeded — looks like no refresh |
| **G2** | **“Refresh status” does not import** | FE `data-consistency.tsx` — refetch `GET /dcs/status/` only | Operator thinks they refreshed data; **no API fetch** |
| **G3** | **Worker never runs → no import** | Celery/Redis down → 503 on POST or run stuck `pending` | Re-run queues but pipeline (and import) never executes |
| **G4** | **Shopify auth fail before pipeline** | `run_dcs_score` returns failed when `live_revalidate` + token dead; **`run_dcs_pipeline` not called** | No import attempt; stale snapshot remains |
| **G5** | **Connected platform skipped** | `fresh_import._connected_connectors` only `connected\|degraded`; `error` skipped | Partial stale (e.g. dead Shopify, live Manago) |
| **G6** | **Zero connected connectors → import noop, score may still run** | `refresh_connected_platforms_for_dcs` returns empty `fresh_imports`; pipeline **continues** | Scores on whatever DB/snapshot already exists |
| **G7** | **Snapshot join not pinned to this run’s import** | `_latest_connector_raw` = global max `version`, not `fresh_imports[platform].data_run_id` | Theoretic race if two imports overlap; usually OK sequential |
| **G8** | **Enqueue metadata still lists bootstrap `source_runs`** | `build_dcs_score_metadata` defaults `resolve_source_runs()` (bootstrap) until worker overwrites after import | Misleading in logs before worker; overwritten on success |
| **G9** | **No integration test without mock** | `test_dcs_orchestrate.test_pipeline_success_path` **patches** `refresh_connected_platforms_for_dcs` | CI green does not prove live import-on-DCS |
| **G10** | **Internal script skips import by design** | `scripts/fix_cc03_and_rerun_dcs.py` patches refresh to reuse prior `fresh_imports` | Dev-only; not product path |

### 2.5 How to prove a run (verification — no code)

After **Re-run checks** (not Refresh status), inspect latest **succeeded** `DataRun` where `name=dcs-score`:

**Fresh import ran for a platform when:**

```json
"metadata": {
  "fresh_imports": {
    "shopify": { "data_run_id": <int>, "counts": { ... }, "window_start": "...", "window_end": "..." },
    "manago_ai": { "data_run_id": <int>, ... }
  }
}
```

**And** sibling rows exist: `DataRun.name` = `dcs-fresh-import:shopify` / `dcs-fresh-import:manago_ai` with `metadata.triggered_by=dcs_score` and `created_at` ≈ DCS run time.

**Fresh import did NOT run when:** `fresh_imports` missing/empty on a succeeded score run while both connectors were connected — **bug / fail-closed violation**.

---

## 3. Target architecture (locks)

```text
Trigger (manual | daily | post_bootstrap)
  → enqueue dcs-score DataRun
  → Celery worker
      FOR EACH required platform (see §3.1):
        fresh import MUST succeed OR parent DCS run FAILs
      build snapshot FROM this run's import IDs (§3.2)
      evaluate 42 + assemble
      SUCCEEDED only if imports + score both OK
```

### 3.1 Required platforms per run (same rule as today’s `_connected_connectors`)

| Company state | Required fresh import |
|---------------|----------------------|
| Shopify `connected\|degraded` | **shopify** must succeed in this DCS run |
| Manago `connected\|degraded` | **manago_ai** must succeed in this DCS run |
| Connector `error` / not connected | **Not required** — same as today (skipped by `_connected_connectors`; FD-* honesty unchanged) |

**Lock:** Require fresh import **only for platforms that are connected/degraded right now** — do **not** require Manago when only Shopify is connected (or vice versa). Do **not** change single-connector eligibility (`company_has_eligible_connector`).

### 3.2 Pin snapshot reads to this run (P1)

Replace blind `_latest_connector_raw(company, platform)` for scoring with:

```text
fresh_imports[platform].data_run_id → import DataRun → Run → ConnectorSnapshot used for that import
```

Fallback to `_latest_connector_raw` only when pinning metadata missing (legacy runs).

### 3.3 Reconnect is fallback, not primary

| Path | Role |
|------|------|
| **Re-run checks** | **Primary** refresh + score |
| **Reconnect / bootstrap** | Credential repair, first connect, or recovery after `error` |
| **Refresh status** | Poll worker only — **never** implied data refresh |

---

## 4. Ship slices

| Slice | Priority | Deliverable |
|-------|----------|-------------|
| **A** | **P0** | **Fail closed:** if any required platform connected but `fresh_imports[platform]` absent after refresh step → `DcsFreshImportError` / FAILED (extend `fresh_import.py` + orchestrate guard) |
| **B** | **P0** | **Status API honesty:** expose `fresh_imports` summary on active/latest DCS run in `GET /dcs/status/` (or nested under `active_run`) — platforms, `data_run_id`, `window_end`, failed platform |
| **C** | **P0** | **Integration test:** one test that runs pipeline with real `refresh_connected_platforms_for_dcs` (VCR/mock HTTP), asserts new `dcs-fresh-import:*` + metadata on succeeded `dcs-score` |
| **D** | **P1** | **FE Data Center:** during run, copy “Fetching latest Shopify + Manago data…” when Foundation stage running; on failure show `fresh_import_failed_platform` from status |
| **E** | **P1** | **Pin joins** to this run’s snapshot ids (§3.2) — consent, lifecycle, catalog, drift, segment, workflow, product_truth, pilot supplemental raw |
| **F** | **P2** | **Integrations:** optional `last_data_refresh` from max(latest bootstrap, latest dcs-fresh-import) per platform |
| **G** | **P2** | **Optional “Refresh data”** button (Admin) → enqueue fresh import without full reconnect |

**Ship A+B+C in one PR** — that is the full **fix-only** scope. D–G are optional; do not block v1 on them.

---

## 5. Backend changes (by file)

| File | Change |
|------|--------|
| `dataruns/dcs/fresh_import.py` | After loop: if required platform connected but not in `fresh_imports` → raise `DcsFreshImportError` |
| `dataruns/dcs/orchestrate.py` | Pre-score guard: empty `fresh_imports` when connectors present → fail; optional pin helper for joins |
| `dataruns/dcs/lifecycle_join.py` | Add `_connector_raw_for_import_data_run(data_run_id)` (P1) |
| `dataruns/dcs/consent_join.py`, `catalog_join.py`, `drift_join.py`, `segment_join.py`, `workflow_join.py`, `product_truth.py` | Accept optional pinned raw (P1) |
| `dataruns/dcs/status.py` | Surface `fresh_imports` / failure on status payload (Slice B) |
| `dataruns/dcs/views.py` | Docstring only — behavior unchanged |
| `dataruns/tests/test_dcs_fresh_import_before_score.py` | Slices A+C tests |
| `docs/dcs_scoring/PRD_DCS_01_ORCHESTRATION_AND_EMAIL.md` | Pointer: fresh import mandatory per DCS-10 (§2 superseded for score input) |
| `scripts/verify_dcs10_fresh_import_backend.py` | Step 4 static + optional `--run-tests` |

**Do not** remove `refresh_connected_platforms_for_dcs` from pipeline. **Do not** score on bootstrap `source_runs` alone without fresh import in the same run.

---

## 6. Frontend changes (Slice D — light)

| Surface | Change |
|---------|--------|
| `data-consistency.tsx` | When `run_progress` Foundation (`00`) `running`, show import-phase copy; distinguish from “Refresh status” |
| Toast on Re-run | Keep success toast but add “Fetched latest connector data” only when status shows fresh imports |
| Integrations | No change required for P0 (Slice F optional) |

**Verify:** `cd klints_frontend && npm run verify:dcs10-fresh-import`

---

## 7. Explicit non-goals

| Item | Why |
|------|-----|
| Incremental sync since last import | Rolling `BOOTSTRAP_DAYS` window stays |
| Auto-reconnect on token failure | CONN-05 — mark `error`, operator reconnects |
| DCS-09 supplemental evaluate CTA | Separate PRD (Slice C optional P1) |
| Changing 42 check definitions | Score inputs only |

---

## 8. Acceptance

### 8.1 Backend

- [x] Connected Shopify + Manago → succeeded `dcs-score` metadata includes **both** `fresh_imports.*` (integration test; manual §9 on staging)
- [x] New `dcs-fresh-import:*` DataRuns created at same time as score run (integration test)
- [x] Simulated import failure → parent `dcs-score` **FAILED** (Step 1 tests)
- [x] Connected platform skipped (mock) → **FAILED** (Step 1 orchestrate guard test)
- [x] `GET /dcs/status/` exposes fresh import / failure (Step 2 tests)
- [x] Integration test (Slice C) without patching `refresh_connected_platforms_for_dcs` (Step 3 + verify script)

**Verify:** `python scripts/verify_dcs10_fresh_import_backend.py --run-tests`

### 8.2 Product / manual

- [ ] Change consent/contact in Manago **without reconnect** → Re-run checks → worklist/check reflects change (when Celery healthy)
- [ ] Integrations `latest_bootstrap` may stay old while DCS still refreshed (documented) **OR** Slice F shipped
- [ ] “Refresh status” documented in UI/help as poll-only, not data refresh

### 8.3 Regression

- [ ] Daily beat still enqueues and completes with fresh imports
- [ ] Post-bootstrap auto-DCS still fresh-imports
- [ ] Shopify token dead → clear failure (CONN-05), not silent stale score

---

## 9. Test plan (QA)

1. Note `ConnectorSnapshot.version` + latest bootstrap time on Integrations.  
2. Change a field visible to a FAIL check (e.g. Manago consent) in platform UI.  
3. **Re-run checks** (Admin, Celery up) — wait for completion.  
4. Verify `dcs-score` run `metadata.fresh_imports` (admin/DB/API).  
5. Confirm worklist/score changes **without** reconnect.  
6. Negative: stop `celery_worker` → Re-run → 503 or stuck banner; **no false “updated” score**.  

---

## 10. PR / branch

- Branch: `feature/dcs-10-fresh-import-before-score`  
- Title: `fix(DCS-10): mandatory fresh import before every DCS score; fail closed on stale data`  
- Working tracker: [DCS_10_WORKING_GAPS.md](./DCS_10_WORKING_GAPS.md)  
- Verify: `python scripts/verify_dcs10_fresh_import_backend.py --run-tests`

---

## 11. Traceability

| Item | Note |
|------|------|
| Parent | DCS-01 orchestration · CONN-01 import |
| Unblocks | Honest Re-run checks · M2 demo without reconnect ritual |
| Related | CONN-05 auth expired · PRD-FE-04 run progress · DCS-09 supplemental (reads snapshot after DCS) |
| Supersedes | DCS-01 §2 “If source_run_ids omitted: use latest bootstrap” as **score input** (bootstrap remains valid for **first** connect) |
