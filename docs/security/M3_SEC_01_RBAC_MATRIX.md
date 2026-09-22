# M3-SEC-01 — RBAC Matrix (product roles)

**PRD:** [PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md](../sahil/PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md)  
**Date:** 2026-09-11  
**Roles:** `User.Role` = `admin` / `analyst` / `viewer` (`tenants/models.py`) — **not** Django `IsAdminUser`  
**Default API auth:** `IsAuthenticated` (`core/settings/base.py` `REST_FRAMEWORK`)  
**Legend:** `R` = allowed read · `W` = allowed mutate · `—` = denied (typically 403) · `public` = `AllowAny` / no JWT  

This matrix documents **current** product behaviour. Missing gates are called out; Phase 2–4 add tests / fixes.

---

## Django staff path (separate)

| Surface | Admin | Analyst | Viewer | Notes / code gate |
|---------|-------|---------|--------|-------------------|
| `GET/POST /admin/*` | staff/superuser only | staff/superuser only | staff/superuser only | Django admin — **not** product `User.Role` |

---

## `/health/` · `/ops/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET /health/` | public | public | public | `HealthCheckView` — no tenant data |
| `POST /ops/m3-obs-01/induce-error/` | token | token | token | `M3ObsInduceErrorView` — ops token gate; not product RBAC |

---

## `/api/v1/auth/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `POST …/register/` | public | public | public | `AllowAny` — creates first user as Admin |
| `POST …/login/` | public | public | public | `AllowAny` |
| `POST …/verify-email/` | public | public | public | `AllowAny` |
| `POST …/resend-verification/` | public | public | public | `AllowAny` |
| `POST …/forgot-password/` | public | public | public | `AllowAny` |
| `POST …/reset-password/` | public | public | public | `AllowAny` |
| `GET/PATCH …/me/` | R/W (self) | R/W (self) | R/W (self) | `IsAuthenticated`; PATCH name only (role not self-escalated) |
| `POST …/change-password/` | W (self) | W (self) | W (self) | `IsAuthenticated` |
| `GET/PATCH …/workspace/` | R/W | — | — | Admin only (`tenants/workspace/views.py`) |

Unauthenticated mutating product APIs → **401** via default `IsAuthenticated` (except `AllowAny` rows above).

---

## `/api/v1/tenants/` ✅ Phase 3 scoped

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/` list/retrieve (ViewSet) | R (own) | R (own) | R (own) | `get_queryset` → caller `tenant_id` only |
| `PUT/PATCH …/` | W (own) | — | — | Admin only (aligns with workspace); `slug`/`is_active` read-only |
| `POST …/` create | — | — | — | **403** — create not allowed |
| `DELETE …/` | — | — | — | **403** — destroy not allowed (no existence leak) |

---

## `/api/v1/team/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/members/` | R | R | R | Any authenticated tenant member; filtered by `tenant_id` |
| `PATCH …/members/<id>/` | W | — | — | Admin only (`TeamMemberDetailView`) |
| `GET …/invites/` | R | R | R | Tenant-scoped list; **no role gate** on GET |
| `POST …/invites/` | W | — | — | Admin only |
| `POST …/invites/<id>/resend/` | W | — | — | Admin only |
| `POST …/invites/<id>/revoke/` | W | — | — | Admin only |
| `GET/POST …/invites/accept/` | public | public | public | `AllowAny` (token) |

---

## `/api/v1/connectors/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/` (list) | R | R | R | Company-scoped; secrets masked |
| `POST …/` (create Manago) | W | W | — | Admin/Analyst |
| `POST …/verify/` | W | W | W | `IsAuthenticated` only — **no role gate** (current) |
| `POST …/shopify/start/` | W | W | — | Admin/Analyst |
| `GET …/shopify/callback/` | public | public | public | OAuth callback `AllowAny` |
| `POST …/shopify/fetch/` | W | — | — | Admin only (`_run_connector_import`) |
| `POST …/manago_ai/fetch/` | W | — | — | Admin only |
| `GET …/manago_ai/owners/` | R | R | R | Authed; auto-ensure primary for Admin/Analyst |
| `PUT …/manago_ai/owners/` | W | W | — | Admin/Analyst |
| `PUT/DELETE …/manago_ai/api-v3-key/` | W | W | — | Admin/Analyst |
| `GET …/<pk>/bootstrap/` | R | — | — | Admin only |
| `DELETE …/<pk>/` (disconnect) | W | W | — | Admin/Analyst |

---

## `/api/v1/dataruns/` ✅ Phase 3 scoped

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET/POST/PUT/PATCH/DELETE …/` (ViewSet) | R/W (own) | R/W (own) | R/W (own) | Always filter caller tenant; ignore foreign `?tenant=`; `tenant_slug` read-only |

---

## `/api/v1/dcs/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/status/` | R | R | R | `_DCS_READ_ROLES` |
| `GET …/history/` | R | R | R | `_DCS_READ_ROLES` |
| `GET …/worklist/` | R | R | R | `_DCS_READ_ROLES` |
| `GET …/worklist/<check_id>/` | R | R | R | `_DCS_READ_ROLES` |
| `POST …/runs/` | W | — | — | Admin only |
| `GET …/pilot-gates/master/` | R | R | R | `_DCS_READ_ROLES` |
| `GET …/pilot-gates/latest/` | R | R | R | `_DCS_READ_ROLES` |
| `POST …/pilot-gates/evaluate/` | W | W | — | `_PILOT_GATE_WRITE_ROLES` Admin/Analyst |
| `GET …/pilots/<uc>/readiness/` | R | R | R | `_DCS_READ_ROLES` |

---

## `/api/v1/writebacks/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/mappings/` | R | R | R | `_WRITEBACK_READ_ROLES` |
| `GET …/kinds/` | R | R | R | same |
| `GET …/possible/` | R | R | R | same |
| `GET …/status/` | R | R | R | same |
| `POST …/preview/` | W | W | — | `_PREVIEW_ROLES` |
| `POST …/execute/` | W | — | — | Admin only |
| `POST …/rollback/` | W | — | — | Admin only |
| `POST …/run/` | W† | W† | — | Delegates: preview=Admin/Analyst; execute/rollback=Admin |
| `POST …/approvals/` | W | W | — | Admin/Analyst request |
| `GET …/approvals/<id>/` | R | R | R | All product roles |
| `POST …/approvals/<id>/approve/` | W | — | — | Admin only |
| `POST …/approvals/<id>/reject/` | W | — | — | Admin only |

† Viewer denied for all `action` values on `/run/`.

---

## `/api/v1/architecture/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/assessments/latest/` | R | R | R | `_AF_READ_ROLES` |
| `POST …/assessments/` | W | — | — | Admin only (ops/tests) |
| `GET …/assessments/<id>/` | R | R | R | `_AF_READ_ROLES` |
| `GET …/assessments/<id>/assets/` | R | R | R | same |
| `GET …/assessments/<id>/graph/` | R | R | R | same |
| `GET …/assessments/<id>/coverage/` | R | R | R | same |
| `GET …/assessments/<id>/gaps/` | R | R | R | same |

---

## `/api/v1/use-cases/` · `/api/v1/build-packages/` · `/api/v1/qa-runs/` · `/api/v1/handoffs/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/use-cases/` (catalogue) | R | R | R | `_UC_READ_ROLES` (global pilots) |
| `GET …/use-cases/<id>/` | R | R | R | same |
| `GET …/use-cases/recommendations/` | R | R | R | company-scoped |
| `GET …/use-cases/recommendations/<id>/` | R | R | R | same |
| `POST …/use-cases/<id>/build-package/` | W | W | — | `_UC_BUILD_ROLES` |
| `GET …/build-packages/<id>/` | R | R | R | `_UC_READ_ROLES` |
| `POST …/build-packages/<id>/qa/` | W | W | W | `_UC_QA_ROLES` = all roles (PRD-QA-01) |
| `GET …/build-packages/<id>/qa/` | R | R | R | same — latest QA for package |
| `GET …/qa-runs/<id>/` | R | R | R | `_UC_QA_ROLES` |
| `GET …/build-packages/<id>/handoff/` | R | R | R | `_UC_HANDOFF_READ_ROLES` — latest staged handoff |
| `POST …/build-packages/<id>/handoff/` | W | W | — | `_UC_HANDOFF_CREATE_ROLES` |
| `GET …/handoffs/` | R | R | R | `_UC_HANDOFF_READ_ROLES` |
| `GET …/handoffs/<id>/` | R | R | R | same |
| `POST …/handoffs/<id>/approve/` | W | — | — | Admin only (HO-02) |
| `POST …/handoffs/<id>/reject/` | W | — | — | Admin only |
| `POST …/handoffs/<id>/confirm-activated/` | W | — | — | Admin only |

---

## `/api/v1/capabilities/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/` | R | R | R | `_CAP_READ_ROLES` — global matrix seed |
| `GET …/<capability_id>/` | R | R | R | same |

---

## `/api/v1/orchestration/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/plan/` | R | R | R | `_ORCH_READ_ROLES` |
| `GET …/tasks/` | R | R | R | same |
| `POST …/tasks/` | W | W | — | `_ORCH_MUTATE_ROLES` |
| `GET …/tasks/<id>/` | R | R | R | `_ORCH_READ_ROLES` |
| `POST …/tasks/<id>/transition/` | W | W‡ | — | Mutate roles; some transitions Admin-only in `task_transitions.py` |

‡ Viewer blocked; Analyst may be blocked on Admin-only transition kinds.

---

## `/api/v1/assessment-reports/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/` | R | R | R | `_REPORT_READ_ROLES` |
| `POST …/` (compose) | W | W | — | `_REPORT_WRITE_ROLES` |
| `GET …/<id>/` | R | R | R | `_REPORT_READ_ROLES` |
| `GET …/<id>/pdf/` | R | R | — | `_REPORT_DOWNLOAD_ROLES` Admin/Analyst |

---

## `/api/v1/ai/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `POST …/suggestions/fix/` | W | W | W | `_AI_READ_ROLES` (all roles may POST) |
| `POST …/suggestions/explain/` | W | W | W | same |
| `POST …/suggestions/nba/` | W | W | W | same |
| `POST …/narratives/report/` | W | W | W | same |

Company scoping via `get_user_company` — isolation covered in Phase 2 (`test_m3_sec01_tenant_isolation`).

---

## `/api/v1/audit/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/events/` | R | R | R | `_AUDIT_ROLES` |
| `POST …/events/<id>/mark-read/` | W | W | W | same (soft mutate) |
| `GET …/notifications/` | R | R | R | same |
| `POST …/notifications/mark-all-read/` | W | W | W | same |

---

## `/api/v1/search/`

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| `GET …/` | R | R | R | `_SEARCH_ROLES` — company-scoped |

---

## Honest findings (packet residuals)

| # | Finding | Follow-up |
|---|---------|-----------|
| F1 | `TenantViewSet` global `.all()` + no role gate | **Fixed Phase 3** — scoped; create/destroy 403; Admin update; slug/is_active RO |
| F2 | `DataRunViewSet` foreign `?tenant=` + no role gate | **Fixed Phase 3** — caller tenant only; tenant_slug RO; force tenant on write |
| F3 | `POST /connectors/verify/` has no role gate | Documented residual (not hardened in SEC-01) |
| F4 | Team `GET /invites/` open to Viewer | Matches current product; document |
| F5 | AI POSTs allowed for Viewer | Matches `_AI_READ_ROLES`; isolation covered Phase 2 |
| F6 | QA run allowed for Viewer | PRD-QA-01 intentional |

**Viewer must not write** on mutating money/connect/score surfaces: writeback execute/rollback, DCS run start, connector fetch, AF start, handoff activate — **already Admin-gated**. Viewer write exceptions above are intentional product choices (QA, AI suggest, audit mark-read). F1/F2 ViewSet leaks fixed in Phase 3.
