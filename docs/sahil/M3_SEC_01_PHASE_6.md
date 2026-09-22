# M3-SEC-01 — Phase 6 notes (employer §11 / PR ready)

**Date:** 2026-09-11 (updated 2026-09-12 testing day + deep recheck)  
**Branch:** `feature/m3-sec-01-rbac-isolation-packet` @ `782fe58` + **uncommitted** deep-recheck polish  
**Depends on:** Phase 5 complete  
**Commit:** base ship on branch; today’s ViewSet/RBAC/writeback tightenings pending operator commit  
**Deep-recheck:** 2026-09-11 — A2 honesty, A10 split, PR §12 paste  
**Testing day:** 2026-09-12 morning — verify PASS + **74** SEC-01 tests OK  
**Deep recheck:** 2026-09-12 afternoon — Steps 2–6 code/docs pass; suites **83 OK**; verify PASS  

## Goal

Run employer acceptance §11, capture evidence, leave PR-ready paste for Rohan review (PRD §11 / §12 / §14).

## Evidence run

### 2026-09-12 (deep recheck — current)

```text
python scripts/verify_m3_sec01_backend.py
→ PASS — M3-SEC-01 static gate (Phase 1–5)

python manage.py test dataruns.tests.test_m3_sec01_tenant_isolation dataruns.tests.test_m3_sec01_rbac_negatives tenants.tests.test_m3_sec01_tenant_isolation --keepdb
→ Ran 83 tests … OK
```

Delta vs morning 74: DataRun isolation edge tests + RBAC bootstrap/owners/api-v3-key/Analyst tenant create-destroy + writeback Viewer-before-action negatives.

### 2026-09-12 (testing day morning)

```text
python scripts/verify_m3_sec01_backend.py
→ PASS — M3-SEC-01 static gate (Phase 1–5)

python manage.py test dataruns.tests.test_m3_sec01_tenant_isolation dataruns.tests.test_m3_sec01_rbac_negatives tenants.tests.test_m3_sec01_tenant_isolation --keepdb
→ Ran 74 tests … OK
```

### 2026-09-11 (original §11 capture)

```text
python scripts/verify_m3_sec01_backend.py
→ PASS — M3-SEC-01 static gate (Phase 1–5)

python manage.py test … (same modules)
→ Ran 73 tests … OK  (PDF Viewer negative added later → 74)
```

## §11 checklist

| ID | Item | Status | Evidence |
|----|------|--------|----------|
| A1 | Matrix covers every `/api/v1/*` family | [x] | Verify family checks PASS |
| A2 | Cross-tenant minimum allowlist | [x] | See **A2 map** below (new suites + cites — not “83 tests alone”) |
| A3 | RBAC negatives green | [x] | `test_m3_sec01_rbac_negatives` in 83-test run |
| A4 | ViewSets no longer leak | [x] | Phase 3 tests in tenants isolation module + verify source gates |
| A5 | Verify script PASS | [x] | PASS Phase 1–5 (re-run 2026-09-12 deep recheck) |
| A6 | Audit evidence `verify_audit_chain` + `0030` + immutability | [x] | `M3_SEC_01_AUDIT_EVIDENCE.md` + packet §5 |
| A7 | Packet residual + theater | [x] | Packet §7 / §8; verify residual/theater gates |
| A8 | Secret masking / audit sanitize cited | [x] | Audit evidence § hygiene |
| A9 | PR does not claim theater items | [x] prepared | Paste body below is theater-safe; confirm when opening PR |
| A10a | WORKING_GAPS + phase notes updated | [x] | This file + WORKING_GAPS + PHASE_0…5 |
| A10b | Rohan review requested | [ ] operator | After commit / push / open PR |

### A2 map (honest — PRD minimum allowlist)

| Family | How A2 is met |
|--------|----------------|
| Writebacks | **New** `dataruns/tests/test_m3_sec01_tenant_isolation.py` |
| DCS | **New** same module |
| Connectors | **New** `tenants/tests/test_m3_sec01_tenant_isolation.py` (+ cite existing connector tests) |
| Team | **New** tenants SEC-01 isolation |
| Audit | **Cite** `dataruns/tests/test_audit.py` (isolation + mark-read) |
| Orchestration | **Cite** `test_orch_sm_phase2.py`, `test_orch_sm_phase3.py` |
| Handoff | **Cite** `test_handoff_package_step*`, `test_handoff_ho02_phase*` |
| ViewSets | **New** tenants SEC-01 ViewSet tests (Phase 3) |

Do **not** claim the SEC-01 command alone re-ran orch/handoff/audit modules.

## Definition of done (§14) — Phase 6 slice

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Phase 0–5 exits met | [x] |
| 2 | Verify PASS | [x] |
| 3 | Isolation + RBAC suites green locally | [x] **83 OK** (2026-09-12 deep recheck) |
| 4 | §11 pasteable with evidence | [x] this file |
| 5 | Honest claim language in PR paste | [x] prepared below |
| — | Merge / Rohan review | [ ] commit + open PR + A10b |

## Allowed claim (use in PR after open)

> Internal M3-SEC-01 security review packet complete; RBAC matrix and automated cross-tenant / role-negative tests green; audit tamper-detection controls evidenced (hash chain + DB immutability).

## PR paste (manual commit / open)

**Title:**

```text
feat(M3-SEC-01): RBAC matrix, tenant isolation evidence, security packet
```

**Body:**

```markdown
## Summary
- Evidence + targeted harden for M3-SEC-01 (RBAC matrix, tenant isolation, RBAC negatives, audit evidence, security review packet).
- Reuse AUDIT-01 hash chain / `0030` immutability — packaged, not rebuilt.
- Hardened `TenantViewSet` / `DataRunViewSet`; Admin-only tenant update; writeback `/run/` Viewer-first then role-before-keys.
- Static gate: `scripts/verify_m3_sec01_backend.py` → PASS.
- **Not claimed:** pen-test, SOC2, DP1, Grafana-as-security, MCP live.

## Test plan
- [x] `python scripts/verify_m3_sec01_backend.py` → PASS (Phase 1–5)
- [x] `python manage.py test dataruns.tests.test_m3_sec01_tenant_isolation dataruns.tests.test_m3_sec01_rbac_negatives tenants.tests.test_m3_sec01_tenant_isolation --keepdb` → 83 OK
- [x] Orch / handoff / audit isolation cited (not re-run in SEC-01 command) — see PHASE_6 A2 map

## Employer acceptance (§11)
- [x] A1–A8 evidenced (`docs/sahil/M3_SEC_01_PHASE_6.md`)
- [x] A9 — this PR does not claim pen-test / SOC2 / DP1 / Grafana-as-security
- [ ] A10 — Rohan review requested

**Allowed claim:** Internal M3-SEC-01 security review packet complete; RBAC matrix and automated cross-tenant / role-negative tests green; audit tamper-detection controls evidenced (hash chain + DB immutability).

## Packet paths
- `docs/security/M3_SEC_01_RBAC_MATRIX.md`
- `docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md`
- `docs/security/M3_SEC_01_AUDIT_EVIDENCE.md`

## Notes for Rohan
- Matrix honesty, ViewSet fix, isolation allowlist coverage, claim language.
- Residual risks: packet §7 (`get_user_company`, Grafana ≠ RBAC, Django `/admin/`, MCP Client-blocked, F3 connectors/verify).
```

## Manual commit file inventory

Include at least:

**Code**
- `tenants/views.py`, `tenants/serializers.py`
- `dataruns/views.py`, `dataruns/serializers.py`
- `dataruns/writebacks/views.py`

**Tests**
- `dataruns/tests/helpers_m3_sec01.py`
- `dataruns/tests/test_m3_sec01_tenant_isolation.py`
- `dataruns/tests/test_m3_sec01_rbac_negatives.py`
- `tenants/tests/test_m3_sec01_tenant_isolation.py`

**Docs / verify**
- `scripts/verify_m3_sec01_backend.py`
- `docs/security/M3_SEC_01_RBAC_MATRIX.md`
- `docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md`
- `docs/security/M3_SEC_01_AUDIT_EVIDENCE.md`
- `docs/sahil/M3_SEC_01_PHASE_0.md` … `PHASE_6.md`
- `docs/sahil/M3_SEC_01_WORKING_GAPS.md`
- (PRD already on branch if committed earlier)

## Git hygiene

Branch tracks `origin/feature/m3-sec-01-rbac-isolation-packet` @ `782fe58` with **local uncommitted** deep-recheck changes (writeback Viewer-first, DataRun/RBAC tests, verify, docs).

**Optional cleanup:** HEAD commit message is missing a blank line between subject and body (`…packetPackage…`). Prefer a **new** commit for today’s polish rather than amend unless you explicitly want amend + force-with-lease.

## Exit

Phase 6 evidence [x] · **83 OK** · packet/F-run wording aligned · operator: **commit → push → open/refresh PR → Rohan (A10b)**.
