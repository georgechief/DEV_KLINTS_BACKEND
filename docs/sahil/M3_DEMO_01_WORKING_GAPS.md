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

**Client Excel:** [BLOCKERS_AND_GAPS_BRIEF_v2.xlsx](./BLOCKERS_AND_GAPS_BRIEF_v2.xlsx) (Lumera + MCP callouts; refreshed 2026-09-23 for Live WBs) · prior: [CLIENT_BLOCKERS_AND_GAPS_BRIEF.xlsx](./CLIENT_BLOCKERS_AND_GAPS_BRIEF.xlsx)

## Writeback / Fix-path gaps (updated 2026-09-29 · REAL-01 Phase A)

**Marked gap — G10 PT-04 writeback** — **Closed by WB-11** (stamp) + **WB-12** (PASS when `klints_net_ltv` ≈ Shopify net on re-score). Treating loop: Approve → re-run DCS → PT-04 can PASS.

| Item | Detail |
|------|--------|
| **Gap (was)** | CheckMaster + WF pack say **PT-04 = Automated writeback (A)**, so Fix should stop on **Approve → execute** like CI-01/CC-03. |
| **Reality (now)** | Mapping + registry + `WritebackAllowedCheck` + FE allowlist shipped (WB-11). |
| **Remaining honesty** | After WB-12: re-run DCS after Approve; PASS when stamp ≈ Shopify net (partial batch may still FAIL until all stamped). |

### Writeback status (CheckMaster vs registry + allowlist)

Compare: CheckMaster `fix_type` contains writeback vs registry enabled + `WritebackAllowedCheck`.  
SoT: `WRITEBACK_FIX_OWNERSHIP_MVP1_42.md` + `WRITEBACK_POSSIBLE_NOT_SHEET.csv` (not this table alone).

| check_id | CheckMaster writeback? | Mapping | Registry enabled | DB allowlisted | Status |
|----------|------------------------|---------|------------------|----------------|--------|
| **CI-01** | Yes | Yes | **Yes** | **Yes** | Live path OK |
| **CC-03** | Yes | Yes | **Yes** | **Yes** | Live path OK (Data lead owner; Approve exception) |
| **WB-SHOP-01** | Sandbox proof | Yes | **Yes** | **Yes** | Live path OK |
| **LE-01** | Yes | **Yes** | **Yes** | **Yes** | **Live (WB-08)** — PURCHASE `event_ingest` |
| **SP-07** | Yes | **Yes** | **Yes** | **Yes** | **Live (WB-09)** — namespace rename |
| **LE-09** | Yes | **Yes** | **Yes** | **Yes** | **Live (WB-10)** — RETURN `event_ingest` |
| **PT-04** | Yes | **Yes** | **Yes** | **Yes** | **Live (WB-11+WB-12)** — stamp `klints_net_ltv`; re-score PASSes when stamp ≈ net |
| **LE-05** | Yes | **Yes** | **Yes** | **Yes** | **Live (WB-13)** — order-level PURCHASE gap |
| **CI-03** | Yes | Plan mapping | **Yes** (plan) | No FE Approve | **Plan-only (WB-16A)** — Preview/Download; CRM executes in Manago |
| **LE-04** | Pack ≠ pure writeback | Stub | No | No | Intentionally off (PRD) |
| **SP-01** | (stub) | Stub | No | No | Disabled stub — not in MVP1-42 |
| **LE-02** | Yes | **Yes** | **Yes** | **Yes** | **Live (WB-14)** — matched PURCHASE value → Shopify gross via `event_correct` |
| **CI-05** | Yes | **`contact_upsert`** | CI-05.identity_key_repair.v1.json | Yes (WB-15) | Live — missing_link_key backfill; reused → CI-03 |
| **SP-03** | Yes | **Yes** | **Yes** | **Yes** | **Live (WB-19)** — detail schema normalize Approve |
| **PT-03** | Yes | **Yes** | **Yes** | No FE Approve yet | **Preview live (WB-20)** — execute blocked until PRODUCT.IMPORT confirmed |
| **CC-01** | Yes | Plan mapping | **Yes** (plan) | No FE Approve | **Plan-only (WB-17A)** — Data lead; Preview/Download |
| **CC-02** | Yes | Plan mapping | **Yes** (plan) | No FE Approve | **Plan-only (WB-18A)** — Data lead; Preview/Download |
| **PT-01** | Yes | **None** | — | No | **Not Klints execute** — External integrator (ID convention) |
| **BR-01** | Yes | **None** | — | No | **Not Klints execute** — Data lead / ERP margin |
| **LE-08** | Yes | **None** | — | No | **Not Klints execute** — External integrator |

Closed treating loops (Approve → re-score): **CI-01 / CI-05 / LE-01 / LE-02 / LE-05 / LE-09 / SP-07 / SP-03 / PT-04 / CC-03**.  
**REAL-01:** Studio/Handoff gates use `REQUIRE_*=True` (real path). Do **not** set flags False to unlock — clear FAIL checks or Architecture instead. Steps UI for non-Approve = REAL-01 Phase B.

### Related product trap (not writeback code)

| Trap | Detail |
|------|--------|
| Gate without Fix execute | FAIL gating check blocks Studio/Handoff, but check has no writeback → manual/External/Data lead path + re-score (REAL-01 §5), **not** demo flags. |
| Demo bypass ≠ writeback | **Historical only:** Flag=False unlocked Studio/Handoff while checks FAIL. **Real path (REAL-01 Phase A):** all three REQUIRE_* = **True**. Neither ever replaces Fix Approve for open gaps. |
| Fixture issues in prod FE | **FE-13:** `iss-*` fixtures blocked when `import.meta.env.PROD` (`fixturesAllowedInBuild`). Prototype `Frontend_design` is not production. |

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
