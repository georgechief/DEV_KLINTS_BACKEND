# M3-SEC-01 — Testing day notes (2026-09-12)

**Employer MSF:** use today as testing and cleanup day.

## Ran today

| Check | Result |
|-------|--------|
| `python scripts/verify_m3_sec01_backend.py` | **PASS** (re-confirmed after deep recheck) |
| SEC-01 isolation + RBAC suites (morning) | **74 OK** |
| SEC-01 isolation + RBAC suites (afternoon deep recheck) | **83 OK** |
| Upstream | `origin/feature/m3-sec-01-rbac-isolation-packet` @ `782fe58` + local polish |

## Cleanup / deep recheck (same day)

- Steps 2–6 deep pass; writeback Viewer-before-action; DataRun + RBAC gap tests; packet/PHASE docs → **83 OK**
- Execute isolation assert tightened (400/403/404 only — not `>=400` which would accept 5xx)
- Verify: Tenant `partial_update` Admin gate; Writeback Viewer-before-action; DataRun `perform_update` / no tenant FK

## Still for you

1. Manual commit of local polish (code + tests + docs + verify)
2. Open or refresh the GitHub PR
3. Optional: HEAD commit message blank line (prefer new commit over amend)
4. Request Rohan review (A10b)

## Do not claim

Pen-test · SOC2 · DP1 · Grafana-as-security · MCP live
