# HO-01 Working / Gaps (PRD-HO-01)

**PRD:** `PRD_HO_01_HANDOFF_PACKAGE_BIND.md`  
**Branch intent:** `feature/ho-01-handoff-package-bind`  
**Scope:** Staged handoff package after QA PASS + live `/handoff` bind (no MCP Send).

---

## Step progress

| Step | Status | Notes |
|------|--------|-------|
| 0 Preconditions | Done | Pilots 16 / UC-02 package / QA PASS verified |
| 1 Schema field lock | **Done** | `dataruns/use_cases/handoff_package.py` |
| 2 Model + migration | **Done** | `HandoffPackage` + `0028_handoff_package` |
| 3 Create service (auto + POST) | **Done** | `handoff_stage.py` + QA PASS hook + audit |
| 4 Read/create APIs | **Done** | GET/POST handoff routes + serialize; invalid UUID → 400 |
| 5 Audit wire | **Done** | §7 lock + create-only; dedicated step5 tests |
| 6 BE create tests | **Done** | PRD §8 BE matrix sign-off (step6); recheck fixes applied |
| 7 FE live bind (API) | **Done** | `lib/handoff.ts` + `/handoff` live GET/POST; no fixture primary |
| 8 FE live STAGED UI | **Done** | §6.3 title/UC/QA/route/human-guide + Manago copy |
| 9 Empty / blocked states | **Done** | Proactive QA gate + blocked/retry states |
| 10 Send locked | **Done** | `HandoffSendLockedButton` + verify:ho01 |
| 11 Acceptance (§9) | **Done** | Demo path + verify scripts + PRD checkoff |
| 12 PR | **Ready** | Manual commit/PR — see §Step 12 below (split BE/FE repos) |

---

## Step 1 — locked contract

**Pack SoT:** `handoff_package.schema.json` (`schema_version` = `1.0.0`)

| Field | Lock |
|-------|------|
| `status` | HO-01 emits **`STAGED` only**; map `STAGED_NOT_LIVE` → `STAGED` |
| `manifest_hash` | sha256 hex via `stable_json` (`^[a-f0-9]{64}$`) |
| `artifact_refs` | ≥1; always includes build `package_id` |
| `approval_ref` | writeback id → else `HUMAN_FALLBACK` if route is → else `NOT_REQUIRED_FOR_STAGED` |
| `qa_ref` | QA run id |
| `package_version` | short package content hash / version string |
| `provenance` | `source_versions`, `created_at`, `created_by` |
| Body extras | **Forbidden** (`additionalProperties: false`) |
| FE siblings | load via package/QA APIs, not stuffed into schema body |

**Tests:** `dataruns.tests.test_handoff_package_step1`

---

## Step 2 — model

**Table:** `handoff_packages` (`0028_handoff_package`)

| Column / constraint | Notes |
|---------------------|-------|
| `id` (UUID PK) | = `handoff_id` |
| `company`, `package`, `qa_result` | FKs; `qa_result` required |
| Unique | `(company, package, qa_result)` |

**Tests:** `dataruns.tests.test_handoff_package_step2`

---

## Step 3 — create / stage service

**Module:** `dataruns/use_cases/handoff_stage.py`

| API | Behavior |
|-----|----------|
| `create_or_get_staged_handoff(package, qa_result, created_by)` | PASS only; idempotent; audit once on create |
| `stage_handoff_for_package(package, qa_run_id=?)` | POST helper — latest QA or explicit id |
| QA hook | `run_qa_for_package` auto-stages when overall **PASS** (same txn) |

**Error codes (409):** `qa_missing` · `qa_not_pass` · `qa_package_mismatch` · `qa_company_mismatch`

**Tests:** `dataruns.tests.test_handoff_package_step3` (12 cases; IntegrityError race handled; atomic create)

---

## Step 4 — HTTP APIs

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/handoffs/{handoff_id}/` | Detail |
| GET | `/api/v1/build-packages/{package_id}/handoff/` | Latest for package |
| GET | `/api/v1/handoffs/?package_id=&qa_run_id=` | List/filter (cap 100) |
| POST | `/api/v1/build-packages/{package_id}/handoff/` | Stage; 201 create / 200 idempotent |

**Roles:** read Admin/Analyst/Viewer · POST create Admin/Analyst  
**Serialize:** pack body + FE siblings (`use_case_id`, `package_id`, `qa_run_id`, title/route/qa_*); identity fields forced from DB columns  
**Validation:** invalid `package_id` / `qa_run_id` query or POST body → **400** (`invalid_package_id` / `invalid_qa_run_id`)  
**Wiring:** `handoffs_urls.py` · `build_packages_urls.py` (`…/handoff/` before detail) · `core/urls.py`

**Tests:** `dataruns.tests.test_handoff_package_step4` (12 cases)

---

## Step 5 — audit wire (PRD §7)

| Lock | Value |
|------|--------|
| `action` | `workflow.handoff_staged` |
| Metadata keys | `handoff_id`, `package_id`, `qa_run_id`, `use_case_id`, `status=STAGED` |
| When | **Create only** (idempotent re-get / race loser / GET → no new audit) |
| Paths | Direct stage · QA PASS auto-stage · HTTP POST |
| Actor | `performed_by` email or `system`; `actor_user_id` when user present |

**Builder:** `build_handoff_staged_audit_metadata` in `handoff_package.py`  
**Emitter:** `create_or_get_staged_handoff` only  

**Tests:** `dataruns.tests.test_handoff_package_step5`

---

## Step 6 — BE case matrix (PRD §8 backend)

Authoritative BE sign-off before FE. FE §8 rows (live `/handoff`, Send) → Steps 7–10.

| §8 / gate | Expect | Status |
|-----------|--------|--------|
| QA PASS → handoff (auto) | STAGED schema-shaped + GET 200 | Pass |
| QA PASS → handoff (POST) | 201 STAGED | Pass |
| Second create same package+qa | 200 same id | Pass |
| QA FAIL → POST | 409 `qa_not_pass` | Pass |
| GET other company | 404 (detail/package); list empty | Pass |
| GET by id / package id | 200 tenant-scoped | Pass |
| Audit on create only | `workflow.handoff_staged` §7 keys | Pass |
| Roles | Admin/Analyst create; Viewer read | Pass |
| Unauthenticated | 401 | Pass |
| UC-02 BE journey | package → QA PASS → GET handoff APIs | Pass |
| QA auto-stage failure | maps to HTTP 409 (not 500); txn rolls back | Pass |
| Serialize provenance | `created_at` aligned with column | Pass |

**Tests:** `dataruns.tests.test_handoff_package_step6`

---

## Step 7 — FE live bind

| Piece | Path / behavior |
|-------|-----------------|
| Client | `klints_frontend/src/lib/handoff.ts` — GET latest / list by qa_run_id / POST stage / classifiers |
| Route | `src/routes/handoff.tsx` — deep-link fetch; auto-POST if never staged; Preparing… state |
| Primary | **No** `getHandoffForIssue` fixtures |
| Empty (no `package_id`) | Link Studio + QA |
| Send | Disabled + honest title (HO-02 later) |
| Recheck | `qa_run_id` respected; live QA id from API; 403 staging copy; status banner honest |

---

## Step 8 — live STAGED UI (PRD §6.3)

| Surface | Behavior |
|---------|----------|
| Title / UC | Handoff title → else build-package title → else `UC-xx · staged handoff` |
| Status | Live `STAGED` chip + honest Manago / MCP banner |
| QA | Score + PASS/Cleared; link back to `/qa` |
| Route | Capability summary; `HUMAN_FALLBACK` called out as supported |
| Human guide | First 4 step titles from build package + Studio link |
| Delivery | Send disabled (no MCP) |

Helpers: `handoffRouteSummary`, `humanGuideStepTitles`, `handoffQaSummary` in `lib/handoff.ts`  
**Recheck:** guide loading/error honesty; QA chip/badge not green on non-PASS; qa summary empty-state copy

---

## Step 9 — empty / blocked states (PRD §6.4)

| Condition | UI |
|-----------|-----|
| No `package_id` | “Generate a package and pass QA first” → Studio + QA |
| QA not PASS / never run | Proactive GET QA (latest or `qa_run_id`); “Clear QA first” + `FLOW_STEPPER_TOOLTIPS.handoffQaLocked` + score chip → `/qa` |
| QA PASS, handoff missing | “Checking QA gate…” then “Preparing staged handoff…”; auto-POST when gate open |
| Stage failed (non-QA) | Retry staging + Refresh + Go to QA |
| Stale handoff + latest QA FAIL | Hidden — blocked state wins (FlowStepper parity) |

Route: `src/routes/handoff.tsx` — `HandoffQaBlockedEmpty`; QA query before auto-stage; no toast on 409 QA block

**Recheck:** QA gate opens only on confirmed PASS + package match (`qaResultMatchesPackage`); unknown QA errors block auto-stage; invalid/mismatched `qa_run_id` gets honest blocked copy; no live handoff flash before QA resolves; stale auto-stage guard cleared on remount; `check` param preserved in journey links; older staged handoff hidden when latest QA PASS is a different run (`handoffMatchesGateQa`)

---

## Step 10 — Send locked (PRD §6.3 / §8)

| Lock | Implementation |
|------|----------------|
| Send / Send all | `HandoffSendLockedButton` — `disabled` + `aria-disabled` + `title` on wrapper span |
| Title SoT | `HANDOFF_SEND_DISABLED_TITLE` in `lib/handoff.ts` |
| Delivery copy | `HANDOFF_SEND_LOCKED_HINT` — no fake “Sent” toast |
| Network | No send/activate API client; staging POST only |
| Verify | `npm run verify:ho01` — Steps 7–10 static sweep |

Component: `src/components/klints/HandoffSendLocked.tsx`  
Surfaces: PageTitle header action + Delivery card (Send + Send all)

**Recheck:** `title` on wrapper span (disabled buttons skip native tooltips); `aria-label` on button; `flow-cta locked` on Send-all variant

---

## Demo path — UC-02 (happy)

1. Fix / Opportunities → Workflow Studio `?uc=UC-02` (optionally `&issue=CC-03`).
2. Generate build package → note `package_id`.
3. Studio CTA → `/qa?uc=UC-02&package_id=…`.
4. `/qa` auto-runs or shows PASS (7 hard tests · score ≥ gate).
5. **Continue to Handoff** → `/handoff?package_id=…&qa_run_id=…` (FlowStepper unlocked).
6. `/handoff` checks QA gate → GET/POST stage if needed → **live STAGED** view (not fixtures).
7. Send / Send all disabled with honest Manago copy — no “Sent” toast.

**BE journey test:** `test_uc02_be_journey_studio_qa_pass_to_handoff_apis` in `test_handoff_package_step6`.

---

## Step 11 — §9 Acceptance

| §9 item | Evidence |
|---------|----------|
| Staged `handoff_package` after QA PASS | `handoff_stage.py` · auto on QA PASS · `test_s8_qa_pass_auto_creates_staged_handoff` |
| GET by handoff id / package id (tenant-scoped) | step4/6 HTTP tests · `getHandoff` / `getLatestPackageHandoff` |
| `/handoff?package_id=&qa_run_id=` live (no fixtures) | `handoff.tsx` · `fetchHandoffForDeepLink` · no `getHandoffForIssue(` |
| Send disabled + honest copy | `HandoffSendLockedButton` · `HANDOFF_SEND_DISABLED_TITLE` |
| Empty / QA-locked states honest | `HandoffQaBlockedEmpty` · proactive QA gate (Step 9) |
| Audit `workflow.handoff_staged` | step5 tests · create-only metadata §7 |
| UC-02 Studio → QA PASS → Handoff → live STAGED | Demo path above · BE `test_uc02_be_journey_*` · QA `handoffFromQa` CTA |

**Verify scripts**

| Script | Command |
|--------|---------|
| FE Steps 7–11 | `npm run verify:ho01` (klints_frontend) |
| BE §9 static (+ optional tests) | `python scripts/verify_ho01_backend.py` · `--run-tests` when Django env ready |

**Test modules (59 cases):** `test_handoff_package_step1` (9) … `step6` (12)

**Deep-check recheck (Steps 1–12):** BE `serialize_handoff` title cascade + always `qa_status`; POST uses warmed `outcome.record`; explicit `qa_run_id` returns `qa_package_mismatch` when wrong package; FE handoff fetch gated on `qaGateOpen`; gate QA merged into STAGED chip; malformed list no false auto-stage; stale handoff from prior QA run triggers re-stage instead of wrong live view

---

## Step 12 — PR (manual)

HO-01 spans **two git repos** (`klints_backend`, `klints_frontend`). Do not commit from the parent `Klints/` folder (no commits there).

### Pre-flight

```bash
# Backend (klints_backend)
python scripts/verify_ho01_backend.py
# Optional when Django env ready:
python scripts/verify_ho01_backend.py --run-tests

# Frontend (klints_frontend)
npm run verify:ho01
```

### Branch (both repos)

`feature/ho-01-handoff-package-bind` → base `main`

### What to commit

| Repo | Already on `main`? | Still to commit |
|------|-------------------|-----------------|
| **klints_backend** | BE Steps 1–6 (`feat(HO-01): staged handoff package APIs…`) | `docs/engineering/HO_01_WORKING_GAPS.md`, `docs/engineering/PRD_HO_01_HANDOFF_PACKAGE_BIND.md`, `scripts/verify_ho01_backend.py` |
| **klints_frontend** | Fixture `/handoff` only | `src/lib/handoff.ts`, `src/routes/handoff.tsx`, `src/lib/qa.ts`, `src/components/klints/HandoffSendLocked.tsx`, `scripts/verify-ho01-frontend.mjs`, `package.json` (`verify:ho01`) |

### Suggested PR titles

| Repo | Title |
|------|-------|
| Backend | `docs(HO-01): acceptance checklist + verify_ho01_backend` |
| Frontend | `feat(HO-01): live /handoff bind + STAGED UI (no MCP Send)` |

PRD §11 default title covers the **frontend** deliverable; backend PR is a small docs/verify follow-up.

### FE PR body (copy)

- Live `/handoff` after QA PASS — no fixture primary
- STAGED UI (§6.3), blocked states (§6.4), Send locked (Step 10)
- Test: `npm run verify:ho01` + UC-02 demo path above

---

## Gaps / defer

| Item | Status |
|------|--------|
| MCP Send / ACTIVATED | HO-02 |

---

## PR note (draft)

**Right:** HO-01 complete for M2 Handoff half — staged `handoff_package` after QA PASS (BE auto + POST), tenant-scoped GET APIs, audit `workflow.handoff_staged`, live `/handoff` with STAGED UI, honest empty/QA-locked states, Send locked (no MCP). UC-02 path: Studio → QA PASS → Continue to Handoff → live staged view.

**Gap:** MCP Send / `ACTIVATED` = HO-02. Optional: wire `verify_ho01_backend.py --run-tests` into CI when Django image available. Step 12 PRs are manual (see WORKING_GAPS §Step 12).
