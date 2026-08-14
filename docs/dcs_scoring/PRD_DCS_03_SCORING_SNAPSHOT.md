# PRD-DCS-03 — Scoring snapshot (frozen inputs)

**Depends on:** CONN-01 persisted contacts/orders; DCS-01 orchestration  
**DataPack:** sheet **06 Field Mapping Reference**, **05** Phases 1–4 entity needs

## 1. Goal

Before evaluating scored checks, build one **immutable scoring snapshot** for the DCS run from already-fetched data (no mid-run live pagination of full histories).

```text
source import Runs (Shopify + Manago)
  → normalize to Klints canonical fields
  → freeze JSON/blob + summary counts
  → checks read only this snapshot
```

## 2. Why

Sheet 08 / Connect Runbook: no score from partial sweep. Live re-fetch during scoring races and duplicates work. Snapshot = reproducible evidence.

## 3. Snapshot contents (v1)

```json
{
  "schema_version": "1.0.0",
  "company_id": "...",
  "as_of": "2026-07-24T06:00:00Z",
  "window_days": 30,
  "source_runs": {
    "shopify": { "run_id": "...", "data_run_id": 10, "window_start": "...", "window_end": "..." },
    "manago_ai": { "run_id": "...", "data_run_id": 11, "window_start": "...", "window_end": "..." }
  },
  "connectors": {
    "shopify": { "status": "connected", "scopes": [] },
    "manago_ai": { "status": "connected" },
    "erp": { "status": "not_connected" }
  },
  "counts": {
    "shopify_customers": 0,
    "shopify_orders": 0,
    "manago_contacts": 0,
    "manago_purchase_events": 0,
    "manago_cart_events": 0,
    "manago_return_events": 0
  },
  "contacts": [
    {
      "person.email": "",
      "person.external_key": "",
      "person.phone": "",
      "source": "shopify|manago_ai|both",
      "shopify_customer_id": "",
      "manago_contact_id": "",
      "email_marketing_consent": null,
      "sms_marketing_consent": null,
      "is_guest_order_identity": false
    }
  ],
  "orders": [
    {
      "order.id": "",
      "person.email": "",
      "person.external_key": "",
      "amount_gross": 0,
      "amount_net": null,
      "currency": "EUR",
      "status": "paid|refunded|cancelled",
      "ordered_at": "",
      "line_product_keys": [],
      "source": "shopify"
    }
  ],
  "events": [
    {
      "type": "PURCHASE|CART|RETURN|CANCEL",
      "order.id": "",
      "person.email": "",
      "person.external_key": "",
      "value": null,
      "product.keys": [],
      "occurred_at": "",
      "source": "manago_ai"
    }
  ],
  "products": [],
  "segments": [],
  "details": [],
  "workflows": [],
  "missing_inputs": [
    "products",
    "segments",
    "details",
    "workflows",
    "consent_provenance"
  ]
}
```

Canonical keys follow sheet **06** (`person.email`, `order.id`, etc.).

## 4. Build process

```text
1. Load latest succeeded bootstrap Run + ConnectorSnapshot per platform
2. Read Contact / Order rows for company (and any event payloads stored in snapshot_data)
3. Map via dataruns/connectors/{platform}/map.json + sheet 06 rules
4. Join identity:
   - preferred spine: person.external_key (CI-05)
   - fallback: normalized lowercase person.email
5. Write snapshot to:
   - DcsRun.snapshot (JSONField) OR
   - object storage / DB table DcsSnapshot
6. Set missing_inputs[] for surfaces not yet ingested
7. sweep_complete = missing_inputs does not include core entities required for RULE MVP1-A
   Core required for scored RULE beyond UNKNOWN:
   contacts + orders + purchase events (both systems)
```

## 5. Gap vs current ingest (explicit)

| Needed by checks | Current `run_import` | Snapshot v1 action |
|------------------|----------------------|--------------------|
| Customers / contacts | yes | include |
| Orders | yes | include |
| Manago purchase events | partial (from client transactions/events) | include from raw snapshot_data if not in tables |
| Products | **not fetched** | `missing_inputs: products` → PT-01/PT-03 may UNKNOWN |
| Consent fields | often absent on Contact | UNKNOWN for CC-* until mapped |
| Segments / details / klints_ | **not fetched** | UNKNOWN for SP-* |
| Workflows | **not fetched** | UNKNOWN for ME-02 |
| ERP | none | NOT_CONNECTED for BR_* |

Follow-up ingest PRDs may extend fetch; DCS-03 documents the contract so checks do not invent data.

## 6. Files

| File | Change |
|------|--------|
| `dataruns/dcs/snapshot.py` | builder |
| `dataruns/dcs/canonical.py` | field helpers from sheet 06 |
| `dataruns/models.py` | snapshot storage on `DcsRun` |
| `dataruns/connectors/shopify/map.json` / `manago_ai/map.json` | extend keys as needed |
| Possibly extend Manago/Shopify clients | products/consent — **only if required to clear UNKNOWN for MVP1-A RULE subset** |

## 7. Acceptance

1. Two DCS runs with same source_run_ids produce identical snapshot hashes.  
2. Snapshot lists `missing_inputs` honestly.  
3. Checks never call Shopify/Manago HTTP directly (gates may do cheap auth only).  
4. Unit test: synthetic contacts/orders → snapshot counts match.
