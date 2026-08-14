# PRD-DCS-08 — Per-check revenue impact from DCS evidence

**Status:** Ready for implementation  
**Owner track:** Sahil (`docs/sahil/`)  
**Depends on:** DCS-03 snapshot + joins (`lifecycle_join`, `product_truth`); DCS-04 RULE executors (LE-02/04/05/09, PT-04 shipped); `persist_dcs_issues` / `RunIssueImpact`  
**Does not change:** DCS 0–100 score assembly (Excel sheets **07 / 08**) — scores stay PASS/WARN/FAIL factors  
**DataPack / Excel:** sheet **02** Business Impact is qualitative; this PRD defines the **numeric €/$ layer** where evidence already has money  
**Surfaces:** `CheckResult.provenance.revenue_impact` → `RunIssueImpact.revenue_impact`; optional run-level rollup for API / report later

---

## 1. Problem

`RunIssueImpact.revenue_impact` exists and `dataruns/dcs/issues.py` already reads:

```text
provenance.revenue_impact
  else evidence[].value.revenue_impact
  else 0
```

Almost no executor sets it today → every issue stores **0**, so UI / report “business impact” is empty even when lifecycle joins already know missing order GMV, return GMV, LTV overstatement, and duplicate purchase value.

Client pack does **not** define one formula for all 21 RULE checks. Inventing € for consent/schema/foundation destroys trust. We only attach money where Shopify/Manago evidence has amounts.

---

## 2. Goal

1. Emit **numeric `revenue_impact`** on FAIL/WARN for a **locked allowlist** of checks.  
2. Use the **same DCS window** as scoring (fresh snapshot preferred, DB fallback) — not all-time guesswork (except PT-04 lifetime semantics).  
3. Document **exact formulas** + **rollup dedupe** so LE-02 and LE-05 do not double-count.  
4. Persist currency + window metadata for audit.  
5. Leave all other checks at `0` (no proxies in v1).

**Out of v1:** CI/CC/SP/ME/BR/FD money proxies; finance-grade multi-currency FX; report PDF composition (may consume rollup later).

---

## 3. Locked check allowlist

| Priority | Check ID | Emit `revenue_impact`? | Role |
|----------|----------|------------------------|------|
| P0 | **LE-05** | Yes | **Canonical** missing-purchase GMV |
| P0 | **LE-09** | Yes | Missing return / cancel GMV |
| P0 | **LE-04** | Yes | Duplicate PURCHASE inflated GMV |
| P0 | **PT-04** | Yes | Per-contact net LTV overstatement |
| P1 | **LE-02** | Yes (check card only) | Same missing GMV as LE-05 for value-parity card |
| — | All other scored / gate checks | **No → 0** | Qualitative Business Impact only |

---

## 4. Data window & sources

### 4.1 Window

```text
as_of          = DCS run evaluated_at (UTC)
window_days    = snapshot.window_days  # default settings.BOOTSTRAP_DAYS (30)
common_days    = history_depth.common_window_days if present else window_days
window_start   = as_of − common_days
```

Include an order/event in money math **iff** its commerce timestamp ∈ `[window_start, as_of]`  
(except **PT-04**: lifetime per linked contact — see §6.4).

### 4.2 Source precedence (already in `lifecycle_join`)

| Rank | Source | When |
|------|--------|------|
| 1 | Fresh connector snapshot **raw** (Shopify orders + Manago transactions from DCS fresh-import) | Preferred “current” |
| 2 | DB `Order` / imported rows for company + platform | Fallback when raw empty |

Do **not** mix double-counting the same `order.id` from raw and DB — joins already prefer one path per platform.

### 4.3 Amount fields

| Side | Field | Notes |
|------|-------|-------|
| Shopify paid order | `total_price` → join `amount_gross` | Primary GMV |
| Shopify | `subtotal_price` → `amount_net` | Used in PT-04 / LE-02 net compares; **not** LE-05 primary |
| Manago PURCHASE | event `value` | For dup / parity residual only |
| Currency | Shopify shop currency (or first order `currency`) | Persist as ISO code string; no FX in v1 |

If currency missing → still emit amount; set `currency=null` and `confidence` one step lower.

---

## 5. When to emit (status rules)

| Check status | `revenue_impact` |
|--------------|------------------|
| `PASS` | `0` |
| `WARN` / `FAIL` | formula below (may be `0` if gap counts > 0 but amounts missing — then set `revenue_impact_unknown=true` in provenance) |
| `UNKNOWN` / `NOT_CONNECTED` / `NOT_APPLICABLE` | `0` (do not invent) |

Always attach provenance block (even when 0 on FAIL with missing amounts):

```json
{
  "revenue_impact": 1234.56,
  "revenue_currency": "EUR",
  "revenue_window_days": 30,
  "revenue_as_of": "2026-08-02T09:30:00Z",
  "revenue_source": "snapshot_raw",
  "revenue_formula_id": "LE-05.missing_purchase_gmv.v1"
}
```

`issues.py` already maps `provenance.revenue_impact` → `RunIssueImpact`. Extend only if you also want currency on `RunIssueImpact` / `details` (optional; can live in `details` JSON via evidence).

---

## 6. Formulas (normative)

Money type: `Decimal` quantized to **2 decimal places** (half-up) for display/storage on impact; keep fuller precision in evidence if useful.

### 6.1 LE-05 — missing purchase GMV (canonical)

**Definition:** Paid, non-test Shopify orders in window with **no** matching Manago PURCHASE (`externalId` match, else already-applied heuristic leave unmatched).

Join already computes:

```text
missing_events_value = Σ amount_gross(order) for order.id in shopify_only_all
```

**Formula:**

```text
revenue_impact_LE05 =
  Σ Shopify.amount_gross
  for order in paid_shopify
  where order.id ∈ shopify_only_all
    and order.created_at ∈ window
```

**Implementation:** set  
`provenance.revenue_impact = round(life["value_decomposition"]["missing_events_value"], 2)`  
when status is FAIL/WARN and that field exists; else compute from `life["orders"]` filtered by `shopify_only_all`.

`revenue_formula_id`: `LE-05.missing_purchase_gmv.v1`

Also put per-order sample in mismatches (id + amount) — cap 50 (existing sample cap OK).

---

### 6.2 LE-02 — purchase value parity (alias of LE-05 missing leg)

Excel: decompose missing events vs value-field vs gross/net drift.

**For revenue_impact on the LE-02 card only:**

```text
revenue_impact_LE02 = missing_events_value   # same Σ as LE-05
```

Do **not** use `|shopify_gross − manago_value|` as revenue_impact (mixes mapping drift + extras).  
Do **not** add `extra_events_value` into revenue_impact in v1 (inflated Manago is not “lost Shopify GMV”).

Optional evidence-only fields (not stored as `revenue_impact`):

```text
parity_abs_delta_gross = |shopify_order_value_gross − manago_purchase_value|
residual_after_gaps    = max(parity_abs_delta_gross − missing_events_value − extra_events_value, 0)
```

`revenue_formula_id`: `LE-02.missing_events_value.v1`

---

### 6.3 LE-09 — missing return / cancel GMV

**Definition:** Shopify refunded / partially_refunded / cancelled orders in window with no Manago RETURN/CANCELLATION on `externalId`.

```text
revenue_impact_LE09 =
  Σ Shopify.amount_gross
  for order in refund_cancel_shopify
  where order.id ∈ shopify_only_returns
    and order timestamp ∈ window
```

Prefer exposing `shopify_only_returns_value` on `return_coverage` in `lifecycle_join` if not already summed; until then sum in executor from order list + id set.

If Shopify has returns but Manago stream empty (`manago_rc == 0` and `shopify_rc > 0`):

```text
revenue_impact_LE09 = Σ amount_gross(all refund_cancel_shopify in window)
```

`revenue_formula_id`: `LE-09.missing_return_gmv.v1`

---

### 6.4 LE-04 — duplicate PURCHASE GMV

For each duplicate cluster (same `externalId`, or same contact+date+value heuristic):

```text
cluster_impact = (event_count − 1) × representative_value
```

`representative_value` = value of **earliest** event in cluster (or mean if timestamps tie — document choice: **earliest**).

```text
revenue_impact_LE04 = Σ cluster_impact over clusters with event_count ≥ 2
```

Only when check is FAIL/WARN. PASS → 0.

`revenue_formula_id`: `LE-04.duplicate_purchase_gmv.v1`

---

### 6.5 PT-04 — net vs gross / refund-blind overstatement

Per linked contact (existing `product_truth`):

```text
overstatement(contact) = max(manago_purchase_value_deduped − shopify_net, 0)
```

where `shopify_net` = paid orders − refunds/cancels for that customer (join already defines).

```text
revenue_impact_PT04 = total_overstatement
                    = Σ overstatement(contact) for linked contacts
```

**Window note:** PT-04 is **lifetime** on linked identities in the snapshot (Excel: per-contact lifetime vs Shopify net). Do **not** force the 30-day window on PT-04 amounts. Still record `revenue_window_days: null` and `revenue_scope: "lifetime_linked_contacts"`.

`revenue_formula_id`: `PT-04.ltv_overstatement.v1`

---

## 7. Run-level rollup (deduped)

For API / future report `business_impact.estimate`:

```text
rollup_revenue_impact =
    revenue_impact_LE05
  + revenue_impact_LE09
  + revenue_impact_LE04
  + revenue_impact_PT04
```

**Hard rules:**

| Include | Exclude from rollup |
|---------|---------------------|
| LE-05, LE-09, LE-04, PT-04 | **LE-02** (same missing GMV as LE-05) |
| | Any check not in allowlist |
| | PASS / UNKNOWN / NOT_CONNECTED zeros |

Helper (new), e.g. `dataruns/dcs/revenue_impact.py`:

```python
ROLLUP_CHECK_IDS = frozenset({"LE-05", "LE-09", "LE-04", "PT-04"})
# LE-02 intentionally omitted

def rollup_revenue_impact(results: list[CheckResult]) -> dict:
    ...
```

Persist optional fields on `DataRun.run_snapshot` or assemble payload:

```json
{
  "business_impact": {
    "currency": "EUR",
    "estimate": 15230.40,
    "by_check": {
      "LE-05": 12000.00,
      "LE-09": 1800.00,
      "LE-04": 430.40,
      "PT-04": 1000.00
    },
    "excluded_from_rollup": { "LE-02": 12000.00 },
    "window_days": 30,
    "as_of": "...",
    "formula_version": "dcs_revenue_impact.v1"
  }
}
```

---

## 8. Implementation plan

### 8.1 Join hardening (small)

| File | Change |
|------|--------|
| `dataruns/dcs/lifecycle_join.py` | Ensure `value_decomposition.missing_events_value` always present; add `return_coverage.shopify_only_returns_value` = Σ gross for `shopify_only_returns` |
| `dataruns/dcs/product_truth.py` | Already has `total_overstatement` — no formula change |

### 8.2 Executors

| File | Change |
|------|--------|
| `lifecycle.py` → LE-05, LE-02, LE-09, LE-04 | Set provenance revenue fields on WARN/FAIL |
| `product.py` → PT-04 | Set from `total_overstatement` |

Shared helper preferred:

```python
def attach_revenue_impact(
    provenance: dict,
    *,
    amount: float | Decimal,
    currency: str | None,
    formula_id: str,
    window_days: int | None,
    as_of: str,
    source: str,
) -> dict:
    ...
```

### 8.3 Rollup + issues

| File | Change |
|------|--------|
| `dataruns/dcs/revenue_impact.py` | **New** — attach helper + `rollup_revenue_impact` |
| `dataruns/dcs/orchestrate.py` or assemble path | After checks, write `business_impact` onto `run_snapshot` |
| `dataruns/dcs/issues.py` | No change required if provenance set; optional copy currency into `details` |

### 8.4 Tests

| Case | Expect |
|------|--------|
| 2 Shopify-only orders €50 + €70 | LE-05 impact `120.00`; LE-02 impact `120.00`; rollup `120.00` (not 240) |
| 1 refund €30 with no Manago RETURN | LE-09 impact `30.00`; rollup includes 30 |
| Dup cluster 3 events value 40 | LE-04 impact `(3−1)×40 = 80` |
| PT-04 total_overstatement 15.5 | PT-04 impact `15.50` |
| LE-05 PASS | impact `0` |
| CI-01 FAIL | impact `0` |
| UNKNOWN missing lifecycle | impact `0`, no crash |

---

## 9. Acceptance

1. FAIL LE-05 with known missing order totals → `RunIssueImpact.revenue_impact` matches Σ gross.  
2. LE-02 FAIL same fixture → same amount on LE-02 issue; **rollup counts once**.  
3. LE-09 / LE-04 / PT-04 match formulas in §6.  
4. PASS / UNKNOWN / non-allowlist → `0`.  
5. Provenance includes `revenue_formula_id`, currency, window (or lifetime scope for PT-04).  
6. `business_impact.estimate` on snapshot equals deduped rollup.  
7. No FX; multi-currency shops: use shop primary currency; if mixed currencies in window → `revenue_impact` still summed in native units **only if single currency**; if mixed, set estimate `null`, attach `revenue_mixed_currency=true`, keep per-check amounts with their currency (v1 stretch: fail closed to null rollup).

**v1 locked for mixed currency:** if >1 currency in contributing orders, per-check may still emit amount in majority currency with `confidence` MEDIUM and flag; rollup `estimate=null` + note. Prefer single-currency shops (Shopify one shop currency) for MVP1.

---

## 10. Explicit non-goals (do not implement in this PRD)

- CI-01/02 AOV × count proxies  
- CC quadrant × email revenue  
- ME-02 “unmeasured workflow” invented uplift  
- BR-01 margin $ without ERP cost feed  
- Changing Excel score weights or PASS/WARN cutovers  
- Replacing qualitative sheet-02 Business Impact text  

---

## 11. Files to change

| File | Change |
|------|--------|
| `dataruns/dcs/revenue_impact.py` | **New** helpers + rollup |
| `dataruns/dcs/lifecycle_join.py` | `shopify_only_returns_value` (+ confirm missing_events_value) |
| `dataruns/dcs/executors/lifecycle.py` | LE-02/04/05/09 provenance |
| `dataruns/dcs/executors/product.py` | PT-04 provenance |
| `dataruns/dcs/orchestrate.py` / assemble | Write `business_impact` on snapshot |
| `dataruns/tests/test_revenue_impact.py` | **New** formula + dedupe tests |
| `docs/dcs_scoring/PRD_DCS_01_...` | Optional one-line pointer to this PRD |

---

## 12. Handoff note for Sahil

1. Do **not** invent money for all 21 RULE checks.  
2. Implement P0 formulas first (LE-05, LE-09, LE-04, PT-04), then LE-02 alias.  
3. Reuse join numbers — don’t re-fetch Shopify inside executors.  
4. Rollup must exclude LE-02.  
5. Score engine untouched; this is impact metadata only.
