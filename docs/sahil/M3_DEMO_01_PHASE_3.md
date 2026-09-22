# M3-DEMO-01 — Phase 3 notes (smoke + contact evidence)

**Date:** 2026-09-15  
**Branch:** `feature/m3-demo-01-shopify-klints-dev`  
**PRD:** [PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md)  
**Prior:** [PHASE_2](./M3_DEMO_01_PHASE_2.md) · [SHOPIFY_PATH](./M3_DEMO_01_SHOPIFY_PATH.md)

| Slice | Status |
|-------|--------|
| **Local smoke (Sahil)** | **DONE** (2026-09-15) — evidence below |
| **Staging smoke (Rohan)** | **PENDING** — same runbook on `apis.klints.io` |
| **PRD Phase 3 full (A3 staging)** | **Local-only accept** in §11 — staging residual Rohan |

## Goal

Prove live path: Simple Sample Data → connect klints-dev → fresh import / DCS → contacts visible. Document counts. **Honest:** score may stay low; Studio may stay blocked.

## Checklist

| # | Task | Done |
|---|------|------|
| 3.1 | Sample data in Shopify (Simple Sample Data) | [x] in progress / growing |
| 3.2 | Connect klints-dev (local tenant) | [x] reconnect after token inactive |
| 3.3 | Fresh import Shopify + Manago on DCS | [x] Celery `ok` both platforms |
| 3.4 | Document counts in SHOPIFY_PATH | [x] local block filled |
| 3.5 | API evidence (`GET /api/v1/connectors/`) | [x] local — see below |
| 3.6 | Staging repeat on Vercel + droplet | [ ] Rohan |
| 3.7 | Screenshot / Loom (optional) | [ ] |
| 3.8 | Update WORKING_GAPS | [x] |
| 3.9 | Fix stale degraded badge on 250 orders | [x] display recompute — see deep-check |

## Local smoke evidence (2026-09-15)

**Environment:** local dev · tenant **yoyo** / company `4e72da96-5cf0-4005-a16a-02a9ed91b62a` · **not** seed tenant  
**Shop:** klints-dev.myshopify.com

### Timeline

| Step | data_run | Result |
|------|----------|--------|
| DCS (inactive token) | 438 | **Failed** — `Shopify refresh token is inactive; reconnect required` |
| Reconnect OAuth | — | `POST /api/v1/connectors/shopify/start/` → callback OK |
| Bootstrap import | 439 | **189** contacts · **250** orders · inventory **250** |
| DCS fresh import | 441 Shopify · 442 Manago | Both **OK** |
| DCS score | 440 | **43.549** · `INCOMPLETE` · `blocking_gates_failed=0` |

**Celery refs:** bootstrap **439** · score **440** · run_score **f300cb90-6499-4a87-bf68-a11d6c59df96**

### Counts (honest)

| Metric | Value | Notes |
|--------|-------|--------|
| Window import (bootstrap) | 189 contacts · 250 orders | From Shopify 30-day window |
| DB contacts (company total) | **396** | Includes prior imports — window count is the honest import metric |
| DCS headline | **43.549** INCOMPLETE | Studio blocked (&lt; 70) — expected |
| Manago | **connected** | ~2k+ profiles; mismatch vs thin Shopify expected |

### API evidence (A3 partial — local)

`GET /api/v1/connectors/` → Shopify `latest_bootstrap` / `last_data_refresh` after Phase 3 deep-check fix:

| Field | Value |
|-------|--------|
| `contacts` | **189** |
| `orders` | **250** |
| `summary_status` | **ok** (recomputed from snapshot; was stale `degraded`) |
| `issue_count` | **0** |
| `data_run_id` | 439 (bootstrap) / 441 (DCS fresh import refresh) |
| Connector `status` | **connected** (reconciled on list after recompute) |

Screenshot still optional for §11; API + Celery + DB counts satisfy local A3 partial.

## Deep-check (2026-09-15 audit)

| Check | Result |
|-------|--------|
| Celery counts match docs (189/250) | **Pass** |
| Fresh import both platforms | **Pass** (441/442) |
| Path not `seed_demo_tenant` | **Pass** |
| Stale `PARTIAL_FETCH` on persisted health_report | **Bug found + fixed** — bootstrap 439/441 stored pre–Phase-2 heuristic issue; snapshot notes empty; current rules → `ok` |
| Display/API still showed degraded after Phase 2 | **Fixed** — `recompute_health_report_summary` + connector reconcile on list |
| Tests | **13** bootstrap_health (+2 recompute) · **20** total with connector list — **OK** |
| Staging repeat | Still open |

## Volume vs ~5k target (Q2)

| Source | Approx count | Notes |
|--------|-------------|--------|
| Shopify (imported window) | **189** contacts | Growing via Simple Sample Data |
| Manago (connected) | **~2k+** | Pre-existing sample; not from seed script |
| Contract ~5k | **Not met** | Document actual; stop-and-flag only if employer requires exact 5k |

## What this proves (A3 partial)

- Live Shopify sample data → Klints **fresh import** pulls contacts/orders  
- Path is **not** `seed_demo_tenant`  
- Score honesty preserved  
- Integrations API exposes import counts for demo proof  

## Still open

| Item | Owner |
|------|--------|
| Staging smoke + screenshot | Rohan residual post-merge |
| §11 Sahil ship | **Done** — [PHASE_6](./M3_DEMO_01_PHASE_6.md) local-only A3 |

## Exit

Phase 3 **local smoke done** (incl. API evidence + stale-degraded fix); staging = residual.  
**Next:** [Phase 6](./M3_DEMO_01_PHASE_6.md) Sahil ship closed.

## Do not

Claim staging §11 A3 complete · claim ~5k Shopify · claim Studio unlocked · claim seed path
