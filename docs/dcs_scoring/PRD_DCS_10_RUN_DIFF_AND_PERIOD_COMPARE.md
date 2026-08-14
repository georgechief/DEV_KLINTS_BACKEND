# PRD-DCS-10 — Run diff (audit) + period compare (Overview)

**Status:** Ready for implementation  
**Owner track:** Backend DCS (`docs/dcs_scoring/`) + FE Overview / Data Center / Activity (backend + frontend surfaces)  
**Depends on:** DCS-01 orchestration · DCS-06 status/history APIs · DCS-08 revenue impact (`business_impact.estimate`) · AUDIT-01 Activity · FE-06 Overview live shell  
**Surfaces:** `GET /api/v1/dcs/history/` · Overview period control · Dimension charts · Captured by Klints · Data Center trend · `/activity`  
**Out of scope:** Real “money captured” workflow attribution · Opportunities live wiring (stub only) · Architecture AF period horizon · inventing Billing/capture ledger  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-DCS-10 (BE first, then FE).

Read: docs/dcs_scoring/PRD_DCS_10_RUN_DIFF_AND_PERIOD_COMPARE.md

Two layers (do not conflate):

A) Persist consecutive run-diff on every SUCCEEDED DCS score (audit + metadata).
   - Compare this run vs previous SUCCEEDED score run for same company.
   - Store under DataRun.metadata["run_diff"] and enrich dcs.score_completed audit metadata.
   - Include: headline_score Δ, dimensions Δ, business_impact.estimate Δ, check_summary counts Δ.
   - First ever run → run_diff.baseline = true, deltas null.

B) On GET /api/v1/dcs/history/?since=&until= (or days=):
   - Keep existing points + value_capture series.
   - ADD period_compare: oldest vs newest SUCCEEDED scored runs INSIDE the requested window.
   - period_compare drives Overview Captured / score Δ / dimension +/- when user changes period.
   - Never use consecutive previous-run for Overview period UI.

FE:
1. Overview period change → resolveOverviewPeriodWindow → refetch history with since/until.
2. Wire score Δ, dimension showDelta, and Captured from period_compare (not hard-coded 0).
3. Captured v1 = at-stake estimate improvement in window (see §1.3). Do not invent revenue_captured.
4. Activity: show human summary from audit metadata when present.

Acceptance: checklist in §10.
```

---

## 1. Product decisions (locked)

### 1.1 Two different comparisons

| Layer | When computed | Baseline | Purpose | Consumers |
|-------|---------------|----------|---------|-----------|
| **A. Consecutive run-diff** | Write-time, after each SUCCEEDED score | Immediately previous SUCCEEDED score run (any time) | Audit trail: “what changed since last score” | `/activity`, DataRun detail, future notifications |
| **B. Period compare** | Read-time on history GET | Oldest SUCCEEDED scored run **in the selected window** vs newest in that window | Executive Overview charts / Captured / Δ for the selected period | Overview, Data Center period charts |

**Do not** use consecutive run-diff for Overview period labels (“Last 14 days”, “This quarter”).  
**Do not** recompute consecutive run-diff only on read — persist it once for audit integrity.

### 1.2 Which runs qualify

Include only terminal DCS score runs that:

- Belong to the company  
- Have a usable headline score (same rules as today’s `build_dcs_histories`)  
- Are not failed/cancelled mid-pipeline  

Prefer **SUCCEEDED** (or equivalent terminal success with score). If product later allows `INCOMPLETE` with a headline, follow the same inclusion rules as history points today — keep one shared filter helper.

### 1.3 “Captured by Klints” — MVP honesty

Today:

- Overview UI reads `value_capture.revenue` / `margin` from history, which only fills when `business_impact.revenue_captured` (etc.) exists.  
- Backend **never writes** those fields; it writes **at-stake** `business_impact.estimate` (DCS-08).  
- So Captured stays empty even when scores improve.

**Locked MVP semantics for Captured (this PRD):**

| Metric | Source | Meaning |
|--------|--------|---------|
| **At stake (current)** | Latest status `business_impact.estimate` | Risk still open — unchanged |
| **Captured (period)** | `period_compare.estimate_delta` when estimate **decreased** | Improvement in open risk over the selected window: `max(0, first.estimate − last.estimate)` |
| **Captured spark / series** | Optional series of per-run `estimate` (or derived improvement vs window start) | Chart of at-stake over period — not fake “cash captured” |

Copy / tooltip must say this is **risk reduced / at-stake improvement**, not banked revenue, until a real capture ledger exists.

**Do not** invent `revenue_captured` persistence in this PRD.  
Future PRD can add true capture when workflows close findings.

### 1.4 Dimension deltas

- Overview dimension chart: `showDelta={true}` when `period_compare.dimensions` has ≥2 runs in window.  
- Delta per dimension = `last.score − first.score` (or % if UI already uses that — match existing `DcsDimensionChart` contract).  
- Consecutive run-diff also stores dimension deltas for Activity.

### 1.5 Period control (FE already exists)

Labels in `src/lib/overview-period.ts`:

- This quarter · Last 30 days · This month · Last quarter · Last 14 days  

On change: recompute `since` / `until` → refetch history → rebuild charts from `points` + bind deltas from `period_compare`.

---

## 2. Why

| Gap | Problem |
|-----|---------|
| Overview Captured | Always empty — FE expects capture fields BE never writes |
| Dimension +/- | Hard-coded `delta: 0` + `showDelta={false}` |
| Score Δ | Works only if ≥2 history points; not clearly tied to period semantics |
| Audit | `dcs.score_completed` logs score/state but not what changed vs prior run |
| Period change | History refetch exists; no first/last compare payload for money/dimensions |

---

## 3. Architecture

```text
                    SUCCEEDED score finishes
                              │
                              ▼
                 ┌────────────────────────┐
                 │ Compute consecutive    │
                 │ run_diff vs previous   │
                 │ SUCCEEDED run          │
                 └───────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     metadata.run_diff   audit metadata   (optional notify later)
              │
              │
     GET /dcs/history/?since=&until=
              │
              ▼
     points[] + value_capture{}
              + period_compare { first, last, deltas }
              │
              ▼
     Overview period UI / Data Center trends
```

---

## 4. Part A — Persist consecutive run-diff (write path)

### 4.1 When

After a DCS score run reaches a terminal success with a headline score (same place as `_audit_dcs_completed` in `dataruns/dcs/orchestrate.py`), **before or immediately after** audit append:

1. Load previous SUCCEEDED scored `DataRun` for the company (exclude current).  
2. Build `run_diff` object.  
3. Persist onto `data_run.metadata["run_diff"]`.  
4. Include the same object (or a compact subset) in `dcs.score_completed` audit `metadata`.

Idempotency: if the task retries and `run_diff` already exists on this run, do not overwrite with a different baseline.

### 4.2 Shape (`metadata.run_diff`)

```json
{
  "schema_version": 1,
  "baseline": false,
  "compared_to_data_run_id": 123,
  "compared_to_finished_at": "2026-07-01T15:00:00Z",
  "headline_score": {
    "previous": 62,
    "current": 71,
    "delta": 9
  },
  "dimensions": {
    "identity": { "previous": 70, "current": 78, "delta": 8 },
    "catalog": { "previous": 55, "current": 60, "delta": 5 }
  },
  "business_impact": {
    "estimate": {
      "previous": 120000,
      "current": 95000,
      "delta": -25000,
      "currency": "EUR"
    }
  },
  "check_summary": {
    "passed": { "previous": 18, "current": 22, "delta": 4 },
    "failed": { "previous": 6, "current": 4, "delta": -2 },
    "blocked": { "previous": 1, "current": 0, "delta": -1 }
  }
}
```

First score ever:

```json
{
  "schema_version": 1,
  "baseline": true,
  "compared_to_data_run_id": null,
  "headline_score": null,
  "dimensions": null,
  "business_impact": null,
  "check_summary": null
}
```

Rules:

- Numeric deltas = `current − previous`.  
- Missing dimension on one side → omit that key or set previous/current null; do not invent 0.  
- Currency from `business_impact` when present.  
- Keep payload small (no full check lists).

### 4.3 Audit enrichment

Extend existing `dcs.score_completed` metadata (do not invent a separate action unless needed):

```json
{
  "data_run_id": 456,
  "run_id": "...",
  "run_state": "SUCCEEDED",
  "headline_score": "71",
  "run_diff": { "...same as metadata.run_diff..." }
}
```

**Activity copy (FE):**

| Condition | Summary line |
|-----------|--------------|
| baseline | `DCS score completed · 71 · SUCCEEDED` (unchanged) |
| delta > 0 | `DCS score completed · 71 (+9) · SUCCEEDED` |
| delta < 0 | `DCS score completed · 71 (−4) · SUCCEEDED` |
| estimate improved | optional secondary: `At-stake −€25,000 vs prior run` |

Tone stays RISK if BLOCKED; else INFO (existing). Optional: tone POSITIVE when score Δ > 0 — product choice; default keep INFO.

### 4.4 Storage note

No new table required for MVP. `DataRun.metadata` + `AuditLog.metadata` are enough.  
If payload size becomes a concern later, move to a narrow `dcs_run_diff` table — out of scope here.

---

## 5. Part B — Period compare on history GET (read path)

### 5.1 Endpoint

`GET /api/v1/dcs/history/`

Existing query params:

| Param | Behavior |
|-------|----------|
| `days` | Window ending now (capped, same as today) |
| `since` | ISO start (preferred when FE has exact window) |

**Add (recommended):**

| Param | Behavior |
|-------|----------|
| `until` | ISO end — required for “Last quarter” (window does not end at now) |

Today `resolve_dcs_score_history_for_user` forces `until = now()`. That breaks **Last quarter**. Fix: honor `until` when provided; default now.

### 5.2 Response additions

Keep:

```json
{
  "points": [ { "at", "score", "data_run_id", "run_state" } ],
  "value_capture": { "revenue": [], "margin": [] },
  "since": "...",
  "until": "..."
}
```

**Add:**

```json
{
  "period_compare": {
    "available": true,
    "run_count": 4,
    "first": {
      "data_run_id": 101,
      "at": "2026-07-01T15:00:00Z",
      "headline_score": 62,
      "dimensions": { "identity": 70, "catalog": 55 },
      "business_impact": {
        "estimate": 120000,
        "currency": "EUR"
      }
    },
    "last": {
      "data_run_id": 140,
      "at": "2026-07-18T15:00:00Z",
      "headline_score": 71,
      "dimensions": { "identity": 78, "catalog": 60 },
      "business_impact": {
        "estimate": 95000,
        "currency": "EUR"
      }
    },
    "deltas": {
      "headline_score": 9,
      "dimensions": {
        "identity": 8,
        "catalog": 5
      },
      "estimate": -25000,
      "captured_from_estimate": 25000
    }
  },
  "at_stake_series": [
    { "at": "...", "value": 120000, "data_run_id": 101, "currency": "EUR" }
  ]
}
```

Rules:

| Field | Rule |
|-------|------|
| `available` | `true` only when ≥2 qualifying runs in window |
| `first` / `last` | Chronological oldest / newest in window (by finished_at) |
| `deltas.headline_score` | `last − first` |
| `deltas.dimensions.*` | per-key `last − first` when both present |
| `deltas.estimate` | `last.estimate − first.estimate` (negative = risk down) |
| `deltas.captured_from_estimate` | `max(0, first.estimate − last.estimate)` — Overview Captured headline |
| `at_stake_series` | Per-run estimate in window for spark charts (replaces empty fake capture series for MVP) |

If only one run in window: `available: false`, `first`/`last` may still be set to that run, deltas null.

### 5.3 Implementation sketch

```text
build_dcs_histories(...)  # existing points
qualifying = scored runs in window (same queryset)
first, last = qualifying[0], qualifying[-1]
period_compare = compare(first, last)
at_stake_series = extract estimate per run
```

Reuse helpers that already extract headline / dimensions / business_impact from metadata (`worklist.extract_*`).

### 5.4 What period_compare is NOT

- Not consecutive previous-run (that is `run_diff`).  
- Not “vs same day last year”.  
- Not Architecture AF horizon.  
- Not Opportunities list ranking (later).

---

## 6. How each surface uses the data

### 6.1 Overview — period change flow

```text
User selects "This quarter"
        │
        ▼
resolveOverviewPeriodWindow("This quarter")
  → { since, until, granularity, spanDays }
        │
        ▼
GET /api/v1/dcs/history/?since=<iso>&until=<iso>
        │
        ▼
FE binds:
  • Trend chart          ← points + aggregateDcsTrendPoints(granularity)
  • Score Δ badge        ← period_compare.deltas.headline_score (if available)
  • Dimension +/-        ← period_compare.deltas.dimensions + showDelta
  • Captured headline    ← period_compare.deltas.captured_from_estimate
  • Captured spark       ← at_stake_series (aggregate like value capture)
  • At stake bar         ← latest status business_impact.estimate (unchanged)
```

Refetch on every period change (React Query key must include `since` + `until`).  
Do not client-side invent period_compare from points alone if dimensions/estimate are missing from points — server owns the compare object.

### 6.2 Overview — widget binding table

| Widget | Today | After DCS-10 |
|--------|-------|--------------|
| Score trend line | `points` | unchanged |
| Score Δ ↑/↓ | `computeTrendDelta(points)` | Prefer `period_compare.deltas.headline_score`; fallback to client compute if needed |
| Dimension chart deltas | `delta: 0`, `showDelta={false}` | Map `period_compare.deltas.dimensions`; `showDelta={period_compare.available}` |
| Captured by Klints amount | `value_capture` / `revenue_captured` | `captured_from_estimate` + currency from compare |
| Captured spark | empty `value_capture` | `at_stake_series` (label as at-stake / risk) |
| At stake vs captured bar | mixes capture % with estimate | Captured segment = captured_from_estimate; remainder = current estimate (document formula in FE) |
| Opportunities | mock `klints-data` | **Out of scope** — leave mock or empty; do not fake from run_diff |

**Captured bar formula (MVP):**

```text
captured = period_compare.deltas.captured_from_estimate   // ≥ 0
at_stake_now = status.business_impact.estimate
total_for_bar = captured + at_stake_now   // when both known
captured_pct = captured / total_for_bar
```

If `available === false`: hide Δ chips; Captured shows “Not available yet” / “Need ≥2 scores in period”.

### 6.3 Data Center (`/data-consistency`)

| Element | Source |
|---------|--------|
| Period control (if present) | Same `resolveOverviewPeriodWindow` + history GET |
| Score history chart | `points` |
| Period Δ callout | `period_compare.deltas.headline_score` |
| Per-run list / detail | Optional: show `metadata.run_diff` on expanded run (“vs prior score”) |

Do not show period_compare on a single-run detail page as “vs prior” — that is consecutive `run_diff`.

### 6.4 Activity / Notifications

| Element | Source |
|---------|--------|
| Timeline row for score complete | Existing audit row + enriched summary with consecutive Δ |
| Expand / metadata | `run_diff` in audit metadata |
| Bell copy (optional follow-up) | “Score +9 vs last run” — not period |

Period compare never appears in Activity (Activity is event-scoped, not window-scoped).

### 6.5 Opportunities (later — stub only)

Future: opportunities that closed between `first` and `last` in a window.  
This PRD: **no** Opportunities API changes. FE may keep mock or empty state.

### 6.6 Lifecycle / Architecture

No change. Architecture display horizon remains independent (AF-01).

---

## 7. Backend deliverables

1. Helper `build_consecutive_run_diff(current_data_run, previous_data_run | None) -> dict`  
2. Persist `metadata["run_diff"]` on success path; enrich audit  
3. Extend history resolver:
   - honor `until`
   - return `period_compare` + `at_stake_series`
4. Shared extraction of estimate/dimensions from run metadata (no duplication drift)  
5. Tests:
   - first run → baseline run_diff  
   - second run → correct deltas  
   - history window with 0 / 1 / N runs → period_compare.available  
   - Last quarter `until` in the past  
   - estimate drop → `captured_from_estimate`  
   - audit metadata includes run_diff  

---

## 8. Frontend deliverables

1. History query: pass `since` **and** `until` from `OverviewPeriodWindow`  
2. OverviewPanel:
   - bind score Δ, dimensions, Captured from `period_compare`  
   - spark from `at_stake_series`  
   - honest empty copy when `!available`  
   - tooltip: Captured = at-stake improvement in period  
3. Data Center: same period_compare for Δ if chart header needs it  
4. Activity: render consecutive Δ in summary when `run_diff` present  
5. Remove hard-coded `showDelta={false}` / `delta: 0` once data exists  

---

## 9. API contract (normative)

### 9.1 History GET

```http
GET /api/v1/dcs/history/?since=2026-04-01T00:00:00Z&until=2026-06-30T23:59:59Z
Authorization: Bearer …
```

```json
{
  "points": [],
  "value_capture": { "revenue": [], "margin": [] },
  "at_stake_series": [],
  "period_compare": {
    "available": false,
    "run_count": 0,
    "first": null,
    "last": null,
    "deltas": null
  },
  "since": "2026-04-01T00:00:00Z",
  "until": "2026-06-30T23:59:59Z"
}
```

`value_capture` remains for future true capture fields; MVP Overview uses `at_stake_series` + `captured_from_estimate`.

### 9.2 Auth / tenancy

Same as existing history: authenticated user → company scope. Empty payload if no company.

---

## 10. Acceptance checklist

### Backend

- [x] Every new SUCCEEDED scored run has `metadata.run_diff` (baseline or compared)  
- [x] Audit `dcs.score_completed` includes `run_diff`  
- [x] `GET /dcs/history/` accepts `until` and returns correct window for Last quarter  
- [x] `period_compare` uses oldest vs newest **in window**, not previous consecutive outside window  
- [x] `captured_from_estimate` is `max(0, first.estimate − last.estimate)`  
- [x] `at_stake_series` populated from `business_impact.estimate` when present  
- [x] Unit tests cover baseline, multi-run window, single-run window  

### Frontend

- [ ] Changing Overview period refetches with matching `since`/`until`  
- [ ] Score Δ and dimension +/- reflect `period_compare` for that period  
- [ ] Captured shows estimate improvement (or honest empty), never silent zeros pretending capture  
- [ ] Tooltip/copy does not claim banked revenue  
- [ ] Activity shows consecutive score Δ when available  
- [ ] No Opportunities fake wiring from this PRD  

---

## 11. Suggested split / owners

| Slice | Owner suggestion | PR focus |
|-------|------------------|----------|
| **BE-A** Persist `run_diff` + audit | Backend / DCS | orchestrate + tests |
| **BE-B** History `until` + `period_compare` + `at_stake_series` | Backend / DCS | history.py + views + tests |
| **FE-A** Overview period binding | Engineering / Overview | OverviewPanel + query keys |
| **FE-B** Activity Δ copy | Engineering / Audit | Activity timeline formatting |
| **FE-C** Data Center Δ (small) | Engineering / Data Center | only if chart header needs period Δ |

Ship **BE-A + BE-B** before FE-A so Overview is not double-mocked.

---

## 12. Related docs

- `docs/dcs_scoring/PRD_DCS_06_API_RESPONSES.md` — status/history contracts  
- `docs/dcs_scoring/PRD_DCS_08_REVENUE_IMPACT.md` — `business_impact.estimate`  
- `docs/frontend/PRD_FE_06_GUIDED_DCS_WORKLIST.md` — Overview live shell  
- `docs/audit/PRD_AUDIT_01_GOVERNANCE_ACTIVITY.md` — Activity / audit  
- `klints_frontend/src/lib/overview-period.ts` — period windows  

---

## 13. Open questions (non-blocking)

| # | Question | Default if unanswered |
|---|----------|------------------------|
| 1 | Show Captured as currency only, or also % of starting at-stake? | Currency primary; % optional secondary |
| 2 | Include INCOMPLETE runs with headline in compare? | Same filter as history `points` today |
| 3 | Positive audit tone on score up? | Keep INFO |
| 4 | Persist `at_stake_series` points on consecutive run_diff? | No — period only on GET |
