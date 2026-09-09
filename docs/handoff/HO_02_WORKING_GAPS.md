# HO-02 Working / Gaps (PRD-HO-02)

**PRD:** `PRD_HO_02_HANDOFF_SEND_HUMAN_ACTIVATION.md`  
**Branch intent:** `feature/ho-02-handoff-send-human-activation`  
**Scope:** Human Manago activation path — approve → guide → confirm (no MCP auto-send).

**Depends on:** HO-01 (STAGED bind live) · QA-01 · CAP-01 · WF-01 `human_guide`

---

## Phase progress

| Phase | Status | Notes |
|-------|--------|-------|
| 1 Schema + constants | **Done** | `activation_meta`, migration `0031`, transition matrix |
| 2 Activation services | **Done** | `handoff_activation.py` approve/reject/confirm |
| 3 HTTP APIs | **Done** | POST approve/reject/confirm-activated |
| 4 Frontend | **Done** | Live approve + guide + confirm; no fake MCP toast |
| 5 Acceptance + verify | **Done** | Audit deep-links, verify scripts, this doc |
| 6 PR | **Ready** | Manual commit/PR — see §Step 12 below |

---

## Phase 1 — schema + helpers

| Deliverable | Location |
|-------------|----------|
| `activation_meta` JSONField | `dataruns/use_cases/models.py` |
| Migration | `0031_handoffpackage_activation_meta.py` |
| Constants, meta builders, audit keys | `dataruns/use_cases/handoff_package.py` |

**Tests:** `test_handoff_ho02_phase1.py` (16)

---

## Phase 2 — services

| Service | Transition |
|---------|------------|
| `approve_handoff_for_activation` | STAGED → APPROVED_FOR_ACTIVATION |
| `reject_handoff` | → REJECTED |
| `confirm_handoff_activated` | APPROVED → ACTIVATED |

**Gates:** Admin-only · `manifest_hash` match · QA PASS on approve/confirm · `select_for_update()`

**Tests:** `test_handoff_ho02_phase2.py` (21)

---

## Phase 3 — HTTP APIs

| Method | Path |
|--------|------|
| POST | `/api/v1/handoffs/{id}/approve/` |
| POST | `/api/v1/handoffs/{id}/reject/` |
| POST | `/api/v1/handoffs/{id}/confirm-activated/` |

GET list/detail includes `activation_meta`, `activation_guide`, `capability` when approved/activated.

**Tests:** `test_handoff_ho02_phase3.py` (20)

---

## Phase 4 — frontend

| Requirement | Status |
|-------------|--------|
| STAGED + Admin → Approve for activation | Done |
| APPROVED → activation guide + Confirm | Done |
| ACTIVATED → success banner, Send disabled | Done |
| REJECTED → honest copy + QA/Studio links | Done |
| No “Sent via MCP” toast | Done |
| Optional `manago_workflow_external_id` on confirm | Done |
| Post-STAGE bypass QA gate for display | Done |
| `handoff_id` deep-link on `/handoff` | Done |

**Files:** `src/lib/handoff.ts` · `src/routes/handoff.tsx` · `HandoffSendLocked.tsx`

---

## Phase 5 — audit + verify + acceptance

### Audit (PRD §9, §7.3)

| Action | When |
|--------|------|
| `workflow.handoff_approved_for_activation` | approve success |
| `workflow.handoff_rejected` | reject |
| `workflow.handoff_activated` | confirm-activated |
| `workflow.handoff_staged` | HO-01 create (unchanged) |

**Deep-link:** `resolve_audit_href` → `/handoff?uc=&package_id=&handoff_id=&qa_run_id=`  
**FE mirror:** `resolveAuditDeepLink` in `src/lib/audit.ts`

### Verify scripts

| Repo | Command |
|------|---------|
| Backend | `python scripts/verify_ho02_backend.py` |
| Backend + tests | `python scripts/verify_ho02_backend.py --run-tests` |
| Full regression | `python scripts/verify_ho02_backend.py --run-tests --with-ho01-regression` |
| Frontend | `npm run verify:ho02` |

**HO-02 BE test total:** 57 (16 + 21 + 20) + audit deep-link tests in `test_audit.AuditDeepLinkTests`  
**HO-01 regression:** 59 handoff tests via `--with-ho01-regression` (109 total with HO-02)

### Demo path (manual staging — PRD §10)

1. UC-02 Ready → Generate → QA PASS → Handoff STAGED  
2. Admin **Approve for activation** → APPROVED_FOR_ACTIVATION + guide  
3. Build/activate in Manago using guide  
4. Admin **Confirm activated** → ACTIVATED  
5. Audit bell entries link to `/handoff`

---

## PRD §11 acceptance

| Criterion | Status |
|-----------|--------|
| Send/Approve for STAGED + role + manifest | Done |
| APPROVED → ACTIVATED via confirm | Done |
| Human Manago guide from `human_guide` | Done |
| No MCP publish network calls | Done |
| MCP.WORKFLOW.PUBLISH stays DISCOVERY_REQUIRED | Done |
| No fake Sent / Delivered to agent toast | Done |
| Audit actions recorded | Done |
| HO-01 STAGED path unchanged | Done |
| `verify_ho02_backend.py` + `npm run verify:ho02` | Done |

---

## Step 12 — PR (manual)

HO-02 spans **two git repos** (`klints_backend`, `klints_frontend`).

### Pre-flight

```bash
# Backend (klints_backend)
python scripts/verify_ho02_backend.py
python scripts/verify_ho02_backend.py --run-tests
python scripts/verify_ho02_backend.py --run-tests --with-ho01-regression
python scripts/verify_ho01_backend.py --run-tests   # alternate HO-01-only regression

# Frontend (klints_frontend)
npm run verify:ho02
npm run verify:ho01   # regression
```

### Branch (both repos)

`feature/ho-02-handoff-send-human-activation` → base `main`

### Suggested PR titles (PRD §14)

| Repo | Title |
|------|-------|
| Backend | `feat(HO-02): handoff approve + confirm activated (human Manago path)` |
| Frontend | `feat(HO-02): unlock Send with approval + activation guide` |

### FE PR body (copy)

- Admin approve → activation guide → confirm activated (human Manago path)
- No MCP auto-send or fake “Sent” toast
- Audit bell deep-links to `/handoff`
- Test: `npm run verify:ho02` + UC-02 demo path above

---

## Gaps / defer

| Item | Status |
|------|--------|
| MCP/A2A live workflow publish | CAP-01B / later |
| Reject button in UI | Backend only; optional admin ops |
| `agent_spec` collapse in guide panel | Optional §7.2 |
| E2E Loom (E2E-01) | Engineering lead |
| CI wire for `--run-tests` | When Django image available |

---

## PR note (draft)

**Right:** HO-02 complete for M2 contract AC “Send with approval gate” — human Manago activation path wired end-to-end. Admin approves STAGED handoff, UI shows `human_guide`, operator confirms after Manago activation. Audit + bell deep-link to `/handoff`. CAP honesty preserved (MCP publish DISCOVERY_REQUIRED).

**Gap:** No automated Manago workflow create/publish. Reject UI optional. Full ORCH 8-state machine deferred.
