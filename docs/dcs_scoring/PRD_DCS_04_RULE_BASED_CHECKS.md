# PRD-DCS-04 — MVP1-A RULE scored checks (21)

**Depends on:** DCS-02 gates, DCS-03 snapshot  
**DataPack:** sheet **09** rows 8–28, **02** detection logic, **06** field mapping  
**IDs:** see [`CHECK_MASTER_42.md`](./CHECK_MASTER_42.md)

## 1. Goal

Implement executors for the **21 SCORED RULE_BASED** checks (not gates). Each returns a full `check_result` from the scoring snapshot only.

## 2. Check list

| ID | Dimension | Systems | Primary inputs |
|----|-----------|---------|----------------|
| CI-01 | Identity | Manago vs Shopify | contact counts both sides |
| CI-02 | Identity | Shopify | guest checkout share |
| CI-03 | Identity | Manago | duplicate emails/contacts |
| CI-05 | Identity | Manago vs Shopify | external_key linkage |
| LE-01 | Lifecycle | Manago vs Shopify | purchase event vs order counts |
| LE-02 | Lifecycle | Manago vs Shopify | purchase value parity |
| LE-03 | Lifecycle | Manago | order.id on events |
| LE-04 | Lifecycle | Manago | duplicate PURCHASE per order |
| LE-05 | Lifecycle | Shopify vs Manago | order-level gap list |
| LE-09 | Lifecycle | Shopify vs Manago | returns/cancels reflected |
| PT-01 | Product | Manago | event product keys ∈ catalog |
| PT-03 | Product | Manago vs Shopify | catalog completeness |
| PT-04 | Product | Manago vs Shopify | net vs gross per contact |
| SP-03 | Segment | Manago | detail schema consistency |
| SP-07 | Segment | Manago | `klints_` namespace |
| CC-01 | Consent | Shopify vs Manago | email opt-in parity |
| CC-02 | Consent | Shopify vs Manago | SMS consent parity |
| CC-03 | Consent | Manago | consent provenance |
| CC-05 | Consent | Manago vs Shopify | opt-out propagation |
| ME-02 | Measurement | Manago | workflow revenue attribution wiring |
| BR-01 | Business | ERP vs Manago | margin coverage → `NOT_CONNECTED` if no ERP |

## 3. Executor contract

```python
def execute(check_id: str, snapshot: ScoringSnapshot, master: CheckDef) -> CheckResult:
    ...
```

Rules:

1. Read detection logic from master (`sheet 02` text).  
2. Thresholds: if sheet 02 defines numeric cutovers, encode as constants named by check_id; do not invent undocumented thresholds — if unspecified, document chosen MVP1 threshold in code comment + PRD appendix below and flag for George.  
3. On missing snapshot inputs: `UNKNOWN` + `MISSING_INPUT:...` (not FAIL).  
4. On evaluated failure: `FAIL` or `WARN` per logic; attach `root_cause_ids` from master on findings.  
5. `confidence`: `HIGH` when both systems present and deterministic count compare; `MEDIUM` if sampling/inference; `LOW` if weak.

## 4. Suggested implementation batches

Ship as three PRs if needed:

| Batch | IDs | Rationale |
|-------|-----|-----------|
| 4a | CI-01, CI-02, CI-03, CI-05, LE-01, LE-02, LE-03, LE-04, LE-05, LE-09 | Uses contacts/orders/events |
| 4b | CC-01, CC-02, CC-03, CC-05, PT-04 | Consent + money truth |
| 4c | PT-01, PT-03, SP-03, SP-07, ME-02, BR-01 | Needs products/segments/workflows/ERP — expect UNKNOWN until ingest extended |

## 5. Finding emission

For each FAIL/WARN:

```json
{
  "finding_id": "...",
  "check_id": "LE-05",
  "severity": "Critical",
  "status": "open",
  "root_cause_ids": ["RC-01", "RC-05", "RC-15"],
  "blocks": ["workflow:purchase-triggered"],
  "recommended_fix": "from sheet 02 Suggested Fix",
  "evidence": []
}
```

Align with `finding.schema.json`. Persist via `RunIssue` or `DcsFinding`.

## 6. MVP1 thresholds appendix (fill during impl; stop-and-flag if sheet silent)

| Check | Provisional rule (replace with sheet 02 exact) |
|-------|-----------------------------------------------|
| CI-01 | relative count delta; WARN/FAIL bands from sheet 02 |
| LE-01 | same for purchase vs orders |
| CI-03 | duplicate rate threshold from sheet 02 |

If sheet 02 gives qualitative logic only, implement qualitative + record metric in evidence.value.

## 7. Files

| File | Change |
|------|--------|
| `dataruns/dcs/executors/identity.py` | CI-* |
| `dataruns/dcs/executors/lifecycle.py` | LE-* |
| `dataruns/dcs/executors/product.py` | PT-* |
| `dataruns/dcs/executors/segment.py` | SP-* |
| `dataruns/dcs/executors/consent.py` | CC-* |
| `dataruns/dcs/executors/measurement.py` | ME-02 |
| `dataruns/dcs/executors/business.py` | BR-01 |
| `dataruns/dcs/tests/test_rule_checks_*.py` | snapshot fixtures |

## 8. Acceptance

1. Each of 21 IDs registered; no silent skip.  
2. With contacts/orders/events only: batch 4a returns PASS/WARN/FAIL (not all UNKNOWN).  
3. BR-01 with `erp_in_scope=false` → `NOT_CONNECTED`.  
4. Assemble still matches DCS-00 math given the produced results.  
5. Evidence includes counts used in the decision.
