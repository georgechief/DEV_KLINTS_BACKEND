# PRD-FE-06 — Live guided DCS worklist (same real Overview UI)

**Status:** Ready for implementation  
**Module:** see folder path  
**Depends on:** FE-03 app lock (routes); FE-04 run progress tiles; DCS-08 revenue impact persistence (`RunIssueImpact`, `metadata.business_impact`); CheckMaster / DimensionMaster  
**Surfaces:**  
- BE: enrich `GET /api/v1/dcs/status/`; add `GET /api/v1/dcs/worklist/` + `GET /api/v1/dcs/worklist/{check_id}/`  
- FE: **one** Overview shell (`overview-panel` / today’s “real” dashboard) + live `/data-consistency` worklist  
**Scope:** Stop shipping a separate gated Overview. Always use the real dashboard UI; hide or empty slots when data is missing; keep FE-04 stage tiles until the headline score is ready; drive NBA / at-stake / evidence from live DCS.

---

## 0. Plan (read this first)

### Product rule (locked)

**Same pixels as the real Overview.** Do **not** design a second homepage (`DcsGatedDashboard` as a different product).

| Rule | Meaning |
|------|---------|
| Empty / hide | Anything not available yet → `—`, muted empty arc, “Not calculated” / “Calculating…”, hide fake widgets |
| Keep stages | Until headline score is ready → show FE-04 **Foundation + 7 dimension** stage tiles (orange / green / red) in the CMO dims slot |
| When ready | Fill score arc; **replace** stage tiles with live dimension scores; fill at-stake + NBA from live impact |
| App lock | FE-03 still gates *other routes* (Fix / Workflow / Data Consistency). Lock ≠ different Overview layout |

### Today vs target

| Surface today | Data | UX |
|---------------|------|-----|
| Locked Overview (`DcsGatedDashboard`) | Live `/dcs/status/` | Sparse alternate page |
| Unlocked Overview (`UnlockedDashboard`) | Mock `klints-data` | Real `overview-panel` with fake € / NBA |
| `/data-consistency` | Mock | Guided-by-impact — not live |

| Surface after FE-06 | Data | UX |
|---------------------|------|-----|
| **One Overview** | Live status (+ worklist) | Always `overview-panel`; slots empty or filled |
| `/data-consistency` | Live worklist + detail | Deep evidence (nav still locked until score ready) |

FE-03 shipped the gated sparse view; **FE-06 replaces Overview rendering**. Deprecate `DcsGatedDashboard` as the Overview target (thin migrate wrapper OK, then remove).

### Split

| PR | Delivers |
|----|----------|
| **BE first** | Status enrichment + worklist/detail APIs + tests |
| **FE second** | Wire real Overview slots + live Data Consistency (depends on BE deploy) |

---

## 1. Problem

Operators see either a sparse blocked page or a polished mock dashboard. They cannot:

1. Stay on the **real** Overview while the score is still calculating / blocked.  
2. See **which DCS stage** the run reached (FE-04) inside that same shell.  
3. See real FAIL/WARN ranked by **money at stake** (when DCS-08 computed it) in the NBA slots.  
4. Inspect **evidence** already on `RunIssue.details`.

Inventing € for checks without formulas destroys trust — same as DCS-08.

---

## 2. Goal

1. Always render the real Overview composition (`overview-panel` in `dashboard.tsx`).  
2. Empty / Not calculated / Calculating… where live data missing; **never** fake Lumera numbers next to live status.  
3. Until score ready: keep FE-04 stage tiles in the dimensions slot.  
4. Enrich status issues (FAIL+WARN) with impact + evidence preview; expose worklist + detail APIs.  
5. Put `check_summary`, `dimensions`, `business_impact` on status when present.  
6. Map NBA / blocker strip / at-stake to live worklist + rollup.  
7. Wire `/data-consistency` to live worklist + evidence; `?check=LE-05` (FE-05).

**Out of v1:** Fix / Workflow builders; inventing Opportunity / Untapped NBA stories; Fix plan PDF; inventing margin / “captured” €; full DCS-06 POST re-run.

---

## 3. Data already available (do not re-compute)

| Need | Source |
|------|--------|
| FAIL/WARN check rows | `DataRun.metadata["check_results"]` |
| Evidence / matches / mismatches / suggested_fix | `RunIssue.details` (fallback: check_results) |
| Per-check € | `RunIssueImpact.revenue_impact` (fallback: provenance) |
| Run rollup € | `DataRun.metadata["business_impact"]` |
| Dimension scores | `DataRun.metadata["dcs_run"]["dimensions"]` |
| Labels / optional / dimension | `CheckMaster` |
| Lock + stage progress | Status `app_access`, `score_display`, `run_progress` (FE-04) |

Join: latest DCS `DataRun` → domain `run_id` → `RunIssue` (`entity_type="dcs_check"`, `issue_type=check_id`).

---

## 4. Backend

### 4.1 Worklist inclusion / exclusion

| Include | Exclude |
|---------|---------|
| `status` in `{FAIL, WARN}` | `UNKNOWN`, `NOT_CONNECTED`, `NOT_APPLICABLE`, `PASS` |
| Synthetic “DCS run failed” when DataRun `failed` + error | `EXECUTOR_NOT_IMPLEMENTED` stubs |

### 4.2 Sort order (locked)

1. `revenue_impact` descending (null/0 → 0)  
2. Required before optional (`is_optional`)  
3. Severity (critical → informational)  
4. `check_id` ascending  

Cap: **30** on status `issues`; worklist may return all FAIL+WARN for latest terminal run.

### 4.3 Enriched issue object (list / status)

```json
{
  "check_id": "LE-05",
  "run_issue_id": "uuid-or-null",
  "title": "Order-level event gap list",
  "status": "FAIL",
  "severity": "critical",
  "dimension": "02 Lifecycle Event",
  "detail": "48 Shopify orders missing PURCHASE in Manago (30d).",
  "suggested_fix": "Upsert contacts before events; recover gaps from Shopify.",
  "root_cause_ids": ["RC-01", "RC-05", "RC-15"],
  "is_optional": false,
  "revenue_impact": 12000.0,
  "currency": "EUR",
  "evidence_preview": [
    {
      "source": "snapshot",
      "locator": "lifecycle_join.missing_purchases",
      "value": { "missing_count": 48, "amount": 12000, "currency": "EUR" },
      "observed_at": "2026-08-03T09:14:00Z"
    }
  ]
}
```

Rules:

- Reuse `status` as `FAIL` | `WARN` (no parallel field).  
- `revenue_impact`: from `RunIssueImpact` / provenance; display `—` when 0 / missing — **never invent**.  
- `currency`: when impact > 0; else `null`.  
- `evidence_preview`: up to **5** (prefer mismatches); truncate large `value`s.  
- `run_issue_id`: UUID or `null`.  
- `dimension`: CheckMaster label.

### 4.4 Status payload additions

Keep FE-03 / FE-04 fields. Add when present:

```json
{
  "check_summary": {
    "PASS": 30,
    "WARN": 4,
    "FAIL": 3,
    "UNKNOWN": 3,
    "NOT_CONNECTED": 2,
    "NOT_APPLICABLE": 0
  },
  "dimensions": {
    "01 Customer Identity": {
      "score": 81.8,
      "coverage": 1.0,
      "confidence": 1.0,
      "weight_percent": 18
    }
  },
  "business_impact": {
    "currency": "EUR",
    "estimate": 15230.4,
    "by_check": { "LE-05": 12000.0, "LE-09": 1800.0 },
    "excluded_from_rollup": { "LE-02": 12000.0 },
    "window_days": 30,
    "formula_version": "dcs_revenue_impact.v1",
    "revenue_mixed_currency": false
  }
}
```

- Score not ready → `dimensions` / `business_impact` / `check_summary` may be null; FE shows **stage tiles** from `run_progress`.  
- `_build_issues` → enriched FAIL+WARN + new sort (**supersedes** FE-03 §5.5 FAIL-only). Update related tests.

### 4.5 New endpoints

Base: `/api/v1/dcs/` — JWT; company from user; admin / analyst / viewer read.

#### `GET /api/v1/dcs/worklist/`

Latest **terminal** DCS DataRun. None → `200` empty list (not 404).

```json
{
  "data_run_id": 55,
  "domain_run_id": "uuid-or-null",
  "run_state": "CONDITIONALLY_READY",
  "headline_score": 72.4,
  "business_impact": { "...": "same as status or null" },
  "count": 3,
  "issues": [ { "...": "enriched issue object" } ]
}
```

#### `GET /api/v1/dcs/worklist/{check_id}/`

**200** — full evidence for one FAIL/WARN on latest terminal run:

```json
{
  "data_run_id": 55,
  "domain_run_id": "uuid",
  "check_id": "LE-05",
  "run_issue_id": "uuid",
  "title": "Order-level event gap list",
  "status": "FAIL",
  "severity": "critical",
  "dimension": "02 Lifecycle Event",
  "detail": "...",
  "suggested_fix": "...",
  "root_cause_ids": ["RC-01", "RC-05"],
  "is_optional": false,
  "revenue_impact": 12000.0,
  "currency": "EUR",
  "revenue_formula_id": "LE-05.missing_purchase_gmv.v1",
  "evidence": [ { "source", "locator", "value", "observed_at" } ],
  "matches": [],
  "mismatches": [],
  "provenance": { }
}
```

| Code | When |
|-----:|------|
| 404 | No terminal run, or check not FAIL/WARN |
| 401/403 | Auth |

Prefer `RunIssue.details` + `RunIssueImpact`; fill gaps from `check_results` + CheckMaster.

### 4.6 Implementation guidance (backend)

| File | Change |
|------|--------|
| `dataruns/dcs/worklist.py` (new) | Build enriched issues; sort; preview; detail |
| `dataruns/dcs/status.py` | Worklist builder for `issues`; attach summary/dimensions/business_impact |
| `dataruns/dcs/views.py` | Worklist list + detail views |
| `dataruns/dcs_urls.py` | `worklist/`, `worklist/<check_id>/` |
| `dataruns/tests/test_dcs_app_status.py` | Enrichment + WARN + revenue sort |
| `dataruns/tests/test_dcs_worklist.py` (new) | List + detail + 404 |

No new scoring logic. Do not invent revenue.

---

## 5. Frontend

### 5.1 Types + clients (`src/lib/dcs.ts`)

Extend `DcsIssue` with: `run_issue_id`, `dimension`, `revenue_impact`, `currency`, `evidence_preview`.  
Extend `DcsAppStatus` with optional `check_summary`, `dimensions`, `business_impact`.

```ts
getDcsWorklist(): Promise<DcsWorklistResponse>
getDcsWorklistIssue(checkId: string): Promise<DcsWorklistIssueDetail>
```

### 5.2 Overview — always the real shell (`dashboard.tsx`)

**Target:** one component tree based on today’s `UnlockedDashboard` / `overview-panel`.  
**Stop:** branching to a separate sparse `DcsGatedDashboard` layout for Overview.  
**Keep:** FE-03 `app_access` for nav / route guards; soft-lock poll.

Company header: live company name (not hardcoded “Lumera Skin” when API/auth provides tenant company).

#### Slot matrix (same UI, different fill)

| Slot | Score not ready (`not_calculated` / `calculating` / hard_locked without headline) | Score ready |
|------|-----------------------------------------------------------------------------------|-------------|
| **CMO score arc** | Label **Not calculated** or **Calculating…**; arc empty/muted (0); no fake number | Live `headline_score` |
| **Score delta / trend** | Hide or empty | Live only if history exists; else hide |
| **CMO dimensions area** | **FE-04 `run_progress` stage tiles** (Foundation + 7 dims) | Live dimension scores / chart from `dimensions` |
| **Value bar — at stake** | `business_impact.estimate` if present, else `—` | Same from `business_impact` |
| **Value bar — captured** | `—` / 0 in v1 (no invented resolved €) | Same until a real captured metric exists |
| **Next best actions** | Live FAIL/WARN as `ov-nba-card`s (impact € or `—`); empty state if none | Same, ranked by impact |
| **Top blocker strip** | #1 worklist issue if any; CTA → Connected stack | #1 issue; CTA → `/data-consistency?check=` |
| **Mock Opportunity / Untapped / fake margin** | **Remove** from live path | **Remove** from live path |
| **Open Data Center** | Disabled or hidden while route locked (FE-03) | Link enabled |
| **Add workflow / Fix menus** | Stay locked per FE-03 | Unlocked |

Message / CTA under score when not ready: reuse status `message`; primary repair path = Connected stack.

Soft-locked: poll status; stage tiles update live; arc stays Calculating….

### 5.3 Data Consistency (`data-consistency.tsx`)

Deep worklist (same issue model). Still behind FE-03 unlock for nav.

| Piece | Source |
|-------|--------|
| Score hero | `score_display` / worklist `headline_score` (or Not calculated if somehow opened) |
| Dimension tiles | Live `dimensions` when ready |
| Worklist | `GET /dcs/worklist/` |
| Expand | `GET /dcs/worklist/{check_id}/` |
| Search | `?check=LE-05`; `?issue=XX-NN` alias → check_id |

Adapt `DiagnoseEvidence` to API evidence props. **No** `klints-data` mock issues on the live path.  
Empty / error: soft copy + retry — never silent mock fallback.  
Re-run / Export: toast-only in v1.

### 5.4 Fix flow

Out of scope. Live CTAs → Connected stack or Data Consistency evidence — not mock `/fix?issue=iss-*`.

---

## 6. Sample UX (same shell)

### Score not ready (still real Overview)

```text
┌─ overview-panel ─────────────────────────────────────────────┐
│ Executive overview · Acme Co                                 │
│ Connected · Shopify · Manago                                 │
│                                                              │
│ Value bar                                                    │
│   Captured: —          At stake: —                           │
│                                                              │
│ Next best actions · ranked by impact                         │
│   [FD-02 Shopify auth · Critical · —]  → Connected stack     │
│                                                              │
│ CMO hero                                                     │
│   Data Consistency Score                                     │
│   [ empty arc ]  Not calculated                              │
│   Fix connectors under Connected stack…                      │
│                                                              │
│   Dimensions slot = FE-04 stages                             │
│   Foundation ● failed  Identity ○ …  Lifecycle ○ …           │
└──────────────────────────────────────────────────────────────┘
```

### Score ready (same shell, filled)

```text
┌─ overview-panel ─────────────────────────────────────────────┐
│ Executive overview · Acme Co                                 │
│                                                              │
│ Value bar                                                    │
│   Captured: —          At stake: €12,430                     │
│                                                              │
│ Next best actions                                            │
│   [LE-05 Event gap · Critical · €12,000] → Data Consistency  │
│   [LE-09 Returns · Critical · €1,800]                        │
│   [CI-01 Contact count · High · —]                           │
│                                                              │
│ CMO hero                                                     │
│   Data Consistency Score  72.4 / 100                         │
│   Dimensions: Identity 81 · Lifecycle 64 · … (live scores) │
│   Open Data Center →                                         │
└──────────────────────────────────────────────────────────────┘
```

### Data Consistency expand

```text
LE-05 · FAIL · €12,000
Evidence: source=snapshot locator=lifecycle_join.missing_purchases
Suggested fix: …
```

---

## 7. Acceptance

1. Overview uses **one** real `overview-panel` layout whether locked or unlocked — **no separate locked dashboard layout**.  
2. Score not ready → arc shows Not calculated / Calculating…; **FE-04 stage tiles** visible in dims slot.  
3. Score ready → live headline; stage tiles replaced by live dimension scores.  
4. No mock € / Opportunity NBA on the live path; at-stake only from `business_impact` when present.  
5. Status `issues` = FAIL+WARN, sorted by revenue then optional/severity/id.  
6. Status exposes `business_impact` / `dimensions` / `check_summary` when present.  
7. Worklist + detail APIs return impact + evidence.  
8. `/data-consistency` live worklist/evidence; no `klints-data` issues fallback.  
9. FE-03 `app_access` / `allowed_routes` unchanged (route lock only).  
10. Tests: revenue sort; WARN included; evidence on detail; Overview empty-state + stages when not ready.

---

## 8. Test plan

### Backend

1. LE-05 FAIL `revenue_impact=12000` ranks above CI-01 FAIL impact 0.  
2. WARN included; UNKNOWN excluded.  
3. Status includes `business_impact.estimate` when metadata has rollup.  
4. Detail 200 has `evidence[]` with `source` + `observed_at`.  
5. Detail 404 for PASS check_id.  
6. Lock tests still pass (FD-03 optional alone does not hard-lock).

### Frontend

1. Hard-locked company: **same** Overview chrome; arc Not calculated; stage tiles from `run_progress`; NBA from live FAIL/WARN.  
2. Soft-locked: Calculating… + live-updating stages.  
3. Unlocked: headline + at-stake from `business_impact`; dims = scores not stages; open `?check=LE-05`.  
4. Expand shows API evidence, not mock `iss-*`.  
5. API error: empty/error UI — no mock fallback.  
6. Fake Lumera captured / Opportunity cards absent on live path.

---

## 9. Related docs

- [`docs/frontend/PRD_FE_03_DCS_APP_LOCK.md`](./PRD_FE_03_DCS_APP_LOCK.md) — route lock / status (issues inclusion+sort superseded; **Overview layout superseded by this PRD**)  
- [`docs/frontend/PRD_FE_04_GATED_DCS_RUN_PROGRESS.md`](./PRD_FE_04_GATED_DCS_RUN_PROGRESS.md) — stage tiles (placement moves into real Overview dims slot until score ready)  
- [`docs/frontend/PRD_FE_05_SPOTLIGHT_GLOBAL_SEARCH.md`](./PRD_FE_05_SPOTLIGHT_GLOBAL_SEARCH.md) — `?check=` deep links  
- [`../dcs_scoring/PRD_DCS_08_REVENUE_IMPACT.md`](../dcs_scoring/PRD_DCS_08_REVENUE_IMPACT.md) — money formulas / rollup  
- [`../dcs_scoring/PRD_DCS_06_API_RESPONSES.md`](../dcs_scoring/PRD_DCS_06_API_RESPONSES.md) — fuller runs/checks (later)
