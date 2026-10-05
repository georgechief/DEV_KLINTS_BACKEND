# M3-DEMO-01 — Phase 1 notes (runbook + credential checklist)

**Date:** 2026-09-15  
**Branch:** `feature/m3-demo-01-shopify-klints-dev`  
**PRD:** [PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md)  
**Prior:** [M3_DEMO_01_PHASE_0.md](./M3_DEMO_01_PHASE_0.md)

## Goal

Ship the operator runbook: Simple Sample Data → connect klints-dev → fresh import / DCS → contacts visible. Credential checklist included. **No staging §11 evidence yet (Phase 3).**

## Checklist

| # | Task | Done |
|---|------|------|
| 1.1 | Write `M3_DEMO_01_SHOPIFY_PATH.md` | [x] |
| 1.2 | Credential / env checklist in runbook | [x] |
| 1.3 | Cite GAP_01F / seed as **non-AC** | [x] |
| 1.4 | Honest Studio / Manago / degraded notes | [x] |
| 1.5 | Link from README + WORKING_GAPS | [x] |
| 1.6 | Update WORKING_GAPS Phase 1 | [x] |

## Deliverable

[M3_DEMO_01_SHOPIFY_PATH.md](./M3_DEMO_01_SHOPIFY_PATH.md)

## Exit

Phase 1 **done**.  
**Next:** Phase 2 — fix connect/import holes only if smoke finds a blocker; else N/A and proceed to Phase 3 smoke evidence.

## Deep-check (2026-09-15)

| Check | Result |
|-------|--------|
| PRD ship item: runbook Simple Sample Data → connect → import | Met — SHOPIFY_PATH |
| Credential checklist | Met |
| GAP_01F / seed cited non-AC | Met |
| Theater register | Met |
| README + WORKING_GAPS + PRD G1 links | Met |
| Full `SHOPIFY_SCOPES` + staging callback hosts in runbook | Fixed this pass |
| DCS-10 link in runbook | Fixed this pass |
| Staging §11 / contact counts filled | Local done (Phase 3) · staging pending |

## Do not

Claim staging proof complete · claim seed is M3 path · mix Grafana · require score ≥ 70 for this phase
