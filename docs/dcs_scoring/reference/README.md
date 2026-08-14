# Local DataPack reference copies

Copied from `DataPack/Klints_MVP1_Rohan_Build_Pack_v1.2_20260718/` for offline PRD/dev use. Prefer these paths in this folder’s PRDs.

## Layout

```text
reference/
  schemas/
    check_definition.schema.json
    check_result.schema.json
    dcs_run.schema.json
    finding.schema.json
  fixtures/
    scoring_golden_dataset.json
    lumera_input/connector_snapshot.json
    lumera_expected_results/check_results.json
    lumera_expected_results/dcs_score.json
    edge_cases/{all_pass,gate_fail,partial_sweep,erp_not_connected,consent_fail,dependency_cycle}.json
```

Workbook (parent folder): `../Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx`
