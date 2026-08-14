# DCS Scoring PRD series

Implementation contracts for connector bootstrap → Data Consistency Score (DCS) on Shopify + Manago.ai data.

## Build order (do not reorder)

| # | File | Delivers |
|---|------|----------|
| 0 | [PRD_00_OVERVIEW.md](./PRD_00_OVERVIEW.md) | What DCS is, diagrams, architecture, scope |
| 1 | [PRD_CONN_01_ON_CONNECT_BOOTSTRAP.md](./PRD_CONN_01_ON_CONNECT_BOOTSTRAP.md) | Celery fetch on connect, 30-day window, connector health + email |
| 2 | [PRD_DCS_00_CHECK_MASTER_AND_SCORE_ENGINE.md](./PRD_DCS_00_CHECK_MASTER_AND_SCORE_ENGINE.md) | 42-check master, score assembly math, golden fixtures |
| 3 | [CHECK_MASTER_42.md](./CHECK_MASTER_42.md) | Authoritative ID table (copy of sheet 09 + catalogue fields) |
| 4 | [PRD_DCS_01_ORCHESTRATION_AND_EMAIL.md](./PRD_DCS_01_ORCHESTRATION_AND_EMAIL.md) | Celery DCS run, persist results, notify |
| 5 | [PRD_DCS_02_FOUNDATION_GATES.md](./PRD_DCS_02_FOUNDATION_GATES.md) | FD-01…FD-07 live gates |
| 6 | [PRD_DCS_03_SCORING_SNAPSHOT.md](./PRD_DCS_03_SCORING_SNAPSHOT.md) | Frozen Manago+Shopify inputs for checks |
| 7 | [PRD_DCS_04_RULE_BASED_CHECKS.md](./PRD_DCS_04_RULE_BASED_CHECKS.md) | 21 MVP1-A scored RULE checks |
| 8 | [PRD_DCS_05_DRIFT_CHECKS.md](./PRD_DCS_05_DRIFT_CHECKS.md) | 14 MVP1-B DRIFT checks |
| 9 | [PRD_DCS_06_API_RESPONSES.md](./PRD_DCS_06_API_RESPONSES.md) | HTTP contracts + FE wiring notes |
| 10 | [PRD_DCS_10_RUN_DIFF_AND_PERIOD_COMPARE.md](./PRD_DCS_10_RUN_DIFF_AND_PERIOD_COMPARE.md) | Persist consecutive run-diff (audit); history GET period_compare (first vs last in window) for Overview Captured / Δ |

## Reference materials (copied into this folder)

| Path | Use |
|------|-----|
| [Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx](./Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx) | DCS tabs **02, 03, 05–10** |
| [reference/schemas/](./reference/schemas/) | `check_definition`, `check_result`, `dcs_run`, `finding` |
| [reference/fixtures/](./reference/fixtures/) | Lumera golden + edge cases + scoring golden dataset |
| [reference/README.md](./reference/README.md) | Inventory of copies |

Workbook SHA-256 (matches DataPack `manifest.json`):  
`2d33671e6b77d4982a12a911f4964d674c4178301e90fa0d72b6ec5a62ffd373`

## Related existing docs

- `docs/connectors/PRD_CONNECTOR_CSV_EXPORT.md` — current sync fetch (superseded for default path by CONN-01)
- `docs/auth/API_AUTH_CONNECTORS.md` — connect/auth
