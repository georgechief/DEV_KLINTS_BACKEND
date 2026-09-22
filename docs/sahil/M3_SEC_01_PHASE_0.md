# M3-SEC-01 — Phase 0 notes (lock / inventory)

**Date:** 2026-09-11  
**Branch:** `feature/m3-sec-01-rbac-isolation-packet`  
**Depends on:** PRD-M3-SEC-01 locked  

> **Historical note:** Findings below describe Phase 0 inventory state.  
> **Resolved later:** ViewSet leaks F1/F2 → Phase 3; isolation holes → Phase 2; RBAC negatives + audit pack → Phase 4; packet/verify → Phase 5; §11 evidence → Phase 6.

## Goal

Inventory API surfaces and existing tests so Phases 1–5 have a fixed allowlist. No production behaviour change in Phase 0 except documenting findings.

## Checklist

| # | Task | Done |
|---|------|------|
| 0.1 | Create branch from latest `main` | [x] — branch present; HEAD = `origin/main` |
| 0.2 | Walk `core/urls.py` → list every include / ViewSet / APIView | [x] |
| 0.3 | Draft RBAC matrix rows (can stay in this file until Phase 1) | [x] — family-level draft below |
| 0.4 | Grep existing isolation / role tests; mark covered vs missing in WORKING_GAPS | [x] |
| 0.5 | Reconfirm `TenantViewSet` / `DataRunViewSet` queryset behaviour | [x] — **were** unscoped/leaky at Phase 0 lock; **fixed Phase 3** |
| 0.6 | Note any FE dependency on global tenant/run list (stop-and-flag if yes) | [x] — see Stop-and-flag |
| 0.7 | Confirm AUDIT-01 artifacts present (`verify_audit_chain`, `0030`, tests) | [x] |

## Roles (reuse — do not change)

| Role | Enum | Path |
|------|------|------|
| Admin | `User.Role.ADMIN` | `tenants/models.py` |
| Analyst | `User.Role.ANALYST` | same |
| Viewer | `User.Role.VIEWER` | same |
| Company resolve | `get_user_company(user)` | `tenants/auth/services.py` |

## API inventory (from `core/urls.py`)

| Prefix | Module | Surfaces (ViewSet / APIView) | Notes |
|--------|--------|------------------------------|-------|
| `/api/v1/auth/` | `tenants/auth_urls.py` + `auth/urls.py` + `workspace/urls.py` | Register, VerifyEmail, Login, ResendVerification, Me, Forgot/Reset/ChangePassword, Workspace | Mostly public or self-scoped |
| `/api/v1/tenants/` | `tenants/urls.py` | **`TenantViewSet`** (CRUD router) | Phase 0 LEAK → **fixed Phase 3** |
| `/api/v1/team/` | `tenants/team_urls.py` | members list/detail, invites list/create/accept/resend/revoke | Cross-tenant GAP → **fixed Phase 2** |
| `/api/v1/connectors/` | `tenants/connector_urls.py` | verify, shopify start/callback/fetch, manago fetch/owners/api-v3-key, list/create, `<pk>/`, `<pk>/bootstrap/` | Uniqueness + SEC-01 isolation **done** |
| `/api/v1/dataruns/` | `dataruns/urls.py` | **`DataRunViewSet`** (CRUD router) | Phase 0 LEAK → **fixed Phase 3** |
| `/api/v1/dcs/` | `dataruns/dcs_urls.py` | status, history, runs, worklist, worklist/`<check_id>`, pilot-gates master/latest/evaluate, pilots/`<uc>`/readiness | Core HTTP GAP → **fixed Phase 2** |
| `/api/v1/writebacks/` | `dataruns/writebacks_urls.py` | mappings, kinds, possible, status, run, preview, execute, rollback, approvals (+ approve/reject) | HTTP cross-company GAP → **fixed Phase 2** |
| `/api/v1/architecture/` | `dataruns/architecture_urls.py` | assessments latest/list/detail/assets/graph/coverage/gaps | Isolation GAP → **fixed Phase 2** |
| `/api/v1/use-cases/` | `dataruns/use_cases_urls.py` | recommendations, catalogue, detail, build-package | Global catalogue OK; company-scoped recs — cite existing |
| `/api/v1/build-packages/` | `dataruns/build_packages_urls.py` | package detail, qa, handoff | Covered via QA/handoff wrong-company tests |
| `/api/v1/capabilities/` | `dataruns/capabilities_urls.py` | list, detail | Global matrix seed — document; role tests exist |
| `/api/v1/qa-runs/` | `dataruns/qa_runs_urls.py` | `<qa_run_id>/` | Covered (`test_qa_api_step5` wrong company) |
| `/api/v1/handoffs/` | `dataruns/handoffs_urls.py` | list, detail, approve, reject, confirm-activated | Covered (`test_handoff_*`) |
| `/api/v1/orchestration/` | `dataruns/orchestration_urls.py` | plan, tasks CRUD, transition | Covered (`test_orch_sm_phase*`) |
| `/api/v1/assessment-reports/` | `dataruns/reports_urls.py` | list/create, detail, pdf | Covered (`test_report_*` cross-tenant) |
| `/api/v1/ai/` | `dataruns/ai_urls.py` | fix / explain / nba / report narrative | Cross-company GAP → **fixed Phase 2** |
| `/api/v1/audit/` | `dataruns/audit_urls.py` | events, mark-read, notifications, mark-all-read | Covered (`test_audit.py`) |
| `/api/v1/search/` | `dataruns/search_urls.py` | GlobalSearchView | Covered (`test_search.py` company isolation) |
| `/health/` | `core.views.HealthCheckView` | public | No tenant data |
| `/ops/m3-obs-01/induce-error/` | `core.views.M3ObsInduceErrorView` | token-gated ops | Document only; not product RBAC |
| `/admin/` | Django admin | staff/superuser | Separate from product `User.Role` |

### Confirmed ViewSet leaks (0.5) — historical; fixed Phase 3

```text
# Phase 0 observed:
#   TenantViewSet.queryset = Tenant.objects.all()
#   DataRunViewSet optional ?tenant= without caller force
# Phase 3 current:
#   TenantViewSet.get_queryset → filter(pk=user.tenant_id); create/destroy 403; Admin update
#   DataRunViewSet.get_queryset → filter(tenant_id=…); ignore ?tenant=; force tenant on write
```

## Isolation coverage snapshot (Phase 0 lock → later resolution)

| Family | Phase 0 gap? | Resolution |
|--------|--------------|------------|
| Writebacks | YES | Phase 2 SEC-01 isolation |
| DCS core HTTP | YES | Phase 2 |
| Connectors | Partial | Cite + Phase 2 SEC-01 |
| Team | YES | Phase 2 |
| Architecture / AI | YES | Phase 2 |
| Tenants / DataRuns ViewSets | YES | Phase 3 harden + tests |
| Orch / handoff / audit / reports / search / QA | Cite existing | Unchanged (cite) |
| Capabilities | Global catalogue | Document only |

## Draft RBAC matrix rows (Phase 1 expands to full method grid)

| Family | Admin | Analyst | Viewer | Mutating? | Notes for Phase 1 |
|--------|-------|---------|--------|-----------|-------------------|
| auth (register/login/…) | public / self | same | same | mixed | Document public vs authed |
| auth/me, change-password, workspace | self | self | self (workspace admin-gated) | Y | workspace: non-admin 403 (`test_workspace`) |
| tenants ViewSet | leak at Phase 0 | same | same | Y | **Fixed Phase 3** |
| team members/invites | R/W | limited | R / — | Y | Cross-tenant **fixed Phase 2** |
| connectors | R/W | R/W (some) | R / blocked mutate | Y | Cite viewer 403; SEC-01 isolation |
| dataruns ViewSet | leak at Phase 0 | same | same | Y | **Fixed Phase 3** |
| dcs/* | R + mutate runs | R + some mutate | R / blocked mutate | Y | Isolation **fixed Phase 2** |
| writebacks/* | R/W | preview; execute admin | blocked | Y | Isolation **fixed Phase 2** |
| architecture/* | Admin start; R for all | R | R | Y | Isolation **fixed Phase 2** |
| use-cases / build-packages / qa / handoffs | per existing | per existing | read-mostly | Y | Cite handoff/build viewer 403 |
| orchestration | R/W | R/W limited | R / blocked create/transition | Y | Cite orch phase2/3 |
| assessment-reports | R/W | R/W | R / blocked create+pdf | Y | Cite report compose/pdf |
| ai/* | all roles POST | same | same | Y | Isolation **fixed Phase 2** |
| audit/* | R + mark-read | R + mark-read | R + mark-read | soft | Cite audit tests |
| search | R | R | R | N | Company-scoped |
| health | public | public | public | N | |
| ops induce | token | token | token | Y | Not product RBAC |
| Django /admin/ | staff | staff | staff | Y | Separate from User.Role |

## AUDIT-01 artifacts (0.7)

| Artifact | Present |
|----------|---------|
| `dataruns/audit.py` hash chain | Yes (reuse) |
| `manage.py verify_audit_chain` | Yes — `dataruns/management/commands/verify_audit_chain.py` |
| Migration `0030_audit_logs_immutability_triggers` | Yes |
| `dataruns/tests/test_audit.py` | Yes |
| `dataruns/tests/test_audit_immutability.py` | Yes |

## Stop-and-flag

1. **`DataRunViewSet`:** Maheep `PRD_FE_05` and older `PRD_CONNECTOR_CSV_EXPORT` document `GET /api/v1/dataruns/` / `{id}`. **Do not unregister** — Phase 3 must **scope to caller tenant** and deny foreign `?tenant=`.
2. **`TenantViewSet`:** No FE in this workspace; README lists `/api/v1/tenants/`. Prefer **scope to caller’s tenant** (not silent delete). If FE later needs multi-tenant admin list, that is a product decision — flag Rohan before expanding.
3. **`get_user_company` = first company by `created_at`:** residual risk for packet (PRD D / §5.6) — do not redesign multi-company-per-tenant in SEC-01.

## Exit

Phase 0 done: WORKING_GAPS filled; this inventory complete → **start Phase 1** (`docs/security/M3_SEC_01_RBAC_MATRIX.md`).
