# WB-08 Phase 0 — Evidence path lock (SP-01 + LE-01)

**Status:** Locked 2026-09-19  
**PRD:** `PRD_WB_08_CATALOGUE_WAVE2_SP01_LE01.md` §4.2 / §5.3  
**Rule:** Prefer mapping / transform fixes. Do **not** reshape DCS executors unless blocked — then escalate to Sahil.

---

## Sources inspected

| Source | What it shows |
|--------|----------------|
| `dataruns/dcs/executors/lifecycle.py` `_gap_mismatch_rows` + `evaluate_le_01` | Real LE-01 FAIL provenance shape |
| `dataruns/tests/test_lifecycle_checks.py` | Asserts FAIL mismatches = `side=shopify_only` + `order.id` |
| `dataruns/writebacks/mappings/LE-01.event_backfill.v1.json` | Stub mapping paths (drifted) |
| `dataruns/tests/test_writeback_*` LE-01 fixtures | Synthetic `missing_purchase_event` — **not** executor truth |
| `dataruns/dcs/lifecycle_join.py` | Rich Shopify order rows exist **before** ID collapse |
| Export DCS-486 | LE-01 **PASS** (no FAIL worklist sample in exports) |
| Executor registry / `check_master_mvp1.json` | **No SP-01 executor**; SP-01 not in scored MVP1 list |

No live staging FAIL blob was required: unit tests pin the executor contract for LE-01. SP-01 has no FAIL blob because the check does not evaluate.

---

## LE-01 — locked FAIL / worklist row shape

`collect_evidence_rows` → worklist prefers `provenance.mismatches`.

**Canonical mismatch row (executor SoT):**

```json
{ "side": "shopify_only", "order.id": "<shopify_order_id>" }
```

Also emitted (not backfill targets): `{ "side": "manago_only", "order.id": "..." }`.

**Aggregate evidence** (worklist secondary; not row-level bind):

```text
locator = lifecycle.purchase_count_parity
value = { shopify_paid_orders, manago_purchase_events, overall_count_delta, failing_months, monthly, … }
```

### Mapping vs reality

| Mapping field today | Expected path | Actual on FAIL row | Verdict |
|---------------------|---------------|--------------------|---------|
| `match.side` | `missing_purchase_event` | `shopify_only` | **DRIFT — must fix** |
| `entity_key` | `order.id` | `order.id` present | **OK** (after match fix) |
| `fields.order_id` | `order.id` | present | **OK** |
| `fields.email` | `person.email` | **absent** | **GAP** |
| `fields.contact_id` | `manago_contact_id` | **absent** | **GAP** |
| `fields.value` | `representative_value` | **absent** (LE-04 only) | **GAP** |

`representative_value` is an **LE-04** cluster field, not LE-01.

### Rich data available but not on worklist rows

`lifecycle_join` paid Shopify orders carry:

```text
order.id · person.email · person.external_key · amount_gross · amount_net · ordered_at · …
```

Reconciliation then stores **ID-only** lists in `lifecycle.shopify_only` / `manago_only`. Executor mismatches therefore cannot satisfy `event_ingest` alone (`adapter` requires `email` or `contactId`).

### Locked Phase 1 binding (LE-01)

1. **Mapping-only (required):**  
   - `match.const` → `shopify_only` (not `missing_purchase_event`)  
   - Keep `entity_key` / `order_id` → `order.id`  
   - Drop or stop requiring `representative_value` as SoT from evidence

2. **Transform enrichment (required for execute, Maheep lane):**  
   Mirror CC-03 pattern: for each `shopify_only` row, resolve from company Order/Contact (or snapshot) → `person.email`, optional Manago `contact_id`, order amount → event value.  
   If unresolved → intent `error` / skip with honest `error_reason` (no silent Written).

3. **Escalate to Sahil only if** enrichment is rejected product-wise and executor must emit richer mismatches. Prefer not changing score shape.

4. **Do not** treat writeback unit-test fixtures with `missing_purchase_event` as production SoT — update those tests when mapping changes.

---

## SP-01 — evidence lock result

| Question | Answer |
|----------|--------|
| DCS executor `evaluate_sp_01`? | **None** |
| In `FOUNDATION` / segment / drift registries? | **No** |
| In `check_master_mvp1` scored set? | **No** (SP-08 / SP-12 exist; SP-01 does not) |
| Real FAIL / WARN worklist blob? | **Unavailable** — check never scores |
| Mapping ops today | `operations: []`, `enabled: false` |
| Closest live tag check | **SP-08** segment sanity — aggregate tag populations, not per-contact consolidation rows |

Architecture joins TAG assets to `_TAG_CHECKS = {SP-01, SP-08}` when those IDs appear on a DCS join — that does **not** create SP-01 evidence.

### Locked Phase 1 binding (SP-01)

Cannot invent `from_evidence` paths from a non-existent FAIL payload (PRD §4.2).

**Options (pick before building ops — do not invent contact fields):**

| Option | Approach | Notes |
|--------|----------|--------|
| **A — Block / escalate** | Defer SP-01 enable until Sahil ships SP-01 executor + FAIL rows with contact key | Cleanest vs PRD “inspect real FAIL” |
| **B — Sandbox transform** | Like `WB-SHOP-01` / CC-03 fallback: synthetic rows from Manago contacts when Settings sandbox / execute enabled | Demo path only; not Catalogue FAIL-driven |
| **C — Narrow MVP** | `tag_add` + const `klints:consolidated` + entity from explicit fixture / allowlist smoke only | Tests pass; Fix worklist still empty until check exists |

**Recommended for WB-08 honesty:** ship **LE-01** with locked paths above; for **SP-01** either escalate (A) or document B/C as sandbox-only and keep registry honest if worklist cannot produce intents.

If product insists on SP-01 mapping ops anyway, pin provisional paths only after choosing B/C — provisional draft (not production SoT):

```json
{
  "match": { "path": "side", "const": "<chosen_side>" },
  "entity_key": { "path": "person.email" },
  "fields": {
    "tag": { "const": "klints:consolidated" },
    "email": { "path": "person.email" },
    "contact_id": { "path": "manago_contact_id" }
  }
}
```

`<chosen_side>` must match whatever transform/sandbox emits — **not** locked until option chosen.

---

## Exit criteria (Phase 0)

- [x] LE-01 real FAIL mismatch shape documented and locked  
- [x] LE-01 mapping drift (`missing_purchase_event`) called out with mapping-only fix  
- [x] LE-01 email/contact/value gap called out (enrichment or escalate)  
- [x] SP-01: no real FAIL evidence; blocker / options locked  
- [x] Product pick: **SP-01 Option B** (sandbox `tag_consolidation` rows) until DCS executor exists  

**Phase 1 (done):** LE-01 match → `shopify_only` + `amount_gross`; transform enrichment; SP-01 ops filled with `klints:consolidated` + sandbox side `tag_consolidation`.

**Phase 2 (done + audited):** Registry + mapping `enabled=true`; migrations `0034`/`0035` seed/ensure allowlist; possible sheet + SURFACE matrix; FE approve allowlist; LE-01 `missing_contact_reference`; sandbox only when worklist empty (not on aggregate-only FAIL); `scripts/verify_wb08_catalogue_wave2.py`.

**Product lock (post Phase 3):** **SP-01 is not in MVP1 42** (`CHECK_MASTER_42` has SP-08/SP-12 only). Do **not** deep-ship SP-01 writeback. Registry/allowlist/sheet = **disabled**; mapping **`operations=[]`**; transform has **no** SP-01 sandbox enrichment. WB-08 ship surface = **LE-01 only**.

**Phase 3 (done):** LE-01 tests + verify script (LE-01-focused); SP-01 disabled via `0036` + stub emptied.
