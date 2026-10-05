# M3-SEC-01 — Working gaps

**PRD:** [PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md](./PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md)  
**Branch:** `feature/m3-sec-01-rbac-isolation-packet`  
**Status:** Phases 0–6 on branch (`782fe58`) + **2026-09-12 deep recheck** (uncommitted) · **83 OK** → commit/push + Rohan (A10b)

## Phase board

| Phase | Status | Notes file |
|-------|--------|------------|
| 0 — Lock / inventory | [x] | [M3_SEC_01_PHASE_0.md](./M3_SEC_01_PHASE_0.md) |
| 1 — RBAC matrix | [x] | [M3_SEC_01_PHASE_1.md](./M3_SEC_01_PHASE_1.md) |
| 2 — Isolation suite | [x] | [M3_SEC_01_PHASE_2.md](./M3_SEC_01_PHASE_2.md) |
| 3 — ViewSet harden | [x] | [M3_SEC_01_PHASE_3.md](./M3_SEC_01_PHASE_3.md) |
| 4 — RBAC negatives + audit evidence | [x] | [M3_SEC_01_PHASE_4.md](./M3_SEC_01_PHASE_4.md) |
| 5 — Packet + verify script | [x] | [M3_SEC_01_PHASE_5.md](./M3_SEC_01_PHASE_5.md) |
| 6 — Employer §11 | [x] evidence + deep recheck | [M3_SEC_01_PHASE_6.md](./M3_SEC_01_PHASE_6.md) — PR/Rohan still open |

## PRD §14 DoD

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Phase 0–5 exits met | [x] |
| 2 | `verify_m3_sec01_backend.py` PASS | [x] |
| 3 | Isolation + RBAC suites green | [x] **83 OK** (2026-09-12 deep recheck) |
| 4 | §11 pasteable with evidence | [x] PHASE_6 |
| 5 | Honest claim language prepared | [x] packet + PHASE_6 PR paste |
| — | Merge / Rohan | [ ] commit + open PR + request review |

## Deliverables (ship list)

| Item | Path |
|------|------|
| RBAC matrix | `docs/security/M3_SEC_01_RBAC_MATRIX.md` |
| Security packet | `docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md` |
| Audit evidence | `docs/security/M3_SEC_01_AUDIT_EVIDENCE.md` |
| Verify gate | `scripts/verify_m3_sec01_backend.py` |
| Isolation tests | `dataruns/tests/test_m3_sec01_tenant_isolation.py`, `tenants/tests/test_m3_sec01_tenant_isolation.py` |
| RBAC negatives | `dataruns/tests/test_m3_sec01_rbac_negatives.py` |
| Helpers | `dataruns/tests/helpers_m3_sec01.py` |
| ViewSet harden | `tenants/views.py`, `tenants/serializers.py`, `dataruns/views.py`, `dataruns/serializers.py` |
| Writeback `/run/` Viewer-first + role-before-keys | `dataruns/writebacks/views.py` |

## Residual (packet §7 — intentional, not open bugs)

`get_user_company` first-by-created_at · Grafana ≠ RBAC · Django `/admin/` · MCP Client-blocked · F3 `POST /connectors/verify/` no role gate · intentional Viewer QA/AI/audit mark-read

## Commands

```bash
python scripts/verify_m3_sec01_backend.py
python manage.py test dataruns.tests.test_m3_sec01_tenant_isolation dataruns.tests.test_m3_sec01_rbac_negatives tenants.tests.test_m3_sec01_tenant_isolation --keepdb
```

## Do not claim

Pen-test · SOC2 · DP1 · Grafana-as-security · MCP live
