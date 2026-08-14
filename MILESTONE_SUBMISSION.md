# Klints MVP1 — Milestone 1 (Foundation & Core) Submission

**Document type:** Client milestone handoff / acceptance package  
**Milestone:** **M1 — Foundation & Core** (Schedule 1, Part A)  
**Payment gate:** **Tranche T1 — USD 3,000** (Schedule 1, Part B — released on Client acceptance of M1)  
**Contract reference:** *Klints × Astrapse Labs · MVP 1 Services Agreement v1.2 (8 July 2026)*  
**Submission date:** 14 August 2026  
**Repositories:**  
- Backend: [`georgechief/DEV_KLINTS_BACKEND`](https://github.com/georgechief/DEV_KLINTS_BACKEND)  
- Frontend: [`georgechief/DEV_KLINTS_FRONTEND`](https://github.com/georgechief/DEV_KLINTS_FRONTEND)  

> This file is identical in both repositories so reviewers have one authoritative writeup regardless of which repo they open first.

---

## 1. Executive summary

Milestone 1 required a working foundation: infrastructure, auth/tenancy, connector ingestion, a live scoring engine, and a live data-fix path — demonstrable on staging with SALESmanago / Manago.ai + Shopify.

**This submission delivers M1 in full, and exceeds the original M1 scope** in several material ways that were agreed during delivery (Build Pack v1.2 / DCS v1.4.1 and the tracked PRD sheets):

| Contract M1 baseline | Delivered |
|----------------------|-----------|
| Scoring engine live — **28 checks / 7 sub-scores** | **42 checks** live across foundation gates + 7 scored dimensions (see §4.4) |
| Ingestion + **webhooks** live | Ingestion live via universal connector framework; **daily Celery Beat scheduled DCS for all eligible tenants** (stronger than webhook-only refresh — see §4.3) |
| Data Fix Agent live | Fix path live with **issue evidence, required fix clarity, and writeback foundation** (see §4.5) |
| Infrastructure ready | Django API, **client-owned DigitalOcean Postgres**, Redis/Celery, **CI/CD deploy workflow** to DO staging (see §4.1) |

In addition, work that is **not required for M1** is already present and referenced in §5 (architecture assessment, lifecycle cockpit, opportunities/pilots, orchestration, assessment PDF, AI narrative/fix suggestions, team invites, audit, and more).

---

## 2. Contract map — Schedule 1 M1

### 2.1 Deliverable bundle (Month 1 / Weeks 0–4)

| # | Contract deliverable | Status | Evidence (files / surfaces) |
|---|----------------------|--------|-----------------------------|
| D1 | Infrastructure ready (repo, Django, PostgreSQL, Celery/Redis, CI/CD) | **Met** | Django project `core/`; Postgres via env (`core/settings/base.py` → `DATABASES`); Celery + Redis (`core/celery.py`, `CELERY_*` in settings); CI/CD `.github/workflows/deploy-development.yml` → DigitalOcean droplet / `apis.klints.io` |
| D2 | Auth + OAuth ready (JWT, RBAC, multi-tenant isolation) | **Met** | `tenants/auth_*`, `tenants/auth/`; JWT SimpleJWT; company/tenant models + API scoping; Shopify OAuth `tenants/shopify.py`, `tenants/connector_*` |
| D3 | Ingestion + webhooks live | **Met (evolved)** | Universal connectors `dataruns/connectors/` (`manago_ai/`, `shopify/`); bootstrap/import `dataruns/connectors/import_data.py`, `tenants/fetch_persist.py`. **Webhook-centric refresh replaced by agreed daily Beat** — `docs/maheep/PRD_DCS_07_DAILY_BEAT_SCHEDULE.md`, schedule in `core/settings/base.py` (`dcs-daily-score-1500-ist`), dispatcher `dataruns.dispatch_daily_dcs_scores` / `dataruns/dcs/enqueue.py` |
| D4 | Scoring engine live (28 checks, 7 sub-scores) | **Exceeded** | Live DCS pipeline `dataruns/dcs/`; master catalogue **42 checks** — `dataruns/dcs/check_master_mvp1.json`, `docs/dcs_scoring/CHECK_MASTER_42.md`; **7 scored dimensions** + foundation gates |
| D5 | Data Fix Agent live | **Met** | Backend writeback/fix foundation `dataruns/writebacks/`; AI fix suggestions `dataruns/ai/`; FE Fix bridge `src/routes/fix.tsx`, `src/lib/fix-flow.ts`, `src/lib/fix-live-plan.ts`; evidence/copy PRDs `docs/maheep/PRD_FE_08_*`, `PRD_FE_09_*` |

### 2.2 Acceptance Criteria (Schedule 1 — M1)

| # | Acceptance criterion | Status | How to verify / evidence |
|---|----------------------|--------|--------------------------|
| A1 | SALESmanago + one ecommerce connector (Shopify) authenticated and ingesting via the **universal framework** | **Met** | Connectors: `dataruns/connectors/base.py`, `manago_ai/`, `shopify/`; API `tenants/connector_*`; FE onboarding/integrations `src/routes/onboarding.tsx`, `src/routes/integrations.tsx` |
| A2 | **100 SM contacts ingested**; schema mapping documented | **Met (demo on staging)** | Ingest/bootstrap paths under `tenants/manago_fetch.py`, `dataruns/connectors/import_data.py`, mapping `dataruns/connectors/mapping.py` + connector `map.json` files; DCS fixtures/docs under `docs/dcs_scoring/reference/` |
| A3 | DCS engine producing scores on seeded SM data | **Met** | Score orchestration `dataruns/dcs/orchestrate.py`, executors `dataruns/dcs/executors/`, APIs `dataruns/dcs/views.py` / `dataruns/dcs_urls.py`; FE Data Consistency `src/routes/data-consistency.tsx`, `src/lib/dcs.ts` |

---

## 3. Clarifications vs original Schedule 1 wording

These points were discussed during delivery, tracked in the PRD / Build Pack sheets, and are intentional upgrades — not open defects.

### 3.1 CI/CD and client-owned database

- **CI/CD:** GitHub Actions workflow `.github/workflows/deploy-development.yml` deploys the Docker stack to the **DigitalOcean development droplet** on push to `main` (and `workflow_dispatch`). Public API host documented in-workflow as `apis.klints.io`.
- **Database:** Application Postgres is provisioned/hosted on **DigitalOcean under Client ownership**. The application connects via environment configuration (see `.env.example`); secrets are never committed.

### 3.2 “Webhooks live” → Daily Celery Beat (all tenants)

Schedule 1 listed “Ingestion + webhooks live.” Delivery kept **ingestion live** and replaced fragile/incomplete webhook-driven refresh with a **stronger, agreed pattern**:

- **Daily Celery Beat** at **15:00 IST** for every eligible connected company  
- Task: `dataruns.dispatch_daily_dcs_scores`  
- Schedule key: `dcs-daily-score-1500-ist` in `core/settings/base.py`  
- Spec: `docs/maheep/PRD_DCS_07_DAILY_BEAT_SCHEDULE.md`  
- Enqueue / idempotency: `dataruns/dcs/enqueue.py` (`DAILY_BEAT_TRIGGER = "daily_beat"`)

This is more powerful than webhook-only refresh: it continuously re-scores **all tenants** on a governed schedule, independent of individual webhook reliability.

### 3.3 “28 checks / 7 sub-scores” → **42 checks** (DCS v1.4.1)

The contract baseline named 28 checks / 7 sub-scores. Authoritative MVP1 scoring (Build Pack / DCS v1.4.1) defines **42 checks**:

| Class | Count | Source |
|-------|------:|--------|
| RULE_BASED GATE | 7 | Foundation gates |
| RULE_BASED SCORED | 21 | Scored dimensions |
| DRIFT SCORED | 14 | Drift / freshness |
| **Total** | **42** | `docs/dcs_scoring/CHECK_MASTER_42.md` |

**Seven scored dimensions** (weights in `check_master_mvp1.json`):

1. Customer Identity  
2. Lifecycle Event  
3. Product & Transaction  
4. Segment & Property  
5. Channel & Consent  
6. Measurement  
7. Business Reality  

Plus **Foundation Gate** checks (FD-01…FD-07).  

Machine catalogue: `dataruns/dcs/check_master_mvp1.json`  
Human master: `docs/dcs_scoring/CHECK_MASTER_42.md`  
Spec workbook: `docs/dcs_scoring/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx`

**Verdict:** M1 scoring acceptance is **met and exceeded**.

### 3.4 Data Fix Agent — shows the exact fix required

The Fix experience is not a placeholder:

- Operator Fix route: `src/routes/fix.tsx`  
- Live plan / evidence helpers: `src/lib/fix-flow.ts`, `src/lib/fix-live-plan.ts`  
- Diagnose / evidence UI: `src/components/klints/DiagnoseEvidence.tsx`  
- Backend writeback pipeline: `dataruns/writebacks/` (adapters, approvals, preflight, transform)  
- AI fix suggestions / narrative: `dataruns/ai/` (`complete.py`, prompts, providers)  
- Product PRDs: `docs/maheep/PRD_FE_08_FIX_LIVE_ISSUE_BRIDGE.md`, `PRD_FE_09_DCS_COPY_AND_FIX_EVIDENCE.md`, `PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md`, `docs/sahil/PRD_AI_01_MISTRAL_NARRATIVE_AND_FIX_SUGGESTIONS.md`

Operators see **what failed**, **why**, and **what fix is required**, with evidence — not only a raw fail flag.

---

## 4. M1 functional walkthrough (recommended acceptance path)

1. **Deploy / staging** — backend via Actions → DO (`deploy-development.yml`); frontend against staging API.  
2. **Auth** — register / verify / login (`/api/v1/auth/`, FE `/signup`, `/signin`, `/verify-email`).  
3. **Connect** — Manago.ai + Shopify via onboarding / integrations.  
4. **Ingest** — bootstrap import runs; contacts/orders land in tenant schema.  
5. **Score** — DCS run (manual and/or daily Beat); open Data Consistency UI.  
6. **Fix** — open a failing issue → Fix bridge shows required remediation / evidence.  

Supporting FE shell: `src/components/klints/AppShell.tsx`  
API client / auth: `src/lib/api.ts`, `src/lib/auth.ts`

---

## 5. Delivered beyond M1 (additional value in this submit)

The following are **outside** the M1 Foundation & Core acceptance row, but are included in this codebase deposit and demonstrate progress toward M2–M4:

| Area | Why it matters | Key references |
|------|----------------|----------------|
| **Architecture assessment (AF-01)** | Lifecycle / stack architecture verdicts after DCS | `dataruns/architecture/`, `docs/sahil/PRD_AF_01_ARCHITECTURE_ASSESSMENT.md`, FE `src/routes/lifecycle.tsx`, `src/lib/architecture.ts` |
| **Use-case / pilot library (UC-01)** | 16 MVP1 pilots / opportunities | `dataruns/use_cases/`, `docs/sahil/PRD_UC_01_*`, FE `src/routes/opportunities.tsx`, `src/routes/workflow.*` |
| **Orchestration (ORCH-01)** | Canonical priority / opportunity planning | `dataruns/orchestration/`, `docs/sahil/PRD_ORCH_01_CANONICAL_PRIORITY.md`, `src/lib/orchestration.ts` |
| **Assessment report PDF (RPT-01 / RPT-01B)** | Governed report compose + polished PDF export | `dataruns/reports/` (`compose.py`, `render_pdf.py`, `views.py`), `docs/sahil/PRD_RPT_01_*`, FE assessment helpers `src/lib/assessment-report.ts` |
| **AI agent setup (PRD-AI-01)** | Narrative + fix suggestions with privacy gate | `dataruns/ai/`, `docs/AI_AGENT_ORCHESTRATION_BLUEPRINT.md`, `docs/sahil/PRD_AI_01_*` |
| **DCS-10 run diff / period compare** | History, diffs, period UX beyond first score | `dataruns/dcs/run_diff.py`, `docs/dcs_scoring/PRD_DCS_10_*`, FE Data Consistency period UI |
| **Team invites / workspace / password** | Multi-user workspace readiness | `tenants/team_*`, `docs/PRD_TEAM_INVITES.md`, FE `src/routes/invite.accept.tsx`, `src/routes/settings.tsx` |
| **Audit / governance** | Activity & audit chain foundations | `dataruns/audit*`, `docs/maheep/PRD_AUDIT_*`, FE `src/routes/activity.tsx` |
| **QA / Handoff surfaces** | Operator QA & handoff screens | FE `src/routes/qa.tsx`, `src/routes/handoff.tsx` |
| **Security / data processing response** | Written security posture for Client | `docs/security/KLINTS_AI_SECURITY_AND_DATA_PROCESSING_RESPONSE.md` |

These items strengthen the M1 story: the foundation is not only “stood up” — it already supports scoring depth, fix guidance, reporting, and operator workflows beyond the Month-1 minimum.

---

## 6. Repository contents (this deposit)

### Backend (`DEV_KLINTS_BACKEND`)

```
core/                 Django settings, Celery, health
tenants/              Auth, connectors, team, workspace
dataruns/             DCS, architecture, orchestration, reports, AI, writebacks
docs/                 PRDs & DCS masters (preserved as authored)
.github/workflows/    deploy-development.yml (DO CI/CD)
.env.example          Required secrets documented (values excluded)
requirements.txt      Dependency manifest
docker-compose.yml    Local/stack helpers
```

### Frontend (`DEV_KLINTS_FRONTEND`)

```
src/routes/           Operator surfaces (auth → DCS → fix → workflows → settings)
src/components/klints Product shell, DCS charts, evidence, onboarding
src/lib/              API, auth, DCS, architecture, reports, writebacks, team
public/               Branding & onboarding assets
```

Secrets (`.env`, production credentials) are **excluded**. Configure from `.env.example`.

---

## 7. Documentation index (authoritative PRDs)

| Topic | Path |
|-------|------|
| DCS overview | `docs/dcs_scoring/PRD_00_OVERVIEW.md` |
| Check master 42 | `docs/dcs_scoring/CHECK_MASTER_42.md` |
| Daily Beat (webhook evolution) | `docs/maheep/PRD_DCS_07_DAILY_BEAT_SCHEDULE.md` |
| Connector bootstrap | `docs/dcs_scoring/PRD_CONN_01_ON_CONNECT_BOOTSTRAP.md` |
| Fix bridge / evidence | `docs/maheep/PRD_FE_08_*`, `PRD_FE_09_*` |
| Writeback foundation | `docs/maheep/PRD_WB_01_*` |
| Architecture | `docs/sahil/PRD_AF_01_*` |
| Reports / PDF | `docs/sahil/PRD_RPT_01_*` |
| AI | `docs/sahil/PRD_AI_01_*`, `docs/AI_AGENT_ORCHESTRATION_BLUEPRINT.md` |
| Team invites | `docs/PRD_TEAM_INVITES.md` |
| Auth / connectors API notes | `docs/API_AUTH_CONNECTORS.md` |

---

## 8. Acceptance request (for T1 release)

Per Agreement clauses **4.2–4.3** and Schedule 1 Part B:

1. Provider hereby gives **written notice of M1 completion** via this document and the corresponding Source Code deposit in the Client-controlled `DEV_KLINTS_*` repositories.  
2. Client is requested to **accept M1 in writing within five (5) business days**, or the Milestone is **deemed accepted** if no reasoned rejection is provided (clause 4.3).  
3. Upon acceptance (or deemed acceptance), Provider will invoice **Tranche T1 — USD 3,000**, payable within ten (10) business days (clause 5.4).

### Suggested Client acceptance checklist

- [ ] Staging API reachable (DO deploy via CI/CD)  
- [ ] Manago + Shopify connect & ingest on staging  
- [ ] DCS run produces headline + dimension scores (42-check master)  
- [ ] Daily Beat schedule present (`dcs-daily-score-1500-ist`)  
- [ ] Fix surface shows concrete fix / evidence for a failing check  
- [ ] Source available in Client GitHub repos listed above  

---

## 9. Closing statement

**Milestone M1 (Foundation & Core) is complete for acceptance.**  
Infrastructure, auth/tenancy, universal connector ingestion, live DCS scoring, and the Fix agent path are delivered on Client-owned DigitalOcean infrastructure with CI/CD. Contract baselines for **28/7 scoring** and **webhook refresh** are **met via the agreed stronger implementations** (**42 checks**; **daily Celery Beat for all tenants**). Material progress beyond M1 (architecture, lifecycle, pilots, orchestration, PDF reporting, AI) is included in the same deposit for Client review.

---

*Submitted by Astrapse Labs LLP / Named Lead Developer for Client milestone review under the MVP 1 Services Agreement.*
