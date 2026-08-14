# PRD-DCS-07 — Daily Celery Beat: DCS pipeline for all connected companies

**Status:** Ready for implementation  
**Depends on:** CONN-01 bootstrap, [PRD-DCS-01](../dcs_scoring/PRD_DCS_01_ORCHESTRATION_AND_EMAIL.md) `run_dcs_score`, [PRD-CONN-03](./PRD_CONN_03_SHOPIFY_OFFLINE_TOKEN_REFRESH.md) token refresh  
**Scope:** Celery Beat schedule + dispatcher task; does not re-implement check executors

## 1. Problem

DCS runs today are only triggered manually / on-connect paths (when DCS-01 lands: `POST /api/v1/dcs/runs/` or post-bootstrap auto). There is no **daily scheduled** re-score for every company that already has a connected account.

Existing Beat config (`core/settings/base.py`):

```python
CELERY_BEAT_SCHEDULE = {
    "core-ping-every-5-minutes": {
        "task": "core.ping",
        "schedule": 300.0,
    },
}
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
TIME_ZONE = "UTC"
CELERY_TIMEZONE = TIME_ZONE
```

## 2. Goal

Every day at **15:00 India Standard Time (IST)** (`Asia/Kolkata`):

1. Find all companies with at least one connector in `{connected, degraded}` for `shopify` and/or `manago_ai`.
2. For each company, enqueue the **DCS score Celery pipeline** (same worker entrypoint as DCS-01: `dataruns.run_dcs_score`).
3. Jobs run asynchronously on workers; Beat only dispatches.

```text
Celery Beat (15:00 IST)
  → dataruns.dispatch_daily_dcs_scores
       → for each eligible company:
            create DCS DataRun (or call shared enqueue helper)
            run_dcs_score.delay(data_run_id)
```

## 3. Schedule definition

| Setting | Value |
|---------|-------|
| Local wall clock | **15:00 IST** every day |
| Timezone | `Asia/Kolkata` |
| Celery crontab | `crontab(hour=15, minute=0)` with `tz=ZoneInfo("Asia/Kolkata")` |
| Task name | `dataruns.dispatch_daily_dcs_scores` |
| Schedule key | `dcs-daily-score-1500-ist` |

### 3.1 Timezone guidance

App `TIME_ZONE` is currently `"UTC"`. Do **not** assume `crontab(hour=9, minute=30)` in UTC without documenting DST — IST has **no DST** (UTC+05:30 always).

**Preferred implementation:**

```python
from zoneinfo import ZoneInfo
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # ...existing ping...
    "dcs-daily-score-1500-ist": {
        "task": "dataruns.dispatch_daily_dcs_scores",
        "schedule": crontab(hour=15, minute=0, tz=ZoneInfo("Asia/Kolkata")),
    },
}
```

Also create/update the same schedule via `django_celery_beat` so Admin can see it (DatabaseScheduler merges with settings — follow project convention used for `core-ping`).

### 3.2 Ops

- Run Beat process in deploy: `celery -A core beat -l info` (in addition to worker).  
- Document in root `README.md` under Celery section.

## 4. Eligibility rules

A **company** is eligible if:

```text
EXISTS Connector
  WHERE company_id = company.id
    AND name IN ('shopify', 'manago_ai')
    AND status IN ('connected', 'degraded')
```

| Case | Dispatch DCS? |
|------|----------------|
| Shopify only connected | Yes (`erp_in_scope=false`; Manago gates → NOT_CONNECTED as per DCS-02) |
| Manago only connected | Yes |
| Both connected | Yes |
| Only `error` / disconnected | No |
| Tenant with no company | No |

**Idempotency for the day (recommended):**

- If a company already has a DCS DataRun with `metadata.kind=dcs_score`, `metadata.triggered_by=daily_beat`, and `created_at` in today’s IST calendar day in `{pending, running, succeeded}` → **skip** duplicate enqueue.
- Failed runs may be retried next Beat tick or same day if product wants — default: **one successful or in-flight daily run per company per IST day**.

## 5. Dispatcher task (new)

**File:** `dataruns/tasks.py`

```python
@shared_task(bind=True, name="dataruns.dispatch_daily_dcs_scores")
def dispatch_daily_dcs_scores(self) -> dict:
    """
    Beat entrypoint: enqueue run_dcs_score for every eligible company.
    """
    ...
```

### 5.1 Per-company enqueue

Reuse the **same helper** DCS-01 will use for HTTP `POST /api/v1/dcs/runs/` so behavior stays identical:

Suggested: `dataruns/dcs/enqueue.py` → `enqueue_dcs_score(company, *, triggered_by, erp_in_scope=False, actor_user_id=None)`

Creates:

```text
DataRun
  name = "dcs-score"
  status = pending
  metadata = {
    "kind": "dcs_score",
    "scoring_model_version": "DCS-1.0.0",
    "erp_in_scope": false,
    "triggered_by": "daily_beat",
    "company_id": "<uuid>",
    "source_runs": { ... latest succeeded bootstraps ... }
  }
```

Then:

```python
run_dcs_score.delay(data_run.id)
```

### 5.2 If DCS-01 is not merged yet

Implement in this order:

1. Land `enqueue_dcs_score` + `run_dcs_score` skeleton from DCS-01 (even if checks stub `UNKNOWN`).  
2. Then enable Beat schedule.  

**Do not** point Beat at `bootstrap_connector_fetch` as a permanent substitute — bootstrap is ingest, not scoring. Optional **pre-step** (out of scope for v1): refresh bootstrap before score; v1 scores from latest persisted data + live auth probes inside the DCS worker.

### 5.3 Dispatcher return payload

```json
{
  "ok": true,
  "eligible_companies": 12,
  "enqueued": 10,
  "skipped_already_ran": 2,
  "errors": []
}
```

Log each enqueue with `company_id` + `data_run_id`. Never fail the whole Beat tick because one company errored — catch, append to `errors`, continue.

## 6. Worker path (existing DCS-01)

Inside `run_dcs_score` (per company):

1. **CONN-03:** ensure Shopify offline token fresh if Shopify connected.  
2. Optional cheap live auth for FD-01/FD-02.  
3. Evaluate checks → `assemble_dcs_score` → persist → email (DCS-01).  

Beat must not pass HTTP request/user; use `company_id` from metadata like bootstrap does.

## 7. Rate / safety

| Concern | Rule |
|---------|------|
| Fan-out size | One Celery task per company (not one giant sync loop doing all scoring) |
| Prefetch | Keep `CELERY_WORKER_PREFETCH_MULTIPLIER = 1` |
| Time limits | DCS task uses existing soft/hard limits; increase later if 42 checks + fetch need it |
| Overlap | If yesterday’s runs still `running`, today’s dispatcher still enqueues only if daily idempotency allows — do not kill in-flight runs |

## 8. Files to change

| File | Change |
|------|--------|
| `core/settings/base.py` | Add Beat schedule entry with IST crontab |
| `dataruns/tasks.py` | `dispatch_daily_dcs_scores` |
| `dataruns/dcs/enqueue.py` (or `dataruns/connectors/base.py`) | Shared enqueue helper with DCS-01 |
| `README.md` | Document beat process + 15:00 IST |
| `dataruns/tests/test_daily_dcs_beat.py` | Eligibility + idempotency + enqueue counts |

## 9. Acceptance

1. With Beat timezone IST, schedule fires at 15:00 Asia/Kolkata (unit-test crontab args / freeze time).  
2. Company with connected Shopify → receives one `run_dcs_score` enqueue.  
3. Company with no connectors → skipped.  
4. Second dispatch same IST day → skip already pending/succeeded daily run.  
5. One company raising inside loop does not prevent others from enqueueing.  
6. Manual `POST /api/v1/dcs/runs/` still works independently (`triggered_by` different).

## 10. Out of scope

- Hourly / per-tenant custom schedules  
- Auto-bootstrap refresh before every daily score (separate PRD if needed)  
- FE UI for “last daily run” (DCS-06 can expose later)
