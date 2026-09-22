# M3-SEC-01 — Phase 3 notes (ViewSet harden)

**Date:** 2026-09-11  
**Branch:** `feature/m3-sec-01-rbac-isolation-packet`  
**Depends on:** Phase 2 complete  

## Goal

Eliminate global list leaks on `TenantViewSet` and `DataRunViewSet` (PRD §5.4 / §8).

## Checklist

| # | Task | Done |
|---|------|------|
| 3.1 | Scope `TenantViewSet` to caller `tenant_id` | [x] |
| 3.2 | Forbid tenant create/destroy via this API | [x] |
| 3.3 | Scope `DataRunViewSet` to caller tenant; ignore foreign `?tenant=` | [x] |
| 3.4 | Force create/update DataRun onto caller tenant; `tenant_slug` read-only | [x] |
| 3.5 | Isolation tests for both ViewSets | [x] |
| 3.6 | Verify script source checks | [x] |
| 3.7 | Suites green | [x] |
| 3.8 | Deep recheck: Admin-only tenant update; lock `slug`/`is_active`; write negatives | [x] |

## Code changes

| File | Change |
|------|--------|
| `tenants/views.py` | `get_queryset` → `pk=user.tenant_id`; create/destroy → 403; update Admin-only |
| `tenants/serializers.py` | `slug` + `is_active` read-only (workspace invariant) |
| `dataruns/views.py` | Always `filter(tenant_id=…)`; ignore `?tenant=`; `perform_*` force tenant |
| `dataruns/serializers.py` | `tenant_slug` read-only (no writable cross-tenant assign) |
| `tenants/tests/test_m3_sec01_tenant_isolation.py` | ViewSet isolation + write/unauth negatives |

## Deep-recheck fixes (post Phase 3)

| Gap found | Fix |
|-----------|-----|
| Any role could PATCH tenant (bypassed workspace Admin gate) | `update`/`partial_update` → Admin only |
| Writable `slug` / `is_active` on TenantSerializer | read-only |
| Missing destroy / foreign PATCH / tenant_slug inject / unauth tests | added |
| Verify gate too weak (comment-only “ignore”) | assert no `tenant__slug=` filter; serializer locks |

## Acceptance (PRD §8)

```text
GET /api/v1/tenants/                         → only caller tenant
GET /api/v1/tenants/{other_slug}/            → 404
GET /api/v1/dataruns/                        → only caller runs
GET /api/v1/dataruns/?tenant={other_slug}    → must NOT return other runs
```

## Exit

Phase 3 done when ViewSet leaks closed + tests green → start Phase 4 (RBAC negatives + audit evidence).
