# M3-SEC-01 — Phase 1 notes (RBAC matrix)

**Date:** 2026-09-11  
**Branch:** `feature/m3-sec-01-rbac-isolation-packet`  
**Depends on:** Phase 0 complete  

## Goal

Author the product RBAC matrix for every `/api/v1/*` family from live code gates; stub verify script asserts.

## Checklist

| # | Task | Done |
|---|------|------|
| 1.1 | Create `docs/security/M3_SEC_01_RBAC_MATRIX.md` | [x] |
| 1.2 | Cover every family from `core/urls.py` | [x] |
| 1.3 | Document Django `/admin/` separately from `User.Role` | [x] |
| 1.4 | Flag ViewSet leaks + honest Viewer write exceptions | [x] |
| 1.5 | Stub `scripts/verify_m3_sec01_backend.py` (matrix asserts) | [x] |
| 1.6 | Run verify → PASS | [x] |
| 1.7 | Deep recheck: add missing `GET …/qa/` + `GET …/handoff/` package rows | [x] |

## Deliverables

| Path | Role |
|------|------|
| `docs/security/M3_SEC_01_RBAC_MATRIX.md` | Method × Admin/Analyst/Viewer + code gate notes |
| `scripts/verify_m3_sec01_backend.py` | Phase 1 static gate (soft-skips later phases) |

## Key findings carried to later phases

| ID | Finding | Phase |
|----|---------|-------|
| F1 | `TenantViewSet` global list | 3 |
| F2 | `DataRunViewSet` foreign `?tenant=` | 3 |
| F3 | Connector verify has no role gate | 4 (optional harden) / packet |
| F4–F6 | Viewer QA / AI / invite-list GET = current product | document only |

## Exit

Phase 1 done when matrix complete for all families and `python scripts/verify_m3_sec01_backend.py` → **PASS** → start Phase 2 isolation suite.
