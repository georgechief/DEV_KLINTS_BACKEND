# PRD-DCS-06 — HTTP API contracts + frontend wiring notes

**Depends on:** DCS-01 (and ideally 02–05 for non-stub results)  
**Scope:** backend response shapes; FE file hints only

## 1. Base

```text
/api/v1/
Authorization: Bearer <jwt>
Tenant/company always from request.user
```

Roles: `admin` for POST; `admin`/`analyst`/`viewer` for GET (viewer read-only).

## 2. Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/dcs/runs/` | Start DCS (202) |
| `GET` | `/dcs/runs/latest/` | Latest run for company |
| `GET` | `/dcs/runs/{dcs_run_id}/` | Run detail |
| `GET` | `/dcs/runs/{dcs_run_id}/checks/` | 42 check_results only |
| `GET` | `/dcs/master/` | 42 check definitions (no secrets) |
| `GET` | `/dcs/history/` | Score trend + period compare (DCS-10) |
| `GET` | `/connectors/{id}/bootstrap/` | From CONN-01 |

## 3. POST /dcs/runs/

### Request

```json
{
  "erp_in_scope": false,
  "source_run_ids": {
    "shopify": "uuid-or-null",
    "manago_ai": "uuid-or-null"
  }
}
```

### Responses

**202**

```json
{
  "data_run_id": 55,
  "dcs_run_id": "uuid",
  "status": "pending",
  "scoring_model_version": "DCS-1.0.0"
}
```

| Code | When |
|-----:|------|
| 401 | no/invalid JWT |
| 403 | not admin |
| 409 | DCS already running for company |
| 422 | no succeeded bootstrap for required connector |

## 4. GET /dcs/runs/latest/ and GET /dcs/runs/{id}/

**200 — running**

```json
{
  "dcs_run_id": "uuid",
  "data_run_id": 55,
  "status": "running",
  "run_state": null,
  "headline_score": null,
  "scoring_model_version": "DCS-1.0.0",
  "started_at": "2026-07-24T06:00:00Z",
  "completed_at": null
}
```

**200 — succeeded** (align with `dcs_score.json` + orchestration fields)

```json
{
  "dcs_run_id": "uuid",
  "data_run_id": 55,
  "status": "succeeded",
  "run_state": "CONDITIONALLY_READY",
  "headline_score": 84.267,
  "blocking_gates_failed": 0,
  "scoring_model_version": "DCS-1.0.0",
  "scope_model_version": "MVP1-42-v1.4.1",
  "coverage": 1.0,
  "confidence": 0.99,
  "dimensions": {
    "01 Customer Identity": {
      "score": 81.8182,
      "coverage": 1.0,
      "confidence": 1.0,
      "weight_percent": 18
    },
    "02 Lifecycle Event": {
      "score": 81.25,
      "coverage": 1.0,
      "confidence": 1.0,
      "weight_percent": 18
    },
    "03 Product & Transaction": {
      "score": 100,
      "coverage": 1.0,
      "confidence": 1.0,
      "weight_percent": 14
    },
    "04 Segment & Property": {
      "score": 86.6667,
      "coverage": 1.0,
      "confidence": 1.0,
      "weight_percent": 12
    },
    "05 Channel & Consent": {
      "score": 76.4706,
      "coverage": 1.0,
      "confidence": 1.0,
      "weight_percent": 18
    },
    "06 Measurement": {
      "score": 87.5,
      "coverage": 1.0,
      "confidence": 0.925,
      "weight_percent": 10
    },
    "07 Business Reality": {
      "score": null,
      "coverage": 0,
      "confidence": null,
      "weight_percent": 10,
      "status": "NOT_CONNECTED"
    }
  },
  "check_summary": {
    "PASS": 30,
    "WARN": 4,
    "FAIL": 3,
    "UNKNOWN": 3,
    "NOT_CONNECTED": 2,
    "NOT_APPLICABLE": 0
  },
  "missing_required_inputs": ["products", "segments"],
  "source_runs": {
    "shopify": "uuid",
    "manago_ai": "uuid"
  },
  "erp_in_scope": false,
  "started_at": "...",
  "completed_at": "..."
}
```

**404** — no runs yet.

## 5. GET /dcs/runs/{id}/checks/

**200**

```json
{
  "dcs_run_id": "uuid",
  "count": 42,
  "results": [
    {
      "schema_version": "1.0.0",
      "tenant_id": "...",
      "run_id": "uuid",
      "check_id": "CI-01",
      "status": "WARN",
      "score_factor": 0.5,
      "numeric_weight": 4,
      "confidence": "HIGH",
      "confidence_factor": 1,
      "reason_code": null,
      "evidence": [
        {
          "source": "snapshot",
          "locator": "counts.manago_contacts",
          "value": { "manago": 125000, "shopify": 119500, "delta_pct": 4.4 },
          "observed_at": "2026-07-24T06:01:00Z"
        }
      ],
      "scoring_model_version": "DCS-1.0.0",
      "evaluated_at": "2026-07-24T06:01:00Z"
    }
  ]
}
```

Must be length 42; order by master seq.

## 6. GET /dcs/master/

**200** — definitions from seeded master (no detection of tenant data):

```json
{
  "scoring_model_version": "DCS-1.0.0",
  "count": 42,
  "dimensions": [
    { "id": "01 Customer Identity", "weight_percent": 18 }
  ],
  "checks": [
    {
      "seq": 8,
      "check_id": "CI-01",
      "mvp1_class": "RULE_BASED",
      "dimension": "01 Customer Identity",
      "check_name": "Contact count reconciliation",
      "check_type": "Cross-system reconciliation",
      "numeric_weight": 4,
      "role": "SCORED",
      "severity": "High",
      "root_cause_ids": ["RC-01", "RC-03", "RC-09"]
    }
  ]
}
```

## 7. GET /dcs/history/

Headline score time series, value-capture placeholders, and period-over-period compare for Overview period controls (PRD-DCS-10).

### Query params

| Param | Behavior |
|-------|----------|
| `days` | Window ending at `until` (default `until` = now), capped at 366 |
| `since` | ISO start (preferred when FE has exact window) |
| `until` | ISO end — required for windows that do not end at now (e.g. Last quarter) |

### Response **200**

```json
{
  "points": [
    {
      "at": "2026-07-18T15:00:00Z",
      "score": 71,
      "data_run_id": 140,
      "run_state": "COMPLETE",
      "dimensions": { "01 Customer Identity": 78 }
    }
  ],
  "value_capture": { "revenue": [], "margin": [] },
  "at_stake_series": [
    {
      "at": "2026-07-18T15:00:00Z",
      "value": 95000,
      "data_run_id": 140,
      "currency": "EUR"
    }
  ],
  "period_compare": {
    "available": true,
    "run_count": 4,
    "first": {
      "data_run_id": 101,
      "at": "2026-07-01T15:00:00Z",
      "headline_score": 62,
      "dimensions": { "01 Customer Identity": 70 },
      "business_impact": { "estimate": 120000, "currency": "EUR" }
    },
    "last": {
      "data_run_id": 140,
      "at": "2026-07-18T15:00:00Z",
      "headline_score": 71,
      "dimensions": { "01 Customer Identity": 78 },
      "business_impact": { "estimate": 95000, "currency": "EUR" }
    },
    "deltas": {
      "headline_score": 9,
      "dimensions": { "01 Customer Identity": 8 },
      "estimate": -25000,
      "captured_from_estimate": 25000
    }
  },
  "since": "2026-04-01T00:00:00Z",
  "until": "2026-06-30T23:59:59Z"
}
```

| Field | Rule |
|-------|------|
| `period_compare.available` | `true` only when ≥2 scored runs in window |
| `period_compare.first` / `last` | Chronological oldest / newest in window |
| `deltas.captured_from_estimate` | `max(0, first.estimate − last.estimate)` — at-stake improvement, not banked revenue |
| `at_stake_series` | Per-run `business_impact.estimate` for spark charts |

`value_capture` remains for future true capture fields; MVP Overview uses `at_stake_series` + `captured_from_estimate`.

### Consecutive run-diff (write path, audit)

On each SUCCEEDED scored run, orchestration persists `DataRun.metadata.run_diff` (vs immediately previous scored run) and includes the same object in `dcs.score_completed` audit metadata. First-ever run: `baseline: true`, deltas null. See `PRD_DCS_10_RUN_DIFF_AND_PERIOD_COMPARE.md`.

## 8. Error envelope

```json
{ "detail": "human readable", "code": "DCS_ALREADY_RUNNING" }
```

## 9. Frontend wiring (notes only)

| FE file | Change |
|---------|--------|
| `klints_frontend/src/lib/klints-data.ts` | Stop using mock DCS for live tenant when API present |
| `klints_frontend/src/components/klints/DcsCharts.tsx` | Bind to `dimensions` + `headline_score` |
| `klints_frontend/src/routes/dashboard.tsx` / data-consistency route | Poll `GET /dcs/runs/latest/` after POST |
| `klints_frontend/src/lib/connectors.ts` | Poll bootstrap status after connect |

FE is out of backend merge scope unless scheduled; shapes above are the contract.

## 10. Files (backend)

| File | Change |
|------|--------|
| `dataruns/dcs_views.py` | views |
| `dataruns/serializers_dcs.py` | serializers |
| `dataruns/urls.py` + `core/urls.py` | routes |
| `dataruns/tests/test_dcs_api.py` | contract tests vs fixture shapes |

## 11. Acceptance

1. OpenAPI-like manual check: responses validate against `check_result.schema.json` / `dcs_run.schema.json` fields used.  
2. Lumera-like stored run GET matches `dcs_score.json` dimension keys.  
3. `/checks/` always 42.  
4. Viewer can GET; cannot POST (403).
