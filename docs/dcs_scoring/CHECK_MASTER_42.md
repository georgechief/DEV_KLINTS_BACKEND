# CHECK MASTER — MVP1 42 checks

**Authority:**  
`docs/dcs_scoring/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx`  
- IDs / weights / phase: tab **09 MVP1 Check Scope**  
- Systems / logic / RC / severity: tab **02 Check Catalogue**  
- Fixture ID set: `reference/fixtures/lumera_expected_results/check_results.json`

Do not rename IDs. Full detection logic text lives in sheet 02 — join by `Check ID` when implementing each executor.

## Summary

| Class | Count | Phase |
|-------|------:|-------|
| RULE_BASED GATE | 7 | MVP1-A |
| RULE_BASED SCORED | 21 | MVP1-A |
| DRIFT SCORED | 14 | MVP1-B |
| **Total** | **42** | |

## isOptional (PRD-FE-03)

| Check ID | isOptional | Notes |
|----------|:----------:|-------|
| FD-03 | `true` | ERP optional; does not block app gate alone |
| All other 41 checks | `false` | Required for app-gate blocking |

## Master table

Notes: **FD-03** is `isOptional=true` (FE-03 / ERP). **FD-07** = Excel VISIT/smclient **+** company-website SalesManago scrape (Sahil PRD; implement under FD-07).

| Seq | Check ID | Class | Dimension | Check Name | Check Type | Weight | Role | Cadence | Phase | Systems Compared | Root Causes | Severity |
|----:|----------|-------|-----------|------------|------------|-------:|------|---------|-------|------------------|-------------|----------|
| 1 | FD-01 | RULE_BASED | 00 Foundation Gate | Manago API authentication valid | Connectivity | 0 | GATE | Initial + Recurring | MVP1-A | Manago | RC-12 | Critical |
| 2 | FD-02 | RULE_BASED | 00 Foundation Gate | Shopify API authentication and scopes | Connectivity | 0 | GATE | Initial + Recurring | MVP1-A | Shopify | RC-12 | Critical |
| 3 | FD-03 | RULE_BASED | 00 Foundation Gate | ERP feed reachable and parseable | Connectivity | 0 | GATE | Initial + Recurring | MVP1-A | ERP | RC-06, RC-12 | High |
| 4 | FD-04 | RULE_BASED | 00 Foundation Gate | API rate-limit headroom measured | Connectivity | 0 | GATE | Initial | MVP1-A | Manago + Shopify | RC-15 | High |
| 5 | FD-05 | RULE_BASED | 00 Foundation Gate | Historical data depth available | Connectivity | 0 | GATE | Initial | MVP1-A | Manago + Shopify + ERP | RC-09 | Medium |
| 6 | FD-06 | RULE_BASED | 00 Foundation Gate | Manago account/sub-account topology mapped | Connectivity | 0 | GATE | Initial | MVP1-A | Manago | RC-11 | High |
| 7 | FD-07 | RULE_BASED | 00 Foundation Gate | Manago site tracking code active | Connectivity | 0 | GATE | Initial + Recurring | MVP1-A | Manago + Storefront | RC-12 | High |
| 8 | CI-01 | RULE_BASED | 01 Customer Identity | Contact count reconciliation | Cross-system reconciliation | 4 | SCORED | Initial + Recurring | MVP1-A | Manago vs Shopify | RC-01, RC-03, RC-09 | High |
| 9 | CI-02 | RULE_BASED | 01 Customer Identity | Guest checkout identity share | Presence | 4 | SCORED | Initial + Recurring | MVP1-A | Shopify | RC-03 | High |
| 10 | CI-03 | RULE_BASED | 01 Customer Identity | Duplicate contacts in Manago | Uniqueness | 4 | SCORED | Initial + Recurring | MVP1-A | Manago | RC-04, RC-08 | High |
| 11 | CI-05 | RULE_BASED | 01 Customer Identity | External ID linkage integrity | Referential integrity | 4 | SCORED | Initial + Recurring | MVP1-A | Manago vs Shopify | RC-01, RC-02 | Critical |
| 12 | LE-01 | RULE_BASED | 02 Lifecycle Event | Purchase event count parity | Cross-system reconciliation | 4 | SCORED | Initial + Recurring | MVP1-A | Manago vs Shopify | RC-01, RC-05, RC-15 | Critical |
| 13 | LE-02 | RULE_BASED | 02 Lifecycle Event | Purchase value parity | Cross-system reconciliation | 4 | SCORED | Initial + Recurring | MVP1-A | Manago vs Shopify | RC-02, RC-13, RC-14 | High |
| 14 | LE-03 | RULE_BASED | 02 Lifecycle Event | Order ID (externalId) presence on events | Presence | 4 | SCORED | Initial | MVP1-A | Manago | RC-02, RC-13 | High |
| 15 | LE-04 | RULE_BASED | 02 Lifecycle Event | Duplicate purchase events per order | Uniqueness | 4 | SCORED | Initial + Recurring | MVP1-A | Manago | RC-04, RC-05, RC-13 | High |
| 16 | LE-05 | RULE_BASED | 02 Lifecycle Event | Order-level event gap list | Cross-system reconciliation | 4 | SCORED | Initial + Recurring | MVP1-A | Shopify vs Manago | RC-01, RC-05, RC-15 | Critical |
| 17 | LE-09 | RULE_BASED | 02 Lifecycle Event | Returns and cancellations reflected | Cross-system reconciliation | 4 | SCORED | Initial + Recurring | MVP1-A | Shopify vs Manago | RC-01 | Critical |
| 18 | PT-01 | RULE_BASED | 03 Product & Transaction | Event product IDs resolve in catalog | Referential integrity | 4 | SCORED | Initial + Recurring | MVP1-A | Manago | RC-02, RC-10, RC-13 | High |
| 19 | PT-03 | RULE_BASED | 03 Product & Transaction | Catalog completeness vs commerce | Cross-system reconciliation | 4 | SCORED | Initial + Recurring | MVP1-A | Manago vs Shopify | RC-01, RC-05, RC-10 | High |
| 20 | PT-04 | RULE_BASED | 03 Product & Transaction | Net vs gross transaction truth per contact | Cross-system reconciliation | 4 | SCORED | Initial + Recurring | MVP1-A | Manago vs Shopify | RC-01 | Critical |
| 21 | SP-03 | RULE_BASED | 04 Segment & Property | Standard detail schema consistency | Schema / format | 4 | SCORED | Initial | MVP1-A | Manago | RC-06, RC-08 | High |
| 22 | SP-07 | RULE_BASED | 04 Segment & Property | klints_ namespace availability | Uniqueness | 5 | SCORED | Initial | MVP1-A | Manago | RC-04 | Critical |
| 23 | CC-01 | RULE_BASED | 05 Channel & Consent | Email opt-in parity | Consent compliance | 4 | SCORED | Initial + Recurring | MVP1-A | Shopify vs Manago | RC-07, RC-05, RC-01 | Critical |
| 24 | CC-02 | RULE_BASED | 05 Channel & Consent | SMS / mobile consent parity | Consent compliance | 4 | SCORED | Initial + Recurring | MVP1-A | Shopify vs Manago | RC-07, RC-05 | Critical |
| 25 | CC-03 | RULE_BASED | 05 Channel & Consent | Consent provenance completeness | Presence | 4 | SCORED | Initial | MVP1-A | Manago | RC-08, RC-09 | High |
| 26 | CC-05 | RULE_BASED | 05 Channel & Consent | Opt-out propagation loop | Consent compliance | 4 | SCORED | Initial + Recurring | MVP1-A | Manago vs Shopify | RC-01, RC-05, RC-07 | Critical |
| 27 | ME-02 | RULE_BASED | 06 Measurement | Workflow revenue attribution wiring | Presence | 4 | SCORED | Initial | MVP1-A | Manago | RC-12 | High |
| 28 | BR-01 | RULE_BASED | 07 Business Reality | Margin data coverage per product | Presence | 4 | SCORED | Initial + Recurring | MVP1-A | ERP vs Manago | RC-01, RC-02 | High |
| 29 | CI-13 | DRIFT | 01 Customer Identity | Contact state distribution sanity | Statistical anomaly | 2 | SCORED | Initial + Recurring | MVP1-B | Manago | RC-08, RC-15 | Medium |
| 30 | CI-14 | DRIFT | 01 Customer Identity | Web identity match rate | Statistical anomaly | 2 | SCORED | Initial + Recurring | MVP1-B | Manago | RC-12, RC-03 | Medium |
| 31 | CI-15 | DRIFT | 01 Customer Identity | Contact record freshness | Freshness | 2 | SCORED | Initial | MVP1-B | Manago | RC-09, RC-01 | Low |
| 32 | LE-08 | DRIFT | 02 Lifecycle Event | Stale open carts | Freshness | 2 | SCORED | Initial + Recurring | MVP1-B | Manago | RC-05, RC-13 | Medium |
| 33 | LE-11 | DRIFT | 02 Lifecycle Event | Event ingestion lag and loss | Statistical anomaly | 4 | SCORED | Initial + Recurring | MVP1-B | Manago | RC-05, RC-15 | High |
| 34 | LE-13 | DRIFT | 02 Lifecycle Event | Event volume drift monitor | Statistical anomaly | 2 | SCORED | Recurring | MVP1-B | Manago vs Shopify | RC-05, RC-15 | Medium |
| 35 | PT-14 | DRIFT | 03 Product & Transaction | Order value distribution anomaly | Statistical anomaly | 2 | SCORED | Initial + Recurring | MVP1-B | Manago | RC-13, RC-14, RC-08 | Medium |
| 36 | SP-08 | DRIFT | 04 Segment & Property | Segment population sanity | Statistical anomaly | 4 | SCORED | Initial + Recurring | MVP1-B | Manago | RC-06, RC-08, RC-10 | High |
| 37 | SP-12 | DRIFT | 04 Segment & Property | Property freshness on decision fields | Freshness | 2 | SCORED | Initial + Recurring | MVP1-B | Manago | RC-05, RC-10 | Medium |
| 38 | CC-12 | DRIFT | 05 Channel & Consent | Consent age and re-permission surface | Freshness | 1 | SCORED | Initial | MVP1-B | Manago | RC-09 | Low |
| 39 | ME-08 | DRIFT | 06 Measurement | Baseline computability for impact claims | Statistical anomaly | 2 | SCORED | Initial | MVP1-B | Manago vs Shopify | RC-09 | Medium |
| 40 | ME-09 | DRIFT | 06 Measurement | Email deliverability posture snapshot | Statistical anomaly | 2 | SCORED | Initial | MVP1-B | Manago | RC-08, RC-15 | Medium |
| 41 | BR-02 | DRIFT | 07 Business Reality | Inventory freshness SLA | Freshness | 4 | SCORED | Initial + Recurring | MVP1-B | ERP vs Shopify vs Manago | RC-05 | High |
| 42 | BR-12 | DRIFT | 07 Business Reality | ERP sync freshness heartbeat | Freshness | 2 | SCORED | Recurring | MVP1-B | ERP | RC-05, RC-15 | Medium |

## Root cause taxonomy (sheet 03)

| Code | Name |
|------|------|
| RC-01 | Integration gap |
| RC-02 | Mapping error |
| RC-03 | Guest / anonymous identity |
| RC-04 | Duplicate creation |
| RC-05 | Sync lag / timing |
| RC-06 | Schema / definition drift |
| RC-07 | Consent flow divergence |
| RC-08 | Manual entry / import artifact |
| RC-09 | Historical migration gap |
| RC-10 | Deleted / archived residue |
| RC-11 | Multi-store / multi-account ambiguity |
| RC-12 | Configuration error |
| RC-13 | API contract violation / type misuse |
| RC-14 | Format / unit / timezone inconsistency |
| RC-15 | Volume loss |

## Dimension weights (sheet 07)

| Dimension | Weight % |
|-----------|---------:|
| 01 Customer Identity | 18 |
| 02 Lifecycle Event | 18 |
| 03 Product & Transaction | 14 |
| 04 Segment & Property | 12 |
| 05 Channel & Consent | 18 |
| 06 Measurement | 10 |
| 07 Business Reality | 10 |
