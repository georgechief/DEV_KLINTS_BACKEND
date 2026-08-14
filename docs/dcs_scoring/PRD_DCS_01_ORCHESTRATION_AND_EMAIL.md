# PRD-DCS-01 — DCS run orchestration (Celery) + email

**Depends on:** PRD-CONN-01 (data present), PRD-DCS-00 (assemble engine)  
**Scope:** queue a DCS job, persist 42 results + score, email; check executors may stub as `UNKNOWN` until DCS-02/04/05

## 1. Goal

Provide one Celery pipeline:

```text
trigger → create DCS DataRun → evaluate/stub 42 checks → assemble_dcs_score → persist → email
```

## 2. Trigger rules

| Trigger | When |
|---------|------|
| `POST /api/v1/dcs/runs/` | Admin explicit start |
| Auto (optional flag) | After **both** `shopify` and `manago_ai` bootstraps `summary_status` in `{ok, degraded}` |

Do not auto-start if either required connector is `error` or bootstrap still `running`.

Request body:

```json
{
  "erp_in_scope": false,
  "source_run_ids": {
    "shopify": "<uuid|null>",
    "manago_ai": "<uuid|null>"
  }
}
```

If `source_run_ids` omitted: use latest succeeded bootstrap `Run` per platform for the company.

## 3. Process

```text
1. Auth JWT admin → company/tenant
2. Validate connectors exist; resolve source import Runs
3. Create DataRun:
   name = "dcs-score"
   status = pending
   metadata.kind = "dcs_score"
   metadata.scoring_model_version = "DCS-1.0.0"
   metadata.erp_in_scope = false
   metadata.source_runs = {...}
4. Create domain Run (run_type=full, status=running) OR reuse a dedicated DcsRun table (see §5)
5. Enqueue run_dcs_score.delay(data_run_id)
6. Return 202 { data_run_id, status: pending }

Worker:
7. status=running
8. Build scoring snapshot (DCS-03); until DCS-03 lands, snapshot may be minimal + missing_required_inputs
9. For each of 42 master checks:
   - call registered executor OR stub UNKNOWN + reason_code=EXECUTOR_NOT_IMPLEMENTED
10. assemble_dcs_score(results, erp_in_scope=..., sweep_complete=...)
11. Persist check results + dcs score payload
12. DataRun succeeded|failed
13. Email admins
```

## 4. Celery task

```python
@shared_task(bind=True, name="dataruns.run_dcs_score")
def run_dcs_score(self, data_run_id: int) -> dict: ...
```

**File:** `dataruns/tasks.py`

Idempotency: ignore if DataRun already `succeeded`; fail if unknown id.

## 5. Persistence mapping

Prefer explicit tables (add if stubs insufficient):

| Store | Content |
|-------|---------|
| `ScoringModel` | `DCS` / `DCS-1.0.0` |
| `RunScore` | `entity_type="company"`, `entity_id=company_id`, `score=headline`, `breakdown=dcs_run JSON` |
| Per-check rows | New model `DcsCheckResult` **or** `QaCheck` with `check_type=check_id`, `result=status`, `details=full check_result` |
| Findings (FAIL/WARN) | `RunIssue` + optional `RunIssueImpact`; `issue_type=check_id`, attach `root_cause_ids` in details JSON |

Minimum viable without new tables:

- `RunScore.breakdown` = full `dcs_run` + embedded `check_results[]`

PRD-DCS-06 APIs must still return the shapes in §7.

Recommended new model (clean):

```text
DcsRun
  id, company, tenant, data_run, scoring_model
  run_state, headline_score, payload(JSON), erp_in_scope
  started_at, completed_at

DcsCheckResult
  dcs_run, check_id, status, score_factor, numeric_weight
  confidence, confidence_factor, reason_code, evidence(JSON), payload(JSON)
  unique (dcs_run, check_id)
```

## 6. Stub policy (until executors exist)

| Situation | status | reason_code |
|-----------|--------|-------------|
| Executor not implemented | `UNKNOWN` | `EXECUTOR_NOT_IMPLEMENTED` |
| Required snapshot field missing | `UNKNOWN` | `MISSING_INPUT:<field>` |
| ERP out of scope (BR_*, FD-03) | `NOT_CONNECTED` | `ERP_OUT_OF_SCOPE` |

Never write FAIL for “not implemented”. Never omit a check_id — always 42 rows.

## 7. API responses

### Start

`POST /api/v1/dcs/runs/` → **202**

```json
{
  "data_run_id": 55,
  "dcs_run_id": null,
  "status": "pending",
  "scoring_model_version": "DCS-1.0.0"
}
```

### Get latest / by id

`GET /api/v1/dcs/runs/latest/`  
`GET /api/v1/dcs/runs/{dcs_run_id}/`

**200** (ready):

```json
{
  "dcs_run_id": "...",
  "data_run_id": 55,
  "status": "succeeded",
  "run_state": "CONDITIONALLY_READY",
  "headline_score": 84.267,
  "blocking_gates_failed": 0,
  "scoring_model_version": "DCS-1.0.0",
  "dimensions": { },
  "coverage": 1.0,
  "confidence": 0.99,
  "check_results": [ ],
  "missing_required_inputs": [ ],
  "source_runs": {
    "shopify": "...",
    "manago_ai": "..."
  },
  "started_at": "...",
  "completed_at": "..."
}
```

While running: `status=running`, scores null.

`check_results` items match `check_result.schema.json`.

## 8. Email

Helpers in `tenants/emails.py`:

- `send_dcs_completed_email`
- `send_dcs_failed_email`

Success body fields: `run_state`, `headline_score`, top FAIL check_ids (max 5), link to Data Consistency page.

## 9. Files to change

| File | Change |
|------|--------|
| `dataruns/tasks.py` | `run_dcs_score` |
| `dataruns/dcs/orchestrate.py` | pipeline |
| `dataruns/dcs/executors/__init__.py` | registry + stubs |
| `dataruns/models.py` (+ migrations) | `DcsRun` / `DcsCheckResult` (recommended) |
| `dataruns/dcs_views.py` + urls | POST/GET |
| `tenants/emails.py` | DCS emails |
| `core/urls.py` or `dataruns/urls.py` | mount `/api/v1/dcs/` |

## 10. Acceptance

1. POST returns 202; worker writes exactly 42 check results.  
2. Assemble output stored; GET returns fixture-compatible shape.  
3. Email sent on success and failure.  
4. Second POST while running returns 409 or reuses active run (document choice: **409**).  
5. With all stubs UNKNOWN → `run_state=INCOMPLETE`, not a fake READY.
