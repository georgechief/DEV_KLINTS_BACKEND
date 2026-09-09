# PRD-QA-01 — Workflow QA gate engine (BL-018)

**Status:** Ready for implementation  
**Owner track:** Engineering  — **BE + FE**  
**Surfaces:** `/qa` · Workflow Studio “→ QA” CTA · FlowStepper Build→QA→Handoff · build package APIs  
**Milestone:** M2 Activation & Blueprint (T2) — contract row **QA + Handoff live (score 0–100, ≥80 gate)**; this PRD ships **QA**; Handoff Send is a follow-up PRD  
**Depends on:**  
- **WF-01 / BL-016** — `WorkflowBuildPackage` + `qa_requirements` on package payload  
- **WF-02** — journey stages; QA step enabled when `package_id` present  
- Pack `qa` block on every pilot blueprint + `03_Machine_Contracts/qa_result.schema.json`  
**Design SoT:** existing `/qa` chrome (`flow-card`, gate rows, Phase 4 PageTitle) — **replace fixtures with live package QA**; keep visual language  
**Out of scope:** Live MCP/A2A Send · full `handoff_package` activation · BL-017 8-state ORCH machine · BL-012 waves · Engineering writebacks · inventing hard_tests beyond pack  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-QA-01 / BL-018 — live Workflow QA against a build package.

Read:
- docs/engineering/PRD_QA_01_WORKFLOW_QA_GATE_ENGINE.md
- docs/engineering/PRD_WF_01_WORKFLOW_BLUEPRINT_STUDIO.md (§7.2 qa_requirements)
- docs/engineering/PRD_WF_02_FIX_FLOW_STAGES_AND_CHECK_ROUTING.md (§4 QA stage)
- Pack: qa_result.schema.json + UC-*_blueprint.json → qa.hard_tests / minimum_score
- BE: dataruns/use_cases/build_package.py
- FE: src/routes/qa.tsx, WorkflowStudio.tsx → QA link, FlowStepper

Ship:
1. BE: POST run QA for package_id → persist qa_result (schema-shaped); GET latest.
2. Deterministic evaluators for the 7 pack hard_tests (§5) against package JSON.
3. Score 0–100; overall PASS only if all hard PASS AND score ≥ minimum_score (80).
4. FE /qa?uc=&package_id= binds live result (not getQaRunForIssue fixtures).
5. Re-run QA; Handoff CTA only when PASS (deep-link stub OK — no MCP send).
6. Audit event + verify script.

Acceptance: §12.
```

---

## 1. Why

M2 requires **QA live** with score **0–100** and **≥80 gate**. Today:

| Surface | Reality |
|---------|---------|
| Studio | Generates real build package; CTA links `/qa?uc=&package_id=` |
| `/qa?uc=&package_id=` | **Stub** — “Full QA gate runner is BL-018” |
| `/qa?issue=iss-*` | **Fixture** `getQaRunForIssue` — fake gates, fake Re-run toast |
| Package payload | Already has `qa_requirements: { minimum_score: 80, hard_tests: [...] }` — **unused** |
| Pack schema | `qa_result.schema.json` — **no producer** |

**WF-01 deferred this on purpose.** Packages are ready; QA is the next connecting stage before Handoff E2E.

---

## 2. References (authoritative)

| Source | Use |
|--------|-----|
| Pack `04_MVP1_Pilot_Blueprints/UC-*_blueprint.json` → `qa` | `minimum_score: 80` + **same 7** `hard_tests` on all 16 pilots |
| Pack `03_Machine_Contracts/qa_result.schema.json` | Persist / API response shape |
| Pack `handoff_package.schema.json` | **Out of scope** for this PRD — only unlock CTA / stub link |
| WF-01 §7.2 | Package already copies `qa_requirements` |
| WF-02 §4 | Stepper QA needs `package_id`; Handoff after QA cleared |
| FE `qa.tsx` | Visual chrome to keep (`flow-card`, `flow-gate-row`, Phase 4 next) |

### Pack hard_tests (locked — all 16 pilots)

```text
data_gates_pass
consent_branching
terminal_reachable
no_orphan_nodes
collision_policy
measurement_wired
rollback_defined
```

`minimum_score` = **80** everywhere. Do not invent extra tests in v1.

---

## 3. Vocabulary

| Term | Meaning |
|------|---------|
| **Build package** | Persisted `WorkflowBuildPackage` from WF-01 (`package_id`) |
| **QA run** | One evaluation of a package → `qa_result` |
| **Hard test** | Pack `qa.hard_tests[]` item — must be **PASS** or overall FAIL |
| **Score** | Number 0–100 from §6 |
| **QA PASS** | All hard tests PASS **and** `score ≥ qa_requirements.minimum_score` |
| **QA FAIL** | Any hard FAIL **or** score below minimum |
| **object_id** | Schema field — use `package_id` (string) |

---

## 4. Current code → target

```text
TODAY
  Studio ──generate──► package (qa_requirements unused)
       │
       └──link──► /qa?uc=&package_id= ──► empty stub

  /qa?issue=iss-* ──► fixture gates + fake Re-run

TARGET
  Studio ──generate──► package
       │
       └──link──► /qa?uc=&package_id=[&issue=]
                      │
                      ├── GET package
                      ├── POST …/qa/run/  (or auto-run on first open)
                      └── render live score + 7 hard tests
                            │
                            ├── PASS → Continue to Handoff (stub OK)
                            └── FAIL → fix package / gates / Studio
```

---

## 5. Hard-test evaluators (deterministic, package-only)

Evaluate against the **stored package payload** (+ embedded blueprint body where needed). No live Manago calls in v1.

| `test_id` | PASS when | FAIL when | Evidence (examples) |
|-----------|-----------|-----------|---------------------|
| **data_gates_pass** | Every **hard** gating check in `gates_snapshot` is `PASS` (or equivalent). `ready_provisional` / `provisional_supplemental` allowed if supplemental-only gaps. | Any hard gate `FAIL` / `WARN` if product treats WARN as block — **v1 lock: FAIL blocks; WARN does not**; `not_evaluated` on hard gate blocks | Locator: `gates_snapshot.<check_id>` |
| **consent_branching** | Workflow graph has ≥1 CONDITION (or equivalent) whose config/description references consent / opt-in / suppression **or** audience.consent is non-empty **and** a branch exists after trigger | No consent-related condition/branch in `agent_spec` / blueprint `workflow.nodes` | `node_id` of consent condition |
| **terminal_reachable** | From every node, BFS/DFS along `next[]` reaches a node with empty `next` **or** explicit terminal type (EXIT/END/STOP if present) | Cycle with no terminal **or** dead path that never ends | Path sample / cycle node ids |
| **no_orphan_nodes** | Every `node_id` is reachable from a TRIGGER (or sole entry) node | Orphan node id | Orphan `node_id` list |
| **collision_policy** | `agent_spec.collision_policy` (or blueprint equivalent) is present and non-empty | Missing / empty | Pointer into package |
| **measurement_wired** | `agent_spec.measurement` (or blueprint `measurement`) has `primary_metric` | Missing primary metric | Metric name |
| **rollback_defined** | `rollback.strategy` non-empty string on package | Missing / blank | Strategy snippet |

**Graph source:** prefer `agent_spec.workflow.nodes` if present; else blueprint `workflow.nodes` from package provenance / re-load blueprint by `blueprint_id` (company-scoped).

**Unknown test_id** in requirements (should not happen): treat as **FAIL** with evidence `unknown_test` — fail closed.

---

## 6. Score formula (locked v1)

```text
hard_pass_count = count(hard_tests where status == PASS)
hard_total      = len(qa_requirements.hard_tests)   # normally 7
score           = round(100 * hard_pass_count / hard_total)   # 0 if hard_total==0 → FAIL

overall_status  = PASS  iff  (hard_pass_count == hard_total)
                         AND (score >= qa_requirements.minimum_score)
                else FAIL
```

With 7 equal tests: 6/7 ≈ 86 but **overall still FAIL** if any hard FAIL — wait: if one fails, score ≈ 85.7 which is ≥80 but overall must be FAIL because hard failed.

**Rule:** hard FAIL **always** forces `status: FAIL` even if numeric score ≥ 80.

```text
if any hard_test == FAIL:
  status = FAIL
else if score >= minimum_score:
  status = PASS
else:
  status = FAIL
```

Soft rubric / weighted domains = **v1.1** only if product asks — do not block M2.

---

## 7. Backend API

### 7.1 Models

| Model | Fields (min) |
|-------|----------------|
| `WorkflowQaResult` | `id` (qa_run_id), `company`, `package` FK, `use_case_id`, `score`, `status` (PASS\|FAIL), `payload` JSON (full schema body), `created_at`, `created_by` |

Optional: keep only **latest** per package (overwrite) **or** append history — **v1 lock: append history; GET returns latest**.

### 7.2 Endpoints

```http
POST /api/v1/build-packages/{package_id}/qa/
Authorization: Bearer …
# body optional: {} 
# → 201 { qa_result per schema + package_id, use_case_id, minimum_score }

GET  /api/v1/build-packages/{package_id}/qa/
# → 200 latest qa_result  |  404 if never run

GET  /api/v1/qa-runs/{qa_run_id}/
# → 200 single run (optional if latest GET enough)
```

| Rule | |
|------|--|
| Auth | Same company scope as build package |
| Role | Admin **or** Analyst may run QA (read+evaluate); document if Admin-only preferred — **v1: any authenticated member of company** |
| 404 | Unknown package / wrong company |
| 409 | Package payload missing `qa_requirements` (should not happen) |
| Audit | `workflow.qa_run_completed` — metadata: package_id, qa_run_id, score, status, hard_fail_ids[] |

### 7.3 Response shape

Conform to pack schema; extend **only** with FE-needed siblings if required (document):

```json
{
  "schema_version": "1.0.0",
  "qa_run_id": "…",
  "tenant_id": "<company_id>",
  "object_id": "<package_id>",
  "package_id": "<package_id>",
  "use_case_id": "UC-02",
  "score": 100,
  "minimum_score": 80,
  "hard_tests": [
    { "test_id": "data_gates_pass", "status": "PASS", "evidence_ids": ["ev-1"] }
  ],
  "status": "PASS",
  "evidence": [
    {
      "source": "build_package",
      "locator": "gates_snapshot.CC-03",
      "value": "PASS",
      "observed_at": "2026-08-20T04:00:00Z"
    }
  ],
  "created_at": "…"
}
```

`evidence_ids` on hard_tests reference `evidence[]` entries (stable ids you assign, e.g. `ev-data_gates_pass-0`).

---

## 8. Frontend — visual & binding

### 8.1 Route contract

| Search | Behaviour |
|--------|-----------|
| `?uc=&package_id=` | **Primary live path** — load package + latest QA (auto-run once if none) |
| `?issue=` | Keep for journey context only; **do not** require fixture issue ids |
| no `package_id` | Empty state: “Generate a build package in Workflow Studio first” → link Studio |

**Remove** dependency on `getQaRunForIssue` for the live path. Fixtures may remain for Storybook/demo **behind explicit `?fixture=`** or delete — **v1 lock: live path never uses fixtures**.

### 8.2 Visual layout (keep chrome)

Preserve existing Phase 4 composition:

```text
┌─ PageTitle ─────────────────────────────────────────────┐
│ Phase 4 · QA validation                                 │
│ Is it safe to hand to the agent?                        │
│ [ Re-run QA ]                                           │
└─────────────────────────────────────────────────────────┘

┌─ flow-card (anchor-tint) ───────────────────────────────┐
│ eyebrow: {UC} · package · route HUMAN_FALLBACK          │
│ title: package.title / pilot title                      │
│ summary: short honesty — package validation, not MCP    │
│ touchpoint pills: from agent_spec / human_guide channels│
│                              ┌ score chip ┐             │
│                              │  100 / 100 │ PASS|FAIL   │
│                              │  gate ≥ 80 │             │
│                              └────────────┘             │
│ Validation gates · 7 total · N passed                   │
│  ┌ gate row ──────────────────────────────────────────┐ │
│  │ hard_test label     desc / evidence snippet  PASS  │ │
│  └────────────────────────────────────────────────────┘ │
│  … ×7                                                   │
│ footer: Review workflow | Continue to Handoff | locked  │
└─────────────────────────────────────────────────────────┘

┌─ flow-next · phase 5 ───────────────────────────────────┐
│ Deliver to the agent (activation stays human)           │
│ [ Continue to Handoff ]  only if QA PASS                │
└─────────────────────────────────────────────────────────┘
```

### 8.3 Copy map (hard_test → UI label)

| `test_id` | Display name | One-line desc |
|-----------|--------------|---------------|
| `data_gates_pass` | Data gates pass | Gating DCS checks on this package are clear |
| `consent_branching` | Consent branching | Workflow branches on consent / opt-in |
| `terminal_reachable` | Terminal reachable | Every path reaches an exit |
| `no_orphan_nodes` | No orphan nodes | All nodes reachable from the trigger |
| `collision_policy` | Collision policy | Overlap / collision rules present |
| `measurement_wired` | Measurement wired | Primary metric defined |
| `rollback_defined` | Rollback defined | Rollback strategy present on package |

### 8.4 Score chip visual

| State | UI |
|-------|-----|
| PASS | Green/revenue tone · “Cleared · score {n} ≥ {min}” |
| FAIL | Spark/blocked · “Blocked · score {n}” + list failed test ids |
| Running | Spinner on Re-run |
| No package | Empty state (no fake 100) |

### 8.5 CTAs

| Control | When | Action |
|---------|------|--------|
| **Re-run QA** | `package_id` present | `POST …/qa/` → refresh |
| **Review workflow** | always when uc known | `/workflow?uc=&package_id=&issue=` |
| **Continue to Handoff** / **View agent package** | `status === PASS` | `/handoff?uc=&package_id=&qa_run_id=&issue=` — **stub page OK**; must not toast “Sent via MCP” |
| Handoff locked | FAIL or no run | Disabled + reason |

### 8.6 Studio CTA honesty

Keep link; rename if needed:

- Prefer: **“Send package to QA”** / **“Validate in QA”**  
- Avoid implying MCP approve/send. Existing “Approve workflow → send to QA” is OK if copy clarifies **package validation**.

### 8.7 FlowStepper (WF-02)

| Stage | Enable when |
|-------|-------------|
| QA | `package_id` in search **or** known for working uc |
| Handoff | **v1:** enable only after latest QA PASS for that package (update `resolveFlowStepperStage` / `deriveJourneyStage`) — tooltip if not: “Clear QA (≥80, all hard tests) first” |

---

## 9. Flows

### Flow Q1 — Happy path (UC-02)

```text
1. Opportunities / Fix → Studio ?uc=UC-02
2. Generate build package → package_id
3. CTA → /qa?uc=UC-02&package_id=…
4. FE loads package; if no QA yet → POST run
5. All 7 hard PASS · score 100 · status PASS
6. Continue to Handoff (stub) with qa_run_id in search
7. Stepper: Build done · QA current · Handoff enabled
```

```mermaid
flowchart LR
  Studio[Workflow Studio] -->|generate| Pkg[Build package]
  Pkg -->|link| QA[/qa]
  QA -->|POST qa/run| Eng[Hard-test engine]
  Eng -->|PASS ≥80| HO[Handoff stub]
  Eng -->|FAIL| Studio
```

### Flow Q2 — Data gates fail

```text
1. Package generated while a hard gate later flipped FAIL (or snapshot already FAIL)
2. data_gates_pass = FAIL → overall FAIL even if other 6 PASS (score ~86)
3. UI: gate row Failed; Handoff locked; link Fix/DCS for failing check_id
```

### Flow Q3 — Graph fail (orphan / no terminal)

```text
1. Corrupt or incomplete node graph in blueprint body
2. no_orphan_nodes or terminal_reachable FAIL
3. Operator returns to Studio — cannot “fake clear”
```

### Flow Q4 — Re-run

```text
1. Operator clicks Re-run QA
2. New qa_run_id appended; UI shows latest
3. Audit second event
```

### Flow Q5 — No package

```text
1. /qa or /qa?uc=UC-02 without package_id
2. Empty state → Studio generate
3. Stepper QA disabled (WF-02 tooltip)
```

---

## 10. FE / BE touch list

### Backend

| Area | Change |
|------|--------|
| `dataruns/use_cases/` | QA model + evaluators module + views/urls |
| Tests | UC-02 package → all PASS; force FAIL fixtures per test_id |
| Audit | `workflow.qa_run_completed` |
| verify script | `scripts/verify_qa01_backend.py` (optional) |

### Frontend

| Area | Change |
|------|--------|
| `src/routes/qa.tsx` | Live bind; score chip; hard_test rows; remove fixture primary path |
| `src/lib/use-cases.ts` or `qa.ts` | API client + types |
| `FlowStepper` / journey | Handoff enable on QA PASS |
| `WorkflowStudio.tsx` | CTA copy polish if needed |
| `scripts/verify-qa01-frontend.mjs` | Static asserts: no fixture-only primary path; POST/GET wiring |

---

## 11. Explicit non-goals

| Item | Defer |
|------|--------|
| MCP Send / A2A delivery | Handoff PRD / M3 |
| Persist full `handoff_package` + manifest_hash activation | Handoff-01 |
| Human override “force PASS” | Never in MVP1 |
| Live Manago workflow inspect | Discovery / MCP |
| Different hard_tests per UC | Pack has identical 7 |
| Soft AI narrative of QA | Optional later |
| BL-017 task state machine | Separate |

---

## 12. Acceptance

- [ ] `POST …/build-packages/{id}/qa/` returns schema-shaped result; persists  
- [ ] All 7 pack hard_tests evaluated per §5  
- [ ] Overall PASS only if all hard PASS **and** score ≥ 80  
- [ ] Any hard FAIL ⇒ status FAIL (even if score ≥ 80)  
- [ ] `/qa?uc=&package_id=` shows live score + gate rows (no fixture)  
- [ ] Re-run creates a new result and refreshes UI  
- [ ] Handoff CTA enabled **only** on PASS; locked otherwise  
- [ ] Studio → QA deep-link still works with `package_id`  
- [ ] FlowStepper Handoff respects QA PASS (or honest tooltip)  
- [ ] Audit event on run  
- [ ] UC-02 (+ optionally UC-06B) demo path documented in PR Working/Gaps  
- [ ] Written right/gap note in PR  

---

## 13. PR title / branch

- Branch: `feature/qa-01-workflow-qa-engine`  
- BE title: `feat(QA-01): build-package QA engine — hard tests + ≥80 gate`  
- FE title: `feat(QA-01): live /qa bind to package QA results`  

Link BE+FE PRs; deliverable for M2 QA row.

---

## 14. Traceability

| Item | |
|------|--|
| Contract | M2 — QA + Handoff live (score ≥80); **this PRD = QA half** |
| Pack | `qa_result.schema.json` · blueprint `qa.*` |
| Parents | WF-01 build package · WF-02 journey |
| Unblocks | Handoff-01 · one-workflow E2E · T2 claim path |
| Explicit next | `PRD_HO_01_HANDOFF_PACKAGE` (human staged package; MCP stub) |

---

## 15. Implementation notes for Engineering

1. Start BE evaluators + UC-02 golden test (seed package → expect PASS).  
2. Wire FE empty/stub path → live; keep CSS classes (`flow-card`, `flow-gate-row`).  
3. Do **not** wait on Engineering writebacks for QA.  
4. If `gates_snapshot` shape differs slightly in prod payloads, normalize in one helper — don’t fork tests.  
5. Score chip is the hero metric; gate table is the proof — same hierarchy as fixture design.  
