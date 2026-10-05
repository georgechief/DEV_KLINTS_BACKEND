# M3-DEMO-01 — Phase 2 notes (connect/import holes)

**Date:** 2026-09-15  
**Branch:** `feature/m3-demo-01-shopify-klints-dev`  
**PRD:** [PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md)  
**Prior:** [PHASE_0](./M3_DEMO_01_PHASE_0.md) · [PHASE_1](./M3_DEMO_01_PHASE_1.md) · [SHOPIFY_PATH](./M3_DEMO_01_SHOPIFY_PATH.md)

## Goal

Fix BE holes that block or mis-signal live klints-dev connect/import. **No staging §11 yet.**

## Checklist

| # | Task | Done |
|---|------|------|
| 2.1 | Inventory connect/import holes from local smoke | [x] |
| 2.2 | Expand `SHOPIFY_SCOPES` (+ `read_locations` capability) | [x] |
| 2.3 | Remove false `PARTIAL_FETCH` %250 degraded heuristic | [x] |
| 2.4 | Tests for exact page-size orders + notes-based partial | [x] |
| 2.5 | Update runbook / WORKING_GAPS | [x] |
| 2.6 | Recompute stale health on connector list (Phase 3 audit) | [x] |

## Holes found → fixed

| Hole | Impact | Fix |
|------|--------|-----|
| OAuth scopes missing `read_locations` (and related) | Inventory 403; incomplete BR-02 path | `.env.example` + `settings` default + `SHOPIFY_ADMIN_SCOPE_CAPABILITY_HANDLES` |
| `PARTIAL_FETCH` when order/customer count % 250 == 0 | Shopify card **degraded** after sample fill even when fetch fully paginated | Drop heuristic; warn only from snapshot notes mentioning truncat/partial |
| Persisted `health_report` still degraded after deploy | Pre-fix bootstrap runs kept stale PARTIAL_FETCH in metadata | Phase 3: recompute postflight from snapshot on connector list + reconcile status |
| List API returned stale `status` before reconcile | UI could still show degraded after Phase 2/3 fix | Phase 6 closeout: set `status` **after** `_latest_bootstrap_for_connector` |

## Not a Phase 2 code hole

| Item | Notes |
|------|--------|
| Inactive refresh token | Ops: reconnect (documented in SHOPIFY_PATH) |
| Score ~44 / Studio blocked | Data mismatch — Phase 3–4 honesty, not import bug |
| Staging `DEV_ENV_FILE` scopes | Rohan confirm |

## Validate

```bash
python manage.py test dataruns.tests.test_bootstrap_health --keepdb
```

## Exit

Phase 2 **done** (two import/health fixes).  
**Next:** [Phase 3](./M3_DEMO_01_PHASE_3.md) · [Phase 4](./M3_DEMO_01_PHASE_4.md) — full path + DP1 readiness.

## Do not

Claim score ≥ 70 · claim staging §11 · mix Grafana · leave seed as M3 AC
