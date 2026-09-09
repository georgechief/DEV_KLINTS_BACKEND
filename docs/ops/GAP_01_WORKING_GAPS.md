# GAP-01 Working / Build order (PRD-GAP-01)

**PRD:** `PRD_GAP_01_M2_CODE_GAPS_WEEKS_5_9.md`  
**Owner:** Engineering (BE + FE)  
**Scope:** M2 code gaps Weeks 5–9 — ordered slices, no theater, no fake MCP.

**Locked decision (confirm in each PR):** Slice A = **A1** (pack ORCH 8-state) unless client waiver → A3.

**Deep A1 build order:** § [Slice A1](#slice-a1--orch-8-state-p0--12-weeks) (Phases 0–6, step-by-step, tests, files).

---

## Rules (read before every slice)

1. **One slice per branch / PR** — `feature/gap01-slice-a-orch-sm`, etc.
2. **Stop-and-flag** before inventing MCP publish or flipping Matrix to `CONFIRMED_LIVE`.
3. **Do not** overload `HandoffPackage` / `WritebackApprovalToken` for ORCH SM — mirror pattern, new table.
4. **Keep** `GET /api/v1/orchestration/plan/` unchanged until explicit bridge task.
5. **PR body must state:** Option A1/A2/A3 · waiver status (filed / not filed) · no Matrix silent flip.
6. **HO-02 is done** — do not regress human Send path.

---

## Master build order (do not skip ahead)

| Order | Slice | Priority | Closes | Blocked? |
|-------|-------|----------|--------|----------|
| **0** | Pre-flight + decision | — | Honesty baseline | — |
| **1** | **A — ORCH 8-state (A1)** | P0 | Contract C1 | No |
| **2** | **B — Track B MCP** | P0 | C2 / AC-A | **Yes** if no Manago MCP access → waiver |
| **3** | **C — Writeback / CDUC honesty** | P1 | W5–6 gaps | No |
| **4** | **D — MCP action / AI copy honesty** | P1 | W7–9 theater | No |
| **5** | **E — Week 8 screens** | P2 | W8-02/03/04 | No |
| **6** | **F — Demo seed** | P2 | W9-03/04/05 | No |
| **—** | Defer | — | Perf 50k, partner API, WB-08 | — |

**If client waives C1+C2 in writing:** skip rows 1–2 for *claim*; still do **D** + staging smoke; file waiver in repo.

---

## Slice 0 — Pre-flight (before coding A1)

| # | Task | Done |
|---|------|------|
| 0.1 | Confirm with employer: **A1** (not A2/A3) unless waiver | [~] assumed — get explicit OK |
| 0.2 | Confirm HO-02 PRs committed / merged (human Send baseline) | [x] |
| 0.3 | Read pack `orchestration_task.schema.json` + PRD §5 Slice A, §7–8 | [x] |
| 0.4 | Skim HO-02 patterns: `handoff_package.py`, `handoff_activation.py`, `verify_ho02_backend.py` | [x] |
| 0.5 | Create branch `feature/gap01-slice-a-orch-sm` (BE + FE when FE starts) | [x] |

**Exit:** Decision logged in PR template; branch ready.

---

## Slice A1 — ORCH 8-state (P0 · ~1–2 weeks)

**Branch:** `feature/gap01-slice-a-orch-sm` (BE + FE when Phase 5)  
**PR title:** `feat(GAP-01A): OrchestrationTask 8-state SM (pack ORCH)`  
**Pack SoT:** `Klints_MVP1_…/03_Machine_Contracts/orchestration_task.schema.json`  
**Pattern to copy:** HO-02 Phases 1–3 — `handoff_package.py` → `handoff_activation.py` → views + tests

### A1 goal (one sentence)

Persist **`OrchestrationTask`** rows with the pack **8 statuses**, enforced **transition graph**, **audit**, **REST API**, **tests**, **verify script**, **minimal FE** — closes Contract **C1**.

### A1 dependency graph (never skip)

```text
Phase 0 Pre-flight
  ↓
Phase 1 constants → model → migration → phase1 tests
  ↓
Phase 2 services (needs Phase 1 green)
  ↓
Phase 3 HTTP (needs Phase 2 green)
  ↓
Phase 4 verify script (needs Phase 3 green)
  ↓
Phase 5 FE minimal (needs Phase 3 green)
  ↓
Phase 6 manual staging demo
```

**Do not touch for A1:** `HandoffPackage` · `WritebackApprovalToken` · `GET /orchestration/plan/` · `matrix_seed.json`

---

### A1 Phase 0 — Pre-flight (~30 min)

| # | Task | Done |
|---|------|------|
| 0.1 | Confirm **A1** with employer (not A3 waiver) | [~] assumed — get explicit OK |
| 0.2 | HO-02 merged on baseline branch | [x] |
| 0.3 | Read pack schema + PRD-GAP-01 §5 Slice A, §7–8 | [x] |
| 0.4 | Skim `handoff_package.py`, `handoff_activation.py`, `verify_ho02_backend.py` | [x] |
| 0.5 | Create branch `feature/gap01-slice-a-orch-sm` | [x] |

**Exit:** Branch ready; transition graph understood. **Completed:** 2026-09-01.

**Phase 0 audit (recheck):**

| Step | Verdict | Evidence |
|------|---------|----------|
| 0.1 A1 locked | **Assumed — confirm with employer** | No written waiver/A3 on file; you chose A1 to start build |
| 0.2 HO-02 baseline | **Pass** | BE PR #71 merged · FE PR #48 merged · `verify_ho02_backend.py` OK · `verify:ho02` OK |
| 0.3 Pack + PRD | **Pass** | `orchestration_task.schema.json` + `PRD_GAP_01_…md` on disk |
| 0.4 HO-02 patterns | **Pass** | `handoff_package.py`, `handoff_activation.py`, `verify_ho02_backend.py`, HO-02 tests ×3 |
| 0.5 Branch | **Pass** | Both repos: `feature/gap01-slice-a-orch-sm` (tracks `origin/feature/ho-02-handoff-send-human-activation`) |

**Notes:**
- HO-02 static verify PASS; Django `--run-tests` not run in this recheck (run in venv before A1 PR).
- `GAP_01_WORKING_GAPS.md` is **uncommitted** — commit when you batch Phase 0/1 docs.
- **Before A1 PR:** get explicit employer OK on **A1** (not A3 waiver).

---

### A1 Phase 1 — Schema + constants (BE only, no HTTP)

**Build inside Phase 1 in this order:**

#### Step 1.1 — Constants file first

**File:** `dataruns/orchestration/task_constants.py`

| # | Item | Done |
|---|------|------|
| 1.1.1 | `ORCH_TASK_SCHEMA_VERSION = "1.0.1"` | [x] |
| 1.1.2 | 8 status constants + `ORCH_STATUS_ENUM` | [x] |
| 1.1.3 | 11 task_type constants + `ORCH_TASK_TYPE_ENUM` | [x] |
| 1.1.4 | `ORCH_ALLOWED_STATUS_TRANSITIONS` (graph below) | [x] |
| 1.1.5 | `ORCH_TERMINAL_STATUSES = {DONE, CANCELLED}` | [x] |
| 1.1.6 | `normalize_orch_status()` | [x] |
| 1.1.7 | `is_allowed_orch_transition(from, to)` | [x] |
| 1.1.8 | `is_orch_terminal_status()` | [x] |
| 1.1.9 | `is_orch_idempotent_transition(current, target)` | [x] |
| 1.1.10 | Error codes: `invalid_transition`, `forbidden`, `not_found` | [x] |
| 1.1.11 | Audit actions: `workflow.orchestration_task_created`, `…_transitioned` | [x] |
| 1.1.12 | `build_orch_task_audit_metadata(...)` | [x] |
| 1.1.13 | `serialize_orch_task(record)` — pack projection for GET | [x] |
| 1.1.14 | `build_default_provenance(created_by)` | [x] |

**Transition graph (must match PRD §7.1):**

```text
PENDING     → READY | BLOCKED | CANCELLED
BLOCKED     → READY | CANCELLED
READY       → IN_PROGRESS | CANCELLED
IN_PROGRESS → AWAITING_APPROVAL | DONE | FAILED
AWAITING_APPROVAL → IN_PROGRESS | DONE | FAILED | CANCELLED
FAILED      → READY | CANCELLED
DONE, CANCELLED → terminal (no outbound)
```

**8 statuses:** `PENDING` · `BLOCKED` · `READY` · `IN_PROGRESS` · `AWAITING_APPROVAL` · `DONE` · `FAILED` · `CANCELLED`

**11 task_types:** `CONNECT` · `DISCOVER` · `SCORE` · `FIX` · `ASSESS` · `PLAN` · `REPORT` · `EXPORT` · `BUILD` · `QA` · `HANDOFF`

#### Step 1.2 — Django model

**File:** `dataruns/orchestration/models.py`

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID pk | |
| `company` | FK Company | tenant isolation |
| `task_id` | CharField | e.g. `FIX-CC-03` (plan style) |
| `task_type` | CharField | pack enum |
| `status` | CharField | default `PENDING` |
| `title` | CharField | optional blank |
| `check_id` | CharField nullable | FIX tasks |
| `priority_class` | CharField | P0/P1/P2 |
| `priority_inputs` | JSONField | 4 ints 0–3 |
| `priority_score` | FloatField | 0–3 |
| `depends_on` | JSONField | default `[]` |
| `wave` | IntegerField | default `0` (pack 0–6) |
| `capability_dependencies` | JSONField | default `[]` |
| `approval` | JSONField | default `{}` |
| `idempotency_key` | CharField | **unique with company** |
| `provenance` | JSONField | pack shape |
| `source_refs` | JSONField | dcs_run_id, handoff_id, etc. |
| `metadata` | JSONField | transition reason, last actor |
| `created_at` / `updated_at` | auto | |

**Meta:** `UniqueConstraint(company, idempotency_key)` · indexes on `(company, status)`, `(company, task_type)`

| # | Deliverable | Done |
|---|-------------|------|
| A1.1 | Model as above | [x] |
| A1.2 | Migration `dataruns/migrations/0032_orchestrationtask.py` | [x] |
| A1.3–A1.5 | Constants file complete | [x] |

#### Step 1.3 — Phase 1 tests

**File:** `dataruns/tests/test_orch_sm_phase1.py` (mirror `test_handoff_ho02_phase1.py`)

| # | Test case | Done |
|---|-----------|------|
| T1.1 | Audit action strings locked | [x] |
| T1.2 | Every allowed edge in matrix → True | [x] |
| T1.3 | Forbidden edges → False (e.g. `PENDING→DONE`, `DONE→READY`) | [x] |
| T1.4 | Terminal + idempotent helpers | [x] |
| T1.5 | `normalize_orch_status` rejects invalid | [x] |
| T1.6 | `serialize_orch_task` includes pack keys | [x] |
| T1.7 | Model create with defaults | [x] |

| # | Deliverable | Done |
|---|-------------|------|
| A1.6 | Phase 1 tests | [x] |

**Phase 1 exit:**

```bash
python manage.py migrate
python manage.py test dataruns.tests.test_orch_sm_phase1
```

All green · **no views yet**. *(Run in venv locally.)*

**Phase 1 audit (recheck):**

| Step | Verdict | Evidence |
|------|---------|----------|
| 1.1 Constants + 16-edge graph | **Pass** | `task_constants.py` · matrix count test · terminal block |
| 1.2 Model + migration | **Pass** | `OrchestrationTask` · `0032_orchestrationtask.py` · default `PENDING` |
| 1.3 Phase 1 tests | **Pass** | `test_orch_sm_phase1.py` — 19 tests OK (venv) |
| HO-02 regression | **Pass** | `verify_ho02_backend.py` OK |
| Scope guard | **Pass** | No HTTP/services · `HandoffPackage` untouched |

**Fixes applied in recheck:** terminal transition guard · audit `to_status` required · default status `PENDING` · idempotency `IntegrityError` test · explicit allowed-edge + error-code tests.

---

### A1 Phase 2 — Services (still no HTTP)

**File:** `dataruns/orchestration/task_transitions.py`

#### Step 2.1 — Types

| # | Item | Done |
|---|------|------|
| 2.1.1 | `OrchTransitionError(code, detail, status)` | [x] |
| 2.1.2 | `OrchTransitionOutcome(record, idempotent)` | [x] |

#### Step 2.2 — `create_orchestration_task()`

| # | Behavior | Done |
|---|----------|------|
| 2.2.1 | Validate `task_type`, `status`, `priority_inputs` (4 keys 0–3) | [x] |
| 2.2.2 | Build `provenance` if missing | [x] |
| 2.2.3 | Idempotent: same `(company, idempotency_key)` → existing row, no duplicate audit | [x] |
| 2.2.4 | Insert + `append_audit_event(…created…)` | [x] |

#### Step 2.3 — `transition_orchestration_task()`

| # | Behavior | Done |
|---|----------|------|
| 2.3.1 | `@transaction.atomic` + `select_for_update()` | [x] |
| 2.3.2 | Company scope — wrong company → not found | [x] |
| 2.3.3 | Role gates (see table below) | [x] |
| 2.3.4 | Idempotent same status → skip duplicate audit | [x] |
| 2.3.5 | Invalid edge → 409 `invalid_transition` | [x] |
| 2.3.6 | Update status + merge `reason` into `metadata` | [x] |
| 2.3.7 | `append_audit_event(…transitioned…, from/to)` | [x] |

**Role gates (lock in PR body):**

| Action | Admin | Analyst | Viewer |
|--------|-------|---------|--------|
| GET (via views later) | ✓ | ✓ | ✓ |
| Create task | ✓ | ✓ | ✗ |
| Operational transitions | ✓ | ✓ | ✗ |
| `AWAITING_APPROVAL → DONE` | ✓ | ✗ | ✗ |

#### Step 2.4 — Phase 2 tests

**File:** `dataruns/tests/test_orch_sm_phase2.py`

| # | Test case | Done |
|---|-----------|------|
| T2.1 | Create happy path | [x] |
| T2.2 | Idempotent create — one row, one create audit | [x] |
| T2.3 | Path `READY → IN_PROGRESS → AWAITING_APPROVAL → DONE` (admin) | [x] |
| T2.4 | Forbidden transition → 409 | [x] |
| T2.5 | Viewer cannot transition | [x] |
| T2.6 | Analyst cannot `AWAITING_APPROVAL → DONE` | [x] |
| T2.7 | `FAILED → READY` retry | [x] |
| T2.8 | Idempotent `→ DONE` twice — one audit | [x] |
| T2.9 | Wrong company → not found | [x] |

| # | Deliverable | Done |
|---|-------------|------|
| A1.7–A1.10 | Services + audit | [x] |
| A1.11 | Phase 2 tests | [x] |

**Phase 2 exit:**

```bash
python manage.py test dataruns.tests.test_orch_sm_phase2
```

All green · **no HTTP yet**. *(17 tests OK in venv · Phase 1+2 = 36 tests · HO-02 verify OK)*

**Phase 2 audit (recheck):**

| Step | Verdict | Evidence |
|------|---------|----------|
| 2.1 Types | **Pass** | `OrchTransitionError` · `OrchTransitionOutcome` |
| 2.2 Create service | **Pass** | validate · provenance default · idempotent · audit · race-safe IntegrityError |
| 2.3 Transition service | **Pass** | row lock · role gates · idempotent (AWAITING_APPROVAL/DONE/CANCELLED) · metadata merge |
| 2.4 Tests | **Pass** | `test_orch_sm_phase2.py` — 17 tests OK |
| HO-02 regression | **Pass** | `verify_ho02_backend.py` OK |
| Scope guard | **Pass** | No HTTP/views · `HandoffPackage` untouched |

**Fixes applied in recheck:** T2.8 now uses `AWAITING_APPROVAL → DONE` (admin) path · added idempotent tests for AWAITING_APPROVAL/CANCELLED · create validation + default provenance tests · `READY → READY` non-idempotent 409 test.

---

### A1 Phase 3 — HTTP APIs

**File:** `dataruns/orchestration/task_views.py`

| View | Method | Path | Done |
|------|--------|------|------|
| List/create | GET | `/api/v1/orchestration/tasks/` | [x] |
| List/create | POST | `/api/v1/orchestration/tasks/` | [x] |
| Detail | GET | `/api/v1/orchestration/tasks/{id}/` | [x] |
| Transition | POST | `/api/v1/orchestration/tasks/{id}/transition/` | [x] |

**POST create body (minimal):**

```json
{
  "task_type": "FIX",
  "task_id": "FIX-CC-03",
  "title": "Fix CC-03",
  "check_id": "CC-03",
  "status": "READY",
  "priority_inputs": {
    "blocker_status": 2,
    "severity_risk": 1,
    "dependency_readiness": 3,
    "effort_impact": 2
  },
  "priority_score": 2.1,
  "idempotency_key": "<company>:FIX-CC-03:dcs:<run_id>"
}
```

**POST transition body:**

```json
{ "to_status": "IN_PROGRESS", "reason": "Started fix" }
```

**Errors:** `invalid_transition` 409 · `forbidden` 403 · wrong company 404

**URLs:** extend `dataruns/orchestration_urls.py` — keep `plan/` first, then `tasks/…`

#### Phase 3 tests

**File:** `dataruns/tests/test_orch_sm_phase3.py`

| # | Test case | Done |
|---|-----------|------|
| T3.1 | POST create → 201 + body shape | [x] |
| T3.2 | GET list + filters | [x] |
| T3.3 | GET detail | [x] |
| T3.4 | POST transition success | [x] |
| T3.5 | Invalid transition → 409 | [x] |
| T3.6 | Viewer POST → 403 | [x] |
| T3.7 | Cross-company → 404 | [x] |
| T3.8 | **Regression:** `GET /orchestration/plan/` still 200 | [x] |

| # | Deliverable | Done |
|---|-------------|------|
| A1.12–A1.14 | Views, URLs, tests | [x] |

**Phase 3 exit:**

```bash
python manage.py test dataruns.tests.test_orch_sm_phase3
python manage.py test dataruns.tests.test_orch_plan_api
```

All green · **16 phase3 tests + plan regression OK** · Phase 1–3 = 52 tests · HO-02 verify OK

**Phase 3 audit (recheck):**

| Step | Verdict | Evidence |
|------|---------|----------|
| 3.1 Views | **Pass** | 4 endpoints · role gates · `{detail, code}` errors · 201/200 idempotent create |
| 3.2 URLs | **Pass** | `plan/` first · `tasks/` · `tasks/{id}/` · `tasks/{id}/transition/` |
| 3.3 Tests | **Pass** | `test_orch_sm_phase3.py` — 16 tests OK |
| Plan regression | **Pass** | `test_orch_plan_api.py` unchanged |
| HO-02 regression | **Pass** | `verify_ho02_backend.py` OK |
| Scope guard | **Pass** | `OrchestrationPlanView` untouched · no HandoffPackage changes |

**Fixes applied in recheck:** analyst `AWAITING_APPROVAL → DONE` HTTP 403 test · invalid filter 400 · missing `to_status` 400 · idempotent transition flag test.

---

### A1 Phase 4 — Verify + doc

**File:** `scripts/verify_orch_sm_01_backend.py` (mirror `verify_ho02_backend.py`)

Static checks: model · migration · 8 statuses · transition helpers · 4 URLs · audit constants · 3 test modules · `--run-tests`

| # | Deliverable | Done |
|---|-------------|------|
| A1.15 | Verify script | [x] |
| A1.16 | Update phase progress table in this doc | [x] |
| A1.17 | PRD §9.2 Slice A BE verify green | [x] |

**Phase 4 exit:**

```bash
python scripts/verify_orch_sm_01_backend.py
python scripts/verify_orch_sm_01_backend.py --run-tests
python scripts/verify_ho02_backend.py --run-tests
```

All green · static + `--run-tests` OK · `--with-ho02-regression` OK · HO-02 verify OK

**Phase 4 audit (recheck):**

| Step | Verdict | Evidence |
|------|---------|----------|
| 4.1 Verify script | **Pass** | 8 statuses · 16-edge test · error codes · pack schema · 4 URLs · 52 tests |
| 4.2 `--run-tests` | **Pass** | phase1 + phase2 + phase3 + plan API (60 tests total with plan) |
| 4.3 `--with-ho02-regression` | **Pass** | + HO-02 phase3 module |
| 4.4 Doc / PRD refs | **Pass** | GAP doc + PRD cite verify script |
| HO-02 `--run-tests` | **Pass** | exit criteria command green |
| Scope guards | **Pass** | no HandoffPackage · plan view unchanged |

**Fixes applied in recheck:** verify script strengthened — pack schema · error codes · 16-edge test · admin approval gate check.

**Deep audit (Phases 1–4, full stack):**

| Area | Verdict | Notes |
|------|---------|-------|
| Phase 1 constants/model | **Pass** | 8 statuses · 11 types · 16-edge graph · pack schema aligned |
| Phase 2 services | **Pass** | idempotent create · row lock · role gates · audit chain |
| Phase 3 HTTP | **Pass** | 4 endpoints · company scope · error codes · plan API untouched |
| Phase 4 verify | **Pass** | static + `--run-tests` + HO-02 regression |
| HO-02 regression | **Pass** | phase1–3 handoff tests (117 total with orch) |
| Scope guards | **Pass** | no HandoffPackage · no WritebackToken · no Matrix flip |

**Bugs fixed in deep audit:**
- Block create in terminal statuses (`DONE`/`CANCELLED`) — SM bypass closed
- Validate `depends_on` / `capability_dependencies` must be lists
- Validate `approval` / `source_refs` / `metadata` / `provenance` must be objects
- Validate `priority_score` numeric + 0–3 · `wave` 0–6

**PRD + pack alignment (verified by `test_orch_sm_pack_alignment.py`):**

| Check | Result |
|-------|--------|
| Pack `status` enum (8) = `ORCH_STATUS_ENUM` | **Match** |
| Pack `task_type` enum (11) = `ORCH_TASK_TYPE_ENUM` | **Match** |
| `schema_version` const `1.0.1` | **Match** |
| PRD §7.1 transition graph (16 edges) | **Match** |
| `serialize_orch_task` pack required fields | **All present** |
| Plan FIX task → persisted create (task_id, idempotency_key, priority) | **Match** |
| Plan API unchanged | **Regression OK** |

**Known deferred (not bugs — v1 scope):**
- Audit bell deep-links for `workflow.orchestration_task_*` (optional v1 per GAP doc)
- Plan API → DB materialize bridge (explicitly deferred)
- FE Phase 5 complete (Overview persisted task list + status chips)

---

### A1 Phase 5 — Frontend (minimal)

**After BE Phases 1–4 green.**

| # | Deliverable | Location | Done |
|---|-------------|----------|------|
| 5.1 | Full `OrchTaskStatus` types | `src/lib/orchestration.ts` or `orchestration-tasks.ts` | [x] |
| 5.2 | `ORCH_TASKS_QUERY_KEY`, GET list/detail | same | [x] |
| 5.3 | POST create + transition clients | same | [x] |
| 5.4 | Task list + status chip (one surface) | Overview **or** Data Center | [x] |
| 5.5 | Optional `verify-gap01-a-frontend.mjs` | `klints_frontend/scripts/` | [x] |

| # | Deliverable | Done |
|---|-------------|------|
| A1.18–A1.21 | FE items above | [x] |

**Do not:** replace ORCH plan UI · wire all 11 task types in FE v1

**Phase 5 exit:** Admin sees persisted task + status in browser.

**Phase 5 audit (recheck):**

| Step | Verdict | Evidence |
|------|---------|----------|
| 5.1 Full OrchTaskStatus (8) | **Pass** | `orchestration-tasks.ts` · verify:gap01a |
| 5.2 GET list/detail | **Pass** | `listOrchestrationTasks` · `getOrchestrationTask` |
| 5.3 POST create/transition | **Pass** | clients + role gate helpers |
| 5.4 Overview list + chip | **Pass** | `PersistedOrchTasksCard` · `data-orch-task-status` |
| 5.5 Verify script | **Pass** | `verify-gap01-a-frontend.mjs` · `npm run verify:gap01a` |
| Plan UI untouched | **Pass** | `orchestration.ts` plan client unchanged |
| TypeScript | **Pass** | `tsc --noEmit` · OverviewSearchSection `orch` |

**Fixes applied in recheck:** `OverviewSearchSection` + SpotlightSearch label · list URL matches handoff pattern.

---

### A1 Phase 6 — Manual staging demo

| Step | Action | Done |
|------|--------|------|
| 6.1 | POST create FIX `FIX-CC-03` status `READY` | [x] |
| 6.2 | Transition `READY → IN_PROGRESS → AWAITING_APPROVAL` | [x] |
| 6.3 | Admin: `AWAITING_APPROVAL → DONE` | [x] |
| 6.4 | Audit bell shows create + transition events | [x] |
| 6.5 | FE shows **DONE** chip | [x] |

**Phase 6 audit:** Manual demo confirmed (FIX-CC-03 · full SM path · audit bell · DONE chip). **Ops note:** run `python manage.py migrate` on any fresh DB — `0032_orchestrationtask` required or list API returns 500.

---

### A1 acceptance (done when)

- [x] Phases 1–6 complete (implementation + manual demo)
- [x] `verify_orch_sm_01_backend.py` PASS (+ `--run-tests`)
- [x] HO-02 regression PASS
- [ ] PR merged: **Option A1 · waiver not filed · no Matrix flip**

---

### A1 explicitly NOT in scope

| Skip | Reason |
|------|--------|
| CDUC dashboard (W5-03/06) | A2 / Slice C |
| Plan API → DB sync / materialize on GET | v1.1 optional |
| HANDOFF task on HO-02 approve | v2 integration |
| All 11 task_types E2E | One FIX demo enough |
| Wave DAG / BL-012 | Later |
| Matrix / MCP changes | Slice B |
| Overload `HandoffPackage` / `WritebackApprovalToken` | PRD forbids |

---

### A1 ORCH-01 relationship

| Layer | A1 behavior |
|-------|-------------|
| `GET /orchestration/plan/` | **Unchanged** — ephemeral ranked FIX list |
| `GET/POST /orchestration/tasks/` | **New** — persisted SM |
| Bridge (later) | Materialize plan row on first transition — not v1 |

ORCH-01 locked compute-on-GET; **GAP-01 A1 adds Option B persistence** per `PRD_ORCH_01` §4.4.

---

### A1 suggested calendar (solo)

| Day | Work |
|-----|------|
| 1 | Phase 0 + 1.1 constants + 1.2 model + migration |
| 2 | 1.3 phase1 tests + 2.1–2.3 services |
| 3 | 2.4 phase2 tests + 3.1–3.2 HTTP |
| 4 | 3.3 phase3 tests + 4 verify script |
| 5 | 5 FE + 6 demo + PR |

---

### A1 daily checklist

```text
[ ] Only current A1 phase in progress
[ ] Phase exit tests green before next phase
[ ] HO-02 verify still passes
[ ] No HandoffPackage / WritebackToken edits
[ ] No Matrix MCP status changes
[ ] Tick checkboxes in this doc
[ ] Commit: feat(GAP-01A): <phase summary>
```

---

### A1 files to create / edit

**New (BE):**

- `dataruns/orchestration/models.py`
- `dataruns/orchestration/task_constants.py`
- `dataruns/orchestration/task_transitions.py`
- `dataruns/orchestration/task_views.py`
- `dataruns/migrations/0032_*.py`
- `dataruns/tests/test_orch_sm_phase1.py`
- `dataruns/tests/test_orch_sm_phase2.py`
- `dataruns/tests/test_orch_sm_phase3.py`
- `scripts/verify_orch_sm_01_backend.py`

**Edit (BE):**

- `dataruns/orchestration_urls.py`
- `dataruns/audit.py` (if deep-links added — optional v1)

**Edit (FE, Phase 5):**

- `src/lib/orchestration.ts` (or `orchestration-tasks.ts`)
- Overview or Data Center panel component

---

## Slice B — Track B MCP (P0 · after A1 or waiver)

| Step | Task | Done |
|------|------|------|
| B0 | **STOP** if no Manago MCP/A2A access → request AC-A waiver | [ ] |
| B1 | Persist discovery evidence (JSON or DB) | [ ] |
| B2 | Thin MCP client — LIST workflows | [ ] |
| B3 | UC-02 capability panel shows live read result | [ ] |
| B4 | UPSERT **only if** discovery proves write tools (sandbox) | [ ] |
| B5 | E2E demo script / test (read-only OK) | [ ] |

**Branch:** `feature/gap01-slice-b-track-b`  
**Never:** flip Matrix `CONFIRMED_LIVE` without evidence · fake MCP Send toast.

---

## Slice C — Writeback / CDUC honesty (P1)

| Gap | Task | Done |
|-----|------|------|
| W6-03 | True auto-rollback **or** honest copy (“stale reclaim only”) | [x] |
| W5-01 | Reject → edit → re-preview → approve | [x] |
| W5-05/06 | Optional Change Preview drawer | [x] |
| W6-01/02 | Shopify metafield rollback **or** document irreversible | [x] |

**Branch:** `feature/gap01-slice-c-writeback-honesty`

**Slice C audit (full stack, recheck):**

| Area | Result | Notes |
|------|--------|-------|
| W6-03 rollback honesty | **Pass** | Manual-only copy; gov + Fix banners; no auto-undo claims |
| W5-01 reject → re-preview | **Pass** | Split Request / Approve & write / Reject; cross-session preview hydration |
| W6-01/02 irreversible + metafield | **Pass** | Mapping fallback for `irreversible` + `operator_disclosure`; confirm dialog |
| W5-05/06 Change Preview drawer | **Pass** | Before/after, DCS impact, workflows-unblocked estimate; executed-phase summary |

**Bug fixed in audit:** When `GET /writebacks/mappings/` failed (500), FE eligibility treated `mappingsLoadError` as a hard block and disabled preview/approve for **CI-01 / CC-03 / WB-SHOP-01** even though PRD-WB-02 treats allowlist + possible sheet as SoT. Fix: `isWritebackAllowlistSheetExecutable` / `isWritebackAllowlistSheetPreviewable` fallback in `writebacks.ts`; soft notice banner (`writeback-mappings-soft-notice`) when registry fails but writeback remains permitted; distinct copy for mapping vs sheet load errors.

**Verify (post-fix):** `verify-wb02` 117/117 · `verify-wb07` 64/64 · `npm run build` · BE writeback tests 24/24.

**Known limitations (acceptable):** rejection banner session-only · orphan pending tokens if re-preview without reject · Slice B MCP still blocked · no separate `/cduc` dashboard (by design).

---

## Slice D — Honesty (P1 · can start small parallel to B if blocked)

| Gap | Task | Done |
|-----|------|------|
| W7-01, W8-01, W8-05 | Rename “AI agent” → rule engine / package builder | [x] |
| W7-03, W9-02 | MCP action object: real builder **or** rename to `HANDOFF_PACKAGE_SPEC` | [x] |
| W6-04 | Lifecycle Architect “AI” → rule-based assessment (theater register) | [x] |

**Branch:** `feature/gap01-slice-d-honesty` (BE + FE · clean WT as of Phase 0)

### Locked decisions (Phase 0 · 2026-09-03)

| ID | Decision |
|----|----------|
| D0.1 | **Option 2** — rename to `HANDOFF_PACKAGE_SPEC` until Track B live (no signed MCP runtime) |
| D0.2 | Pack `UC-*_blueprint.json` stay SoT — **runtime override** in `build_package.py` |
| D0.3 | Keep machine field `agent_spec` (no breaking rename) |
| D0.4 | “Manago.ai agent” OK only as **external delivery target** — never imply Klints is an LLM agent |
| D0.5 | Include **W6-04** Lifecycle in this slice |
| D0.6 | Studio **PDF** out of scope |
| D0.7 | No Matrix `CONFIRMED_LIVE` flip · no fake MCP Send · do not expand Slice B MCP in this PR |
| D0.8 | UX audit required after copy changes (nav · Studio · QA · Handoff · Download JSON) |

**PR body must state:** Option 2 (HANDOFF_PACKAGE_SPEC) · Slice B still blocked/waiver · no Matrix flip.

### Branch note (contamination)

BE commit `(GAP-01C)` also tracked Slice B scaffold (`manago_mcp_*`, `test_manago_mcp_b0.py`, `run_manago_mcp_b0_discovery.py`). **Do not expand those files in Slice D.** Separate / ignore in Slice D PR description if still on branch.

### Phase checklist

| Phase | Focus | Done |
|-------|-------|------|
| **0** Pre-flight | Branch · decisions · verify baselines · inventory · this doc | [x] |
| **1** BE format | `_handoff_stub_from_blueprint` → `HANDOFF_PACKAGE_SPEC` + tests | [x] |
| **2** FE Studio | W7-01 copy (index + `WorkflowStudio`) | [x] |
| **3** FE QA | W8-01 copy (`qa.tsx`) | [x] |
| **4** FE Handoff + shell | W8-05 nav/Spotlight/title/machine-spec card | [x] |
| **5** Fixtures / Overview | `klints-data.ts` · Overview spill | [x] |
| **6** Lifecycle W6-04 | Grep + rename or N/A | [x] |
| **7** Verify gate | wf/qa/ho + new Slice D asserts + `npm run build` | [x] |
| **8** Deep UX audit | Click-path Studio→QA→Handoff + Download JSON format | [x] |
| **9** Docs + PR | Mark gaps · known limits · FE/BE PRs | [x] |

### Phase 0 verify baselines (2026-09-03)

| Gate | Result | Notes |
|------|--------|-------|
| FE `npm run verify:wf01` | **39/39** | Pass |
| FE `npm run verify:qa01` | **PASS** | Pass |
| FE `npm run verify:ho01` | **PASS** | Pass |
| FE `npm run verify:ho02` | **PASS** | Pass |
| BE `verify_wf01_backend.py` | **PASS** | get_or_create tenant (Phase 1 audit) |
| BE `verify_qa01_backend.py` | **PASS** | Static |
| BE `verify_ho01_backend.py` | **PASS** | Static (no `--run-tests`) |
| BE `verify_ho02_backend.py` | **PASS** | Static (no `--run-tests`) |

**Theater confirmed (pre Phase 1):** `handoff_stub.format == 'MCP_ACTION_OBJECT_AND_A2A_TASK_SPEC'` on UC-02 / UC-06B build packages.

**Phase 1 shipped (2026-09-03):** `_handoff_stub_from_blueprint` always emits `HANDOFF_PACKAGE_SPEC` (constants in `use_cases/constants.py`). Pack JSON unchanged. Tests + `verify_wf01_backend.py` assert honest format.

**Phase 1 audit fix:** `serialize_build_package` / `normalize_handoff_stub_format` strip MCP_ACTION theater on **GET/Download** for pre-Slice-D stored rows (DB payload immutable; API honest). `verify_wf01_backend.py` uses `get_or_create` for `wf01-verify` tenant (re-run safe).

**Phase 1 deep recheck (2026-09-03):** `normalize` now **always** forces `HANDOFF_PACKAGE_SPEC` when `handoff_stub` is a dict (D0.1 — closes lowercase/variant theater leak). GET detail test asserts format; verify asserts both generate payload + serialize. Handoff machine-spec preview does **not** embed build-package `handoff_stub` (no leak). Known: stored DB row + `package_content_hash` may still reflect pre-Slice-D theater until regenerate; API/Download honest.

**Phase 2 shipped (2026-09-03):** Studio index + `WorkflowStudio` W7-01 copy — package builder / staged handoff / machine package JSON; format chip `handoff-package-spec-format`; `verify-wf01` Slice D asserts.

**Phase 2 deep recheck:** Format chip always shown when package exists (fallback `HANDOFF_PACKAGE_SPEC`); brief copy unified to “stage for handoff”; verify locks Download JSON label + index “package builder” + Studio “for the agent” absence. No agent theater left under `src/components/workflow` or `workflow.index.tsx`.

**Phase 3 shipped (2026-09-03):** QA `qa.tsx` W8-01 — title “safe to stage?”, rule-engine description, “Stage for human activation” / staged package copy; `verify-qa01` Slice D asserts. Kept “not MCP delivery”.

**Phase 3 deep recheck:** Head meta aligned (rule-engine / not MCP); verify locks full “not MCP delivery”, “This is not an MCP send”, Continue to Handoff, no agent-ready/for-the-agent. Spotlight Studio hint “Agent blueprints” → “Package blueprints” (Phase 2 spill). Nav “Agent handoff” still Phase 4.

**Phase 4 shipped (2026-09-03):** Nav/Spotlight/stepper **Handoff** (not Agent handoff); page titles/kicker; **Staged package · machine spec**; MCP auto-send honesty kept; `verify-ho01` / `verify-ho02` Slice D asserts.

**Phase 4 audit fix:** Spotlight unlocked hint still said “Deliver validated specs” — now **Staged package · human activation**; verify locks doc title, kicker, and that hint.

**Phase 5 shipped (2026-09-03):** Fixture/`klints-data` honesty — no “for the agent” / “Delivered to agent” / `MCP / A2A → Manago.ai agent`. Handoff fixtures use **Staged package · human activation in Manago.ai**. Ambiguous “the agent” → Manago / staged handoff. D0.4: “Manago.ai agent” kept only as external handoff target. Overview already names Manago.ai agent. `verify-ho01` Phase 5 asserts.

**Phase 5 deep recheck (2026-09-03):** Pass (+ polish). Theater needles gone under `src/` + `klints-data`. Diagnose provenance titles now name **Manago.ai** (not bare “The agent”). Remaining “agent” strings: Manago.ai agent as external handoff target (D0.4) · machine field `manago.agent.relevance_set`. Overview single line locked. `verify:ho01` Phase 5 asserts. **Known out of product path:** root `index (1).html` design mock still has Agent handoff / MCP/A2A theater — not imported by the React app; leave unless a separate mock-cleanup pass.

**Phase 6 shipped (2026-09-03):** W6-04 Lifecycle — product path already AF-01 rule engine (no “Lifecycle Architect AI” in FE/BE). Locked honesty: `/lifecycle` subtitle + description **Rule-based architecture assessment** / **Not an AI agent**; Spotlight hint aligned. BE `dataruns/architecture/` unchanged (already rule-based). `verify:ho01` Phase 6 asserts.

**Phase 6 deep recheck (2026-09-03):** Pass (+ verify harden). No “Lifecycle Architect” / positive “is an AI agent” under `src/` or `dataruns/architecture/`. Loading/error/ready AppShell subtitles all rule-based; head meta aligned; Spotlight locked. Overview lifecycle card + BE serialize messages have no AI theater (counts/coverage only). `verify:ho01` locks head meta + ≥3 subtitle occurrences.

**Phase 7 shipped (2026-09-03):** Full verify gate green.

| Gate | Result | Notes |
|------|--------|-------|
| FE `npm run verify:wf01` | **59/59** | Slice D Studio asserts included |
| FE `npm run verify:qa01` | **PASS** | Slice D QA asserts included |
| FE `npm run verify:ho01` | **PASS** | Slice D Phases 4–6 asserts included |
| FE `npm run verify:ho02` | **PASS** | Slice D Handoff asserts included |
| BE `verify_wf01_backend.py` | **PASS** | HANDOFF_PACKAGE_SPEC path |
| BE `verify_qa01_backend.py` | **PASS** | Static |
| BE `verify_ho01_backend.py` | **PASS** | Static (no `--run-tests`) |
| BE `verify_ho02_backend.py` | **PASS** | Static (no `--run-tests`) |
| FE `npm run build` | **PASS** | vite + nitro production build |

**Phase 7 recheck (2026-09-03):** Re-ran FE `verify:wf01/qa01/ho01/ho02` + BE `verify_wf01/qa01/ho01/ho02` + `npm run build` — all **PASS**. Checklist scope complete (Slice D asserts already embedded in those verifies).

**Phase 7 deep recheck (2026-09-03):** Pass. Re-confirmed FE/BE verify scripts green; **~68** FE `Slice D` assert lines across wf/qa/ho scripts; `src/` free of Agent-handoff / agent-ready / for-the-agent / MCP A2A delivery / Lifecycle Architect theater needles. BE `verify_wf01` locks generate+serialize `HANDOFF_PACKAGE_SPEC`. Extra (beyond checklist): `manage.py test dataruns.tests.test_use_case_build_package --noinput` → **12/12 OK**. Known: HO-01/HO-02 BE scripts remain static by design (no `--run-tests` in this gate, same as Phase 0).

**Phase 8 shipped (2026-09-03):** Deep UX audit (D0.8) — static click-path + Download JSON format. **Pass · no copy fixes required.**

| Surface | Check | Result |
|---------|-------|--------|
| Nav | `Handoff` (not Agent handoff); Studio / QA / Lifecycle labels | **Pass** |
| Spotlight | Package blueprints · Package QA · Staged package · human activation · Rule-based architecture | **Pass** |
| Stepper | `short: "Handoff"` | **Pass** |
| Studio index | package builder meta + staged package description | **Pass** |
| Studio | stage-for-handoff · machine package JSON · Spec chip `HANDOFF_PACKAGE_SPEC` · Download JSON · No live MCP send · Approve → QA | **Pass** |
| QA | “safe to stage?” · rule engine · not MCP delivery · Stage for human activation · Continue to Handoff | **Pass** |
| Handoff | title Handoff · Staged package · machine spec · no MCP auto-send · locked Send · Approve for activation | **Pass** |
| Lifecycle | Rule-based architecture assessment · Not an AI agent | **Pass** |
| Download JSON | FE `downloadPackageJson` stringifies API `BuildPackageResponse`; BE GET/generate uses `serialize_build_package` → `handoff_stub.format == HANDOFF_PACKAGE_SPEC`; `verify_wf01` UC-02/UC-06B green | **Pass** |
| Theater needles | Studio/QA/Handoff components free of Agent handoff / agent-ready / for the agent | **Pass** |

**Manual click-path (operator):** `/workflow?uc=UC-02` → Generate → confirm Spec chip + **Download JSON** (`handoff_stub.format`) → **Approve → QA** → PASS → **Continue to Handoff** → staged package / no MCP auto-send / locked Send. Nav + Spotlight + `/lifecycle` spot-check.

**Known (not Phase 8 blockers):** `agent_spec` field name kept (D0.3); pack JSON may still say MCP_ACTION (runtime override); `index (1).html` mock out of product path; Studio CTA wording “send to QA” is journey language with adjacent “No live MCP send”.

**Phase 8 deep recheck (2026-09-03):** Pass. Re-grepped D0.8 surfaces (nav/Spotlight/Studio/QA/Handoff/Lifecycle) — no Agent-handoff / agent-ready / for-the-agent theater. Download chain intact: FE downloads API `BuildPackageResponse` only; BE `serialize_build_package` normalizes format. Re-ran FE `wf01/qa01/ho01/ho02` + BE `verify_wf01` — all **PASS**. No product fix required. (Live browser click-path remains operator manual per Phase 8 note.)

**Phase 9 shipped (2026-09-03):** Docs closeout · known limits · FE/BE PR drafts (Engineering commits manually).

### Slice D known limits (ship with PR)

| Limit | Detail |
|-------|--------|
| Option 2 only | `HANDOFF_PACKAGE_SPEC` until Track B — **no** signed MCP action object / live MCP Send |
| Pack JSON | `UC-*_blueprint.json` may still label MCP_ACTION — **runtime + serialize override** is SoT |
| Stored rows | Pre-Slice-D DB `payload` / `package_content_hash` may retain theater until regenerate; **GET/Download honest** |
| `agent_spec` | Machine field name kept (D0.3) — UI says machine package JSON |
| Slice B | Still blocked / waiver path — do **not** expand `manago_mcp_*` in this PR (BE may still carry GAP-01C scaffold on branch) |
| Matrix | No `CONFIRMED_LIVE` flip (D0.7) |
| Mock HTML | `klints_frontend/index (1).html` still has Agent handoff / MCP theater — **not** product path |
| Studio PDF | Out of scope (D0.6) |

**Slice D final deep audit (2026-09-03):** **Engineering scope complete.** Gaps W7-01/W8-01/W8-05 · W7-03/W9-02 Option 2 · W6-04 all `[x]`; phases 0–9 `[x]`. D0.1–D0.8 satisfied in code/docs. `src/` theater needles **NONE**. Slice D WT does **not** touch `manago_mcp_*`. FE `wf01/qa01/ho01/ho02` + BE `wf01/qa01/ho01/ho02` re-ran **PASS**. Pack JSON still MCP_ACTION (intentional D0.2). **Remaining ops (not code gaps):** manual commit + push + open FE/BE PRs · live browser smoke optional.

### Slice D PR drafts (after manual commit + push)

**BE title:** `feat(GAP-01D): HANDOFF_PACKAGE_SPEC runtime honesty (Option 2)`

**FE title:** `feat(GAP-01D): Studio/QA/Handoff/Lifecycle copy honesty`

**Shared PR body (both repos):**

```markdown
## GAP-01 Slice D — MCP / AI copy honesty (Option 2)

**Option:** 2 (`HANDOFF_PACKAGE_SPEC` until Track B) · **Slice B:** still blocked / waiver · **Matrix:** no CONFIRMED_LIVE flip

## Summary
- BE: runtime + serialize normalize `handoff_stub.format` → `HANDOFF_PACKAGE_SPEC` (pack JSON unchanged)
- FE: Studio / QA / Handoff / nav / Spotlight / fixtures / Lifecycle — rule engine / package builder / staged handoff (not AI agent / MCP action object theater)
- W6-04: Lifecycle rule-based assessment honesty
- Verify: `verify:wf01` · `verify:qa01` · `verify:ho01` · `verify:ho02` · BE `verify_wf01_backend.py` (+ sibling static HO/QA) · `npm run build`

## Test plan
- [ ] FE `npm run verify:wf01` / `verify:qa01` / `verify:ho01` / `verify:ho02`
- [ ] BE `python scripts/verify_wf01_backend.py` (and qa01/ho01/ho02 static)
- [ ] Optional: `manage.py test dataruns.tests.test_use_case_build_package --noinput`
- [ ] Manual: `/workflow?uc=UC-02` → Generate → Download JSON format chip → QA → Handoff (no MCP auto-send)
- [ ] Spot-check `/lifecycle` rule-based subtitle

## Not in this PR
- Track B MCP/A2A live Send · Matrix discovery flips · Slice E screens · demo seed · Studio PDF · rewriting pack blueprint JSON · expanding Slice B `manago_mcp_*` scaffold
```

### Grep inventory (Phase 0) — FE theater hotspots

| Area | Path | Issue |
|------|------|-------|
| Nav | `AppShell.tsx` | ~~`"Agent handoff"`~~ → **Phase 4 fixed** (`Handoff`) |
| Spotlight | `SpotlightSearch.tsx` | ~~`"Agent handoff"`~~ → **Phase 4 fixed** |
| Stepper | `klints-data.ts` | ~~`short: "Agent handoff"`~~ → **Phase 4 fixed** |
| Studio index | `workflow.index.tsx` | ~~“for the agent” / “agent-ready”~~ → **Phase 2 fixed** |
| Studio | `WorkflowStudio.tsx` | ~~agent JSON / handed to agent~~ → **Phase 2 fixed** (+ format chip) |
| QA | `qa.tsx` | ~~“hand to the agent?” / “Deliver to the agent”~~ → **Phase 3 fixed** |
| Handoff | `handoff.tsx` | ~~titles + Agent-ready~~ → **Phase 4 fixed** |
| Fixtures | `klints-data.ts` | ~~for the agent / Delivered to agent / MCP A2A delivery~~ → **Phase 5 fixed** |
| Overview | `OverviewPanel.tsx` | Manago.ai agent (external) · already honest |
| Lifecycle | `lifecycle.tsx` | ~~Architect AI theater~~ → **Phase 6** rule-based assessment honesty |
| BE builder | `build_package.py` | ~~MCP_ACTION format default~~ → **Phase 1** `HANDOFF_PACKAGE_SPEC` + serialize normalize |
| Pack JSON | `UC-*_blueprint.json` | same format (leave; override at runtime) |

**Already honest (do not regress):** HO-02 human activation · QA “not MCP delivery” · Studio “No live MCP send” · `PackageRouteHonesty`.

### Copy glossary (locked)

| Avoid | Prefer |
|-------|--------|
| AI agent (Klints) | Rule engine / package builder / hard-test QA |
| Lifecycle Architect AI | Rule-based architecture assessment (AF-01) |
| Agent handoff | Handoff / Package handoff |
| agent-ready (UI) | Package-ready / staged package |
| MCP action object | `HANDOFF_PACKAGE_SPEC` / staged handoff package |
| Agent JSON (UI) | Machine package JSON |

---

## Slice E — Week 8 screens (P2)

| Gap | Task | Done |
|-----|------|------|
| W8-02 | 3-way routing: Data→Fix, Workflow→Studio, Security→Integrations | [x] |
| W8-03 | Merchant sync health panel (extend Integrations) | [x] |
| W8-04 | QA FAIL deep-link matrix | [x] |

**Branch:** `feature/gap01-slice-e-week8-screens` (FE + BE · cut from Slice D merge)

**PR titles (draft):**
- BE: `docs(GAP-01E): Week 8 screens working gaps + PRD ship notes` (docs-only · no API)
- FE: `feat(GAP-01E): W8-02/03/04 routing + sync health + QA FAIL matrix`

### Locked decisions (Phase 0 · 2026-09-04)

| ID | Decision |
|----|----------|
| **E0.1** | **Ship order:** W8-03 → W8-04 → W8-02. PRD §9 allows claiming Week 8 residual with **W8-02 or W8-03**; still aim for all three. |
| **E0.2** | **W8-03 = Integrations only** — extend existing “Connector health”; **no** new `/sync-health` dashboard route. |
| **E0.3** | **No fake metrics.** Kill hardcoded **`42s` latency**. Show **last sync** (`last_data_refresh.finished_at`), **lag** (now − finished_at), **errors** (`issue_count` / status / `summary_status`). |
| **E0.4** | **Webhook counts:** only if BE already exposes them. Else honest label (e.g. bootstrap/import issues) — **do not invent** webhook pipelines or fake counts. |
| **E0.5** | **W8-02 taxonomy** (not app-unlock fallback alone): **Data** → `/fix?issue=…`; **Workflow** → Studio via `workflowStudioFromFix` / `workflowStudioLink`; **Security** → `/integrations` (reconnect / revoke / disconnect). |
| **E0.6** | **W8-02 Security** = connector auth / connection failures only — not every DCS FAIL. Prefer classify from existing signals (`check_id`, `dimension`, connector status, fix_owner) — **no new taxonomy DB** unless blocked. |
| **E0.7** | **W8-04 matrix by `test_id`:** `data_gates_pass` → Fix (check from evidence when present); graph/logic (`consent_branching`, `terminal_reachable`, `no_orphan_nodes`, `collision_policy`, `measurement_wired`, `rollback_defined`) → Studio for package `use_case_id`; **stale/freshness** (when evidenced) → Integrations or DCS re-import / fresh import — never invent check ids. |
| **E0.8** | Shared helper (e.g. `routeIssueTarget` / QA fail CTA map) reused by Overview / DCS / QA — **not** a third marketing dashboard unless UX requires a thin “Where to go” strip. |
| **E0.9** | **FE-first** on existing connector + QA payloads; BE only if list/API fields missing for lag/last sync. |
| **E0.10** | **Honesty / out of scope:** no Matrix `CONFIRMED_LIVE` flip · no fake MCP Send · do **not** expand Slice B `manago_mcp_*` · no W8-06 partner API · Slice B still blocked pending waiver. |
| **E0.11** | UX + verify asserts for new CTAs / sync-health labels after each phase. |

**PR body must state:** FE-first Week 8 screens · no fake latency/webhooks · Slice B still blocked · no Matrix flip.

### Branch note (contamination)

BE tree may still carry Slice B scaffold (`manago_mcp_*`). **Do not expand those files in Slice E** (E0.10). Ignore in PR description if present.

### Open decision — **locked in Phase 2**

**W8-04 stale → import:** pack has **no** `stale_*` hard_test. **Locked:** treat `not_evaluated` / `missing_or_empty` (and freshness/latency evidence keywords) as import path → `/data-consistency` (or `/integrations` when connector/latency evidenced). Do not invent a hard_test id.

### Phase checklist

| Phase | Focus | Done |
|-------|-------|------|
| **0** Pre-flight | Branch · decisions · verify baselines · inventory · this doc | [x] |
| **1** W8-03 | Integrations connector health — real last sync / lag / errors; kill `42s` | [x] |
| **2** W8-04 | QA FAIL row CTAs — Fix / Studio / import matrix + verify asserts | [x] |
| **3** W8-02 | Shared 3-way router on Overview/DCS (+ optional strip) | [x] |
| **4** Verify + UX | FE/BE gates · click-path · known limits · deep probes | [x] |
| **5** Docs + PR | Mark gaps · FE/BE PRs | [x] |

### Phase 0 verify baselines (2026-09-04)

| Gate | Result | Notes |
|------|--------|-------|
| FE `npm run verify:wf01` | **59/59** | Pass (post–Slice D) |
| FE `npm run verify:qa01` | **PASS** | Pass |
| FE `npm run verify:ho01` | **PASS** | Pass |
| FE `npm run verify:ho02` | **PASS** | Pass |
| BE `verify_wf01_backend.py` | **PASS** | venv `.venv` |
| BE `verify_qa01_backend.py` | **PASS** | Static + Django when venv |
| BE `verify_ho01_backend.py` | **PASS** | Static (no `--run-tests`) |
| BE `verify_ho02_backend.py` | **PASS** | Static (no `--run-tests`) |

**Phase 1 shipped (2026-09-04):** W8-03 Integrations “Connector health” — kill hardcoded `42s`; `connectorSyncHealth` / `formatConnectorSyncLag` from `last_data_refresh.finished_at` + `issue_count`; copy “Last sync, lag, and import issues”; no webhook count claim. FE `npm run verify:gap01e` locks asserts.

**Phase 1 deep recheck fix (2026-09-04):** Never-synced → `No sync` (not Healthy); health table includes `error` connectors; `Syncing` / `No sync` StatusBadge styles; in-flight keeps prior `finished_at` for Last sync via `connectorLastSyncDisplayKind`; verify hardens badge + issueCount cases.

**Phase 2 shipped (2026-09-04):** W8-04 QA FAIL deep-link matrix — `qaFailDeepLink` / `extractCheckIdFromQaEvidence`; FAIL row CTAs on `/qa` (`data-qa-fail-route`). `data_gates_pass` + check id → Fix; `not_evaluated` / `missing_or_empty` → Data Center re-import; graph/logic tests → Studio (`use_case_id`). Open decision locked: no pack `stale_*` id — import path from evidence values only. `verify:gap01e` Phase 2 asserts.

**Phase 2 deep recheck fix (2026-09-04):** Drop bare `"sync"` Integrations match; bare Fix when no check id (ignore URL `issueId`); `firstDataGatesCheckEvidence` when `evidence_ids` missing; known limit: multi-blocking gates → first evidence CTA only; verify locks Integrations / async false-positive / bare Fix.

**Phase 3 shipped (2026-09-04):** W8-02 shared routing — `classifyIssueRouteKind` + `routeIssueTarget`; Overview NBA/stake/top issue use taxonomy + FE-13 unlock fallback; DCS `resolveDcsRowCtas` Security → Integrations primary; optional gated → Studio (workflow). No new dashboard strip (E0.8). `verify:gap01e` Phase 3 asserts.

**Phase 3 deep recheck fix (2026-09-04):** Tighten Security regex (drop needs-attention / authorization / unauthorized); unlock→Integrations uses `taxonomy: "fallback"`; `FailedRunWorklistRow` → Data Center (or Integrations if security copy), never bare `/fix`; verify locks false-positive cases.

**Phase 4 shipped (2026-09-04):** Verify + UX gate (deep bar, not checklist-only).

| Gate | Result |
|------|--------|
| FE `npm run verify:gap01e` (static + deep probes) | **PASS** |
| FE `verify:wf01` / `qa01` / `ho01` / `ho02` | **PASS** |
| FE `verify:wf02` / `fe13` / `dcs10-fresh-import` | **PASS** |
| FE `npm run build` | **PASS** |
| BE `verify_wf01` / `qa01` / `ho01` / `ho02` | **PASS** (venv; HO static) |

**Phase 4 deep recheck (2026-09-04):** Hostile pass found remaining Security false positives — bare `credential(s)` / bare `reconnect` routed data/marketing copy to Integrations. Tightened to auth-scoped phrases (`reconnect required` / `oauth credentials` / `access token invalid`, etc.); dropped dead External-integrator branch; probes/verify lock the new cases + bootstrap fallback assert.

**Click-path (operator smoke):**
1. `/integrations` — Connector health: Last sync / Lag / Issues; no `42s`; Never → `No sync`
2. `/qa` after FAIL — per-row CTAs: Fix / Studio / Data Center (or Integrations)
3. Overview NBA / stake — Data→Fix · optional→Studio · auth→Integrations · unlock fallback tagged `fallback`
4. DCS worklist — Security primary Integrations; failed-run row → Data Center (not bare Fix)

### Codebase inventory (Phase 0)

| Area | Path | Today | Slice E need |
|------|------|-------|--------------|
| Overview routing | `OverviewPanel.tsx` `issueOpenTarget` / `routeIssueTarget` | **Shipped** — Data/Workflow/Security + unlock `fallback` | W8-02 |
| NBA open | `nbaOpenTarget` → `routeIssueTarget` | Taxonomy-aware (optional → Studio when gated) | W8-02 |
| DCS CTA | `resolveDcsRowCtas` + `data-consistency.tsx` | Security → Integrations; optional → Build; else Fix | W8-02 |
| Studio bridge | `use-cases.ts` `workflowStudioFromFix` | Exists | W8-02 Workflow + W8-04 Studio CTAs |
| Integrations health | `integrations.tsx` “Connector health” | **Shipped** — last sync / lag / issues; no `42s`; Never → `No sync` | W8-03 |
| Connector types | `connectors.ts` `LastDataRefresh` | `finished_at`, `issue_count`, `summary_status` | FE-first lag (no BE API) |
| BE health | `bootstrap_health.py` `health_report` | duration / issues on DataRun metadata | Unchanged (E0.9) |
| QA FAIL UI | `qa.tsx` | **Shipped** — per-FAIL CTA via `qaFailDeepLink` | W8-04 |
| Hard tests | `qa.ts` `PACK_HARD_TEST_IDS` | 7 pack ids | Matrix keys (E0.7) |
| Fixtures | `klints-data.ts` webhook latency copy | Demo narrative only | Do not treat as live sync health |
| Verify | `verify:gap01e` + `probe-gap01-e-phase4.mjs` | Static + deep probes | Phase 4/5 gate |

**Already honest (do not regress):** Slice D HANDOFF_PACKAGE_SPEC · HO-02 human Send · QA “not MCP delivery” · Studio “No live MCP send”.

### Slice E known limits (ship with PR)

| Limit | Detail |
|-------|--------|
| Webhook counts | Product metric unavailable — UI shows **import issues** (`issue_count`), not webhooks (E0.4) |
| Lag meaning | Age since last refresh `finished_at`, not source-platform webhook latency |
| Error banner | Auth/`error` connectors still also surface in top “needs attention” banner (health table includes them too) |
| W8-04 multi-block | `data_gates_pass` CTA uses **first** evidence row only |
| W8-04 stale→import | No pack `stale_*` test — evidence `not_evaluated` / `missing_or_empty` / freshness keywords |
| W8-02 strip | No dedicated “Where to go” strip (E0.8) |
| W8-02 Security | Auth-scoped phrases only (not bare credential/reconnect); unlock→Integrations is `fallback` taxonomy (incl. Overview null-target markers) |
| Failed-run row | No `check_id` → `/data-consistency` (same page) or Integrations — never bare `/fix` / invent check |
| NBA unlock | `nbaOpenTarget` does not re-apply app-unlock; stakes/top-issue use unlock-aware `issueOpenTarget` |
| Out of scope | Pack / Matrix / MCP unchanged (E0.10). Live browser smoke = operator-manual |

**Phase 5 shipped (2026-09-04):** Docs closeout · known limits table · FE/BE PR drafts (Engineering commits manually). BE = docs-only (E0.9 FE-first; no sync-health API).

**Phase 5 deep recheck (2026-09-04):** Hostile docs pass found PRD §4.4 still **PARTIAL / Not Started** for W8-02/03/04 while §9 + WORKING_GAPS claimed shipped — timeline Code column updated to **DONE (Slice E)** with honest scope (no dedicated 3-way screen; Integrations health not continuous dashboard; QA matrix via `qaFailDeepLink`). Stale “Open decision (refine…)” header cleaned. FE `verify:gap01e` + `wf02`/`fe13`/`qa01` reconfirmed **PASS**. Branch still tracks `origin/feature/gap01-slice-d-honesty` until first push `-u` to Slice E remote (ops, not code).

**Slice E final deep audit (2026-09-04):** **Engineering scope complete** (post full-slice deep check). Gaps W8-02/03/04 `[x]`; phases 0–5 `[x]`. E0.1–E0.11 satisfied. No BE `manago_mcp_*` expansion. Gates: FE `verify:gap01e` + `wf01`/`qa01`/`ho01`/`ho02`/`wf02`/`fe13`/`dcs10-fresh-import` + `npm run build` **PASS**; BE `wf01`/`qa01`/`ho01`/`ho02` static **PASS**. Full-slice deep check also fixed Overview null/unlock → Integrations links that were falsely tagged `data-issue-route="security"` (now `fallback`, matching E0.6 / `routeIssueTarget`). **Remaining ops (not code gaps):** manual commit + push (`-u` Slice E) + open FE/BE PRs · live browser smoke optional.

### Slice E PR drafts (after manual commit + push)

**BE title:** `docs(GAP-01E): Week 8 screens working gaps + PRD ship notes`

**FE title:** `feat(GAP-01E): W8-02/03/04 routing + sync health + QA FAIL matrix`

**Suggested commit messages (manual):**
- BE: `docs(GAP-01E): close Week 8 screens working gaps + PRD notes`
- FE: `feat(GAP-01E): W8-02/03/04 routing + sync health + QA FAIL matrix`

**FE files expected in commit:**
`src/lib/issue-routing.ts` · `connectors.ts` · `qa.ts` · `use-cases.ts` · `integrations.tsx` · `qa.tsx` · `data-consistency.tsx` · `OverviewPanel.tsx` · `primitives.tsx` · `scripts/verify-gap01-e-frontend.mjs` · `scripts/probe-gap01-e-phase4.mjs` · `package.json` · `scripts/verify-fe13-frontend.mjs` · `scripts/verify-wf02-frontend.mjs`

**BE files:** `docs/engineering/GAP_01_WORKING_GAPS.md` · `docs/engineering/PRD_GAP_01_M2_CODE_GAPS_WEEKS_5_9.md`

**Shared PR body (both repos — FE is code; BE is docs-only):**

```markdown
## GAP-01 Slice E — Week 8 residual screens (W8-02/03/04)

**Order:** W8-03 → W8-04 → W8-02 (E0.1) · **FE-first** (E0.9) · **Slice B:** still blocked / waiver · **Matrix:** no CONFIRMED_LIVE flip

## Summary
- W8-03: Integrations connector health — real last sync / lag / import issues (no fake `42s` / webhook counts)
- W8-04: QA FAIL deep-link matrix — Fix / Studio / Data Center (or Integrations); never invent check ids
- W8-02: shared Data→Fix · Workflow→Studio · Security→Integrations (`classifyIssueRouteKind` + `routeIssueTarget`)
- BE: docs only (`GAP_01_WORKING_GAPS` + PRD §4/§9 ship notes) — no sync-health API change
- Verify: FE `npm run verify:gap01e` (static + deep probes) · sibling wf/qa/ho · BE static wf/qa/ho

## Test plan
- [ ] FE `npm run verify:gap01e`
- [ ] FE `npm run verify:wf01` / `qa01` / `ho01` / `ho02` / `wf02` / `fe13` / `dcs10-fresh-import`
- [ ] FE `npm run build`
- [ ] BE `python scripts/verify_wf01_backend.py` (+ qa01/ho01/ho02 static)
- [ ] Manual: `/integrations` health · `/qa` FAIL CTAs · Overview/DCS open targets
- [ ] Confirm no invented webhook counts / no `42s` / Security stays auth-scoped

## Not in this PR
- Track B live MCP · Matrix discovery flips · W8-06 partner API · Slice F demo seed · expanding Slice B `manago_mcp_*` scaffold
```

---

## Slice F — Demo seed (P2)

| Gap | Task | Done |
|-----|------|------|
| W9-05 | `manage.py seed_demo_tenant --vertical=skincare` | [x] |
| W9-03 | ~5k contacts fixtures, DCS mid-band target | [x] |
| W9-04 | Document demo path connect→score→fix→studio→qa→handoff | [x] |

**Branch:** `feature/gap01-slice-f-demo-seed` (BE primary · FE cut for continuity; FE code optional)

**PR titles (draft):**
- BE: `feat(GAP-01F): seed_demo_tenant + demo path docs (W9-03/04/05)`
- FE: only if productized demo UX is required (default: **none**)

### Locked decisions (Phase 0 · 2026-09-04)

| ID | Decision |
|----|----------|
| **F0.1** | **Branch:** `feature/gap01-slice-f-demo-seed` (cut after Slice E). |
| **F0.2** | **Offline-first seed** — no live Shopify/Manago HTTP. Inject via `persist_normalized_records` / patched `run_import` (bootstrap helper pattern). |
| **F0.3** | `--vertical=skincare` = **data profile** only (names / failure mix). **No** `Company.vertical` migration in v1. |
| **F0.4** | Scale default **~5,000 contacts**; `--contacts=N` for CI smoke (e.g. 200). |
| **F0.5** | Score target: **REMEDIATE (50–69)** mid-band; sheet “~62” is **not** a hard AC — verify band, not exact 62. |
| **F0.6** | Idempotent: `--reset` **retires** demo tenant slug (rename + deactivate) then recreates; without it, refuse if slug exists. Hard-delete blocked by append-only `audit_logs`. |
| **F0.7** | Command runs (or requires) `seed_dcs_master` + `load_use_case_pilots`. |
| **F0.8** | **W9-04** = markdown demo path + reset  — **not** an in-app tour. |
| **F0.9** | Honesty: no fake MCP Send · no Matrix `CONFIRMED_LIVE` · stub connectors labeled as demo · do not expand `manago_mcp_*`. |
| **F0.10** | Verify: `scripts/verify_gap01f_backend.py` (command + small-N seed + REMEDIATE band + doc asserts). |

**PR body must state:** offline seed · REMEDIATE band target · Slice B still blocked · no Matrix flip.

### Phase checklist

| Phase | Focus | Done |
|-------|-------|------|
| **0** Pre-flight | Branch · F0 decisions · inventory · offline DCS spike | [x] |
| **1** W9-05 scaffold | `seed_demo_tenant` identity + masters + stub connectors | [x] |
| **2** W9-03 corpus | ~5k contacts + offline DCS → REMEDIATE band | [x] |
| **3** W9-04 doc | Demo path + reset markdown | [x] |
| **4** Verify + tests | `verify_gap01f` + small-N Django test | [x] |
| **5** Docs + PR | Mark gaps · known limits · PR draft | [x] |

### Phase 0 inventory (2026-09-04)

| Area | Path | Today | Slice F need |
|------|------|-------|--------------|
| Identity seed analog | `scripts/seed_dev_recovery.py` | Tenant/Company/User + pilots + DCS master | Pattern for W9-05 (no contacts/DCS) |
| DCS master | `seed_dcs_master` + Excel workbook | **Present** locally | Required before score |
| Pilots | `load_use_case_pilots` | Exists | Required for Studio path |
| Contacts/Orders | `persist_normalized_records` | Ready | Bulk offline insert |
| Offline import helper | `tenants/tests/bootstrap_test_helpers.py` | `successful_run_import_side_effect` | Spike + seed bypass |
| DCS pipeline | `run_dcs_pipeline` | Calls live `refresh_connected…` | Patch/bypass for seed (F0.2) |
| Score bands | `assemble.py` | REMEDIATE = 50–69 | W9-03 target band |
| Vertical field | `Company` | **None** | Profile flag only (F0.3) |
| `seed_demo_tenant` | `dataruns/management/commands/seed_demo_tenant.py` | **Slice F complete** | Manual commit + BE PR |
| Demo path doc | `docs/engineering/GAP_01F_DEMO_PATH.md` | **Done** (W9-04) | Operator walkthrough |
| Verify | `scripts/verify_gap01f_backend.py` | **Done** (F0.10) | Static + `--run-tests` |
| FE routes | onboarding → DCS → fix → studio → qa → handoff | Exist | Document only (F0.8) |

**Defer (not Slice F):** W9-07 perf 50k · W8-06 partner API · W9-01 continuous recheck · Track B MCP.

### Phase 0 spike (2026-09-04)

**Script:** `scripts/spike_gap01f_offline_dcs.py`  
**Method:** stub Shopify+Manago connectors → patch `run_import` with `successful_run_import_side_effect` → real `refresh_connected_platforms_for_dcs` + `run_dcs_pipeline` → print headline → delete spike tenant.

| Gate | Result |
|------|--------|
| DCS workbook present | **Yes** (`docs/dcs_scoring/…v1.4.1….xlsx`) |
| Spike offline pipeline | **PASS** — `ok=True`, `status=succeeded`, fresh_imports `shopify`+`manago_ai`, **no live HTTP** |
| Headline on tiny bootstrap payload | `None` / `BLOCKED` (expected — 1-contact helper payload; Phase 2 corpus tunes REMEDIATE) |

**Phase 0 shipped (2026-09-04):** Branch cut · F0.1–F0.10 locked · inventory · offline DCS spike green. **Next:** Phase 1 W9-05 scaffold (`seed_demo_tenant` identity + masters + stub connectors).

**Phase 1 shipped (2026-09-04):** W9-05 scaffold — `manage.py seed_demo_tenant --vertical=skincare`.

| Piece | Detail |
|-------|--------|
| Package | `dataruns/demo_seed/` (`constants`, `identity`) |
| Command | `dataruns/management/commands/seed_demo_tenant.py` |
| Flags | `--vertical` · `--contacts` · `--reset` · `--slug` · `--email` · `--password` · `--skip-masters` |
| Defaults | slug `klints-demo-skincare` · `demo@example.com` / `DemoPass123!` |
| Masters | `load_use_case_pilots` + `seed_dcs_master` (unless `--skip-masters`) |
| Connectors | Shopify + Manago `connected` stubs with `gap01f_demo_seed` config marker (not live OAuth) |
| Smoke | create OK · refuse without `--reset` · `--reset` recreates |

**Phase 1 deep recheck (2026-09-04):** Hostile pass found **destructive `--reset` ordering bug** — email owned by another tenant could retire demo slug then fail create. Fixed: `assert_email_available_for_slug` **before** reset; clearer error (`--reset` only retires target slug). Also: connector types via `resolve_connector_type` (no invalid `crm`); warn if CheckMaster/pilots empty; login `check_password` verified. Tests: `dataruns.tests.test_seed_demo_tenant_phase1` **PASS**.

**Phase 1 known limits:** stub connectors are `connected` so Beat/UI may attempt live refresh and fail outside the offline seed path (still true at Slice F close).

**Phase 1 exit:** Login-able demo tenant with masters + stub connectors. **Next:** Phase 2 corpus + offline DCS REMEDIATE.

**Phase 2 shipped (2026-09-04):** W9-03 corpus + offline DCS → REMEDIATE band.

| Piece | Detail |
|-------|--------|
| Corpus | `dataruns/demo_seed/corpus.py` — skincare mix: 10% matched · 55% Shopify-only · 10% Manago-only · 15% email mismatch · 10% Manago dups |
| Offline DCS | `dataruns/demo_seed/offline_dcs.py` — patched `run_import` + foundation stubs (tracking / topology / rate budget) with `gap01f_demo_seed` markers |
| Command | `seed_demo_tenant` runs corpus+DCS unless `--skip-dcs`; `--require-remediate` hard-fails out of band |
| Flags | `--skip-dcs` · `--require-remediate` (plus Phase 1 flags) |
| Score | Headline **~61.4** in REMEDIATE [50, 69.999] (CI-01/CI-03 + LE/PT fails); `run_state` often `INCOMPLETE` (coverage — F0.5 AC is band, not state) |
| Tests | `dataruns.tests.test_seed_demo_tenant_phase2` **PASS** |
| Smoke | `--contacts=200 --require-remediate` → headline 61.415 in band |

**Phase 2 honesty / known limits:** live foundation probes stubbed (not live auth); no Shopify/Manago HTTP; Windows console uses ASCII `OK` (no Unicode checkmark). Default `--contacts=5000` not re-smoked every change — CI uses small N; corpus mix ratios locked by test for N=5000. **Next:** Phase 3 W9-04 demo path markdown.

**Phase 2 deep recheck (2026-09-04):** Hostile pass found:

| Finding | Severity | Fix |
|---------|----------|-----|
| FD-07 Path B still scraped `Company.domain` over live HTTP during "offline" DCS | High (F0.2 honesty) | Force `skip_website_scrape=True` via patched `build_foundation_gate_context` |
| `--require-remediate --skip-dcs` exited 0 with no headline | Med | `CommandError` when combined |
| Remaining em-dash WARNING stdout could crash Windows cp1252 | Low | ASCII `-` |
| Phase 2 tests only hit helper, not command path | Med | Added command + scrape-not-called + contradict + 5k mix ratio tests |

Awkward N (7/19/21) still land in REMEDIATE. `contacts` arg = corpus index slots (DB rows higher due to Manago dups).

**Phase 3 shipped (2026-09-04):** W9-04 demo path markdown — [GAP_01F_DEMO_PATH.md](./GAP_01F_DEMO_PATH.md).

| Piece | Detail |
|-------|--------|
| Doc | Seed + reset · login · connect→score→fix→studio→qa→handoff with real FE routes |
| Linked | `docs/engineering/README.md` build-order row |
| Honesty | Offline stubs · REMEDIATE band · human Send · no in-app tour · no Matrix/MCP theater |

**Phase 3 exit:** Operator can follow markdown only (F0.8). **Next:** Phase 4 `scripts/verify_gap01f_backend.py` + asserts (incl. doc presence).

**Phase 3 deep recheck (2026-09-04):** Hostile pass found doc oversell.

| Finding | Severity | Fix |
|---------|----------|-----|
| Linear Studio→QA→Handoff implied ready after seed | High | Document seed unlocks connect+score+fix only; no package/QA/handoff staged |
| Score ~61 vs pilot `min_dcs: 70` → `blocked_dcs_score` | High | Explicit “Needs higher score” expected; REMEDIATE vs build-ready honesty |
| UI never shows the word “REMEDIATE” | Med | Doc says numeric ~61 + “Below 70 threshold” badge |
| Global masters upsert omitted | Med | Called out in “What this demo is” |
| Nav labels / `/dashboard` Overview weak | Low | Table uses AppShell labels |
| UI “Run score” vs offline seed | Low | Warn live re-score may fail on stubs |

**Phase 4 shipped (2026-09-04):** `scripts/verify_gap01f_backend.py` (F0.10).

| Piece | Detail |
|-------|--------|
| Static | Command flags · offline DCS patches · stub markers · no Matrix/MCP · W9-04 doc honesty (min_dcs 70 / no package) · F0.1–F0.10 locks |
| `--run-tests` | `test_seed_demo_tenant_phase1` + `phase2` (small-N seed + REMEDIATE + scrape skip + contradict flags) |
| PRD | Slice F section references verify script |

**Phase 4 exit:** `python scripts/verify_gap01f_backend.py --run-tests` green. **Next:** Phase 5 docs + mark W9-03/04/05 + PR draft.

**Phase 4 deep recheck (2026-09-04):** Hostile pass found **weak verify locks** (false-green risk). Hardened:

| Finding | Severity | Fix |
|---------|----------|-----|
| `REMEDIATE_MIN/MAX` symbols only — band could widen to always-pass | High | Lock `= 50.0` / `= 69.999` + `in_remediate_band` inequality |
| Email + reset both present but **order** unchecked | High | Assert first call index email &lt; reset |
| `"70" in demo_path` matched anything | Med | Require `min_dcs: 70` + `Below 70 threshold` |
| F0.9 `and`/`or` precedence soft | Med | Require `CONFIRMED_LIVE` **and** `no Matrix flip` |
| MCP needle fragile (`not** live MCP`) | Med | Lock `not** live MCP publish` + human activation |
| Missing PRD verify reference assert | Low | Assert `verify_gap01f_backend.py` in PRD |
| Missing scrape patch target / `assert_not_called` | Med | Lock `build_foundation_gate_context` patch + test mock |
| `Command` always true | Low | Require `class Command` + GAP-01 identity |

Static re-ran **PASS** after harden.

**Phase 5 shipped (2026-09-04):** Docs closeout · gaps marked · PR draft (manual commit by owner).

| Piece | Detail |
|-------|--------|
| Gaps | W9-05 / W9-03 / W9-04 → `[x]` |
| Demo path | [GAP_01F_DEMO_PATH.md](./GAP_01F_DEMO_PATH.md) |
| Verify | `python scripts/verify_gap01f_backend.py` · `--run-tests` |
| Login | `demo@example.com` / `DemoPass123!` · slug `klints-demo-skincare` |
| FE | **None** (F0.8 markdown only; no productized demo UX) |

### Slice F known limits (final)

| Limit | Note |
|-------|------|
| Offline seed | No live Shopify/Manago HTTP; FD-07 website scrape forced off |
| Score | REMEDIATE ~61 · `run_state` often `INCOMPLETE` · exact 62 not AC |
| Studio path | Pilots `min_dcs: 70` → **Needs higher score** until remediating/re-score |
| No pre-built package | Seed does not stage Studio/QA/Handoff artifacts |
| Stub connectors | UI live refresh / re-score may fail outside seed — expected; later failed runs can become “latest” and hide seeded headline |
| `--reset` | **Retires** prior demo slug (audit_logs append-only — no hard delete) then recreates |
| Sign-in email | `demo@example.com` (not `*.local`) — HTML5 email fields reject `.local` |
| Shared masters | CheckMaster + pilots upserts are global |
| `--contacts` | Corpus index slots; DB rows higher (Manago dups) |
| Default 5k | Mix ratios locked by test; full 5k DCS not required every CI run |
| Out of scope | In-app tour · W9-07 50k · W8-06 · Track B MCP · Matrix flips |

**Slice F engineering scope: complete.** Remaining ops: **manual commit** · push · open BE PR (FE none).

**Slice F final deep recheck (2026-09-04):** Engineering AC met; residual demo friction found and fixed/documented.

| Finding | Severity | Disposition |
|---------|----------|-------------|
| Phases 0–5 + W9-03/04/05 + verify `--run-tests` | — | **PASS** (re-ran green; 9 Django tests OK) |
| Most Slice F files still **uncommitted** | Ops | Not engineering gap — owner manual commit still required |
| `--reset` hard-delete raised `audit_logs rows cannot be deleted` after UI activity | **Critical** | Reset now **retires** tenant (rename/deactivate); test + verify lock |
| Retire path: `Company.save(update_fields=[…, "updated_at"])` | **Critical** | `Company` has **no** `updated_at` — fixed to `["domain"]` only |
| Demo path teardown recommended admin CASCADE delete | Med (honesty) | Removed; retire / throwaway `--slug` only; verify locks |
| Default email `demo@klints.local` rejected by FE `type="email"` | High (demo path) | Default → `demo@example.com`; docs + verify updated |
| Terminal: `bad_password` / `user_not_found` on wrong email | Ops/UX | Operator error + old `.local` friction |
| Post-seed UI re-score created newer failed runs (366–369); seed 365 still has 61.415 | Med | Documented known limit — re-seed to restore clean latest |
| D1/D2 GAP-01 doc acceptance | Out of Slice F | Still open (timeline sheet / client note) — not W9-03/04/05 |

**Verdict:** Slice F **engineering complete**. Not “fully shipped” until **manual commit + BE PR**. Live demo: re-seed with `demo@example.com` after retire fix (`--reset --require-remediate`).

---

## Documentation acceptance (PRD §9.1 — do early)

| # | Task | Done |
|---|------|------|
| D1 | Update timeline sheet Weeks 5–9 vs PRD §4 (stop false Completed) | [ ] |
| D2 | Client note: HO-02 human Send · Matrix seed · C1/C2 open or waived | [ ] |

---

## Regression gates (run after each slice)

| Gate | Command |
|------|---------|
| HO-02 BE | `python scripts/verify_ho02_backend.py --run-tests` |
| HO-01 handoff | `python scripts/verify_ho02_backend.py --run-tests --with-ho01-regression` |
| ORCH plan | `python scripts/verify_orch_*` / existing `test_orch_plan_api.py` |
| GAP-01F demo seed | `python scripts/verify_gap01f_backend.py` · `--run-tests` |
| FE HO-02 | `npm run verify:ho02` |
| FE tsc | `npm run build` or `tsc --noEmit` |

---

## What we explicitly skip

| Item | Reason |
|------|--------|
| WB-08 catalogue wave | Engineering / out of GAP-01 |
| Partner external API (W8-06) | M3 |
| Perf 50k / &lt;60s (W9-07) | Defer |
| Inventing MCP publish | Slice B + evidence only |
| Full BL-012 wave DAG | Post-A1 |

---

## Phase progress (update as you go)

| Slice | Status | Notes |
|-------|--------|-------|
| 0 Pre-flight | **Done*** | *0.1 employer OK pending · else PASS |
| A1 ORCH SM | **A1 complete*** | *Pending PR merge* · verify + HO-02 regression green · Phase 6 demo done |
| B Track B MCP | **Blocked?** | Need access or waiver |
| C Writeback honesty | **Done** | W6-03, W5-01, W6-01/02, W5-05/06 on branch · audit recheck + mappings-fallback fix |
| D Copy honesty | **Merged** | FE #51 · BE #74 · Option 2 |
| E Week 8 screens | **Engineering complete*** | *Pending manual commit + FE/BE PRs · W8-02/03/04 |
| F Demo seed | **Engineering complete*** | *Pending manual commit + BE PR · W9-03/04/05 |

---

## One-page daily checklist

**Today is Slice A1 Phase N only** — finish exit criteria before next phase.

```text
[ ] Branch correct (gap01-slice-a)
[ ] Only this phase's files touched
[ ] Tests for this phase green
[ ] verify script updated if new surface
[ ] HO-02 regression not broken
[ ] No Matrix flip · no fake MCP
[ ] Update GAP_01_WORKING_GAPS.md checkboxes
[ ] Commit message: feat(GAP-01A): <phase summary>
```

---

## PR template (copy per slice)

```markdown
## GAP-01 Slice A1 — OrchestrationTask 8-state SM

**Option:** A1 (pack ORCH) · **Waiver:** not filed

## Summary
- …

## Test plan
- [ ] verify_orch_sm_01_backend.py
- [ ] HO-02 regression
- [ ] Manual demo: READY → … → DONE

## Not in this PR
- CDUC dashboard · Track B · WB-08
```

```markdown
## GAP-01 Slice D — MCP / AI copy honesty (Option 2)

**Option:** 2 (`HANDOFF_PACKAGE_SPEC` until Track B) · **Slice B:** still blocked / waiver · **Matrix:** no CONFIRMED_LIVE flip

## Summary
- BE: runtime + serialize normalize → `HANDOFF_PACKAGE_SPEC`
- FE: Studio / QA / Handoff / Lifecycle / fixtures honesty (not AI agent / MCP action theater)
- Verify gates green (wf/qa/ho + build)

## Test plan
- [ ] FE verify:wf01 / qa01 / ho01 / ho02
- [ ] BE verify_wf01 (+ qa01/ho01/ho02 static)
- [ ] Manual UC-02 Studio → Download JSON → QA → Handoff
- [ ] `/lifecycle` rule-based copy

## Not in this PR
- Track B live MCP · Matrix flips · Slice E/F · pack JSON rewrite · `manago_mcp_*` expansion
```

```markdown
## GAP-01 Slice F — Week 9 demo seed (W9-03/04/05)

**Offline seed** · **REMEDIATE band target** · **Slice B:** still blocked / waiver · **Matrix:** no CONFIRMED_LIVE flip

## Summary
- W9-05: `manage.py seed_demo_tenant --vertical=skincare` (identity + masters + stub connectors)
- W9-03: offline skincare corpus (default ~5k slots) + offline DCS → REMEDIATE [50, 69] (~61 typical; ~62 not hard AC)
- W9-04: `docs/engineering/GAP_01F_DEMO_PATH.md` — reset + connect→score→fix→studio→qa→handoff (not in-app tour)
- Verify: `scripts/verify_gap01f_backend.py` (+ `--run-tests`)
- Honesty: no live connector HTTP in seed · no `Company.vertical` migration · stubs marked `gap01f_demo_seed`
- Demo login: `demo@example.com` / `DemoPass123!` (separate tenant — does not overwrite real CRM data)

## Test plan
- [ ] `python scripts/verify_gap01f_backend.py`
- [ ] `python scripts/verify_gap01f_backend.py --run-tests`
- [ ] `manage.py seed_demo_tenant --vertical=skincare --contacts=200 --reset --require-remediate`
- [ ] Manual: login demo → `/data-consistency` ~61 / Below 70 → Fix worklist
- [ ] Confirm Studio shows Needs higher score (`min_dcs: 70`) — expected mid-band honesty
- [ ] Confirm no live Shopify/Manago calls during seed

## Not in this PR
- Track B live MCP · Matrix flips · W9-07 perf 50k · W8-06 · in-app demo tour · FE productized demo UX · pre-built Studio/QA/Handoff package
```
