# PRD-FE-04 — Gated dashboard: DCS run progress (7 dimension stages)

**Status:** Ready for implementation  
**Module:** see folder path  
**Depends on:** FE-03 gated dashboard (`DcsGatedDashboard`); `GET /api/v1/dcs/status/`; CheckMaster / DimensionMaster  
**Repos:** Gated `/dashboard` when score is **Not calculated** / **Calculating…**  
**Design inspiration:** Data Consistency “seven dimension” tiles (`DcsSubScores` variant=`tiles`)

## 0. Plan (read this first)

### Clarification

The Data Consistency tab’s seven boxes are **DCS score dimensions**, not the Lifecycle cockpit (5 groups / 11 sub-stages). This PRD uses those **dimension tiles** so the gated dashboard answers: *how far did the last (or current) DCS run get?*

### Stage list (CheckMaster order)

Show **Foundation Gate first**, then the **7 scored dimensions** (8 tiles total). Foundation is required to explain early BLOCKED / auth failures; the seven scored tiles match Data Center.

| # | `dimension_id` | Label (short) |
|---|----------------|---------------|
| 0 | `00` | Foundation Gate |
| 1 | `01` | Customer Identity |
| 2 | `02` | Lifecycle Event |
| 3 | `03` | Product & Transaction |
| 4 | `04` | Segment & Property |
| 5 | `05` | Channel & Consent |
| 6 | `06` | Measurement |
| 7 | `07` | Business Reality |

If product later insists on **exactly 7** boxes, drop Foundation from the grid and keep it only in the status line — default ship is **8** (Foundation + 7).

### Visual states (ring around each box)

| State | Ring / treatment | When |
|-------|------------------|------|
| `pending` | No ring; muted box | Not reached yet |
| `running` | **Orange** ring around box | Dimension currently evaluating (live run) |
| `passed` | **Green** ring | Dimension finished; **no FAIL** among its checks (WARN / UNKNOWN / NOT_* allowed) |
| `failed` | **Red** ring | Dimension finished; **≥1 FAIL** (required or optional — still red; optional can note in subtitle) |
| `skipped` | No ring; faded / dashed | Run ended before this dimension (failed import, worker death, or blocked assemble with no results for later dims) |

### When it appears

Only on **gated** dashboard (`hard_locked` or `soft_locked_running`) — i.e. score not unlocked / not calculated.  
Do **not** replace the unlocked executive dashboard with this strip (unlocked keeps charts later via DCS-06).

### Data strategy

1. **Finished / failed / incomplete runs:** derive stage states from persisted `check_results` on the latest DCS DataRun (group by CheckMaster `dimension_id`).  
2. **Live Calculating…:** pipeline must write progressive `stage_progress` into DataRun metadata as each dimension batch completes; status API exposes it; FE already polls while soft-locked.  
3. Without progressive writes, live UI can only show a single orange “Scoring…” on Foundation or a generic spinner — **progressive metadata is in scope**.

### FE placement

Inside `DcsGatedDashboard`, below the score / status block and **above** the Issues list: section “Run progress” with the tile grid (same density as Data Center dimension tiles).

---

## 1. Problem

When DCS is not calculated, the gated dashboard shows Not calculated + issues, but not **which dimension the run reached**. Users cannot tell whether the last run died at Foundation, finished Identity, or never started scored checks.

## 2. Goal

1. Show dimension progress tiles on the gated dashboard.  
2. Orange / green / red rings for running / passed / failed.  
3. Reflect **current** run while Calculating… and **last** run when hard-locked after a finished/failed/incomplete score.  
4. Reuse Data Center tile visual language (boxes in a responsive grid).  
5. Extend `GET /api/v1/dcs/status/` with a `run_progress` payload (no separate page).

## 3. Backend

### 3.1 Progressive stage updates (live)

In `run_dcs_pipeline` (or check evaluation loop), after each dimension’s checks are evaluated (or after foundation batch, then each scored dimension):

```json
"stage_progress": {
  "updated_at": "ISO-8601Z",
  "current_dimension_id": "01",
  "stages": [
    {
      "dimension_id": "00",
      "key": "foundation",
      "label": "Foundation Gate",
      "state": "passed",
      "fail_count": 0,
      "warn_count": 1,
      "check_count": 7,
      "evaluated_count": 7
    },
    {
      "dimension_id": "01",
      "key": "identity",
      "label": "Customer Identity",
      "state": "running",
      "fail_count": 0,
      "warn_count": 0,
      "check_count": 4,
      "evaluated_count": 1
    }
  ]
}
```

Persist on `DataRun.metadata["stage_progress"]` (and optionally mirror final snapshot into `dcs_run`).

On terminal success/failure, set all reached stages to `passed`/`failed` and remaining to `skipped` (or leave pending→skipped).

### 3.2 Derive from check_results (finished runs)

Helper: load CheckMaster → map `check_id` → `dimension_id` → aggregate statuses.

Per dimension:

- If no results for that dimension and run still running → `pending` / `running` per `current_dimension_id`  
- If no results and run terminal → `skipped`  
- If any `FAIL` → `failed`  
- Else if all checks for that dimension present → `passed`  
- Partial mid-run → `running` if `current_dimension_id` matches else `pending`

`NOT_CONNECTED` / `NOT_APPLICABLE` / `UNKNOWN` do **not** alone make a dimension `failed`.

### 3.3 Status API addition

Extend `GET /api/v1/dcs/status/` response:

```json
{
  "run_progress": {
    "data_run_id": 58,
    "data_run_status": "running",
    "current_dimension_id": "02",
    "stages": [ /* 8 items, Foundation + 7 */ ]
  }
}
```

When `no_run`: `run_progress: null` or stages all `pending`.  
When unlocked: may omit or still return last run (FE ignores on unlocked dashboard).

### 3.4 Fresh-import phase (optional v1)

Before Foundation checks, run is importing. Options:

- A) Show Foundation as `running` during import (simple)  
- B) Add synthetic stage `import` (out of 7-box design)  

**Ship A** unless import regularly takes >2 minutes — then add a single status line “Refreshing connector data…” above the tiles.

## 4. Frontend

### 4.1 Component

New: `components/klints/DcsRunProgress.tsx` (or under `DcsGatedDashboard`).

- Grid: `sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8` (or 7 if Foundation omitted) — same card chrome as `DcsSubScores` tiles.  
- Each tile: short label, small state caption (`Running` / `Passed` / `Failed` / `Waiting`), optional `fail_count`.  
- Ring: `ring-2` (or border)  
  - running → orange / `risk` or dedicated spark/amber token  
  - passed → green / `revenue`  
  - failed → red / `loss`  
  - pending/skipped → default border, reduced opacity for skipped  

Accessibility: `aria-current` on running; text state not color-only.

### 4.2 Wire into gated dashboard

`DcsGatedDashboard.tsx`:

1. Score block (existing)  
2. Status line (existing)  
3. **NEW** `DcsRunProgress` from `status.run_progress`  
4. Issues list (existing)

Soft-locked: poll status (already) so orange ring advances.  
Hard-locked after last run: static rings showing how far that run got.

### 4.3 Copy

- Section title: **Run progress**  
- Description: **How far the latest Data Consistency run got across dimensions**  
- Empty / no_run: all pending + “No score run yet — connect stack to start.”

## 5. Acceptance

1. Soft-locked run: one stage shows **orange** ring; earlier stages green or red as appropriate; later pending.  
2. Hard-locked after BLOCKED at Foundation: Foundation **red** (or passed with later skipped if only gates blocked assemble — match actual check_results); later dimensions **skipped**.  
3. Hard-locked after Identity FAILs but run completed assemble: Identity **red**; other evaluated dims green/red; none stuck orange.  
4. Visual language recognizable vs Data Center dimension tiles.  
5. Unlocked dashboard does not show this strip (FE-03 gated-only).  
6. Status payload includes `run_progress.stages` with stable `dimension_id` keys.  
7. Progressive updates appear within one poll interval while Calculating…

## 6. Files to change

| Area | File |
|------|------|
| Pipeline progress writes | `dataruns/dcs/orchestrate.py` (+ small helper) |
| Status builder | `dataruns/dcs/status.py` |
| Tests | stage aggregation + status shape + soft-lock progression |
| FE component | `DcsRunProgress.tsx` |
| Gated dashboard | `DcsGatedDashboard.tsx` |
| Types | `lib/dcs.ts` |

## 7. Out of scope

- Lifecycle cockpit (5×11) UI  
- Replacing Data Center dimension scores with this strip when unlocked  
- Per-check expansion inside each tile (Data Center expandable detail can wait)  
- Changing assemble / scoring math  

## 8. Related

| Doc / artifact | Relation |
|----------------|----------|
| FE-03 | Gated dashboard host surface |
| Data Consistency `DcsSubScores` tiles | Visual inspiration |
| CHECK_MASTER_42 / DimensionMaster | Stage catalogue |
| DCS-01 orchestrate | Where to write `stage_progress` |
| DCS-06 | Unlocked dashboard later — not this strip |
