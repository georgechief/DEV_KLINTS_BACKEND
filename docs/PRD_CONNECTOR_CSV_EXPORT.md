# Connector fetch API — common import / export + JSON maps

> **NOTE**
>
> The default connector bootstrap behaviour described in this document has been superseded by
>
> `docs/dcs_scoring/PRD_CONN_01_ON_CONNECT_BOOTSTRAP.md`
>
> Connector bootstrap now runs asynchronously using connector-bootstrap DataRuns.
>
> CSV export behaviour itself is unchanged.

**Scope (now):** backend APIs only. No frontend, no CSV.

**Goal:** fetch last **10 days** from a connector for the JWT user’s company, then:

1. Create a **`DataRun`** (job log — `pending` / `running` / `succeeded` / `failed` + errors in `metadata`)
2. Create a **`Run`** (data artifact linked to snapshots / contacts)
3. Save raw + normalized data in a **`ConnectorSnapshot`** (+ **`RunConnector`**)
4. Upsert **`contacts`** + **`orders`**
5. Write **`contact_metrics`** for this run

On failure: mark **`DataRun`** as `failed` and store the error in **`metadata`** (do not leave the job hanging as `running`).

**Design rule:** many connectors later → **one common folder**, **shared keys**, **JSON maps**. Do not hardcode Shopify/Manago field names inside upsert logic.

## 1. Auth (JWT required)

```http
Authorization: Bearer <access_jwt>
```

| Token | Source |
|-------|--------|
| Klints JWT | Login → user → tenant → **company** (workspace) |
| Connector secret | `connectors.config` (encrypted) — never in the request body |

- Missing/invalid JWT → `401`
- Not `admin` → `403`
- Workspace always from `request.user` — **never** pass `tenant_id` / `company_id` from the client

In mapping JSON, prefer the name **`workspace_id`** only where a *platform* API uses that concept (e.g. Manago). Persistence still uses our DB `company_id` resolved from the JWT.

---

## 2. Common connectors folder (required)

Lives under **`dataruns/`** (fetch → runs / contacts / orders / metrics), not under `tenants/`.

```text
dataruns/connectors/
  __init__.py
  base.py                 # JWT→company, decrypt, create Run / Snapshot / RunConnector
  import_data.py          # generic import (api_key → db_key)
  export_data.py          # generic export (db_key → api_key, reverse of same map)
  shopify/
    __init__.py
    client.py             # HTTP only
    map.json              # THIS connector’s key_mapping
  manago_ai/
    __init__.py
    client.py
    map.json
```

**One file per connector** (not one giant file for all).  
Same JSON shape in every `map.json`. Import and export both use that file:

| Direction | Uses map as |
|-----------|-------------|
| **Import** (API → DB) | `api_key` → `db_key` |
| **Export** (DB → API JSON) | `db_key` → `api_key` (reverse) |

**Note:** Credentials stay on `tenants.Connector`.  
`dataruns/connectors/` owns mapping + import/export into dataruns tables.

**Adding a future connector:** new folder + `map.json` + `client.py` + register route. No new upsert code.

---

## 3. DB keys we normalize to (same for every connector)

These are the **`db_key`** values used in every map.

### Contact → `contacts`

| `db_key` | Column |
|----------|--------|
| `external_id` | `contacts.external_id` |
| `email` | `contacts.email` |
| `phone` | `contacts.phone` |

`company_id` is **not** in the map — set from JWT workspace.

### Order → `orders`

| `db_key` | Column |
|----------|--------|
| `external_id` | `orders.external_id` |
| `amount` | `orders.amount` |
| `currency` | `orders.currency` |
| `status` | `orders.status` |
| `contact_external_id` | resolve to `orders.contact_id` |
| `created_at` | order timestamp when present |

### Connector config (credentials / workspace)

Only where the **platform** needs it (not contact/order rows):

| `db_key` | Where we store it |
|----------|-------------------|
| `workspace_id` | `connectors.config.workspace_id` (Manago) |
| `shop_domain` | `connectors.config.shop_domain` (Shopify) |
| `access_token` / `api_key` | encrypted in config — **never** written to contacts/orders |

---

## 4. `map.json` shape (sample — use this everywhere)

Every connector file looks like:

```json
{
  "type": "connector",
  "name": "shopify",
  "key_mapping": [
    {
      "entity": "contact",
      "api_key": "id",
      "db_key": "external_id"
    },
    {
      "entity": "contact",
      "api_key": "email",
      "db_key": "email"
    },
    {
      "entity": "contact",
      "api_key": "phone",
      "db_key": "phone"
    },
    {
      "entity": "order",
      "api_key": "id",
      "db_key": "external_id"
    },
    {
      "entity": "order",
      "api_key": "total_price",
      "db_key": "amount"
    },
    {
      "entity": "order",
      "api_key": "currency",
      "db_key": "currency"
    },
    {
      "entity": "order",
      "api_key": "financial_status",
      "db_key": "status"
    },
    {
      "entity": "order",
      "api_key": "customer.id",
      "db_key": "contact_external_id"
    },
    {
      "entity": "order",
      "api_key": "created_at",
      "db_key": "created_at"
    },
    {
      "entity": "config",
      "api_key": "shop",
      "db_key": "shop_domain"
    }
  ],
  "status_map": {
    "paid": "paid",
    "partially_paid": "paid",
    "refunded": "refunded",
    "partially_refunded": "refunded",
    "voided": "failed",
    "pending": "failed"
  }
}
```

### Field meaning

| Field | Meaning |
|-------|---------|
| `type` | Always `"connector"` |
| `name` | Platform id: `shopify`, `manago_ai`, … |
| `entity` | `contact` \| `order` \| `config` |
| `api_key` | Field path on the **platform API** response (dot path OK) |
| `db_key` | Our **shared** column/key (same across connectors) |

**Import:** read `api_key` from payload → write `db_key`.  
**Export:** read `db_key` from DB → emit under `api_key` (or under shared `db_key` if export is “Klints JSON”; v1 export = shared `db_key` list is fine).

---

## 5. Two connectors = two files (samples)

### `dataruns/connectors/shopify/map.json`

Use the sample in §4 (`name`: `"shopify"`).

### `dataruns/connectors/manago_ai/map.json`

```json
{
  "type": "connector",
  "name": "manago_ai",
  "key_mapping": [
    {
      "entity": "contact",
      "api_key": "contactId",
      "db_key": "external_id"
    },
    {
      "entity": "contact",
      "api_key": "email",
      "db_key": "email"
    },
    {
      "entity": "contact",
      "api_key": "phone",
      "db_key": "phone"
    },
    {
      "entity": "order",
      "api_key": "transactionId",
      "db_key": "external_id"
    },
    {
      "entity": "order",
      "api_key": "value",
      "db_key": "amount"
    },
    {
      "entity": "order",
      "api_key": "currency",
      "db_key": "currency"
    },
    {
      "entity": "order",
      "api_key": "email",
      "db_key": "contact_external_id"
    },
    {
      "entity": "order",
      "api_key": "date",
      "db_key": "created_at"
    },
    {
      "entity": "config",
      "api_key": "clientId",
      "db_key": "workspace_id"
    }
  ],
  "status_map": {
    "PURCHASE": "paid",
    "CANCELLED": "failed"
  }
}
```

Same `db_key` values as Shopify (`external_id`, `email`, `amount`, …).  
Only `api_key` (left side) changes per platform.  
Manago workspace: API `clientId` ↔ our `workspace_id` in connector config.

**Do not** merge both connectors into one JSON file — keeps diffs small when you add Magento later.

---

## 6. Import vs export modules

| File | Role |
|------|------|
| `import_data.py` | Fetch via platform client → apply `map.json` → shared records → upsert DB + snapshot + metrics |
| `export_data.py` | Load run / contacts / orders → emit **shared-key JSON** (same shape for all platforms) |

### Import pipeline (`import_data.run_import(platform, user, days)`)

1. Resolve company + tenant from JWT user  
2. Load connector for that company (`shopify` / `manago_ai`)  
3. Decrypt secrets  
4. **Create `DataRun`** (see §6b) — `status=running`, `started_at=now`  
5. **Create `Run`** — `run_type=incremental`, `status=running`, `started_at=now`  
6. Store `run_id` on `DataRun.metadata` (link job ↔ data run)  
7. `try:`  
   - `client.fetch(window)` → raw lists  
   - Map rows with `map.json` (`api_key` → `db_key`)  
   - Write `ConnectorSnapshot` + `RunConnector`  
   - Upsert `contacts` / `orders`  
   - Compute `contact_metrics`  
   - Set `Run` → `completed`, `completed_at=now`  
   - Set **`DataRun` → `succeeded`**, `finished_at=now`, merge success info into `metadata`  
   - Return counts + `data_run_id` + `run_id`  
8. `except:` → **§6b failure path** (log on `DataRun`, re-raise / return `502`)

### Export pipeline (`export_data.run_export(platform, user, run_id)`) — optional API later

Returns shared-key JSON only:

```json
{
  "platform": "shopify",
  "run_id": "uuid",
  "contacts": [
    { "external_id": "…", "email": "…", "phone": "…" }
  ],
  "orders": [
    {
      "external_id": "…",
      "amount": "19.99",
      "currency": "EUR",
      "status": "paid",
      "contact_external_id": "…"
    }
  ]
}
```

**v1 must ship import.** Export helper can exist in code; HTTP export endpoint can wait.

---

## 6b. Use `DataRun` to log success / failure

We already have **`DataRun`** (Django model → table managed by dataruns app; related name `tenant.data_runs`).  
It supports: `pending` | `running` | `succeeded` | `failed`, plus **`metadata` JSON** for errors — same pattern as `dataruns/tasks.py`.

| Model | Role |
|-------|------|
| **`DataRun`** | Job tracker + **error log** (`status`, `metadata`, `started_at`, `finished_at`) |
| **`Run`** | Domain run for snapshots / contacts / metrics |

### Create at start of import

```python
data_run = DataRun.objects.create(
    tenant=user.tenant,
    name=f"connector-fetch:{platform}",  # e.g. connector-fetch:shopify
    status=DataRun.Status.RUNNING,
    started_at=timezone.now(),
    metadata={
        "platform": platform,
        "days": days,
        "company_id": str(company.id),
    },
)
```

After `Run` is created, update:

```python
data_run.metadata = {
    **data_run.metadata,
    "run_id": str(run.id),
}
data_run.save(update_fields=["metadata", "updated_at"])
```

### Success

```python
data_run.status = DataRun.Status.SUCCEEDED
data_run.finished_at = timezone.now()
data_run.metadata = {
    **data_run.metadata,
    "counts": {"contacts": …, "orders": …, "contact_metrics": …},
    "snapshot_id": str(snapshot.id),
}
data_run.save(update_fields=["status", "finished_at", "metadata", "updated_at"])
```

### Failure (required)

Any exception after `DataRun` exists (upstream 401, timeout, map error, DB error):

```python
data_run.status = DataRun.Status.FAILED
data_run.finished_at = timezone.now()
data_run.metadata = {
    **(data_run.metadata or {}),
    "error": str(exc),
    "error_type": type(exc).__name__,
}
data_run.save(update_fields=["status", "finished_at", "metadata", "updated_at"])
```

Also set linked `Run` to a terminal state if it was created (`completed` with empty data, or leave `running` only if you add `failed` to `Run` later). Prefer: if `Run` exists, set `completed_at` and put `"ok": false` in the snapshot when possible.

**API response on failure:** `502` (or `400` for bad input) with:

```json
{
  "detail": "Shopify request failed: …",
  "data_run_id": "uuid"
}
```

Client can `GET /api/v1/dataruns/{data_run_id}/` to see `status=failed` and `metadata.error`.

**Do not** swallow errors without updating `DataRun`.

---

## 7. HTTP APIs (v1)

Base: `/api/v1/`

| Method | Path | Calls |
|--------|------|--------|
| `POST` | `/connectors/shopify/fetch/` | `import_data` for `shopify` |
| `POST` | `/connectors/manago_ai/fetch/` | `import_data` for `manago_ai` |

### Request

```json
{ "days": 10 }
```

| Field | Default | Rules |
|-------|---------|--------|
| `days` | `10` | Integer 1–31 |

### Response `200`

```json
{
  "data_run_id": 123,
  "run_id": "uuid",
  "snapshot_id": "uuid",
  "connector": "shopify",
  "window_start": "2026-07-10T12:00:00Z",
  "window_end": "2026-07-20T12:00:00Z",
  "status": "succeeded",
  "counts": {
    "contacts": 42,
    "orders": 18,
    "contact_metrics": 42
  }
}
```

`status` here mirrors **`DataRun.status`** (`succeeded`).

### Errors

| Status | When |
|--------|------|
| `401` | No / bad JWT |
| `403` | Not admin |
| `404` | Connector not connected |
| `400` | Bad `days` / unknown platform |
| `502` | Upstream / import failed — **`DataRun` saved as `failed`** with `metadata.error`; body includes `data_run_id` |

---

## 8. Persist rules (after mapping)

```text
Contact: update_or_create(company=…, external_id=…, defaults={email, phone})
Order:   update_or_create(company=…, external_id=…, defaults={contact, amount, currency, status})
```

**contact_metrics** (per run + contact):

| Field | v1 compute |
|-------|------------|
| `total_orders` | count orders for contact |
| `total_revenue` | sum `amount` where `status=paid` |
| `last_order_at` | max order created_at |
| `avg_order_value` | revenue / orders (0 if none) |
| `ltv` | = total_revenue |
| `lifecycle_stage` | `new` if 1 order, `repeat` if 2+, else `""` |

---

## 9. Snapshot shape

```json
{
  "ok": true,
  "platform": "shopify",
  "fetched_at": "…",
  "window_start": "…",
  "window_end": "…",
  "raw": { "customers": [], "orders": [], "transactions": [] },
  "normalized": {
    "contacts": [{ "external_id": "", "email": "", "phone": "" }],
    "orders": [{ "external_id": "", "amount": "", "currency": "", "status": "", "contact_external_id": "" }]
  },
  "notes": []
}
```

Raw = platform payloads. Normalized = shared keys (from maps). Never store secrets.

---

## 10. Out of scope (now)

- Frontend  
- CSV download  
- Celery  
- HTTP export endpoint (module OK)  
- Extra connectors beyond shopify / manago_ai  

---

## 11. Build order

1. Create `dataruns/connectors/` + `shopify/map.json` + `manago_ai/map.json`  
2. `base.py` (company, decrypt, run/snapshot helpers)  
3. `shopify/client.py` + import path end-to-end  
4. `manago_ai/client.py` + import path  
5. `export_data.py` (reverse map: `db_key` → `api_key`)  
6. Wire two POST fetch views (can live in `dataruns` urls or thin wrappers under `/api/v1/connectors/`)  
7. Tests (mock HTTP; assert map → contacts/orders)

---

## 12. Acceptance tests

1. JWT required → `401` without header  
2. Shopify fetch → `DataRun` succeeded + `Run` + snapshot + contacts/orders/metrics  
3. Same `external_id` second fetch → upsert, no duplicates  
4. Snapshot has `raw` + `normalized`, no access_token  
5. Manago map uses same `db_key`s as Shopify  
6. Forced upstream failure → `DataRun.status=failed`, `metadata.error` set, response includes `data_run_id`  
7. Adding a fake platform map in unit test proves import does not hardcode Shopify field names  

---

## 13. Do / don’t

**Do**
- Common `dataruns/connectors/` package  
- **One `map.json` per connector** with `{ type, name, key_mapping: [{ entity, api_key, db_key }] }`  
- Same `db_key` values across connectors; only `api_key` changes  
- Import and export use the same file (forward / reverse)  
- JWT for auth; workspace from user  
- Log every fetch job on **`DataRun`**; on failure set `failed` + `metadata.error`  

**Don’t**
- One giant mapping file for all connectors  
- Put platform field names inside upsert/SQL  
- Put this package under `tenants/` (credentials stay in tenants; import pipeline in dataruns)  
- Pass tenant/company ids from the client  
- Fail silently without updating `DataRun`  
- Ship CSV/UI in this pass