# M3-DEMO-01 — Phase 5 notes (verify script + theater register)

**Date:** 2026-09-15  
**Branch:** `feature/m3-demo-01-shopify-klints-dev`  
**PRD:** [PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md)  
**Prior:** [PHASE_4](./M3_DEMO_01_PHASE_4.md) · [SHOPIFY_PATH](./M3_DEMO_01_SHOPIFY_PATH.md)

| Slice | Status |
|-------|--------|
| **Verify script (Sahil)** | **DONE** — `scripts/verify_m3_demo01_backend.py` |
| **§11 A5 (static)** | **PASS** · staging Loom still Phase 6 |
| **PRD Phase 5** | **DONE** for repo prep |

## Goal

Ship `verify_m3_demo01_backend.py`: static gates for docs, theater register, Phase 2 import fixes, and Phase 3–4 evidence docs. Optional Django tests for bootstrap health.

## Checklist

| # | Task | Done |
|---|------|------|
| 5.1 | Create `scripts/verify_m3_demo01_backend.py` | [x] |
| 5.2 | Lock docs chain (PRD · phases 0–5 · SHOPIFY_PATH · GAPS) | [x] |
| 5.3 | Theater register static asserts (no seed-as-M3 · no Grafana here) | [x] |
| 5.4 | Phase 2 code gates (scopes · PARTIAL_FETCH · recompute) | [x] |
| 5.5 | `--run-tests` → `test_bootstrap_health` | [x] |
| 5.6 | Update WORKING_GAPS + PRD + README | [x] |
| 5.7 | Deep-check harden weak asserts | [x] |

## Run

```bash
cd klints_backend
python scripts/verify_m3_demo01_backend.py
python scripts/verify_m3_demo01_backend.py --run-tests
```

## What the verify script checks

| Section | Gates |
|---------|--------|
| Docs | PRD · WORKING_GAPS · SHOPIFY_PATH · PHASE_0–6 · README PHASE_6 link |
| Runbook | klints-dev Admin URL · Simple Sample Data · DCS-10 · credentials · staging callback · routes · Manago stop-and-flag |
| Theater | Seed not M3 AC · OBS-01B separate · Gate B · HO-02 · MCP forbid · score &lt; 70 Studio honesty |
| Code | `read_locations` · PARTIAL_FETCH notes-only · `build_latest_bootstrap_payload` → recompute · connector reconcile · stale tests |
| Phase 4 | blocked_dcs_score · DP1 readiness · GAP-01F contrast · HO-02 |
| Phase 3 | Local contact/order evidence + API path (not hardcoded forever-counts) |
| GAP-01F | Stubs / not live OAuth · not rebranded as M3-DEMO-01 |
| §11 prep | A1–A10 in PRD · A5 tied to verify |

## Deep-check (2026-09-15 audit)

| Gap found | Fix |
|-----------|-----|
| Weak `"human" in prd` / `"not" in path` tautologies | Require **HO-02**, explicit **NOT the M3 demo AC**, theater rows |
| Weak GAP-01F `"or not in lower"` always-true | Require stubs / not live OAuth · forbid `M3-DEMO-01` rename |
| Missing wiring assert | `build_latest_bootstrap_payload` must call `recompute_health_report_summary` |
| Missing test locks | `StaleHealthReportRecomputeTests` + page-size PARTIAL_FETCH test |
| Hardcoded 189/250 in verify | Softened to local contact/order + numeric evidence (survives sample growth) |
| Missing staging callback / Manago stop-and-flag gates | Added |
| PHASE_DOCS omitted PHASE_5 | Included |
| Duplicate gap id **G6** (verify + §11) | Split → **G6** verify · **G9** §11 |

## Validate (2026-09-15)

```bash
python scripts/verify_m3_demo01_backend.py          # static PASS
python scripts/verify_m3_demo01_backend.py --run-tests  # + bootstrap_health + connector list (21)
```

## Exit

Phase 5 **done** for Sahil prep (hardened).  
**Next:** [Phase 6](./M3_DEMO_01_PHASE_6.md) — Sahil ship DONE (local-only A3).

## Do not

Claim §11 complete · claim staging smoke · claim verify replaces live OAuth proof
