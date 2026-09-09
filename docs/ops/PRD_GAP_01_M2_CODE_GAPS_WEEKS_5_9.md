# PRD-GAP-01 — M2 code gaps (Weeks 5–9) · point-to-point SoT

**Status:** Ready for Engineering — **P0 (solo engineer · M2 claim honesty)**  
**Owner track:** Engineering  — **BE + FE** (Engineering track closed; no parallel owner)  
**Surfaces:** Approval / writeback lifecycle · ORCH SM · Track B MCP · Studio/QA/Handoff honesty · demo seed  
**Milestone:** M2 Activation & Blueprint (T2) — close **code** gaps vs contract + pack + timeline Weeks 5–9  
**SoT layers (priority order when they conflict):**  
1. **Contract** Schedule 1 M2 (Astrapse v1.2)  
2. **Pack** `Klints_MVP1_Rohan_Build_Pack_v1.2_20260718`  
3. **Timeline sheet** (Week 5–9 task descriptions — often overclaimed)  
4. **Code on `main`** (truth)  
**Out of scope:** Loom / Schedule 2 deposit ops (separate claim packet) · WB-08 catalogue wave · M3 security/Grafana · inventing MCP `CONFIRMED_LIVE` without discovery evidence  

---

## 0. Cursor agent brief (paste this)

```text
Implement from PRD-GAP-01 — M2 code gaps Weeks 5–9 (point-to-point).

Read:
- docs/engineering/PRD_GAP_01_M2_CODE_GAPS_WEEKS_5_9.md (this file)
- Pack: 03_Machine_Contracts/orchestration_task.schema.json
- Pack: 02_Execution_Capabilities/manago_mcp_discovery_results.json
- Contract Schedule 1 M2 (approval SM 8 states + Track B; Send; Matrix; writeback; Studio; QA+Handoff)
- Existing: HO-02, QA-01, CAP-01, WF-01, writebacks CI-01/CC-03/WB-SHOP-01, AF-01

Do NOT mark theater as done. Follow §3 priority slices.
Stop-and-flag before inventing MCP publish or flipping Matrix to CONFIRMED_LIVE.
```

---

## 1. Why this PRD exists

| Problem | Effect |
|---------|--------|
| Timeline sheet marks many Week 5–8 items **Completed** | Client may think CDUC 8-state, MCP Send, AI agents, auto-rollback, demo seed exist |
| Contract M2 still lists **8-state SM** + **Track B MCP/A2A** | Code has **neither** as literal runtime |
| Pack forbids inventing MCP live | HO-02 human Send is correct for pack; contract AC still names Track B |
| Only Engineering remains | Need one ordered gap list — not Engineering WB-08 |

This document is the **code gap SoT**. Each row: timeline/contract ask → code reality → gap → slice ID.

---

## 2. Contract M2 — point to point

| # | Contract wording | Code on `main` | Gap |
|---|------------------|----------------|-----|
| C1 | Approval state machine live (**8 states**) | **No** single 8-state SM. Live: handoff **4** (`STAGED`→`APPROVED_FOR_ACTIVATION`→`ACTIVATED`+`REJECTED`); writeback job statuses + `WritebackApprovalToken` 5 statuses. Pack ORCH enum exists in schema only. | **MISSING** — see §5 Slice A |
| C2 | **Track B MCP/A2A prototype** | Matrix seeded; MCP UPSERT/PUBLISH = `DISCOVERY_REQUIRED`; discovery JSON `PENDING_EXECUTION`; HO-02 = `HUMAN_MANAGO_UI` only; **no** MCP client / A2A runtime | **MISSING** — §5 Slice B |
| C3 | Writeback + Lifecycle live (SM REST, rollback, audit hash) | Writeback execute/rollback for **CI-01 / CC-03 / WB-SHOP-01**; audit `prev_hash` + immutability triggers; AF `/lifecycle` (rule engine, not LLM) | **PARTIAL** — auto-rollback 15m **missing**; Shopify metafield rollback stub; no CDUC product |
| C4 | Workflow Blueprint Studio + SM-agent-ready JSON | `/workflow` Studio; build package JSON + `human_guide`; `agent_spec` / handoff format **label** | **PARTIAL** — no Studio PDF; MCP action object not signed/runtime |
| C5 | QA + Handoff live (0–100, 80 gate) | QA-01 + HO-01 STAGED + HO-02 Send human path | **DONE** for human path |
| AC-A | Track B prototype E2E **one workflow** | None | **MISSING** (= C2) |
| AC-B | ‘Send to Manago.ai’ functional with approval gate | HO-02 approve → guide → confirm | **DONE** (human; not MCP) |
| AC-C | MCP Capability Matrix delivered | CAP-01 registry + GET + route honesty | **DONE** (seed; discovery flips still open) |

**Honest claim without more code:** AC-B + AC-C + C3–C5 (with caveats) are defensible. **C1 + C2 / AC-A block** a literal reading unless waived in writing or Slices A+B ship.

---

## 3. Priority for Engineering (build order)

Do **not** start everything. Solo order:

| Priority | Slice | Closes | Effort |
|----------|-------|--------|--------|
| **P0** | **A — ORCH / Approval 8-state** | Contract C1 + Week 5 sheet honesty | L |
| **P0** | **B — Track B prototype (read-first)** | Contract C2 / AC-A **or** prove waiver needed | M–L (blocked on Manago MCP access) |
| **P1** | **C — CDUC / writeback lifecycle honesty** | Week 5–6 overclaims (auto-rollback, reject-edit loop, preview dashboard) | M |
| **P1** | **D — Studio/Handoff MCP object honesty** | Pack MCP action object theater | S–M |
| **P2** | **E — Week 8 residual screens** | 3-way routing, merchant sync health | M |
| **P2** | **F — Week 9 demo seed** | `seed_demo_tenant`, demo corpus | M |
| **Defer** | Perf 50k/60s · partner external API · full AI “agents” rename | M3 / post-claim | — |

If client **waives C1+C2 in writing**, Engineering skips A+B for claim and only does **D (honesty)** + staging smoke. Still document waiver against this PRD.

---

## 4. Weeks 5–9 — point to point (sheet → code → gap)

Legend: **DONE** · **PARTIAL** · **MISSING** · **THEATER** (named as AI/agent/MCP live but deterministic/stub)

### 4.1 WEEK 5 — Approval state machine / CDUC

| Timeline task | Sheet | Code | Gap ID |
|---------------|-------|------|--------|
| Tamper-proof audit hash chain + DB immutability | Completed | **DONE** — `dataruns/audit.py`, migration `0030`, `verify_audit_chain` | — |
| Review/edit loop for rejected data changes | Completed | **MISSING** — reject token/status only; no revise → re-preview | **W5-01** |
| **8 status stages** (proposed→preview→awaiting approval→approved→synced→failed→rolled back) | In Progress / claimed | **MISSING** as one SM. Writeback uses job statuses + separate approval; not CDUC 8-state | **W5-02** (= Slice A variant) |
| Customer Data Update Control module | Completed | **PARTIAL** — Fix writeback approximates; **no** CDUC app/route/dashboard | **W5-03** |
| Test sync 100 profiles doesn’t break Manago | In Progress | **PARTIAL** — sandbox/smoke scripts; not productized CDUC test-sync | **W5-04** |
| Real-time impact preview before apply | Completed | **PARTIAL** — dry-run intents + `diff_hash`; no dedicated impact panel (DCS delta / workflows unblocked) | **W5-05** |
| Change Preview screen + CDUC dashboard | Completed | **MISSING** as named screens — preview tab inside `/fix` only | **W5-06** |

**Pack note:** Pack ORCH statuses are different 8:

```text
PENDING | BLOCKED | READY | IN_PROGRESS | AWAITING_APPROVAL | DONE | FAILED | CANCELLED
```

(`03_Machine_Contracts/orchestration_task.schema.json`)

Timeline Week 5 8-state ≠ pack ORCH enum. **Slice A must pick which 8-state the contract means** (recommend: implement **pack ORCH task SM** for C1, and map writeback job lifecycle honestly for Week 5 CDUC — or one unified model with documented mapping).

### 4.2 WEEK 6 — Writeback + Lifecycle

| Timeline task | Sheet | Code | Gap ID |
|---------------|-------|------|--------|
| Platform-neutral writeback interface | Completed | **DONE** — `WriteAdapter`, pipeline, registry | — |
| Manago rollback adapter | Completed | **PARTIAL** — contact upsert / detail / tag; **not** event_ingest | **W6-01** |
| Shopify rollback adapter | Completed | **PARTIAL** — customer note only; metafield `NotImplementedError` | **W6-02** |
| **Auto-rollback failed change within 15 minutes** | Not Started / sometimes claimed | **MISSING** — `WRITEBACK_EXECUTING_STALE_MINUTES=15` only **reclaims stale `executing` → failed**; does **not** undo successful writes | **W6-03** |
| Log writeback with unique hash | Completed | **DONE** — `diff_hash` + audit | — |
| Lifecycle Architect **AI** agent (16×7) | In Progress | **THEATER** if called AI — **DONE** as rule AF-01 (`lifecycle_model` 16×7, `/lifecycle`) | **W6-04** rename/honesty |
| Lifecycle Architecture dashboard | In Progress | **DONE** — `/lifecycle` | — |
| Ranked Opportunity Backlog dashboard | In Progress | **PARTIAL** — `/opportunities` + plan queue; not separate “backlog” product | **W6-05** |

### 4.3 WEEK 7 — Blueprint Studio

| Timeline task | Sheet | Code | Gap ID |
|---------------|-------|------|--------|
| Workflow Blueprint **AI** agent | Completed | **THEATER** — deterministic `build_package` from pack JSON; AI tasks = fix/explain/nba/report only | **W7-01** honesty |
| SM platform-specific build guide | In Progress | **PARTIAL** — `human_guide` from blueprint | **W7-02** deepen if pack incomplete |
| Required Klints fields per workflow | In Progress | **DONE** — `data_contract.required_fields` | — |
| Studio dashboard | Completed | **DONE** — `/workflow` | — |
| Platform-neutral then SM guide tabs | Completed | **DONE** | — |
| Export human PDF + machine JSON + MCP action object | Completed | **PARTIAL** — JSON download yes; **no** Studio PDF; MCP action = **format string theater** | **W7-03** |
| Revenue Impact **AI** agent | Completed | **MISSING** as agent — DCS `revenue_impact` numbers only | **W7-04** |

### 4.4 WEEK 8 — QA + Handoff (sheet badly stale)

| Timeline task | Sheet | Code | Gap ID |
|---------------|-------|------|--------|
| QA Validation **AI** agents (data + workflow) | Not Started | **THEATER** if AI — **DONE** as rule hard-tests `qa_evaluators` / `compute_qa_score` | **W8-01** honesty |
| 3-way issue routing screen | Not Started | **DONE** (Slice E) — shared Data→Fix / Workflow→Studio / Security→Integrations via `routeIssueTarget` (no dedicated marketing screen · E0.8) | **W8-02** |
| Merchant sync health dashboard | Not Started | **DONE** (Slice E) — Integrations “Connector health”: last sync / lag / import issues (not continuous sync-health product; no fake webhook counts · E0.2–E0.4) | **W8-03** |
| QA score 0–100, pass ≥80 | Not Started | **DONE** — QA-01 | — *(update sheet)* |
| Route QA failures to right fix | Not Started | **DONE** (Slice E) — `/qa` FAIL CTAs via `qaFailDeepLink` (Fix / Studio / import; never invent check ids · E0.7) | **W8-04** |
| QA Validation Studio dashboard | Not Started | **DONE** — `/qa` | — *(update sheet)* |
| Agent Handoff **AI** agent | Not Started | **THEATER** if AI — **DONE** deterministic HO-01 stage | **W8-05** honesty |
| Handoff Center dashboard | Not Started | **DONE** — `/handoff` HO-01+02 | — *(update sheet)* |
| Stable external API for CRM/agency | Not Started | **MISSING** — tenant JWT `/api/v1` only | **W8-06** (defer M3) |
| Send + approval | (implied Week 8) | **DONE** HO-02 human path | — |

### 4.5 WEEK 9 — Demo / MCP schema / tests

| Timeline task | Sheet | Code | Gap ID |
|---------------|-------|------|--------|
| Continuous connector recheck + impact | Completed? | **MISSING** as continuous pipeline | **W9-01** |
| MCP action object schema · signed · traceable · preconditions | Not Started | **MISSING** runtime — pack label only | **W9-02** (= Slice D / B) |
| Demo env ~5k contacts DCS ~62 | Not Started | **DONE (Slice F)** — offline seed REMEDIATE mid-band (~61; ~62 not hard AC) · `seed_demo_tenant` | **W9-03** |
| Investor + DP demo paths | Not Started | **DONE (Slice F)** — markdown demo path + reset (`GAP_01F_DEMO_PATH.md`); not in-app tour | **W9-04** |
| `seed_demo_tenant` command | Not Started | **DONE (Slice F)** — offline identity + corpus + DCS · `verify_gap01f_backend.py` | **W9-05** |
| Full E2E integration tests | Not Started | **PARTIAL** — module tests only | **W9-06** |
| Perf score 50k / &lt;60s | Not Started | **MISSING** | **W9-07** (defer) |

---

## 5. Implementation slices (code specs)

### Slice A — Approval / ORCH 8-state (P0 · Contract C1)

**Decision lock (Engineering must confirm in PR body):**

```text
Option A1 (pack-aligned): Implement OrchestrationTask model + SM matching
  pack orchestration_task.schema.json status enum (8 values).
Option A2 (timeline-aligned): Implement CDUC ChangeSet SM
  proposed → preview → awaiting_approval → approved → synced → failed → rolled_back
  (+ optional 8th if product requires).
Option A3 (claim mapping): Document existing handoff 4 + writeback statuses
  as “approval surfaces” and get client waiver for literal 8-state — NO code.
```

**If building A1 (recommended for pack/contract alignment):**

| Deliverable | Detail |
|-------------|--------|
| Model | `OrchestrationTask` (or equivalent) with pack-required fields |
| Transitions | Allowed graph for the 8 statuses; audit each transition |
| API | CRUD/transition endpoints company-scoped |
| FE | Minimal task list + status chip on Studio or Overview (one surface) |
| Tests | Transition matrix + forbidden jumps |
| Verify | `scripts/verify_orch_sm_01_backend.py` |

**Do not** claim CDUC dashboard done unless W5-03/W5-06 also ship.

**Code refs to extend:**  
`dataruns/use_cases/` · pack `orchestration_task.schema.json` · existing `WritebackApprovalToken` pattern (mirror, don’t overload).

---

### Slice B — Track B MCP/A2A prototype (P0 · Contract C2 / AC-A)

**Pack rule:** MCP stays `DISCOVERY_REQUIRED` until evidence stored. Read discovery **before** any write.

| Step | Deliverable |
|------|-------------|
| B0 | Client dependency: Manago MCP/A2A beta access (contract §6.1) — **blocked without this** |
| B1 | Persist discovery run results into pack-shaped evidence (update `manago_mcp_discovery_results.json` or DB evidence table) |
| B2 | Thin MCP client: **LIST** workflows (or documented read tool) for one tenant |
| B3 | Prototype path for **one** UC (prefer UC-02): show live list result in Studio/Handoff capability panel |
| B4 | **Only if** discovery proves write tools: sandbox UPSERT on non-prod workflow — never invent |
| B5 | E2E demo script (code/test) for “Track B prototype with one workflow” — still may be read-only |

**Stop-and-flag** if no public/MCP tool for workflow create — keep HO-02 human path; request **waiver** for AC-A.

**Code refs:**  
`dataruns/capabilities/` · `matrix_seed.json` · `manago_mcp_discovery_results.json` · HO-02 must stay honest (`HUMAN_MANAGO_UI` until B4 proven).

---

### Slice C — Writeback / CDUC honesty (P1 · Weeks 5–6)

| Gap ID | Ship |
|--------|------|
| W6-03 | Either implement true auto-rollback Celery for **failed-after-partial-write** **or** change product copy / sheet to “stale executing reclaim only” |
| W5-01 | Rejected writeback → edit evidence/mapping → new preview → approve |
| W5-05 / W5-06 | Optional: Change Preview drawer with before/after + “workflows unblocked” estimate |
| W6-01 / W6-02 | Document irreversible ops; implement Shopify metafield rollback **or** keep note-only and sheet-honest |

**Code refs:**  
`dataruns/writebacks/run_gate.py` · `rollback.py` · `adapters/manago.py` · `adapters/shopify.py` · FE `fix.tsx`.

---

### Slice D — MCP action object honesty (P1 · Pack / Week 7–9)

| Gap ID | Ship |
|--------|------|
| W7-03 / W9-02 | **DONE (Option 2)** — runtime/API `HANDOFF_PACKAGE_SPEC` until Track B; pack JSON left; serialize normalize on GET/Download |
| W7-01 / W8-01 / W8-05 | **DONE** — FE copy: rule engine / package builder / Handoff (not AI agent) + W6-04 Lifecycle rule-based |

---

### Slice E — Week 8 residual screens (P2)

| Gap ID | Ship |
|--------|------|
| W8-02 | One screen/flow: Data issue → Fix; Workflow issue → Studio; Security → Integrations revoke — **Slice E shipped** (FE `routeIssueTarget` / E0.5–E0.8) |
| W8-03 | Merchant sync health: last sync, lag, webhook/error counts (may extend Integrations) — **Slice E shipped** (Integrations; import issues not webhook counts · E0.2–E0.4) |
| W8-04 | QA FAIL deep-link matrix (field miss → Fix; logic → Studio; stale → trigger import) — **Slice E shipped** (`qaFailDeepLink` · E0.7) |

---

### Slice F — Week 9 demo seed (P2)

| Gap ID | Ship |
|--------|------|
| W9-05 | `python manage.py seed_demo_tenant --vertical=skincare` |
| W9-03 | Seed ~scale contacts + fixtures aiming DCS mid-band (sheet “~62” is target, not hard AC) |
| W9-04 | Document reset + demo path routes (connect→score→fix→studio→qa→handoff) |

**Verify:** `python scripts/verify_gap01f_backend.py` · `--run-tests` for Phase 1–2 Django (small-N seed + REMEDIATE).

**Defer:** W9-07 perf 50k; W8-06 partner API.

---

## 6. Theater / overclaim register (do not re-claim)

| Claimed as | Actually | Action |
|------------|----------|--------|
| Lifecycle Architect AI | AF-01 rules | **DONE** Slice D — rule-based copy |
| Blueprint / QA / Handoff AI agents | Deterministic engines | **DONE** Slice D — rename |
| Auto-rollback 15 min | Stale executing reclaim | Fix or reword |
| MCP action object / MCP Send | Label + human HO-02 | **DONE** Slice D Option 2 (`HANDOFF_PACKAGE_SPEC`); Track B still open for live MCP |
| CDUC dashboard | Fix writeback tab | Slice C or reword sheet |
| Week 8 QA/Handoff Not Started | Live on main | **Update sheet to Completed** |

---

## 7. Expected data models (Slice A sketch)

### 7.1 Pack-aligned `OrchestrationTask` (A1)

| Field | Type | Notes |
|-------|------|--------|
| `id` / `task_id` | UUID | |
| `company` | FK | tenant isolation |
| `task_type` | enum | CONNECT…HANDOFF (pack) |
| `status` | enum | 8 pack statuses |
| `depends_on` | JSON list | task ids |
| `priority_score` / `priority_inputs` | as pack | may link ORCH-01 |
| `capability_dependencies` | JSON | Matrix ids |
| `approval` | JSON | roles / refs |
| `idempotency_key` | char | unique per company |
| `payload` / `provenance` | JSON | pack shape |

Transitions (minimum):

```text
PENDING → READY | BLOCKED | CANCELLED
BLOCKED → READY | CANCELLED
READY → IN_PROGRESS | CANCELLED
IN_PROGRESS → AWAITING_APPROVAL | DONE | FAILED
AWAITING_APPROVAL → IN_PROGRESS | DONE | FAILED | CANCELLED
FAILED → READY (retry) | CANCELLED
DONE, CANCELLED terminal
```

### 7.2 CDUC ChangeSet (A2 / W5) — only if chosen

Mirror writeback job + approval into explicit ChangeSet with timeline 8 states; FE CDUC dashboard. Prefer **not** duplicating writeback pipeline — wrap it.

---

## 8. APIs (Slice A1 sketch)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/orchestration/tasks/` | List company tasks |
| `POST` | `/api/v1/orchestration/tasks/` | Create |
| `POST` | `/api/v1/orchestration/tasks/{id}/transition/` | `{ "to_status", "reason?" }` |
| `GET` | `/api/v1/orchestration/tasks/{id}/` | Detail |

Errors: `invalid_transition` 409 · `forbidden` 403 · company 404.

---

## 9. Acceptance (this PRD)

### 9.1 Documentation acceptance (immediate)

- [ ] Sheet Weeks 5–9 updated to match §4 (DONE/PARTIAL/MISSING) — stop false Completed  
- [ ] Client informed: HO-02 = human Send; Matrix delivered; Track B + literal 8-state still open **or** waiver requested  

### 9.2 Code acceptance (per slice)

| Slice | Done when |
|-------|-----------|
| A | Chosen option shipped + verify script green **or** written waiver filed |
| B | Discovery evidence stored + one-workflow prototype **or** waiver for AC-A |
| C | W6-03 resolved (code or honest copy) + tests |
| D | No MCP action theater in UI/API without runtime |
| E | W8-02 or W8-03 shipped if claimed in Week 8 — **Slice E: W8-02 + W8-03 + W8-04 shipped** (FE-first) |
| F | `seed_demo_tenant` runs on clean DB |

### 9.3 Not acceptance

- Loom alone without code/waiver for C1/C2  
- Flipping Matrix MCP to `CONFIRMED_LIVE` without discovery file evidence  
- Claiming Week 9 perf without harness  

---

## 10. Code reference map

| Area | Path |
|------|------|
| Audit hash / immutability | `dataruns/audit.py` · `migrations/0030_*` |
| Writeback pipeline | `dataruns/writebacks/` |
| Stale 15m reclaim (not auto-rollback) | `dataruns/writebacks/run_gate.py` |
| Handoff 4-state + HO-02 | `dataruns/use_cases/handoff_*.py` · FE `handoff.tsx` |
| QA 0–100 / 80 | `dataruns/use_cases/qa_*.py` · FE `qa.tsx` |
| Studio package | `dataruns/use_cases/build_package.py` · FE `WorkflowStudio.tsx` |
| AF lifecycle 16×7 | `dataruns/architecture/` · FE `lifecycle.tsx` |
| Capability Matrix | `dataruns/capabilities/` |
| Pack ORCH schema | `Klints_MVP1_Rohan_Build_Pack_v1.2_20260718/03_Machine_Contracts/orchestration_task.schema.json` |
| Pack MCP discovery | `…/02_Execution_Capabilities/manago_mcp_discovery_results.json` |
| AI tasks (only 4) | `dataruns/ai/constants.py` |

---

## 11. Branch / PR hygiene

- Branch per slice: `feature/gap01-slice-a-orch-sm` · `feature/gap01-slice-b-track-b` · …  
- PR title: `feat(GAP-01A): …`  
- PR body must state: Option A1/A2/A3 · waiver status · no Matrix silent flip  

---

## 12. Traceability

| Field | Value |
|-------|--------|
| Milestone | M2 T2 — code honesty + remaining AC |
| Parents | HO-02 · QA-01 · CAP-01 · WF-01 · WB-03…07 · AF-01 |
| Pack | v1.2 Build Pack · ORCH schema · MCP discovery PENDING |
| Contract | Schedule 1 M2 bundle + AC |
| Timeline | Weeks 5–9 task list (NV CX sheet) |
| Next after gaps | Claim packet / Schedule 2 deposit (ops) · M3 |
| Independent of | Engineering WB-08 · closed Engineering PRs #69/#46 |

---

## 13. One-page summary for Engineering

```text
DONE enough: Studio, QA≥80, Handoff STAGED, HO-02 human Send+approval,
             Matrix seed, writeback trio + audit hash, AF lifecycle UI.

MISSING for literal M2: 8-state SM (C1), Track B MCP/A2A (C2).

OVERCLAIMED on sheet: CDUC, auto-rollback 15m, AI agents, MCP action object,
                      Week 8 “Not Started” (actually largely live).

YOU BUILD NEXT: Slice A then B (or get waiver) → C/D honesty → F demo seed.
SKIP: WB-08, partner API, 50k perf, inventing MCP publish.
```
