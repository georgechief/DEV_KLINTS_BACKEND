# PRD-DCS-02 — Foundation gates (FD-01…FD-07)

**Depends on:** CONN-01 health evidence, DCS-00/01  
**DataPack:** sheet **09** (gates), **02** (detection logic), **05** Phase 0, **08** step 1

## 1. Goal

Implement live executors for Foundation Gate checks. Blocking failures suppress headline (`BLOCKED`).

## 2. Gate inventory

| ID | Systems | Blocking when |
|----|---------|---------------|
| FD-01 | Manago | Manago required/connected and auth FAIL |
| FD-02 | Shopify | Shopify required/connected and auth/scopes FAIL |
| FD-03 | ERP | Only if `erp_in_scope=true`; else `NOT_CONNECTED` / `ERP_OUT_OF_SCOPE` |
| FD-04 | Manago + Shopify | FAIL if no rate headroom / hard rate-limit on bootstrap |
| FD-05 | Manago + Shopify (+ERP) | FAIL if neither side can supply ≥ configured history window (bootstrap 30d counts as pass for MVP1) |
| FD-06 | Manago | FAIL if account/owner topology cannot be resolved |
| FD-07 | Manago + Storefront | WARN/FAIL per sheet 02 logic; if not measurable → `UNKNOWN` + `MISSING_INPUT:tracking` (do not fake PASS) |

Weights: all `0`. Role: `GATE`.

## 3. Process per DCS run

```text
For each FD-*:
  read connector status + last bootstrap health_report
  optionally re-validate auth with a single cheap read (do not full re-fetch)
  emit check_result with evidence locators
```

Reuse CONN-01 codes:

| Health code | Gate mapping |
|-------------|--------------|
| `AUTH_FAILED` on manago | FD-01 FAIL |
| `AUTH_FAILED` on shopify | FD-02 FAIL |
| `SCOPES_MISSING` required | FD-02 FAIL |
| `RATE_LIMIT` | FD-04 FAIL |
| bootstrap succeeded 30d | FD-05 PASS (MVP1) |

## 4. Evidence shape

```json
{
  "source": "manago_ai",
  "locator": "bootstrap:data_run:123:preflight.auth_ok",
  "value": true,
  "observed_at": "2026-07-24T05:00:00Z"
}
```

## 5. Files

| File | Change |
|------|--------|
| `dataruns/dcs/executors/foundation.py` | FD-01…07 |
| `dataruns/dcs/executors/registry.py` | register |
| tests using recorded health_report fixtures | — |

## 6. Acceptance

1. Manago auth broken → FD-01 FAIL → assemble `BLOCKED`, `headline_score=null`.  
2. ERP out of scope → FD-03 `NOT_CONNECTED`, not blocking.  
3. Both bootstraps OK → FD-01/02/05 PASS with HIGH confidence.  
4. Matches sheet 08: blocking gate suppresses headline.
