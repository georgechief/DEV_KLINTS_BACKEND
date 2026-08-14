# PRD-CONN-01 — On-connect Celery bootstrap (30-day fetch + health)

**Depends on:** existing connect + `run_import`  
**Blocks:** DCS live evaluation (DCS-02+)  
**Scope:** backend + Mailer; FE poll optional (see §10)

## 1. Problem

Connect today only stores credentials (`tenants/connector_views.py`). Fetch is a separate sync `POST .../fetch/` with default `days=10` (`_parse_fetch_days`, `run_import`). Large windows risk HTTP timeouts. Operators get no automatic proof the connector can pull data.

## 2. Goal

On successful connect of `shopify` or `manago_ai`:

1. Enqueue Celery task immediately.
2. Preflight connector health.
3. Fetch + persist **last 30 days** via existing import pipeline.
4. Write a structured health report.
5. Email company admins on success or failure.
6. Expose status for FE polling.

## 3. Defaults

| Setting | Value |
|---------|-------|
| `BOOTSTRAP_DAYS` | `30` |
| Allowed `days` on manual fetch | `1..31` (unchanged max; Manago client `_MAX_MODIFIED_WINDOW_DAYS = 30`) |
| Manual fetch default | change from `10` → `30` |
| Idempotency | one active bootstrap per `(company_id, connector.name)` |

## 4. Process

```text
A. Connect succeeds (Manago create OR Shopify OAuth callback)
B. Create DataRun name=connector-bootstrap:{platform} status=pending
   metadata = {
     "kind": "connector_bootstrap",
     "platform": "shopify"|"manago_ai",
     "connector_id": "<uuid>",
     "days": 30,
     "triggered_by": "on_connect",
     "actor_user_id": "<uuid|null>"   # null on Shopify callback
   }
C. Enqueue bootstrap_connector_fetch.delay(data_run_id)
D. HTTP returns without waiting for fetch
E. Worker:
   E1. status=running
   E2. preflight_health(connector) → issues[]
   E3. if blocking auth failure → mark failed, connector.status=error, email, stop
   E4. else run_import(platform, user_or_system, days=30)
       - reuse dataruns/connectors/import_data.py
       - refactor so Celery can call without HttpRequest
   E5. postflight_health(import result + counts) → issues[]
   E6. write metadata.health_report
   E7. connector.status = connected | degraded | error
   E8. DataRun succeeded|failed
   E9. email admins
```

### 4.1 Shopify callback special case

OAuth callback is unauthenticated (`ShopifyOAuthCallbackView`). After `update_or_create` connector:

- Resolve company admin (first `role=admin` for company) as `actor_user_id` for import ownership, OR pass `company_id` into a Celery-only import entrypoint that does not need a User.
- Redirect query params: `shopify=connected&bootstrap=queued&data_run_id=<id>`

### 4.2 Manago create

After `Connector.objects.create` in `ConnectorListCreateView.post`:

- Enqueue bootstrap.
- Response **201** body adds bootstrap fields (§8).

## 5. Health report (connector issues — not DCS)

Stored at `DataRun.metadata["health_report"]`:

```json
{
  "platform": "shopify",
  "days": 30,
  "window_start": "2026-06-24T00:00:00Z",
  "window_end": "2026-07-24T00:00:00Z",
  "preflight": {
    "auth_ok": true,
    "scopes_ok": true,
    "scopes_granted": ["read_customers", "read_orders", "read_products"],
    "scopes_missing": [],
    "issues": []
  },
  "fetch": {
    "ok": true,
    "contacts_upserted": 1204,
    "orders_upserted": 388,
    "raw_customers_or_contacts": 1204,
    "raw_orders_or_transactions": 388,
    "duration_ms": 41200
  },
  "postflight": {
    "issues": [
      {
        "code": "EMPTY_ORDERS_WINDOW",
        "severity": "warn",
        "message": "0 orders in last 30 days",
        "rc_hint": "RC-09"
      }
    ]
  },
  "blocking": false,
  "summary_status": "degraded"
}
```

### 5.1 Issue codes (closed set for CONN-01)

| Code | Severity | When | Maps toward |
|------|----------|------|-------------|
| `AUTH_FAILED` | error | Token/signed call fails | FD-01 / FD-02 / RC-12 |
| `SCOPES_MISSING` | error if required missing; else warn | Shopify scopes lack `read_customers` or `read_orders` | FD-02 |
| `RATE_LIMIT` | error | Hard 429 / exhausted retries | FD-04 / RC-15 |
| `FETCH_FAILED` | error | Client exception after auth | RC-12 / RC-15 |
| `EMPTY_CONTACTS_WINDOW` | warn | 0 contacts/customers in window | RC-09 |
| `EMPTY_ORDERS_WINDOW` | warn | 0 orders/transactions in window | RC-09 |
| `PERSIST_FAILED` | error | DB/upsert failure | — |
| `PARTIAL_FETCH` | warn | Pagination stopped early / truncated | RC-15 |

`summary_status`:

- `ok` — no error-severity issues  
- `degraded` — succeeded persist but warn issues  
- `error` — auth/fetch/persist failed  

Connector.status mapping:

| summary_status | `connectors.status` |
|----------------|---------------------|
| ok | `connected` |
| degraded | `degraded` |
| error | `error` |

(Add `degraded` / `error` to allowed statuses if only `connected` exists today.)

## 6. Preflight checks (per platform)

### Manago (`manago_ai`)

1. Decrypt config; call existing verify path (`tenants/manago.py` / signed read).
2. Resolve owner / account (same as `ManagoClient`).
3. Fail → `AUTH_FAILED`.

### Shopify

1. Decrypt token; `fetch_shop` (already used in OAuth).
2. Parse granted `scopes` from config.
3. Required: `read_customers`, `read_orders`.  
4. Recommended: `read_products`, `read_inventory` → warn if missing (`SCOPES_MISSING` warn).  
5. Fail auth → `AUTH_FAILED`.

## 7. Celery task

**File:** `dataruns/tasks.py` (replace stub usage for this flow)

```python
@shared_task(bind=True, name="dataruns.bootstrap_connector_fetch")
def bootstrap_connector_fetch(self, data_run_id: int) -> dict: ...
```

Rules:

- `acks_late` already global — keep task idempotent via DataRun status guard (`pending`/`running` only).
- Soft time limit: size for 30-day pagination (recommend ≥ 15–30 min soft / hard in settings for this task, or use dedicated queue).
- On exception: `DataRun.status=failed`, `metadata.error`, connector `error`, email.

Also keep/repurpose `process_data_run` only if needed; do not leave bootstrap as status-flip stub.

## 8. API changes

### 8.1 Manago create — extend 201

Existing create response + :

```json
{
  "id": "...",
  "status": "connected",
  "bootstrap": {
    "data_run_id": 123,
    "task_queued": true,
    "days": 30
  }
}
```

### 8.2 Manual fetch — async option (required)

Change default path to queue (same task) instead of sync `run_import` in the request.

`POST /api/v1/connectors/shopify/fetch/`  
`POST /api/v1/connectors/manago_ai/fetch/`

Request:

```json
{ "days": 30 }
```

| Field | Default | Rules |
|-------|---------|-------|
| `days` | `30` | integer 1–31 |

Response **202**:

```json
{
  "data_run_id": 123,
  "run_id": null,
  "status": "pending",
  "days": 30,
  "platform": "shopify",
  "detail": "Bootstrap fetch queued."
}
```

When finished, `run_id` appears on status endpoint (domain `runs.id`).

### 8.3 Status endpoint (new)

```http
GET /api/v1/connectors/{connector_id}/bootstrap/
Authorization: Bearer <jwt>
```

**200:**

```json
{
  "connector_id": "...",
  "connector_name": "shopify",
  "connector_status": "degraded",
  "data_run_id": 123,
  "data_run_status": "succeeded",
  "run_id": "a1b2c3...",
  "days": 30,
  "window_start": "...",
  "window_end": "...",
  "health_report": { },
  "started_at": "...",
  "finished_at": "..."
}
```

**404** if never bootstrapped.

### 8.4 Auth

| Endpoint | Roles |
|----------|-------|
| enqueue fetch / bootstrap status | admin (match current fetch: admin only) |
| connect still | admin/analyst as today |

## 9. Email

Use `tenants/emails.py` → `send_email`.

New helpers:

- `send_connector_bootstrap_success_email(...)`
- `send_connector_bootstrap_failure_email(...)`

Recipients: all company users with `role=admin` and `email_verified=True`.

Success subject: `Klints: {platform} import finished (30 days)`  
Body: counts, window, link to Integrations, warn issues if any.

Failure subject: `Klints: {platform} import failed`  
Body: issue codes + message, link to reconnect.

## 10. Files to change

| File | Change |
|------|--------|
| `dataruns/tasks.py` | Add `bootstrap_connector_fetch`; wire real work |
| `dataruns/connectors/import_data.py` | Extract callable usable from Celery (`user` or `company_id`); default days 30 |
| `dataruns/connectors/base.py` | Bootstrap DataRun helpers if needed |
| `tenants/connector_views.py` | Enqueue on Manago create + Shopify callback; fetch → 202 queue; default days 30; new bootstrap status view |
| `tenants/connector_urls.py` | Register bootstrap GET |
| `tenants/models.py` | Allow connector statuses `degraded`, `error` if constrained |
| `tenants/emails.py` | Bootstrap email helpers |
| `core/settings/base.py` | Task time limits / queue if needed |
| `tenants/tests/test_connector_fetch.py` (+ new bootstrap tests) | Async enqueue, on-connect trigger, health_report |
| `docs/connectors/PRD_CONNECTOR_CSV_EXPORT.md` | Add note: default path superseded by this PRD |

## 11. Out of scope

- DCS 42-check scoring  
- Product catalog ingest  
- ERP  
- Frontend UI (optional: poll §8.3)

## 12. Acceptance tests

1. Connect Manago → DataRun `pending`→`succeeded` without blocking HTTP; contacts/orders for ~30d present.  
2. Connect Shopify via OAuth → same.  
3. Invalid Manago secret → `AUTH_FAILED`, connector `error`, email sent, no silent success.  
4. Shopify missing `read_orders` → blocking scopes error.  
5. Second connect/bootstrap while running → no duplicate concurrent bootstraps.  
6. `POST .../fetch/` with `{}` uses `days=30` and returns 202.  
7. `GET .../bootstrap/` returns health_report after completion.
