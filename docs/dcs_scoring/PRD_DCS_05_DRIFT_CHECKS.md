# PRD-DCS-05 — MVP1-B DRIFT checks (14)

**Depends on:** DCS-04 (stable snapshot + RULE path)  
**DataPack:** sheet **09** rows 29–42, **02** detection logic, **07** confidence

## 1. Goal

Implement the **14 DRIFT** checks (freshness + statistical anomaly). Same executor contract as DCS-04.

## 2. Check list

| ID | Type | Systems |
|----|------|---------|
| CI-13 | Statistical anomaly | Manago |
| CI-14 | Statistical anomaly | Manago |
| CI-15 | Freshness | Manago |
| LE-08 | Freshness | Manago |
| LE-11 | Statistical anomaly | Manago |
| LE-13 | Statistical anomaly | Manago vs Shopify |
| PT-14 | Statistical anomaly | Manago |
| SP-08 | Statistical anomaly | Manago |
| SP-12 | Freshness | Manago |
| CC-12 | Freshness | Manago |
| ME-08 | Statistical anomaly | Manago vs Shopify |
| ME-09 | Statistical anomaly | Manago |
| BR-02 | Freshness | ERP vs Shopify vs Manago |
| BR-12 | Freshness | ERP |

## 3. Process notes

- Prefer `confidence=MEDIUM` when using distribution heuristics.  
- Recurring cadence checks (`LE-13`, `BR-12`) must be safe to re-run; store prior window metrics in snapshot or prior `DcsRun` for drift compare.  
- ERP checks → `NOT_CONNECTED` when `erp_in_scope=false`.  
- If segments/workflows absent → related checks `UNKNOWN`, not FAIL.

## 4. Recurring hook (minimal)

Optional Celery beat (later): weekly `run_dcs_score` for companies with connectors `connected|degraded`. Not required to close DCS-05 unit acceptance.

## 5. Files

| File | Change |
|------|--------|
| `dataruns/dcs/executors/drift.py` | CI/LE/PT/SP/CC/ME/BR drift IDs |
| `dataruns/dcs/tests/test_drift_checks.py` | — |

## 6. Acceptance

1. All 14 registered.  
2. Golden-style synthetic distributions produce stable PASS/WARN/FAIL.  
3. Full 42-check live run no longer stubs DRIFT as `EXECUTOR_NOT_IMPLEMENTED`.  
4. Assemble + state machine unchanged (DCS-00).
