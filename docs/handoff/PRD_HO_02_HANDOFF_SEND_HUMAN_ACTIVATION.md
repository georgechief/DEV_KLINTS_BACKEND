# PRD-HO-02 — Handoff Send with approval (human activation path)

**Status:** Ready for implementation — **P0 (M2 contract AC)**  
**Owner track:** Engineering  — **BE + FE**  
**Surfaces:** `/handoff` Send · approval gate · status `APPROVED_FOR_ACTIVATION` → `ACTIVATED` · audit/bell  
**Milestone:** M2 Activation & Blueprint (T2) — contract AC **“Send to Manago.ai functional with approval gate”**  
**Depends on:** HO-01 (STAGED handoff live) · QA-01 · CAP-01 (route honesty) · WF-01 build package `human_guide`  
**Pack SoT:**  
- `03_Machine_Contracts/handoff_package.schema.json` (status enum)  
- Capability Matrix **v1.1** sheet **05 Fallback Rules** — Workflow publish  
- `02_Execution_Capabilities/manago_mcp_discovery_results.json` (MCP still pending)  
- Blueprint `approval` + `handoff` blocks (e.g. `UC-02_blueprint.json`)  
**Contract SoT:** Schedule 1 M2 — *Send to Manago.ai functional with approval gate*  
**Out of scope:** MCP/A2A live workflow upsert/publish (no public REST create-workflow API; MCP `DISCOVERY_REQUIRED`) · inventing `CONFIRMED_LIVE` for `MCP.WORKFLOW.PUBLISH` · Engineering contact writebacks · full BL-017 8-state ORCH SM · Track B MCP discovery (CAP-01B) · E2E Loom (E2E-01 later)

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-HO-02 — Handoff Send with approval (human Manago activation).

Read:
- docs/engineering/PRD_HO_02_HANDOFF_SEND_HUMAN_ACTIVATION.md (this file)
- docs/engineering/PRD_HO_01_HANDOFF_PACKAGE_BIND.md
- Pack: handoff_package.schema.json · Matrix sheet 05 Fallback Rules (Workflow publish)
- BE: dataruns/use_cases/models.py HandoffPackage.Status
- BE: dataruns/use_cases/handoff_package.py (status constants already exist)
- BE: dataruns/use_cases/handoff_stage.py (STAGED only today)
- BE: dataruns/models.py WritebackApprovalToken (pattern to mirror — do NOT couple FK)
- FE: src/routes/handoff.tsx · src/lib/handoff.ts · HandoffSendLocked.tsx
- CAP: dataruns/capabilities/contract.py CAP_ID_MCP_WORKFLOW_PUBLISH

Ship:
1. State machine on HandoffPackage: STAGED → APPROVED_FOR_ACTIVATION → ACTIVATED
   (+ REJECTED optional) (§4).
2. Approval gate bound to handoff_id + manifest_hash (§5).
3. APIs: approve · reject · confirm-activated · (optional) request-approval (§6).
4. FE: unlock Send when eligible; no fake MCP toast; show human activation guide
   from build package human_guide (§7–8).
5. Audit + bell deep-links (§9).
6. CAP honesty: if MCP.WORKFLOW.PUBLISH still DISCOVERY_REQUIRED, Send = human path only (§3).

Acceptance: §11. Do NOT call undocumented Manago workflow-create REST.
Do NOT mark MCP PUBLISH live without discovery evidence.
```

---

## 1. Why (simple)

| Today (HO-01) | Gap |
|---------------|-----|
| Handoff shows **live STAGED** package after QA PASS | ✓ |
| Send buttons **disabled** (`HandoffSendLocked`) | Contract wants Send + approval |
| Pack: publish = **human in Manago UI** first | Need that path **wired**, not fake MCP |
| Public Manago REST: contact upsert / workflow **list/stats** only | No documented workflow-create API |

**HO-02** makes **Send** mean: approve in Klints → package marked ready for activation → operator activates in Manago using our guide → confirm → **ACTIVATED**.  
It does **not** invent automated workflow graph push until MCP is proven.

---

## 2. Product decision (locked)

```text
Send (MVP1 / this PRD) =
  1. Operator clicks Send (or Approve for activation)
  2. Approval gate passes (Admin / allowed role)
  3. Status → APPROVED_FOR_ACTIVATION
  4. UI shows human_guide steps + “Open Manago → build/activate this workflow”
  5. Operator confirms activation done (or optional later webhook)
  6. Status → ACTIVATED
  7. Audit each transition

NOT in this PRD =
  POST to Manago MCP.WORKFLOW.UPSERT / PUBLISH
  Toast “Sent via MCP” / “Delivered to agent”
  Contact writeback adapters (Engineering)
```

**Contract mapping:** “Send to Manago.ai functional with approval gate” = steps 1–4 functional in product + honest activation completion (5–6). Document in PR / submission that activation execution is **human in Manago** per pack Fallback Rules.

---

## 3. Capability / Manago reality (do not violate)

### 3.1 Pack Fallback Rules (sheet 05)

| Operation | Preferred | Fallback | MVP1 rule |
|-----------|-----------|----------|-----------|
| Workflow publish | **Human activation** | `MCP.WORKFLOW.PUBLISH` after confirmation | **No autonomous activation** |

### 3.2 Matrix seed (code)

| Capability ID | Status today | Implication |
|---------------|--------------|-------------|
| `MCP.WORKFLOW.PUBLISH` | `DISCOVERY_REQUIRED` | Must not auto-call |
| `MCP.WORKFLOW.UPSERT` | `DISCOVERY_REQUIRED` | Must not auto-call |
| `HUMAN.WORKFLOW.BUILD` | `CONFIRMED_LIVE` | Build path already used |
| `RESTV2.WORKFLOW.LIST` | `CONFIRMED_LIVE` | **READ only** — not publish |

Constants: `dataruns/capabilities/contract.py`  
Seed: `dataruns/capabilities/matrix_seed.json`  
Discovery: pack `manago_mcp_discovery_results.json` → `PENDING_EXECUTION`

### 3.3 Public Manago docs (external)

- Workflows created in **UI** ([support.manago.ai/workflow-first-steps](https://support.manago.ai/workflow-first-steps/))  
- REST: contacts, `/api/workflow/list`, `/api/workflow/statistics` — **no create/publish workflow graph** in public docs  

**Stop-and-flag** if someone proposes inventing REST workflow-create without Manago-written SoT.

---

## 4. State machine (data model)

### 4.1 Existing model (reuse — do not reinvent)

`dataruns.use_cases.models.HandoffPackage` already has:

```text
Status:
  STAGED
  APPROVED_FOR_ACTIVATION
  REJECTED
  ACTIVATED
```

HO-01 **only emits STAGED**. HO-02 **transitions** the same row.

Also already in `handoff_package.py`:

```python
HANDOFF_STATUS_STAGED
HANDOFF_STATUS_APPROVED_FOR_ACTIVATION
HANDOFF_STATUS_REJECTED
HANDOFF_STATUS_ACTIVATED
```

### 4.2 Allowed transitions

| From | To | Trigger |
|------|-----|---------|
| `STAGED` | `APPROVED_FOR_ACTIVATION` | Approve / Send with valid approval |
| `STAGED` | `REJECTED` | Reject (optional but recommended) |
| `APPROVED_FOR_ACTIVATION` | `ACTIVATED` | Confirm human activation |
| `APPROVED_FOR_ACTIVATION` | `REJECTED` | Reject before confirm |
| `REJECTED` | `STAGED` | **Forbidden** — create new handoff via new QA/package if needed |
| `ACTIVATED` | * | Terminal — no further Send |

Idempotent: approving already `APPROVED_FOR_ACTIVATION` → 200 same row.  
Confirm on already `ACTIVATED` → 200 same row.

### 4.3 Payload updates (JSON on `HandoffPackage.payload`)

Keep pack-required fields. On transitions, update:

| Field | On approve | On activate confirm |
|-------|------------|---------------------|
| `status` | `APPROVED_FOR_ACTIVATION` | `ACTIVATED` |
| `approval_ref` | activation approval token id (or `HUMAN_ACTIVATION_APPROVED:{uuid}`) | keep + add `activation_ref` in payload extension |
| `payload.activation` (extension) | see §4.4 | filled |

Pack schema `additionalProperties: false` on root — **prefer**:

1. Keep root pack fields strict in a `pack_body` key already used, **or**  
2. Store activation metadata in **DB columns / sibling JSON** `activation_meta` (migration) without breaking schema validation of pack body.

**Recommended (clean):** add nullable JSONField `activation_meta` on `HandoffPackage` (migration) so pack `payload` stays schema-valid.

### 4.4 `activation_meta` shape (expected)

```json
{
  "path": "HUMAN_MANAGO_UI",
  "capability_checked": "MCP.WORKFLOW.PUBLISH",
  "capability_status_at_send": "DISCOVERY_REQUIRED",
  "approved_at": "ISO-8601",
  "approved_by_user_id": "uuid",
  "approval_token_id": "uuid-or-null",
  "activated_at": "ISO-8601-or-null",
  "activated_by_user_id": "uuid-or-null",
  "manago_workflow_external_id": "optional-string-operator-pasted",
  "notes": "optional"
}
```

`path` locked for HO-02: always `HUMAN_MANAGO_UI` unless a **later** PRD flips MCP after discovery.

### 4.5 Optional: `HandoffActivationApproval` model

Mirror Engineering `WritebackApprovalToken` **pattern**, not the same table:

| Field | Type | Notes |
|-------|------|--------|
| `id` | UUID PK | |
| `company` | FK | |
| `handoff` | FK → `HandoffPackage` | |
| `manifest_hash` | char(64) | Must match handoff at approve time |
| `status` | PENDING \| APPROVED \| REJECTED \| EXPIRED \| CONSUMED | |
| `actor_user` / `approver_user` | FK User nullable | |
| `issued_at` / `expires_at` / `approved_at` / `consumed_at` | datetime | |
| `metadata` | JSON | roles, use_case_id |

**Simpler v1 (allowed):** single-step Admin approve without separate token table — store approval on `activation_meta` + require `User.Role.ADMIN` (or Admin+Analyst). Prefer token table if dual-control needed for demo.

Blueprint UC-02 says approval roles `CRM_OWNER`, `DATA_OWNER` — map pragmatically to **Admin** (and optional Analyst) for MVP1 unless RBAC already has those roles.

---

## 5. Approval gate rules

1. Handoff must be `STAGED` (or already approved for idempotent re-get).  
2. Linked QA still `PASS`; package still belongs to company.  
3. `manifest_hash` on request must equal `HandoffPackage.manifest_hash` (tamper detect — same idea as writeback `diff_hash`).  
4. Approver role allowed.  
5. Optional TTL on pending approval (e.g. 24h) — if token model used.  
6. Consume approval on transition to `APPROVED_FOR_ACTIVATION` (one-shot).

**Reject:** sets `REJECTED`; FE shows reason; Send disabled.

---

## 6. Backend APIs

Base: existing handoffs under `/api/v1/handoffs/` (`dataruns/handoffs_urls.py`).

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/handoffs/{handoff_id}/` | Already exists — must return new status + `activation_meta` + guide refs |
| `POST` | `/api/v1/handoffs/{handoff_id}/approve/` | STAGED → APPROVED_FOR_ACTIVATION (+ optional body) |
| `POST` | `/api/v1/handoffs/{handoff_id}/reject/` | → REJECTED |
| `POST` | `/api/v1/handoffs/{handoff_id}/confirm-activated/` | APPROVED_FOR_ACTIVATION → ACTIVATED |

### 6.1 `POST …/approve/` body

```json
{
  "manifest_hash": "<must match>",
  "approval_id": null,
  "notes": optional
}
```

If using pending-token flow: first `POST …/request-approval/` then approve with `approval_id`.

**Response 200:**

```json
{
  "handoff_id": "…",
  "status": "APPROVED_FOR_ACTIVATION",
  "activation_meta": { … },
  "activation_guide": {
    "path": "HUMAN_MANAGO_UI",
    "summary": "Build/activate this workflow in Manago UI using the package guide.",
    "human_guide": { … from build package payload … },
    "use_case_id": "UC-02",
    "package_id": "…",
    "manago_hint": "Automations → Automation Processes → Workflow → New / edit matching blueprint"
  },
  "capability": {
    "mcp_publish_status": "DISCOVERY_REQUIRED",
    "route": "HUMAN_FALLBACK"
  }
}
```

**Errors:**

| Code | HTTP | When |
|------|------|------|
| `handoff_not_staged` | 409 | Wrong status |
| `manifest_mismatch` | 409 | Hash mismatch |
| `qa_not_pass` | 409 | QA no longer PASS |
| `forbidden` | 403 | Role |

### 6.2 `POST …/confirm-activated/` body

```json
{
  "manifest_hash": "<must match>",
  "manago_workflow_external_id": "optional",
  "notes": "optional"
}
```

### 6.3 Roles

| Action | Roles |
|--------|--------|
| GET | Admin, Analyst, Viewer |
| approve / reject / confirm | Admin (Analyst optional — lock in PR) |

---

## 7. Frontend

### 7.1 Replace locked Send

Files today:

- `src/components/klints/HandoffSendLocked.tsx` — disabled wrapper  
- `src/lib/handoff.ts` — `HANDOFF_SEND_DISABLED_TITLE`, status types already include new statuses  
- `src/routes/handoff.tsx` — uses locked buttons  

**HO-02:**

1. When `status === "STAGED"` and user can approve → enable **Send** / **Approve for activation** CTA → calls `approve`.  
2. When `status === "APPROVED_FOR_ACTIVATION"` → show **Activation guide** panel (`human_guide.steps`) + **Confirm activated** button.  
3. When `status === "ACTIVATED"` → success banner; Send disabled (“Already activated”).  
4. When `REJECTED` → honest copy + link back to QA/Studio.  

**Never:** toast “Sent to MCP” / “Delivered to agent.”

Suggested copy after approve:

> Approved for activation. Open Manago and build/activate this workflow using the steps below. When live in Manago, click Confirm activated.

### 7.2 Guide data source

From linked build package (already on package payload):

- `human_guide` — `dataruns/use_cases/build_package.py` `_human_guide_from_blueprint`  
- `agent_spec` — for advanced operators (optional collapse)  
- CAP route summary — reuse `packageRouteSummary` / `PackageRouteHonesty`

GET handoff serialize should include `activation_guide` or FE fetches package by `package_id` from artifact_refs.

### 7.3 Deep links

Audit → `/handoff?handoff_id=` (or existing package_id/qa_run_id query). Extend `resolveAuditDeepLink` if needed (Engineering may help — coordinate).

---

## 8. What “Send” writes (expectations)

| Layer | What changes |
|-------|----------------|
| **Klints DB** | `HandoffPackage.status`, `activation_meta`, audit rows |
| **Manago** | **Nothing via API in HO-02** — human creates/activates workflow in UI |
| **Not written** | Contact fields, Shopify notes (Engineering writebacks) |

Operator may paste `manago_workflow_external_id` after confirm (from Manago workflow list UUID) for traceability — optional.

---

## 9. Audit

| Action | When |
|--------|------|
| `workflow.handoff_approved_for_activation` | approve success |
| `workflow.handoff_rejected` | reject |
| `workflow.handoff_activated` | confirm-activated |

Metadata keys (minimum): `handoff_id`, `package_id`, `qa_run_id`, `use_case_id`, `status`, `manifest_hash`, `path=HUMAN_MANAGO_UI`.

Reuse `dataruns.audit.append_audit_event` (same as HO-01 staged). Bell should surface these (FE-13 / audit notifications).

---

## 10. Tests & verify

### BE

- Transition matrix unit tests  
- manifest mismatch → 409  
- non-Admin → 403  
- Viewer cannot approve  
- Idempotent approve / confirm  
- CAP seed still `DISCOVERY_REQUIRED` for PUBLISH after HO-02 (no silent flip)  
- Pack payload still validates required fields if still stored in `payload`

Script: `scripts/verify_ho02_backend.py` (mirror `verify_ho01_backend.py`).

### FE

- Send enabled only when STAGED + allowed role  
- After approve, guide visible; Confirm calls API  
- No `HandoffSendLocked` on happy path for eligible users  
- `npm run verify:ho02`

### Manual staging

1. UC-02 Ready → Generate → QA PASS → Handoff STAGED  
2. Approve / Send → APPROVED_FOR_ACTIVATION  
3. Show guide  
4. Confirm activated → ACTIVATED  
5. Audit entries visible  

---

## 11. Acceptance

- [x] Send/Approve works for STAGED handoff with role + manifest check  
- [x] Status becomes `APPROVED_FOR_ACTIVATION` then `ACTIVATED` via confirm  
- [x] UI shows human Manago activation guide from `human_guide`  
- [x] No MCP publish/upsert network calls in this PR  
- [x] Matrix `MCP.WORKFLOW.PUBLISH` remains `DISCOVERY_REQUIRED` unless separate CAP-01B evidence PR  
- [x] No toast “Sent” / “Delivered to agent”  
- [x] Audit actions recorded  
- [x] HO-01 STAGED create path unchanged  
- [x] `verify_ho02_backend.py` + `npm run verify:ho02` pass  

---

## 12. Explicitly next / not this PRD

| Item | Owner |
|------|--------|
| **E2E-01** Loom + T2 submission (include HO-02 path) | Engineering lead |
| **CAP-01B / TRACK-B** MCP discovery → real auto publish | Later if client requires |
| **ORCH-SM-01** full 8-state machine | Negotiate; HO-02 ships minimal approve/activate |
| Engineering writeback catalogue | Unrelated |
| M2-OPS staging re-cert | Engineering |

---

## 13. References (read these)

### Pack / contract

| Artifact | Path |
|----------|------|
| Handoff schema | `Klints_MVP1_Rohan_Build_Pack_v1.2_20260718/03_Machine_Contracts/handoff_package.schema.json` |
| Matrix + Fallback Rules | `…/02_Execution_Capabilities/Klints_Manago_ExecutionCapabilityMatrix_v1.1_20260718.xlsx` sheets **02**, **05** |
| MCP discovery | `…/02_Execution_Capabilities/manago_mcp_discovery_results.json` |
| UC-02 blueprint approval/handoff | `…/04_MVP1_Pilot_Blueprints/UC-02_blueprint.json` |
| BUILD_README MCP rule | `…/06_Implementation/BUILD_README.md` |
| Contract Schedule 1 M2 | `Klints_Contract_MVP1ServicesAgreement_Astrapse_v12_20260708_4.pdf` |

### Code — backend

| File | Why |
|------|-----|
| `dataruns/use_cases/models.py` | `HandoffPackage` + Status enum |
| `dataruns/use_cases/handoff_package.py` | Status constants, payload builder, audit staged |
| `dataruns/use_cases/handoff_stage.py` | Create STAGED (do not break) |
| `dataruns/handoffs_urls.py` | Extend with approve/reject/confirm |
| `dataruns/use_cases/views.py` | HandoffDetailView / serializers |
| `dataruns/use_cases/build_package.py` | `human_guide` / `agent_spec` |
| `dataruns/capabilities/contract.py` | `CAP_ID_MCP_WORKFLOW_PUBLISH` |
| `dataruns/models.py` | `WritebackApprovalToken` — **pattern only** |
| `dataruns/audit.py` | `append_audit_event` |

### Code — frontend

| File | Why |
|------|-----|
| `src/routes/handoff.tsx` | Main UI |
| `src/lib/handoff.ts` | Client + status types + locked copy |
| `src/components/klints/HandoffSendLocked.tsx` | Replace/gate with live Send |
| `src/lib/capability-route.ts` | Honesty banner |
| `src/components/klints/PackageRouteHonesty.tsx` | Route display |

### Parent PRDs

| PRD | Role |
|-----|------|
| [PRD_HO_01](./PRD_HO_01_HANDOFF_PACKAGE_BIND.md) | STAGED bind |
| [PRD_QA_01](./PRD_QA_01_WORKFLOW_QA_GATE_ENGINE.md) | PASS unlocks handoff |
| [PRD_CAP_01](./PRD_CAP_01_CAPABILITY_MATRIX_RESOLVER.md) | Route / MCP honesty |
| [PRD_WF_01](./PRD_WF_01_WORKFLOW_BLUEPRINT_STUDIO.md) | Package + human_guide |

---

## 14. PR title / branch

- Branch: `feature/ho-02-handoff-send-human-activation`  
- BE title: `feat(HO-02): handoff approve + confirm activated (human Manago path)`  
- FE title: `feat(HO-02): unlock Send with approval + activation guide`

---

## 15. Traceability

| Item | Note |
|------|------|
| Milestone | M2 / T2 — contract Send + approval |
| Pack | Handoff schema · Matrix Fallback “Workflow publish” · no autonomous activation |
| Parent | HO-01 |
| Independent of | CAP-01B · MCP write evidence · Engineering WB catalogue |
