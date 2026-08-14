# Klints MVP1 — Backend Milestone Submission

**Repository:** `DEV_KLINTS_BACKEND`  
**Submission date:** 14 August 2026  
**Specification baseline:** Klints MVP1 Build Pack v1.2 / DCS v1.4.1  
**Purpose:** Client delivery of the current backend milestone codebase for review and acceptance.

---

## 1. Executive summary

This repository contains the Django API for **Klints** — the AI orchestration layer that sits above a martech stack and proves stack integrity before agents act.

This milestone delivers a working multi-tenant backend covering:

- Authentication, workspace onboarding, and team invites
- Connector bootstrap (Manago AI, Shopify) with encrypted credential storage
- Data Consistency Scoring (DCS) — headline 42-check engine, run history, diffs, and period compare
- Architecture assessment (AF-01)
- Pilot / use-case library (UC-01) and orchestration (ORCH-01)
- Assessment report composition + PDF export (RPT-01 / RPT-01B)
- Writeback foundation (WB-01) with approval-oriented adapters
- AI orchestration blueprint + provider wiring (PRD-AI-01)

Product and engineering PRDs under `docs/` are included **as authored** for this handoff (not rewritten for this submit).

---

## 2. What is included

| Area | Location | Status for this submit |
|------|----------|------------------------|
| Auth (register, verify, login, me, password flows) | `tenants/auth_*` | Delivered |
| Team invites | `tenants/team_*`, `docs/PRD_TEAM_INVITES.md` | Delivered |
| Connectors + bootstrap | `tenants/connector_*`, `dataruns/connectors/` | Delivered |
| DCS scoring & orchestration | `dataruns/dcs/`, `docs/dcs_scoring/` | Delivered |
| DCS run diff / period compare (DCS-10) | `dataruns/dcs/`, PRDs under `docs/dcs_scoring/` | Delivered |
| Architecture assessment (AF-01) | `dataruns/architecture/` | Delivered |
| Use-case / pilot library (UC-01) | `dataruns/use_cases/` | Delivered |
| Orchestration (ORCH-01) | `dataruns/orchestration/` | Delivered |
| Reports + PDF (RPT-01 / RPT-01B) | `dataruns/reports/` | Delivered |
| Writebacks (WB-01) | `dataruns/writebacks/` | Foundation delivered |
| AI orchestration (PRD-AI-01) | `dataruns/ai/`, `docs/AI_AGENT_ORCHESTRATION_BLUEPRINT.md` | Delivered |
| Security / data processing notes | `docs/security/` | Included |

---

## 3. Repository layout

```
DEV_KLINTS_BACKEND/
├── manage.py
├── requirements.txt
├── .env.example                 # copy → .env (secrets not committed)
├── core/                        # Django project, settings, Celery
├── tenants/                     # Users, tenants, auth, connectors, team
├── dataruns/                    # DCS, architecture, orchestration, reports, AI
├── docs/                        # PRDs & specs (unchanged for this handoff)
├── deploy/                      # Deployment helpers
├── docker-compose.yml
├── Dockerfile
└── MILESTONE_SUBMISSION.md      # this file
```

---

## 4. How to run (local)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # set SECRET_KEY and connector keys
python manage.py migrate
python manage.py runserver
```

**Also required for async work:**

- Redis (Celery broker)
- Celery worker: `celery -A core worker -l info`

**Smoke checks**

- `GET /health/`
- Auth: `/api/v1/auth/`
- Tenants: `/api/v1/tenants/`
- Dataruns / DCS / orchestration / reports under `/api/v1/`

Pair with **`DEV_KLINTS_FRONTEND`** for the full product UI.

---

## 5. Security & secrets

- **Not included:** `.env`, `production.env`, local databases, uploaded media.
- Use `.env.example` as the template for local/client environments.
- Connector credentials are stored encrypted (Fernet); set `CONNECTOR_FERNET_KEY` before connecting live systems.

---

## 6. Documentation package (`docs/`)

The `docs/` tree is submitted **as-is** for this milestone (no rewrite of PRD content). Key entry points:

| Doc | Description |
|-----|-------------|
| `docs/dcs_scoring/PRD_00_OVERVIEW.md` | DCS program overview |
| `docs/dcs_scoring/CHECK_MASTER_42.md` | Headline 42-check master |
| `docs/dcs_scoring/PRD_DCS_*.md` | DCS engine, gates, scoring, API, diffs |
| `docs/PRD_TEAM_INVITES.md` | Team invite build guide |
| `docs/PRD_PASSWORD_AND_WORKSPACE.md` | Password / workspace flows |
| `docs/PRD_CONNECTOR_CSV_EXPORT.md` | Connector CSV export |
| `docs/API_AUTH_CONNECTORS.md` | Auth + connector API notes |
| `docs/AI_AGENT_ORCHESTRATION_BLUEPRINT.md` | AI agent orchestration blueprint |
| `docs/security/KLINTS_AI_SECURITY_AND_DATA_PROCESSING_RESPONSE.md` | Security / data processing |

---

## 7. Acceptance notes for the client

1. This is a **milestone code submit**, not a claim of production go-live readiness for every external Manago/MCP path.
2. External MCP capabilities that remain discovery-dependent should be treated per Build Pack stop-and-flag rules.
3. Frontend companion: **`georgechief/DEV_KLINTS_FRONTEND`**.
4. For walkthroughs, start with auth → connect → DCS run → architecture → opportunity/workflow → report export.

---

## 8. Suggested review path

1. Read `docs/dcs_scoring/PRD_00_OVERVIEW.md`
2. Run API locally with `.env.example` filled
3. Exercise `/api/v1/auth/login/` and `/api/v1/auth/me/`
4. Review DCS + architecture endpoints against PRDs
5. Open the frontend repo and validate end-to-end against a sandbox connector

---

*Submitted by the Klints engineering team for client milestone review.*
