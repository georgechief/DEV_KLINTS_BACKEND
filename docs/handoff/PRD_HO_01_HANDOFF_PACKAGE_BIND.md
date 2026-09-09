# PRD-HO-01 — Handoff package bind (staged · live page · no fake Send)

**Status:** In progress — **P0 (M2 Handoff half)** · Steps 0–11 done; Step 12 PR ready (manual commit)  
**Owner track:** Engineering  — **BE + FE**  
**Surfaces:** `/handoff` · QA “Continue to Handoff” · FlowStepper Handoff · build-package APIs  
**Milestone:** M2 Activation & Blueprint (T2) — contract row **QA + Handoff live**; QA-01 shipped QA; **this PRD ships Handoff bind + staged package**  
**Depends on:**  
- **QA-01 / BL-018** — latest QA PASS for package  
- **WF-01** — `WorkflowBuildPackage` + `handoff_stub`  
- **OPS-UC-01** — pilots seeded (otherwise no package to hand off)  
**Pack SoT:** `03_Machine_Contracts/handoff_package.schema.json` · blueprint `handoff` block  
**Design SoT:** existing `/handoff` chrome — **replace fixture body** with live package; keep visual language  
**Out of scope:** Live MCP/A2A **Send** to Manago · Capability Matrix resolver (**CAP-01**) · Engineering writebacks · BL-012 waves · BL-017 8-state ORCH · force-PASS QA  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-HO-01 — live Handoff page bound to QA-passed build package.

Read:
- docs/engineering/PRD_HO_01_HANDOFF_PACKAGE_BIND.md
- docs/engineering/PRD_QA_01_WORKFLOW_QA_GATE_ENGINE.md (§ Handoff CTA)
- Pack: handoff_package.schema.json
- BE: dataruns/use_cases/build_package.py (handoff_stub)
- FE: src/routes/handoff.tsx, qa.tsx Continue to Handoff

Ship:
1. BE: on QA PASS (or explicit POST), create/persist staged HandoffPackage
   schema-shaped record linked to package_id + qa_run_id (§4).
2. GET handoff by id and/or by package_id / qa_run_id (§5).
3. FE /handoff?package_id=&qa_run_id=&uc=&issue= shows LIVE package
   (not getHandoffForIssue fixtures) (§6).
4. Send / Send all remain disabled — honest “activation stays human in Manago”
   OR “STAGED — MCP Send later” (§6.3).
5. Empty states: no package / QA not PASS (§6.4).
6. Audit on create (§7).

Acceptance: §9.
```

---

## 1. Why

| Surface | Today |
|---------|--------|
| QA PASS | Unlocks Handoff CTA + stepper (QA-01) ✓ |
| `/handoff?…` | Still **`getHandoffForIssue` fixtures** · ignores `package_id` / `qa_run_id` |
| Pack | `handoff_package.schema.json` — **no runtime producer** |
| Build package | `handoff_stub` with `STAGED_NOT_LIVE` only |

M2 needs an honest **Handoff stage**: operator sees the **real staged package** after QA, not demo rows. **MCP Send** can stay deferred if activation is explicitly **human in Manago**.

---

## 2. Product decision (locked for this PRD)

```text
Handoff = STAGED package after QA PASS
Send via MCP/A2A = NOT in this PRD (buttons disabled, honest copy)
Activation = human builds/activates in Manago from the staged brief
```

Status on persisted package: prefer pack enum **`STAGED`** (map blueprint `STAGED_NOT_LIVE` → `STAGED`).

Do **not** toast “Sent” or “Delivered to agent.”

---

## 3. Vocabulary

| Term | Meaning |
|------|---------|
| **Build package** | WF-01 `WorkflowBuildPackage` |
| **QA run** | `WorkflowQaResult` with `status=PASS` |
| **Handoff package** | New persisted record validating against pack schema (pragmatic subset OK — §4) |
| **Deep-link** | `/handoff?uc=&package_id=&qa_run_id=&issue=` from QA CTA |

---

## 4. Backend — create staged handoff

### 4.1 When to create

**Preferred:** Automatically when QA run overall status becomes **PASS** (same transaction/service as QA persist), idempotent:

```text
IF latest QA for package is PASS
  AND no HandoffPackage exists for (company, package_id, qa_run_id)
THEN create HandoffPackage status=STAGED
```

**Also allow:** `POST /api/v1/build-packages/{package_id}/handoff/` when latest QA is PASS (409 if QA FAIL / missing).

### 4.2 Minimum payload fields (align to schema)

| Field | Source |
|-------|--------|
| `schema_version` | `1.0.0` |
| `handoff_id` | UUID |
| `tenant_id` | company/tenant id string |
| `package_version` | build package version / content hash short |
| `artifact_refs` | `[build_package_id, …]` (+ human_guide / agent_spec refs if ids exist) |
| `qa_ref` | `qa_run_id` |
| `approval_ref` | optional: `"HUMAN_FALLBACK"` or writeback approval id if present; else `"NOT_REQUIRED_FOR_STAGED"` documented |
| `manifest_hash` | sha256 of canonical package body (stable_json) |
| `status` | `STAGED` |
| `created_at` / `provenance` | actor + timestamps + source_versions from package |

Store FK: `company`, `build_package`, `qa_result` (nullable only if create-from-POST validates separately).

### 4.3 Idempotency

Same `(company, package_id, qa_run_id)` → return existing row (200), do not duplicate.

---

## 5. Backend — read APIs

| Method | Path | Behavior |
|--------|------|----------|
| GET | `/api/v1/handoffs/{handoff_id}/` | Full handoff package JSON |
| GET | `/api/v1/build-packages/{package_id}/handoff/` | Latest handoff for package (404 if none) |
| GET | `/api/v1/handoffs/?package_id=&qa_run_id=` | Optional list/filter for FE |

**404** if wrong company. Roles: Admin / Analyst / Viewer read; create = Admin / Analyst (match QA/build).

---

## 6. Frontend — `/handoff`

### 6.1 Search params (keep QA-01)

```text
uc, package_id, qa_run_id, issue
```

### 6.2 Data bind

| Priority | Source |
|----------|--------|
| 1 | If `package_id` (and optional `qa_run_id`) → **GET live handoff / package** |
| 2 | Else empty-state (do **not** fall back to fixture as primary) |

Remove `getHandoffForIssue` as the primary body for deep-linked journeys. Fixtures may remain only behind an explicit demo flag / non-prod — default **off**.

### 6.3 UI content (live)

Show from live package / build package:

- Title / UC id  
- Status **STAGED**  
- QA ref (score / PASS)  
- Route / capability resolution summary from build package (`HUMAN_FALLBACK` OK)  
- Short human-guide excerpt or “Open in Workflow Studio” link  
- Copy: **Activation stays human in Manago** · MCP Send not live  

**Send** / **Send all**: `disabled` + `title` explaining not live. Never success toast.

### 6.4 Empty / blocked states

| Condition | UI |
|-----------|-----|
| No `package_id` | “Generate a package and pass QA first” → link Studio / QA |
| Package exists, QA not PASS | “Clear QA (≥80, all hard tests) first” → `/qa?…` |
| QA PASS but handoff missing | Trigger GET/POST create or show “Preparing staged handoff…” + retry |

### 6.5 FlowStepper

Unchanged rule from QA-01: Handoff enabled when latest QA PASS. Deep-link should include `package_id` + `qa_run_id` when known.

---

## 7. Audit

On create:

```text
action: workflow.handoff_staged
metadata: handoff_id, package_id, qa_run_id, use_case_id, status=STAGED
```

---

## 8. Tests

| Case | Expect |
|------|--------|
| QA PASS → handoff row exists (auto or POST) | 201/200 STAGED |
| Second create same package+qa | Idempotent same id |
| QA FAIL → POST handoff | 409 |
| GET other company handoff | 404 |
| FE with package_id | Renders live title/status; no fixture title |
| Send click | No network send; no success toast |

---

## 9. Acceptance

- [x] Staged `handoff_package`-shaped record after QA PASS  
- [x] GET by handoff id / package id works (tenant-scoped)  
- [x] `/handoff?package_id=&qa_run_id=` shows **live** package, not fixtures  
- [x] Send disabled + honest copy  
- [x] Empty/QA-locked states honest  
- [x] Audit `workflow.handoff_staged`  
- [x] UC-02 path: Studio → QA PASS → Continue to Handoff → live staged view  

---

## 10. Explicitly next PRD (not this one)

| Later | Why |
|-------|-----|
| **CAP-01** | Matrix-backed MCP vs human route |
| **HO-02** | Live MCP/A2A Send + `ACTIVATED` status |
| **E2E-01** | Loom + M2 submission doc |

---

## 11. PR title / branch

- Branch: `feature/ho-01-handoff-package-bind` (both `klints_backend` and `klints_frontend`)
- **Frontend PR title:** `feat(HO-01): live /handoff bind + STAGED UI (no MCP Send)`
- **Backend follow-up** (docs/verify only; APIs already on `main`): `docs(HO-01): acceptance checklist + verify_ho01_backend`
- Manual checklist: [HO_01_WORKING_GAPS.md](./HO_01_WORKING_GAPS.md) §Step 12

---

## 12. Traceability

| Item | Note |
|------|------|
| Contract | M2 — Handoff half after QA-01 |
| Pack | `handoff_package.schema.json` · BL-020 partial (staged, not full Lumera E2E) |
| Parents | QA-01 · WF-01 · WF-02 |
| Independent of | Engineering WB-04/05/06 |
