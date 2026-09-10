# Klints MVP1 — Milestone 2 (Activation & Blueprint) Submission

**Document type:** Client milestone handoff / acceptance package  
**Milestone:** **M2 — Activation & Blueprint** (Schedule 1, Part A)  
**Payment gate:** **Tranche T2 — USD 3,000** (Schedule 1, Part B — released on Client acceptance of M2)  
**Contract reference:** *Klints × Astrapse Labs · MVP 1 Services Agreement v1.2 (8 July 2026)*  
**Submission date:** 9 September 2026 (deposit) · **Amended:** 10 September 2026 (release system live + Build Pack on staging)  
**Repositories:**  
- Backend: [`georgechief/DEV_KLINTS_BACKEND`](https://github.com/georgechief/DEV_KLINTS_BACKEND)  
- Frontend: [`georgechief/DEV_KLINTS_FRONTEND`](https://github.com/georgechief/DEV_KLINTS_FRONTEND)  

**Staging backend (live):** `https://apis.klints.io` — deployed from release tag **[`v1.0.1`](https://github.com/georgechief/DEV_KLINTS_BACKEND/releases/tag/v1.0.1)** (tag-based CD; see [`RELEASES.md`](https://github.com/georgechief/DEV_KLINTS_BACKEND/blob/main/RELEASES.md) on the backend repo). Health: `GET /health/` → `{"status":"ok"}`.  
**M2 demo walkthrough:** play in-frame → [`M2_WALKTHROUGH.html`](./M2_WALKTHROUGH.html) · [one-click player (jsDelivr)](https://cdn.jsdelivr.net/gh/georgechief/DEV_KLINTS_BACKEND@main/M2_WALKTHROUGH.html) · [Loom share](https://www.loom.com/share/f7b6ae96d15d4c6da1555487de595e3f)

> This file is identical in both repositories so reviewers have one authoritative writeup regardless of which repo they open first.  
> Prior M1 deposit writeup (historical): see git history for `MILESTONE_SUBMISSION.md` (14 August 2026). This document is the **M2** claim SoT.

---

## 1. Executive summary

Milestone 2 required Activation & Blueprint: an **approval state machine (8 states)** plus Track B MCP/A2A prototype; **writeback + lifecycle** live; **Workflow Blueprint Studio** with SM-agent-ready JSON; **QA + Handoff** (0–100 / 80-point gate); and Acceptance Criteria for Track B E2E, Send-to-Manago with approval, and MCP Capability Matrix.

**This deposit delivers the M2 product surfaces on Client-controlled repos, with staging backend already released and healthy under the tag-based deploy system (`v1.0.1`)**, with an honest reading of each Schedule 1 row:

| Contract M2 item | Delivery status | Notes |
|------------------|-----------------|-------|
| Approval state machine live (**8 states**) | **Met** | Pack-aligned **OrchestrationTask** 8-status SM (API + UI) — see §2.1 D1 |
| Track B MCP/A2A prototype | **Deferred / Client-dependent** | Capability Matrix + human Send path shipped; **live MCP/A2A E2E blocked** on Manago MCP OAuth / beta access (Agreement §6.1) — see §3.1 |
| Writeback + Lifecycle live | **Met (with disclosed caveats)** | SM REST writebacks for allowlisted checks; rollback; audit hash chain; Lifecycle rule engine — see §2.1 D3 / §3.2 |
| Workflow Blueprint Studio + SM-agent-ready JSON | **Met (with disclosed caveats)** | Studio live; machine package JSON; honest handoff package format until MCP runtime — see §2.1 D4 / §3.3 |
| QA + Handoff live (0–100, 80 gate) | **Met** | QA gate engine + staged handoff + Send with approval (human Manago activation) — see §2.1 D5 |
| **AC-A** Track B E2E one workflow | **Open / waiver requested** | Same Client dependency as Track B — §3.1 |
| **AC-B** Send to Manago.ai + approval | **Met** | Human Manago UI activation path (HO-02) — §2.2 |
| **AC-C** MCP Capability Matrix delivered | **Met** | Registry + API + Studio/Handoff route honesty — §2.2 |

**Recommended Client posture for T2:** accept M2 **with written deferral/waiver of literal AC-A / Track B live MCP** until Manago grants MCP access (or Client waives), while treating AC-B, AC-C, and the remainder of the M2 bundle as delivered with the caveats in §3.

---

## 2. Contract map — Schedule 1 M2

### 2.1 Deliverable bundle (Month 2 / Weeks 5–8)

| # | Contract deliverable | Status | Evidence (files / surfaces) |
|---|----------------------|--------|-----------------------------|
| D1 | Approval state machine live (**8 states**) + Track B MCP/A2A prototype | **D1a Met · D1b Deferred** | **8-state:** `dataruns/orchestration/` (`models.py`, `task_transitions.py`, views/URLs under orchestration); migration `dataruns/migrations/0032_orchestrationtask.py`; pack statuses PENDING→…→DONE/CANCELLED. FE orchestration surfaces / API client. Spec trail: `docs/ops/PRD_GAP_01_M2_CODE_GAPS_WEEKS_5_9.md`, `docs/orchestration/PRD_ORCH_01_CANONICAL_PRIORITY.md`. **Track B:** Matrix seed `dataruns/capabilities/`; discovery remains Client/Manago-gated — §3.1 |
| D2 | *(part of D1 in Schedule 1)* Track B called out in ACs | See AC-A | — |
| D3 | Writeback + Lifecycle live (SM REST writeback, rollback, audit hash chain) | **Met (caveats §3.2)** | Writebacks: `dataruns/writebacks/` (pipeline, approvals, adapters, registry); allowlisted execute **CI-01 / CC-03 / WB-SHOP-01**; FE Fix `src/routes/fix.tsx`, `src/lib/writebacks.ts`. Lifecycle: `dataruns/architecture/`, FE `src/routes/lifecycle.tsx`. Audit chain: `dataruns/audit.py`, immutability migration `0030_*`. Docs: `docs/writebacks/`, `docs/architecture/PRD_AF_01_ARCHITECTURE_ASSESSMENT.md`, `docs/audit/` |
| D4 | Workflow Blueprint Studio live + SM-agent-ready JSON spec output | **Met (caveats §3.3)** | BE package build `dataruns/use_cases/build_package.py` (+ related); FE Studio `src/routes/workflow.*`, `src/components/workflow/`. Specs: `docs/workflow/PRD_WF_01_WORKFLOW_BLUEPRINT_STUDIO.md`, `docs/workflow/PRD_WF_02_*` |
| D5 | QA + Handoff live (QA score 0–100, 80-point gate) | **Met** | QA: `dataruns/use_cases/qa_*`, FE `src/routes/qa.tsx` — hard tests + ≥80 gate. Handoff: staged package bind + Send approval → human Manago activation — `dataruns/use_cases/handoff_*`, FE `src/routes/handoff.tsx`. Specs: `docs/workflow/PRD_QA_01_*`, `docs/handoff/PRD_HO_01_*`, `docs/handoff/PRD_HO_02_*` |

### 2.2 Acceptance Criteria (Schedule 1 — M2)

| # | Acceptance criterion | Status | How to verify / evidence |
|---|----------------------|--------|--------------------------|
| **AC-A** | Track B prototype demonstrated end-to-end with **one workflow** | **Not met as live MCP** — **Client dependency** | Requires Manago MCP/A2A beta access (Agreement §6.1). Code holds Capability Matrix + honest `DISCOVERY_REQUIRED` / human fallback. **Request:** written waiver deferring AC-A to MCP grant, **or** provision of MCP credentials to complete Slice B. See §3.1 |
| **AC-B** | ‘Send to Manago.ai’ functional with **approval gate** | **Met** | Operator: Handoff → approve → human guide → confirm activated in Manago UI. BE handoff activation services + FE handoff Send flow. Spec: `docs/handoff/PRD_HO_02_HANDOFF_SEND_HUMAN_ACTIVATION.md` |
| **AC-C** | MCP Capability Matrix delivered | **Met** | Capability registry + GET API; Studio/Handoff show MCP vs human route honestly (no silent `CONFIRMED_LIVE` invent). Spec: `docs/workflow/PRD_CAP_01_CAPABILITY_MATRIX_RESOLVER.md` |

---

## 3. Clarifications vs Schedule 1 wording (honesty register)

### 3.1 Track B MCP/A2A / AC-A — Client dependency

Schedule 1 names a **Track B MCP/A2A prototype** and AC-A “demonstrated end-to-end with one workflow.”

**Delivered now:**

- MCP **Capability Matrix** seeded and exposed (AC-C).  
- Handoff **Send** works with approval via **human Manago UI** activation (AC-B) — consistent with pack honesty when MCP write tools are not proven.  
- Scaffolding for discovery exists; Matrix entries that require live discovery remain **`DISCOVERY_REQUIRED`** / not falsely marked live.

**Not delivered as literal MCP runtime:**

- End-to-end MCP client workflow create/publish against Manago MCP.  
- A2A runtime.

**Contract relief:** Agreement **§6.1** Client Dependencies include Manago OAuth / MCP/A2A beta access. Provider requested access; until granted, Provider requests **written waiver or deferral of AC-A** (and the Track B “live MCP” half of the D1 sentence) without blocking acceptance of the remainder of M2.

### 3.2 Writeback + Lifecycle — caveats (still “live”)

| Topic | Reality |
|-------|---------|
| Allowlisted automated writebacks | **CI-01**, **CC-03**, **WB-SHOP-01** execute with preview → approve → once-per-DCS-run gate |
| Catalogue wave 2 (e.g. SP-01 / LE-01) | Documented as follow-on (`docs/writebacks/PRD_WB_08_*`) — **not** required to call writeback “live” for M2 |
| “Auto-rollback within 15 minutes” (timeline sheet language) | Product implements **stale `executing` reclaim** (~15m) → failed; **not** automatic undo of successful writes. Manual rollback path exists for supported ops |
| CDUC named product / separate dashboard | Fix writeback UI is the operator surface — **no** separate CDUC app |
| Shopify metafield rollback | Limited / stub where not implemented — customer-note path supported for WB-SHOP-01 |
| Lifecycle “AI” | **Rule-based** architecture assessment (AF-01), not an LLM agent |

### 3.3 Studio “SM-agent-ready JSON”

- Studio generates **build packages** with machine JSON + human guide.  
- Runtime/API handoff format is **`HANDOFF_PACKAGE_SPEC`** (honest) until Track B MCP action objects are proven — pack blueprint JSON may still label MCP shapes for specification; product does **not** claim live MCP auto-send.  
- Studio **PDF export** is out of M2 scope.

### 3.4 Approval “8 states” — which eight

Timeline sheets sometimes describe a CDUC change-set 8-state. **This deposit implements the Build Pack orchestration task 8-status machine** (PENDING, BLOCKED, READY, IN_PROGRESS, AWAITING_APPROVAL, DONE, FAILED, CANCELLED) as the contract’s **approval state machine live** deliverable, alongside writeback approval tokens and handoff 4-state for Send. That is the pack SoT used in delivery.

### 3.5 Items that belong to M3 (not claimed under T2)

Do **not** treat the following as M2 acceptance:

| Item | Milestone |
|------|-----------|
| Demo env ~5,000 contacts / DCS ~62 (seed helpers may exist) | **M3** demo bundle |
| Security review + tenant isolation verification AC | **M3** |
| Grafana / observability hardened | **M3** (PRD in `docs/ops/PRD_M3_OBS_01_*` — implementation may land after this deposit) |
| Design Partner 1 live on production | **M3** |

---

## 4. M2 functional walkthrough (recommended acceptance path)

**Recorded demo — play in frame**

GitHub’s markdown viewer strips `<iframe>` tags, so the playable embed lives in [`M2_WALKTHROUGH.html`](./M2_WALKTHROUGH.html). Open that file in a browser (or use the [one-click player](https://cdn.jsdelivr.net/gh/georgechief/DEV_KLINTS_BACKEND@main/M2_WALKTHROUGH.html)) to watch without leaving the deposit.

<iframe
  src="https://www.loom.com/embed/f7b6ae96d15d4c6da1555487de595e3f?hide_owner=true&hide_share=true&hide_title=true"
  title="Klints M2 Activation and Blueprint walkthrough"
  width="100%"
  height="480"
  frameborder="0"
  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
  allowfullscreen
  webkitallowfullscreen
  mozallowfullscreen
></iframe>

Fallback: [Loom share page](https://www.loom.com/share/f7b6ae96d15d4c6da1555487de595e3f). Use the steps below for live re-verification on staging.

1. **Auth + connect** — Manago + Shopify (M1 baseline still required).  
2. **Import + DCS score** — Data Consistency; optional fresh-import gate (DCS-10).  
3. **Fix** — open allowlisted FAIL (CI-01 / CC-03 / WB-SHOP-01) → preview → approve writeback → provenance; optional rollback.  
4. **Lifecycle** — `/lifecycle` architecture assessment (rule-based).  
5. **Opportunities / Studio** — ready pilot → Workflow Studio → generate package → download JSON.  
6. **QA** — run gate; PASS only if hard tests pass **and** score ≥ 80.  
7. **Handoff** — stage package → **Send** with approval → follow human Manago activation guide → confirm.  
8. **Capability Matrix** — confirm MCP vs human route labels remain honest (no false live MCP).  
9. **Orchestration SM** — create/list/transition an OrchestrationTask through the 8-status graph (admin/analyst roles as implemented).

### Staging release system (backend)

Staging is **not** deployed on every `main` push. Client reviews and ships via **semver tags**:

| Item | Detail |
|------|--------|
| Docs | Backend [`RELEASES.md`](https://github.com/georgechief/DEV_KLINTS_BACKEND/blob/main/RELEASES.md) (authoritative for CD) |
| Workflow | `.github/workflows/deploy-development.yml` — **Deploy release (tag)** |
| Tag shape | `vMAJOR.MINOR.PATCH` (e.g. `v1.0.1`) |
| Triggers | Tag push, published GitHub Release, or manual workflow_dispatch with tag |
| Server stamp | `/opt/klints_backend/DEPLOY_VERSION` |
| Public API | `https://apis.klints.io` (Client DigitalOcean + Let’s Encrypt) |

**Releases already cut for this M2 deposit:**

| Tag | Status | Notes |
|-----|--------|-------|
| [`v1.0.0`](https://github.com/georgechief/DEV_KLINTS_BACKEND/releases/tag/v1.0.0) | Failed boot | Initial tag; Build Pack omitted from first rsync → `load_use_case_pilots` blocked gunicorn (nginx 502) |
| [`v1.0.1`](https://github.com/georgechief/DEV_KLINTS_BACKEND/releases/tag/v1.0.1) | **Live** | Build Pack restored ([PR #1](https://github.com/georgechief/DEV_KLINTS_BACKEND/pull/1)); health **200**; **current staging** |

Frontend: Client Vercel / configured staging origin against that API (no tag-deploy requirement for this claim).

---

## 5. What shipped since M1 (M2-relevant highlights)

| Area | Summary | Key references |
|------|---------|----------------|
| **Orchestration 8-state SM** | Pack ORCH statuses, transitions, audit, REST, FE | `dataruns/orchestration/`, `docs/ops/PRD_GAP_01_*` |
| **Writeback execute path** | Approve/execute, once-per-run gate, provenance, hygiene | `docs/writebacks/PRD_WB_02` … `PRD_WB_07` |
| **Handoff Send (human)** | Approval gate + Manago UI activation | `docs/handoff/PRD_HO_02_*` |
| **QA gate** | 0–100 + 80 + hard tests | `docs/workflow/PRD_QA_01_*` |
| **Studio** | Blueprint → package builder | `docs/workflow/PRD_WF_01_*` |
| **Capability Matrix** | MCP vs human route honesty | `docs/workflow/PRD_CAP_01_*` |
| **Pilot gates / fresh import** | UC readiness + DCS-10 | `docs/dcs_scoring/PRD_DCS_09_*`, `PRD_DCS_10_*` |
| **M2 honesty / demo seed helpers** | Copy honesty, optional `seed_demo_tenant` | `docs/ops/GAP_01F_DEMO_PATH.md`, `dataruns/management/commands/seed_demo_tenant.py` |
| **Tag-based staging CD** | Semver tags only; Releases published | `RELEASES.md`, `.github/workflows/deploy-development.yml` |
| **MVP1 Build Pack in image** | Pilots seed on every `web` boot | `Klints_MVP1_Rohan_Build_Pack_v1.2_20260718/` (required for `load_use_case_pilots`) |

---

## 6. Repository contents (this deposit)

### Backend (`DEV_KLINTS_BACKEND`)

```
core/                 Django settings, Celery, health
tenants/              Auth, connectors, team, workspace
dataruns/             DCS, writebacks, architecture, use cases, QA, handoff,
                      orchestration SM, capabilities, reports, AI, audit
Klints_MVP1_…/        MVP1 Build Pack (pilot_manifest + blueprints — required at deploy)
docs/                 PRDs by module (see docs/README.md) — no contributor folders
RELEASES.md           Tag-based staging deploy SoT + release history
M2_MILESTONE_SUBMISSION.md   This claim
.github/workflows/    deploy-development.yml — Deploy release (tag) only
.env.example          Required secrets documented (values excluded)
docker-compose.yml    Stack definition
scripts/              Verification gates (verify_*.py)
```

### Frontend (`DEV_KLINTS_FRONTEND`)

```
src/routes/           Operator surfaces (DCS → Fix → Studio → QA → Handoff → …)
src/components/klints Product shell, evidence, overview, notifications
src/lib/              API clients (writebacks, use-cases, handoff, QA, orchestration, …)
scripts/              Frontend verify gates (verify-*.mjs)
```

Secrets (`.env`, production credentials, API tokens) are **excluded**. Configure from `.env.example`.

Documentation uses **module folders only** (no individual contributor directories or names).

---

## 7. Documentation index (by module)

Full index: [`docs/README.md`](docs/README.md).

| Module | Path | M2 relevance |
|--------|------|----------------|
| Ops / M2 gap SoT | `docs/ops/` | GAP-01 M2 code-gap PRD, demo path, staging harden, M3 OBS PRD (forward) |
| Workflow / Matrix / QA | `docs/workflow/` | Studio, QA, Capability Matrix |
| Handoff | `docs/handoff/` | HO-01 bind, HO-02 Send |
| Writebacks | `docs/writebacks/` | WB-01…WB-08 |
| Orchestration | `docs/orchestration/` | Priority + ORCH planning |
| Architecture / Lifecycle | `docs/architecture/` | AF-01 |
| Use cases / pilots | `docs/use_cases/` | UC-01 library |
| DCS scoring | `docs/dcs_scoring/` | DCS-07 Beat, DCS-09/10, check master |
| Frontend | `docs/frontend/` | Fix bridge, shell honesty |
| Audit | `docs/audit/` | Governance activity |
| Security | `docs/security/` | Data-processing response |
| AI / Reports / Auth / Team / Connectors | respective folders | Supporting |

---

## 8. Acceptance request (for T2 release)

Per Agreement clauses **4.2–4.3** and Schedule 1 Part B:

1. Provider hereby gives **written notice of M2 completion** (subject to §3.1 Track B / AC-A deferral) via this document and the corresponding Source Code deposit in the Client-controlled `DEV_KLINTS_*` repositories.  
2. Client is requested to either:  
   - **(A)** Accept M2 **including written waiver/deferral of AC-A / live Track B MCP** until MCP access is provided; **or**  
   - **(B)** Provide Manago MCP/A2A access so Provider can complete AC-A, then accept; **or**  
   - **(C)** Reject in writing within five (5) business days with specific unmet criteria (clause 4.3).  
3. If Client does not respond within five (5) business days, the Milestone is **deemed accepted** (clause 4.3), except where Client has already opened a written objection to AC-A — in which case only the waived/deferred items remain open.  
4. Upon acceptance (or deemed acceptance) of the accepted scope, Provider will invoice **Tranche T2 — USD 3,000**, payable within ten (10) business days (clause 5.4).  
5. Milestone source-code deposit obligations (Schedule 2 / clause 9) are satisfied by this push to Client GitHub repositories listed above.

### Suggested Client acceptance checklist

- [x] Staging API reachable (`https://apis.klints.io/health/` → ok) on release **`v1.0.1`**  
- [ ] Review [M2 Loom walkthrough](https://cdn.jsdelivr.net/gh/georgechief/DEV_KLINTS_BACKEND@main/M2_WALKTHROUGH.html) (in-frame player)  
- [ ] Frontend configured against that API  
- [ ] Fix: approve writeback on ≥1 allowlisted check (CI-01 / CC-03 / WB-SHOP-01)  
- [ ] Lifecycle page loads rule-based assessment  
- [ ] Studio: generate package + download JSON for a ready pilot  
- [ ] QA: observe 0–100 scoring and 80 / hard-test gate  
- [ ] Handoff: Send with approval → human Manago guide path  
- [ ] Capability Matrix visible; no false “MCP live” claim  
- [ ] OrchestrationTask 8-status transitions demonstrable  
- [ ] Written position on AC-A (waiver **or** MCP access timeline)  
- [x] Source present in Client GitHub repos listed above  
- [x] Backend release process documented (`RELEASES.md`); GitHub Releases **`v1.0.0`** / **`v1.0.1`** published  

---

## 9. Closing statement

**Milestone M2 (Activation & Blueprint) is submitted for Client acceptance** with full delivery of Send-with-approval (**AC-B**), Capability Matrix (**AC-C**), writeback + lifecycle, Workflow Blueprint Studio, QA + Handoff, and the pack **8-state orchestration approval SM**.  

Staging backend for this claim is **already released** under the Client tag-based CD system at **`v1.0.1`** (after correcting the Build Pack omission that blocked `v1.0.0`). Further staging updates should be cut as new tags — see backend [`RELEASES.md`](https://github.com/georgechief/DEV_KLINTS_BACKEND/blob/main/RELEASES.md).

**Literal Track B MCP/A2A E2E (AC-A)** remains **Client-dependent** under §6.1; Provider requests written waiver/deferral or MCP access rather than inventing live MCP evidence.  

Disclosed caveats (§3.2–§3.4) are intentional honesty, not silent omissions. M3 items (Grafana, security review AC, DP1 live) are **out of scope** for T2.

---

*Submitted by Astrapse Labs LLP / Named Lead Developer for Client milestone review under the MVP 1 Services Agreement.*
