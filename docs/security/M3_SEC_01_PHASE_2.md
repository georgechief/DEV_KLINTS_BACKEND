# M3-SEC-01 — Phase 2 notes (isolation suite)

**Date:** 2026-09-11  
**Branch:** `feature/m3-sec-01-rbac-isolation-packet`  
**Depends on:** Phase 1 complete  

## Goal

Cross-company isolation tests for PRD allowlist holes; cite existing coverage for orch/handoff/QA/reports/search/audit/pilot-gates.

## Checklist

| # | Task | Done |
|---|------|------|
| 2.1 | Shared A/B fixture helper | [x] `dataruns/tests/helpers_m3_sec01.py` |
| 2.2 | Writeback HTTP A-vs-B (approval/approve/reject/rollback) | [x] |
| 2.3 | Core DCS status/history/worklist A-vs-B | [x] |
| 2.4 | Architecture assessment A-vs-B | [x] |
| 2.5 | AI fix/explain with foreign `dcs_run_id` | [x] |
| 2.6 | Team member list/patch A-vs-B | [x] |
| 2.7 | Connector list/disconnect/bootstrap A-vs-B | [x] |
| 2.8 | Cite covered families in test module docstring | [x] |
| 2.9 | Run suites green | [x] isolation green (counts grew in Phase 3+; see PHASE_6 for current 73+) |
| 2.10 | ViewSet isolation tests | deferred → **Phase 3** (done) |

## Deliverables

| Path | Role |
|------|------|
| `dataruns/tests/helpers_m3_sec01.py` | Company A/B + admin APIClient pair |
| `dataruns/tests/test_m3_sec01_tenant_isolation.py` | WB / DCS / AF / AI |
| `tenants/tests/test_m3_sec01_tenant_isolation.py` | Team / connectors |

## Commands

```bash
python manage.py test dataruns.tests.test_m3_sec01_tenant_isolation tenants.tests.test_m3_sec01_tenant_isolation --keepdb
# Ran 18 tests … OK
```

## Deep recheck (2026-09-11)

Found and fixed weak/gap issues in first Phase 2 pass:

| Issue | Fix |
|-------|-----|
| DCS status/history/AF latest assertions vacuous when B empty | Positive controls (A sees own) + assert B empty / id absent from payload |
| History missing `finished_at` | Set `finished_at` so A has real history points |
| AF `latest` looked for top-level `assessment_id` (wrong shape) | Assert nested `assessment` is None for B |
| AF only tested coverage subresource | Also assets / graph / gaps → 404 |
| Writeback execute path not covered | B execute with A's `approval_id` fail-closed + token unchanged |
| No positive control on writeback get | A can GET own approval |
| AI only fix/explain | Added NBA + report narrative foreign report id |
| Connector list empty for B (weak) | Seed B connector; assert B sees self, not A |
| Bootstrap accepted 403\|404 | Exact **404** for Admin B |
| Team invites not covered | Invite list/revoke/resend cross-tenant 404 |

**Result:** `Ran 28 tests … OK`

## Exit

Phase 2 done when isolation suites green for new allowlist holes → start Phase 3 ViewSet harden.
