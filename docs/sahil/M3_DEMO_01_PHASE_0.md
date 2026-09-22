# M3-DEMO-01 — Phase 0 notes (lock / inventory)

**Date:** 2026-09-15  
**Branch:** `feature/m3-demo-01-shopify-klints-dev` (from `main` @ `811edbe` after OBS-01B merge)  
**PRD:** [PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md)  
**SoT:** Live Shopify **klints-dev** + [Simple Sample Data](https://admin.shopify.com/store/klints-dev/apps/simple-sample-data)  
**Not SoT:** `seed_demo_tenant` / [GAP_01F_DEMO_PATH.md](./GAP_01F_DEMO_PATH.md) for M3 claim  

## Goal

Lock shop, scopes, callbacks, and Manago honesty rules. Inventory what already works. **No claim of §11 done.**

## Checklist

| # | Task | Done |
|---|------|------|
| 0.1 | Branch from latest `main` | [x] `feature/m3-demo-01-shopify-klints-dev` |
| 0.2 | Read PRD + DCS-10 + GAP_01F (legacy non-AC) | [x] |
| 0.3 | Lock shop URL + Simple Sample Data app | [x] below |
| 0.4 | Lock Shopify scopes (local + example) | [x] below — staging `DEV_ENV_FILE` confirm Rohan |
| 0.5 | Document OAuth callback / frontend redirect shapes | [x] below |
| 0.6 | Rohan Q1–Q4 (drafted; staging still confirm) | [x] drafted |
| 0.7 | Capture local smoke facts (not staging proof) | [x] below |
| 0.8 | Update WORKING_GAPS | [x] |

## Locked inventory

| Item | Value |
|------|--------|
| Shop | **klints-dev** (`klints-dev.myshopify.com`) |
| Sample app | [Simple Sample Data](https://admin.shopify.com/store/klints-dev/apps/simple-sample-data) |
| Klints path | Connect Shopify OAuth → DCS ([DCS-10](./PRD_DCS_10_FRESH_IMPORT_BEFORE_SCORE.md) fresh import) → contacts in Klints |
| Grafana | **Out of scope** → [OBS-01B](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md) |
| Seed script | Local smoke only — **not** M3 AC |

### Shopify scopes (OAuth request list)

Local / `.env.example` / settings default (must match code on this branch):

```text
read_customers,write_customers,read_orders,read_products,read_inventory,read_locations,read_store_credit_account_transactions
```

**Must reconnect Shopify after changing scopes.**  
**Rohan:** confirm same string in staging `DEV_ENV_FILE` / droplet `.env`.

### Callbacks (shapes — env-specific)

| Key | Local example | Staging (confirm with Rohan) |
|-----|---------------|------------------------------|
| `SHOPIFY_OAUTH_REDIRECT_URI` | ngrok → `/api/v1/connectors/shopify/callback/` | expected `https://apis.klints.io/api/v1/connectors/shopify/callback/` |
| `FRONTEND_SHOPIFY_REDIRECT_URL` | `http://localhost:8080/integrations` | expected `https://klints-frontend.vercel.app/integrations` |

Do **not** commit secrets (`SHOPIFY_API_KEY` / `SECRET`).

## Rohan / ops checklist (Q1–Q4)

| # | Question | Phase 0 answer | Still need |
|---|----------|----------------|------------|
| Q1 | Staging Shopify app creds for klints-dev? | Local reconnect works; staging assumed same Partners app | **Confirm** on staging |
| Q2 | Volume if sample app &lt; 5k? | **Document actual count**; not a hard fail unless contract insists exact 5k | Confirm if employer needs exact 5k |
| Q3 | Manago required? | **Connect if present** (current: ~2k profiles, live). If blocked → **stop-and-flag**. Do not fake via seed | Keep honest in Phase 3–4 |
| Q4 | Grafana? | **Yes — OBS-01B only** | Locked |

## Local facts already observed (2026-09-14 → 15)

| Fact | Detail |
|------|--------|
| Shopify reconnect | Required after inactive refresh token; import works after OAuth |
| Sample data | In progress via Simple Sample Data (contacts/orders growing) |
| Latest bootstrap (local) | ~189 contacts · 250 orders · inventory 250 (after scopes) |
| Connector badge | Was false **degraded** on 250 orders (`PARTIAL_FETCH` heuristic) — **fixed Phase 2** |
| Manago | Connected; large sample set (~2k+) |
| DCS | **Runs** with both connectors; headline ~**43–44**, `INCOMPLETE` |
| Studio | BUILD BLOCKED (score &lt; 70) — **out of DEMO-01 must-prove**; document honesty in Phase 4 |

## Gaps still open after Phase 0–1

| Gap | Owner | Phase |
|-----|--------|-------|
| Staging OAuth + scopes confirmed | Rohan | residual post-merge |
| Connect/import code holes | Sahil | **2–6 done** |
| Local smoke evidence | Sahil | **3 done** |
| verify_m3_demo01_backend.py | Sahil | **5 done** |
| §11 Sahil ship | Sahil | **6 done** (local-only A3) |

## Deep-check (2026-09-15)

- Phase 0 checklist complete for repo lock; Rohan staging confirm still open (expected).  
- Stale “runbook not yet” wording removed after Phase 1.  
- Staging callback URLs made concrete (expected hosts).

## Exit

Phase 0 **done** for repo lock + local inventory.  
**Next:** Phase 1 closed — [M3_DEMO_01_PHASE_1.md](./M3_DEMO_01_PHASE_1.md) + [M3_DEMO_01_SHOPIFY_PATH.md](./M3_DEMO_01_SHOPIFY_PATH.md). Phase 2 only if connect/import hole; else Phase 3 smoke.

## Do not

Claim contacts from seed · mix Grafana · claim Studio unlocked · commit `.env` secrets · require exact 5k without documenting actual
