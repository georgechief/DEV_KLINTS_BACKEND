# PRD-CONN-04 — Integrations card: real status + bootstrap stats; drop product/inventory scopes

**Status:** Ready for implementation  
**Module:** see folder path  
**Depends on:** CONN-01 bootstrap health + `GET …/connectors/{id}/bootstrap/`; existing Integrations UI  
**Repos:** `/integrations` connector cards  
**Scope:** stop treating `read_products` / `read_inventory` as required or recommended; show live bootstrap stats on connected cards; treat `degraded` as still connected in UI

## 1. Problem

### 1.1 Fake “Integrity contribution” strip

Integrations cards (Manago / Shopify) show mock data from `integrationHealth` in `klints-data.ts`:

- Fake score (e.g. **72**)
- Fake issue contribution (**4 issues**)
- Fake run label (**Last clean R#146**)

That is not bootstrap / DCS truth. Operators need **real** post-connect stats.

### 1.2 Status looks “disconnected” when still linked

After a successful Shopify bootstrap, missing **recommended** scopes sets `summary_status=degraded` → `Connector.status=degraded`.

FE only treats `status === "connected"` as connected, so the card flips to **Not connected** / Connect even though OAuth + import succeeded.

### 1.3 Product / inventory scopes are not required

Bootstrap warns (`SCOPES_MISSING` severity **warn**) when Shopify lacks:

- `read_products`
- `read_inventory`

That alone forces **degraded**. Product decision: these scopes are **not required** for MVP connect / DCS foundation. Stop requesting them as recommended (and align FD-02 / OAuth defaults).

## 2. Goal

1. **Scopes:** `read_customers` + `read_orders` remain the only Shopify scopes that matter for bootstrap preflight and FD-02. Remove `read_products` and `read_inventory` from recommended / required lists and from default OAuth scope string where we control it.  
2. **Status UI:** Cards show Connected for `connected` **and** `degraded`; show Error for `error`; optional Degraded badge when status is `degraded` (other warn reasons may remain).  
3. **Stats UI:** Replace the mock Integrity contribution strip with live bootstrap stats:
   - **Run id** (domain `run_id` or `data_run_id` — pick one and label clearly)
   - **Contacts** imported (count)
   - **Orders** imported (count)
   - **Issue count** (warn + error issues from latest bootstrap `health_report`)

## 3. Backend — scopes

### 3.1 Bootstrap health

File: `dataruns/connectors/bootstrap_health.py`

| Today | Change |
|-------|--------|
| `SHOPIFY_REQUIRED_SCOPES = {read_customers, read_orders}` | **Keep** |
| `SHOPIFY_RECOMMENDED_SCOPES = {read_products, read_inventory}` | **Empty** (or delete recommended path / never emit warn for these two) |

After change: granted `read_customers` + `read_orders` → preflight scopes OK with **no** `SCOPES_MISSING` warn for products/inventory → `summary_status` can be `ok` when fetch/persist are clean.

Update tests in `dataruns/tests/test_bootstrap_health.py` and any bootstrap tests that expect product/inventory warns.

### 3.2 FD-02 foundation gate

File: `dataruns/dcs/executors/foundation.py`

Today `SHOPIFY_FD02_REQUIRED_SCOPES` includes `read_products` and `read_inventory`.  

**Change:** FD-02 required = `{read_customers, read_orders}` only (same as bootstrap required).

Update `foundation_gates.json` copy / catalogue text if it still lists the four scopes. Update FD-02 unit tests.

### 3.3 OAuth request scopes

| Location | Change |
|----------|--------|
| `SHOPIFY_SCOPES` default in `core/settings/base.py` | Prefer `read_orders,read_customers` (drop `read_products`) |
| `.env.example` | Same |
| Local `.env` | Ops note: update and **re-connect** Shopify so the token matches (existing tokens may still have extra scopes — harmless) |

Do not fail connect if a shop already granted extra scopes.

### 3.4 Existing degraded connectors

Optional one-liner in PR notes: after deploy, re-run bootstrap or manually set `status=connected` if the only warn was those scopes. Not required for code if re-bootstrap is easy.

## 4. Backend — stats for the card

Prefer extending what list/detail already returns so Integrations needs one fetch.

### Option A (preferred): enrich `GET /api/v1/connectors/`

Each connector result adds optional `latest_bootstrap` (null if none):

```json
{
  "id": "…",
  "name": "shopify",
  "status": "connected",
  "latest_bootstrap": {
    "data_run_id": 53,
    "run_id": "a680e914-…",
    "data_run_status": "succeeded",
    "contacts": 13,
    "orders": 20,
    "issue_count": 0,
    "summary_status": "ok",
    "finished_at": "2026-07-30T14:23:34Z"
  }
}
```

Sources (already on bootstrap `DataRun.metadata`):

| Field | Source |
|-------|--------|
| `run_id` | `metadata.run_id` (domain UUID) — **prefer for UI “Run id”** |
| `data_run_id` | `DataRun.id` — secondary / debug |
| `contacts` | `health_report.fetch.contacts_upserted` or `metadata.counts.contacts` |
| `orders` | `health_report.fetch.orders_upserted` or `metadata.counts.orders` |
| `issue_count` | count of issues in preflight + postflight + import (all severities), or warn+error only — **document: count all health issues in the report** |

Reuse `find_latest_bootstrap_data_run` (same as bootstrap status view).

### Option B

Keep list thin; FE calls existing `GET /api/v1/connectors/{id}/bootstrap/` per connected card. Works but N+1 and today admin-only — if used, open to `admin` + `analyst` (+ `viewer` read).

**Ship Option A** unless list payload size is a concern.

## 5. Frontend — Integrations card

File: `klints_frontend/src/routes/integrations.tsx`

### 5.1 Connected definition

```ts
const isLinked = connector?.status === "connected" || connector?.status === "degraded";
const isError = connector?.status === "error";
```

- **Linked** → Connected badge (or Connected + muted “Degraded” when `degraded`), Remove, stats strip, Healthy / Degraded footer.  
- **Error** → Error badge, show Connect / retry as product allows, no fake healthy.  
- **Missing row** → Not connected / Connect.

Do **not** show Connect as primary when status is `degraded`.

### 5.2 Replace mock Integrity strip

Remove use of `integrationHealth` on this page for the card body.

When `isLinked` and `latest_bootstrap` present, show a compact stats row (keep similar sand strip layout; **no** fake DCS score):

| Label | Value |
|-------|--------|
| Run id | `run_id` (shorten in UI if needed, full in `title`) |
| Contacts | number |
| Orders | number |
| Issues | `issue_count` |

If bootstrap still running / missing: show “Bootstrap pending…” or hide stats until finished.

Link to `/data-consistency` is optional; not required if that page is still mock/locked.

### 5.3 Footer health copy

| `connector.status` | Footer |
|--------------------|--------|
| `connected` | Healthy |
| `degraded` | Degraded (optional short reason later) |
| `error` | Error / needs reconnect |
| none | Ready to connect |

## 6. Files to change

| Area | File |
|------|------|
| Recommended scopes | `dataruns/connectors/bootstrap_health.py` |
| FD-02 scopes | `dataruns/dcs/executors/foundation.py`, catalogue JSON if needed |
| OAuth defaults | `core/settings/base.py`, `.env.example` |
| List API enrich | `tenants/connector_views.py` (or serializer helper) |
| FE card | `integrations.tsx`; stop using mock `integrationHealth` for this strip |
| Tests | bootstrap_health, FD-02, connectors list shape, FE connected/`degraded` |

## 7. Acceptance

1. Shopify token with only `read_customers` + `read_orders` → bootstrap `summary_status=ok` (absent other warns) → `Connector.status=connected`.  
2. Missing `read_products` / `read_inventory` does **not** create `SCOPES_MISSING` warn and does **not** alone degrade or FAIL FD-02.  
3. Integrations card for Manago/Shopify shows **Connected** when status is `connected` or `degraded` (not “Not connected”).  
4. Stats strip shows real **run id**, **contacts**, **orders**, **issue count** from latest bootstrap — not mock 72 / R#146.  
5. Company with no bootstrap yet: linked card without fake numbers (pending/empty state).  
6. Manago card uses the same stats shape from its bootstrap counts.

## 8. Out of scope

- Full DCS score on the Integrations card  
- Changing required scopes `read_customers` / `read_orders`  
- AUDIT-01 Activity timeline  
- Redesigning the whole Integrations page beyond status + this strip + footer copy

## 9. Related

| Doc / artifact | Relation |
|----------------|----------|
| CONN-01 | Bootstrap health + status mapping; amend recommended scopes section |
| DCS-02 FD-02 | Align required Shopify scopes to customers + orders |
| Screenshot / current UI | Mock Integrity contribution → replace with live stats |
| Prior bug | `degraded` looked disconnected in FE |
