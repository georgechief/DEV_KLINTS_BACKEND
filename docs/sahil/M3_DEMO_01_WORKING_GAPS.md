# M3-DEMO-01 — Working gaps

**PRD:** [PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md)  
**Branch:** `feature/m3-demo-01-shopify-klints-dev`  
**Status:** **Sahil ship DONE** · staging A2/A3 + A10 = post-merge residual · SoT = live Shopify, not seed

## Phase board

| Phase | Status | Notes |
|-------|--------|-------|
| 0 — Lock shop / scopes / staging | [x] | [PHASE_0](./M3_DEMO_01_PHASE_0.md) |
| 1 — Runbook Simple Sample Data → Klints | [x] | [PHASE_1](./M3_DEMO_01_PHASE_1.md) · [SHOPIFY_PATH](./M3_DEMO_01_SHOPIFY_PATH.md) |
| 2 — Connect/import fixes | [x] | [PHASE_2](./M3_DEMO_01_PHASE_2.md) |
| 3 — Smoke + contact evidence | Local [x] · Staging residual | [PHASE_3](./M3_DEMO_01_PHASE_3.md) |
| 4 — Full path + DP1 readiness note | [x] | [PHASE_4](./M3_DEMO_01_PHASE_4.md) |
| 5 — Verify script | [x] | [PHASE_5](./M3_DEMO_01_PHASE_5.md) · verify PASS |
| 6 — §11 + PR closeout | Sahil [x] · Staging residual | [PHASE_6](./M3_DEMO_01_PHASE_6.md) |

## Gaps

| Gap | Status |
|-----|--------|
| G1 Shopify sample-data runbook | **Done** |
| G2 OAuth klints-dev ↔ staging | **Residual ops** / Rohan (local works) |
| G3 Fresh import contacts into Klints | **Local done** (A3 local-only accept) · staging residual |
| G4 Contact count documented | **Done** (189 Shopify / ~2k Manago; not 5k) |
| G5 Manago honest status | **Connected** ~2k+ — documented |
| G6 verify script | **Done** — verify PASS |
| G7 Full path + DP1 readiness | **Done** |
| G8 FE honesty if import/score copy wrong | Optional / out of Sahil ship |
| G9 §11 Sahil ship | **Done** — local-only A3 · [PHASE_6](./M3_DEMO_01_PHASE_6.md) |
| G9b staging A2 + A10 | **Residual** post-merge |
| **G10 PT-04 writeback** | **Closed (WB-11+WB-12)** — stamp `klints_net_ltv`; re-score PASSes when stamp ≈ Shopify net · see §Writeback gaps |

**Client Excel:** [CLIENT_BLOCKERS_AND_GAPS_BRIEF.xlsx](./CLIENT_BLOCKERS_AND_GAPS_BRIEF.xlsx) — Architecture false INCOMPLETE + writeback gaps + pilot/Handoff traps (for client share).

## Writeback / Fix-path gaps (2026-09-17)

**Marked gap — G10 PT-04 writeback** — **Closed by WB-11** (stamp) + **WB-12** (PASS when `klints_net_ltv` ≈ Shopify net on re-score). Treating loop: Approve → re-run DCS → PT-04 can PASS.

| Item | Detail |
|------|--------|
| **Gap (was)** | CheckMaster + WF pack say **PT-04 = Automated writeback (A)**, so Fix should stop on **Approve → execute** like CI-01/CC-03. |
| **Reality (now)** | Mapping + registry + `WritebackAllowedCheck` + FE allowlist shipped (WB-11). |
| **Remaining honesty** | After WB-12: re-run DCS after Approve; PASS when stamp ≈ Shopify net (partial batch may still FAIL until all stamped). |

### Same class of gaps (CheckMaster “Automated writeback” but not execute-ready)

Compare: CheckMaster `fix_type` contains writeback vs registry enabled + `WritebackAllowedCheck`.

| check_id | CheckMaster writeback? | Mapping | Registry enabled | DB allowlisted | Status |
|----------|------------------------|---------|------------------|----------------|--------|
| **CI-01** | Yes | Yes | **Yes** | **Yes** | Live path OK |
| **CC-03** | Yes | Yes | **Yes** | **Yes** | Live path OK |
| **WB-SHOP-01** | Sandbox proof | Yes | **Yes** | **Yes** | Live path OK |
| **CI-03** | Yes | Stub | No | No | Gap — stub only |
| **LE-01** | Yes | Stub | No | No | Gap — stub only |
| **LE-04** | Pack ≠ pure writeback | Stub | No | No | Intentionally off (PRD) |
| **SP-01** | (stub) | Stub | No | No | Gap — stub only |
| **PT-04** | Yes | **Yes** | **Yes** | Yes | **Live (WB-11+WB-12)** — stamp `klints_net_ltv`; re-score PASSes when stamp ≈ net |
| **LE-09** | Yes | **Yes** | **Yes** | Yes | **Live (WB-10)** |
| **LE-02** | Yes | **None** | — | No | Gap — not connected |
| **LE-05** | Yes | **None** | — | No | Gap — not connected |
| **CI-05** | Yes | **None** | — | No | Gap — not connected |
| **PT-01** | Yes | **None** | — | No | Gap — not connected |
| **PT-03** | Yes | **None** | — | No | Gap — not connected |
| **SP-03** | Yes | **None** | — | No | Gap — not connected |
| **SP-07** | Yes | **Yes** | `SP-07.namespace_clean.v1.json` | Yes | WB-09 — rename collisions off namespace |
| **CC-01** | Yes | **None** | — | No | Gap — not connected |
| **CC-02** | Yes | **None** | — | No | Gap — not connected |
| **BR-01** | Yes | **None** | — | No | Gap — not connected |
| **LE-08** | Yes | **None** | — | No | Gap — not connected |

PRD-WB-02 §3.2 already lists most of these as **Approve must stay OFF** until built. Gap vs demo UX: **pilot/Handoff still gate on FAIL checks** while Fix is incomplete. **PT-04** treating loop closed by WB-11+WB-12 (Approve → re-score → PASS when stamp ≈ net).

### Related product trap (not writeback code)

| Trap | Detail |
|------|--------|
| Gate without Fix execute | FAIL gating check blocks Studio/Handoff, but check has no writeback → only manual Manago + re-score or demo bypass flags. |
| Demo bypass ≠ writeback | `REQUIRE_PILOT_GATING_CHECKS=False` unlocks Studio; `REQUIRE_HANDOFF_QA_PASS=False` opens Handoff while QA FAIL. Neither adds PT-04 writeback. |

## Local smoke snapshot (2026-09-15)

| Metric | Value |
|--------|-------|
| Shopify contacts imported | 189 |
| Shopify orders imported | 250 |
| DCS headline | 43.549 INCOMPLETE |
| Pilots ready | **0** (all **16** `blocked_dcs_score`) |
| Fix checks (live) | 15 FAIL · 1 WARN · 18 PASS (42 total) |
| Build packages | **0** |
| Architecture | INCOMPLETE · 12 lifecycle gaps |
| Verify | `python scripts/verify_m3_demo01_backend.py --run-tests` **PASS** |
| Path | Simple Sample Data → connect → fresh import ✓ |
| API `latest_bootstrap` | 189 / 250 · summary **ok** · issue_count **0** |
| Connector list `status` | **connected** (reconcile after recompute) |

## Not this PRD

- Grafana → [OBS-01B](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md)  
- `seed_demo_tenant` as M3 AC  

## Do not claim

Script-filled demo · Gate B closed · MCP live · Grafana done here · Studio unlocked · exact 5k Shopify · DP1 production live · staging OAuth proven
