# M3-DEMO-01 — Phase 6 notes (§11 + Loom / PR closeout)

**Date:** 2026-09-15  
**Branch:** `feature/m3-demo-01-shopify-klints-dev`  
**PRD:** [PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md)  
**Prior:** [PHASE_5](./M3_DEMO_01_PHASE_5.md) · [SHOPIFY_PATH](./M3_DEMO_01_SHOPIFY_PATH.md) · [WORKING_GAPS](./M3_DEMO_01_WORKING_GAPS.md)

| Slice | Status |
|-------|--------|
| **Sahil ship (repo + local AC)** | **DONE** (2026-09-15) — §11 local-only accept · PR ready |
| **Staging residual (Rohan)** | **Post-merge handoff** — A2 staging OAuth · staging A3 screenshot · A10 |
| **PRD Sahil close** | **DONE** — employer §11 paste with explicit local-only A3 |

## Goal

1. Close Sahil AC: docs + code + local smoke + verify  
2. Honest §11 with **local-only A3** (staging residual tracked)  
3. PR draft ready · **user commits manually**  

## Ownership split

| Owner | Scope |
|-------|--------|
| **Sahil** | Phases 0–6 ship, verify PASS, §11 local accept, PR body |
| **Rohan / ops (post-merge)** | Staging A2/A3 evidence · A10 review · scopes on droplet |

## Sahil checklist

| # | Task | Done |
|---|------|------|
| S1 | §11 paste with local-only A3 accept | [x] |
| S2 | PR title + body draft | [x] |
| S3 | Local evidence refs (Phase 3–4) | [x] |
| S4 | Staging residual checklist for Rohan | [x] |
| S5 | WORKING_GAPS Phase 6 Sahil close | [x] |
| S6 | Manual commit (user) — no agent commit | [x] noted |
| S7 | Full deep-check all phases + list status-order bugfix | [x] |

## Residual ops (post-merge — does not block Sahil ship)

| # | Task | Done |
|---|------|------|
| R1 | Confirm `SHOPIFY_SCOPES` + callbacks on staging | [ ] |
| R2 | Connect klints-dev on staging (A2) | [ ] |
| R3 | Staging DCS → paste counts (A3 staging) | [ ] |
| R4 | Optional Loom L1–L5 | [ ] |
| R5 | Rohan A10 review | [ ] |

### Staging smoke (when Rohan available)

Follow [M3_DEMO_01_SHOPIFY_PATH.md](./M3_DEMO_01_SHOPIFY_PATH.md) on `apis.klints.io` / Vercel.

## Loom / screenshot checklist (staging residual)

| Shot | Surface | Expect |
|------|---------|--------|
| L1 | Shopify Admin Simple Sample Data | Customers/orders exist |
| L2 | Staging `/integrations` | Shopify + Manago connected |
| L3 | Staging `/data-consistency` | Score + import counts |
| L4 | Staging `/fix` | Live FAIL/WARN |
| L5 | Staging `/workflow?uc=UC-02` | Needs higher score if &lt; 70 |

**Local proven (2026-09-15):** [PHASE_3](./M3_DEMO_01_PHASE_3.md) · [PHASE_4](./M3_DEMO_01_PHASE_4.md) — 189 contacts · 250 orders · score 43.549 · 0 ready pilots.

## §11 paste block (Sahil ship — local-only A3)

```markdown
### M3-DEMO-01 employer acceptance (§11)

**Live Shopify klints-dev + Simple Sample Data → Klints import · not seed_demo_tenant · Grafana = OBS-01B**

- [x] **A1** — Runbook uses Simple Sample Data on klints-dev — [M3_DEMO_01_SHOPIFY_PATH.md](./M3_DEMO_01_SHOPIFY_PATH.md)
- [ ] **A2** — Staging Klints connected to klints-dev via OAuth — **residual ops / Rohan** (local OAuth proven)
- [x] **A3** — Fresh import / DCS pulls Shopify sample contacts — **local-only accept** 2026-09-15: 189 contacts · 250 orders · API `latest_bootstrap` · [PHASE_3](./M3_DEMO_01_PHASE_3.md)  
  - Staging repeat = residual handoff (not blocking Sahil ship)
- [x] **A4** — Demo path documented; seed cited **not** M3 AC — PHASE_4 + SHOPIFY_PATH theater
- [x] **A5** — `python scripts/verify_m3_demo01_backend.py` (+ `--run-tests`) **PASS**
- [x] **A6** — Grafana not mixed; points to OBS-01B
- [x] **A7** — No MCP / Gate B closed / pen-test claims (theater register)
- [x] **A8** — Manago honest — **connected** ~2k+ (local)
- [x] **A9** — Phase 0–6 notes + WORKING_GAPS updated
- [ ] **A10** — Rohan review — **residual** _name / date_

**Local-only note:** A3 accepted on local smoke evidence. A2 + staging A3 + A10 remain post-merge ops.

**Verify command:** `python scripts/verify_m3_demo01_backend.py --run-tests`

**Allowed claim:**  
M3 demo path uses live Shopify shop **klints-dev** with Simple Sample Data; Klints imports contacts via normal connect + fresh import.

Signed off (Sahil ship): Sahil / 2026-09-15  
Ops residual: _Rohan / date_
```

## Final deep-check (all phases — 2026-09-15)

| Phase | Verdict |
|-------|---------|
| 0 Lock | Pass — shop/scopes/callbacks locked; Rohan staging confirm residual |
| 1 Runbook | Pass — SHOPIFY_PATH + credentials + theater |
| 2 Code | Pass — scopes · PARTIAL_FETCH · recompute · **list status-order bug fixed** |
| 3 Smoke | Pass — local A3 evidence |
| 4 Full path + DP1 | Pass — honest Studio block |
| 5 Verify | Pass — static + 21 tests |
| 6 §11 | Pass — Sahil ship with local-only A3 |

### Bug fixed this closeout

| Bug | Fix |
|-----|-----|
| `GET /api/v1/connectors/` returned stale `status` | Serialize `status` **after** bootstrap reconcile (was captured before) |
| No list-level regression test | `test_list_reconciles_stale_degraded_status_after_partial_fetch_retire` |

## PR draft

**Title:** `feat(M3-DEMO-01): live Shopify klints-dev demo path + import health fixes`

**Body:**

```markdown
## Summary
- Live demo SoT: Shopify **klints-dev** + Simple Sample Data → OAuth → DCS-10 fresh import (not `seed_demo_tenant`)
- Runbook + Phase 0–6 notes + WORKING_GAPS
- Connect/import fixes: full `SHOPIFY_SCOPES` (+ `read_locations`), remove false PARTIAL_FETCH %250, recompute stale health; connector list returns reconciled `status`
- `scripts/verify_m3_demo01_backend.py` static + bootstrap_health / connector-list tests
- §11 Sahil ship with **local-only A3**; staging A2/A3 + A10 = post-merge Rohan residual

## Test plan
- [x] `python scripts/verify_m3_demo01_backend.py` → PASS
- [x] `python scripts/verify_m3_demo01_backend.py --run-tests` → PASS
- [x] `manage.py test dataruns.tests.test_bootstrap_health tenants.tests.test_connector_list_latest_bootstrap` → 21 OK
- [ ] Residual: staging connect + DCS evidence (Rohan)

## Allowed claim
M3 demo path uses live Shopify **klints-dev** with Simple Sample Data; Klints imports via connect + fresh import.

## Do not claim
seed_demo_tenant as M3 AC · score ≥ 70 / Studio unlocked · DP1 partner PII live · Gate B closed · MCP · Grafana done here · exact 5k Shopify · staging OAuth proven
```

## Validate

```bash
cd klints_backend
python scripts/verify_m3_demo01_backend.py --run-tests
```

## Exit

| Exit | Status |
|------|--------|
| Sahil Phase 6 ship | **Met** |
| Staging residual | Tracked for Rohan post-merge |

## Do not

Agent git commit · claim A2 without staging · claim Studio unlocked · mix Grafana · claim seed is M3 path
