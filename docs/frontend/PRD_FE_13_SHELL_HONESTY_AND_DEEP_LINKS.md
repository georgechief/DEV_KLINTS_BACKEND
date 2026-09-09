# PRD-FE-13 — Shell honesty, deep-links & Data Center assessment export

**Status:** Ready for implementation  
**Owner track:** Engineering  — **FE primary** (reuse existing assessment PDF BE; no new writeback APIs)  
**Surfaces:** AppShell · bell / NotificationsPanel · Settings · Data Consistency · Overview · Activity · Spotlight · Fix deep-links · nav Phase 4–5  
**Depends on:**  
- **RPT-01** — `downloadAssessmentBrief` / compose + PDF (already wired on Overview **Export brief**)  
- **AUDIT-01 / AUDIT-02** — activity + notifications  
- **FE-08** — live Fix `?issue=<check_id>`  
- **WF-02 / QA-01** (Engineering) — Phase 4–5 real engines; this PRD only adds **honest shell** until those land  
**Design SoT:** Keep existing chrome; stop lying CTAs and dead clicks  
**Out of scope:** QA hard-test engine · Handoff MCP Send · new writeback mappings · CONN-07 · inventing a second PDF format  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-FE-13 — production shell honesty + deep-links + DCS assessment download.

Read:
- docs/engineering/PRD_FE_13_SHELL_HONESTY_AND_DEEP_LINKS.md
- src/lib/assessment-report.ts (downloadAssessmentBrief — Overview Export brief)
- src/routes/data-consistency.tsx (Export fix plan toast stub)
- AppShell.tsx handleNotificationItemClick, settings.tsx Coming soon fields
- docs/engineering/PRD_RPT_01_FULL_ASSESSMENT_REPORT_PDF.md (reuse only)

Ship:
1. Data Consistency “Export fix plan” → same PDF download as Overview Export brief (§4).
2. Bell / Activity / Overview activity → smart deep-links from audit metadata (§5).
3. Settings deferred fields honest (not fake filled inputs) (§6).
4. Nav Phase 4–5 honesty until QA/Handoff live (§7).
5. Live Overview/Plan → /fix?issue=<check_id>; block iss-* fixture bleed in prod (§8).
6. Spotlight / Plan-queue dead ends (§9).
7. Activity load-more with next_cursor (§10).

Acceptance: §13.
```

---

## 1. Why (plain language)

Operators already trust **Re-run checks**, **Fix**, and **Export brief** on Overview. Production still has “product theater”:

| What they see | What happens today | How it feels |
|---------------|--------------------|--------------|
| **Export fix plan** on Data Consistency | Toast: “not available in v1” | Broken primary button next to live Re-run |
| Bell notification click | Always `/activity` dump | Can’t open the thing that happened |
| Settings Timezone / Industry / Currency | Input filled with the words “Coming soon” | Looks like bad data |
| QA / Handoff in sidebar | Fully clickable | Lands on fixtures / fake Send |
| Overview “open fix” / Plan queue | Often fixture-aware or “No deep-link” | Dead ends mid-demo |
| `?issue=iss-*` | Still serves Lumera demo Fix | Fixture bleed in prod |

This PRD is **trust polish**: same report download everywhere it belongs, clicks go somewhere useful, deferred = clearly deferred.

---

## 2. References

| Source | Use |
|--------|-----|
| `src/lib/assessment-report.ts` → `downloadAssessmentBrief` | **Canonical** PDF export path (compose + stream + filename) |
| Overview `Export brief` in `OverviewPanel.tsx` | UX + busy/disabled + toast errors to **mirror** |
| RPT-01 / RPT-01B | Backend already audits `report.downloaded` |
| AUDIT-02 | Bell list; extend click routing only |
| FE-08 | Live Fix URL contract |

---

## 3. Vocabulary

| Term | Meaning |
|------|---------|
| **Assessment brief PDF** | Same RPT-01 PDF Overview already downloads |
| **Deep-link** | Navigate to the most specific live surface for an audit/check (Fix, DCS, Activity hash, Studio) |
| **Deferred** | Not built — shown as Coming soon / Soon / disabled, **never** as a fake success |
| **Fixture bleed** | Demo `iss-*` / `wf-*` paths usable on a live tenant |

---

## 4. Data Consistency — Export fix plan = Overview report

### 4.1 Product decision (locked)

**Do not invent a new “fix plan PDF.”**  
Data Consistency button **Export fix plan** must download the **same assessment report PDF** as Overview **Export brief**, using the same helper:

```ts
downloadAssessmentBrief({ since, until })
```

### 4.2 Why the label can stay

| Surface | Label | Same file? |
|---------|-------|------------|
| Overview | **Export brief** | Yes |
| Data Consistency | **Export fix plan** | Yes — operators are on the diagnose page; “fix plan” = full assessment incl. what to fix |

Optional later rename to “Export assessment” on both — **not required** for v1.

### 4.3 Behaviour (mirror Overview)

| Rule | Spec |
|------|------|
| Disabled when | No DCS score ready (`!scoreReady`) **or** export in flight |
| On click | Spinner on button · call `downloadAssessmentBrief` |
| Period window | Prefer the **same period** DCS page already uses for history/compare if present; else last **30 days through now** (document choice in PR). Must be ISO `since` / `until` like Overview. |
| Success | Browser downloads PDF · invalidate audit notification queries (same as Overview) |
| Error | `toast.error` + `assessmentReportErrorMessage(error)` — **no** “Export queued” lie |
| Permissions | Same as Overview (403 copy already in helper) |

### 4.4 Remove

```ts
toast.message("Export queued", {
  description: "Fix plan PDF export is not available in v1.",
});
```

### 4.5 Visual

Keep the primary button next to **Re-run checks**. While busy: `Loader2` + disabled (match Overview Export brief pattern).

```text
[ Re-run checks ]   [ Export fix plan ]  ← primary; downloads assessment PDF
```

---

## 5. Notifications & Activity deep-links

### 5.1 Problem

`handleNotificationItemClick` always `navigate({ to: "/activity" })`. Mark-read is good; destination is weak.

### 5.2 Resolve target (FE helper)

Add something like `resolveAuditDeepLink(event: AuditEvent): { to; search?; hash? }`.

**Priority order (first match wins):**

| Signal in event (`metadata` / known fields / `href`) | Go to |
|------------------------------------------------------|--------|
| `check_id` or worklist issue id | `/fix?issue=<CHECK>` if Fix-allowed; else `/data-consistency?issue=<CHECK>` |
| `package_id` + `use_case_id` | `/workflow?uc=&package_id=` (or `/qa` if action is QA-related) |
| `report_id` / `report.downloaded` | `/activity` (or stay; optional highlight) |
| `run_id` / DCS run | `/data-consistency` (+ hash `#dcs-score` if exists) |
| Connector / integration action | `/integrations` |
| Writeback execute / rollback | `/fix?issue=<check_id>` when present |
| Nothing useful | `/activity` (fallback — today’s behaviour) |

Use API `href` **when present and same-origin path**; otherwise compute from metadata. Do not open external URLs blindly.

### 5.3 Bell UX

| Behaviour | Spec |
|-----------|------|
| Click row | Mark read (best-effort) → navigate to resolved deep-link → close panel |
| Unread | Slightly stronger weight / dot (if not already) |
| Mark-read fail | Still navigate (keep current resilience) |
| Mark all | Unchanged |

### 5.4 Activity page

| Item | Spec |
|------|------|
| Row click | Same `resolveAuditDeepLink` |
| Load more | Wire `next_cursor` from audit list API — button or infinite scroll |
| Empty / error | Keep honest empty states |

### 5.5 Overview recent activity

Each recent activity row → same deep-link (not a flat `/activity` noop).

---

## 6. Settings honesty

### 6.1 Deferred workspace fields

Timezone / Industry / Reporting currency (and any sibling using `defaultValue="Coming soon"`):

| Do | Don’t |
|----|--------|
| Show a **read-only** row: label + badge **Coming soon** + short helper | Put the literal string “Coming soon” inside an editable-looking input |
| Keep Save only for real fields (name, domain, writebacks toggle) | Imply those fields will persist |

### 6.2 API keys / Billing tabs

Already copy-honest (FE-07). Optional polish:

- Tab label suffix **Soon**, or  
- Selecting tab shows a single empty-state card (no fake forms)

**v1 lock:** at least §6.1; §6.2 nice-to-have in same PR if cheap.

---

## 7. Nav honesty — Phase 4 QA / Phase 5 Handoff

Until Engineering **QA-01** / **HO-01** are live in prod:

### 7.1 Options (pick one — prefer A)

| Option | Behaviour |
|--------|-----------|
| **A — Soft lock (preferred)** | Nav items stay visible; click goes to page; page empty-state says **“QA validation is next — generate a package in Studio first”** / **“Handoff Send is not live yet — package stays staged”**. Hide or disable **Send** / fake Re-run toasts that claim success. |
| **B — Soon badge** | Sidebar shows **Soon** chip; click still allowed but empty-state as above |

### 7.2 Must stop

| Bad | Fix |
|-----|-----|
| Handoff **Send** / **Send all** toast “Sent” | Disable + “Not live yet — activation stays human in Manago” **or** remove buttons until HO-01 |
| QA **Re-run** toast that pretends gates ran | Disable until QA-01; or only show when live package QA exists |
| Spotlight listing QA/Handoff as if fully productized | Add hint “Phase 4 · soon” / “Phase 5 · soon” in search hint text |

When QA-01 ships, remove soft-lock copy in a tiny follow-up — don’t block this PRD on Engineering.

---

## 8. Live Fix routing & fixture bleed

### 8.1 Overview NBA / Opportunities Plan → Fix

| Today | Target |
|-------|--------|
| Live checks often open Data Center only; `iss-*` opens Fix | **Any live `check_id`** → `/fix?issue=<CHECK>` (FE-08) |
| Plan row “No deep-link” | If `check_id` present → Fix; else DCS worklist hash; never a dead muted string if we have an id |

### 8.2 Fixture bleed (prod)

| Rule | Spec |
|------|------|
| `?issue=iss-*` on live tenant | Redirect to `/data-consistency` **or** show banner “Demo fixture — pick a live issue” + block Approve theater |
| Prefer | **Hard redirect** away from fixture plans in production builds (`import.meta.env.PROD`) |
| Local/demo | Fixtures may remain behind `?fixture=1` or non-prod only |

### 8.3 Legacy `/workflow/$id` with `wf-*`

Already redirected/commented in WF-01 — ensure nav never invents new `wf-*` links from Overview/Plan.

---

## 9. Spotlight & Plan queue

| Surface | Spec |
|---------|------|
| Spotlight audit/check hits | Prefer API `href`; else map type → Fix / DCS / Activity / Integrations |
| Spotlight page entries for QA/Handoff | Honest hints (§7.2) |
| Opportunities Plan “No deep-link” | Replace with Fix/DCS link when `checkId` exists; if truly none, hide CTA |

---

## 10. Activity pagination

| Spec |
|------|
| Use existing list API `next_cursor` (or equivalent) |
| **Load more** control at bottom while cursor present |
| Preserve mark-read / deep-link behaviour on newly loaded rows |

---

## 11. Flows (operator-visible)

### Flow E1 — Export from Data Consistency

```text
1. Score ready on /data-consistency
2. Click Export fix plan
3. Button spins → PDF downloads (same family as Overview Export brief)
4. Bell may show report.downloaded
5. Never “Export queued / not available”
```

### Flow E2 — Bell to Fix

```text
1. Writeback or DCS audit arrives with check_id=CC-03
2. Open bell → click row
3. Lands /fix?issue=CC-03 (or DCS if Fix locked)
4. Marked read
```

### Flow E3 — Settings deferred

```text
1. Settings → Workspace
2. Timezone shows Coming soon badge — not a fake value in an input
3. Allow writebacks toggle still real (WB-03)
```

### Flow E4 — No fixture surprise

```text
1. Someone pastes ?issue=iss-campaign on prod
2. Redirect / honest empty — no Lumera Approve demo
```

```mermaid
flowchart TD
  subgraph export [Export]
    DCS[Data Consistency]
    OV[Overview Export brief]
    API[RPT-01 compose + PDF]
    DCS -->|Export fix plan| API
    OV --> API
  end

  subgraph links [Deep-links]
    Bell[Bell click]
    Act[Activity row]
    Bell --> R[resolveAuditDeepLink]
    Act --> R
    R --> Fix[/fix?issue=]
    R --> DC[/data-consistency]
    R --> Int[/integrations]
    R --> Fallback[/activity]
  end
```

---

## 12. FE touch list

| File / area | Change |
|-------------|--------|
| `data-consistency.tsx` | Wire Export fix plan → `downloadAssessmentBrief`; busy/disabled |
| `assessment-report.ts` | Reuse; optional shared `useExportAssessmentBrief` hook if duplication hurts |
| `AppShell.tsx` | `resolveAuditDeepLink` on notification click; nav/Spotlight hints |
| `NotificationsPanel.tsx` | Unread affordance if missing |
| `activity.tsx` | Row links + load more |
| `OverviewPanel.tsx` | Activity row deep-links; NBA → live Fix |
| `opportunities.tsx` | Plan deep-links |
| `settings.tsx` | Deferred field UI |
| `handoff.tsx` / `qa.tsx` | Soft-lock Send / fake re-run until Engineering engines (minimal) |
| `fix-flow.ts` / `fix.tsx` | Prod fixture bleed gate |
| `SpotlightSearch.tsx` | Hints + href respect |
| verify script | `verify:fe13` — Export uses `downloadAssessmentBrief`; no “not available in v1” toast; notification click ≠ only `/activity` hardcoded |

**Backend:** none required if RPT-01 + audit list already expose metadata. If `check_id` missing on important audit events, add a **small BE follow-up** — call out in PR Gaps; FE still ships fallbacks.

---

## 13. Acceptance

- [ ] Data Consistency **Export fix plan** downloads assessment PDF (same path as Overview Export brief)  
- [ ] Disabled when score not ready; spinner while exporting; real error toasts  
- [ ] No “Export queued / not available in v1”  
- [ ] Bell click deep-links when `check_id` / useful metadata exists; else Activity  
- [ ] Activity rows clickable + **Load more** when cursor present  
- [ ] Overview recent activity uses same deep-link helper  
- [ ] Settings deferred fields do not look like filled real values  
- [ ] Handoff Send does not toast fake “Sent” (disabled or honest)  
- [ ] Live Plan/NBA opens `/fix?issue=<check_id>` when check known  
- [ ] Prod build does not serve `iss-*` fixture Fix as live Approve theater  
- [ ] Written Working / Gaps in PR  

---

## 14. PR title / branch

- Branch: `feature/fe-13-shell-honesty-deep-links`  
- Title: `feat(FE-13): DCS assessment export, audit deep-links, shell honesty`

---

## 15. Traceability

| Item | |
|------|--|
| Parents | RPT-01 Export brief · AUDIT-02 bell · FE-07 Settings · FE-08 Fix |
| Sibling | Engineering QA-01 / HO-01 (real Phase 4–5) — this PRD only honesty until then |
| Explicit non-goal | Second PDF type · MCP Send · new writebacks |

---

## 16. Implementation order (suggested for Engineering)

1. **Export fix plan** (§4) — highest visible win, ~S  
2. Settings deferred UI (§6) — ~S  
3. Handoff/QA fake Send honesty (§7) — ~S  
4. Deep-link helper + bell/Activity/Overview (§5, §10) — ~M  
5. Plan/NBA + fixture bleed (§8–9) — ~M  
6. verify script + PR note  

Ship as **one PR** if possible; split only if review size hurts (Export+Settings first, deep-links second).
