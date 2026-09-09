# PRD-WF-02 — Fix-flow stages, check→UC routing, honest CTAs & redirects

**Status:** Ready for implementation  
**Owner track:** Engineering  — FE primary · BE only if journey cursor API needed  
**Surfaces:** FlowStepper · `/data-consistency` · `/fix` · `/workflow` · `/qa` · `/handoff` · Opportunities  
**Depends on:**  
- **WF-01 / BL-016** Studio live bind (`?uc=`) + build package  
- **UC-01** recommendations + `gating_check_ids`  
- **FE-08** Fix live issue bridge  
- Pack pilots + blueprints (authoritative gates)  
**Design SoT:** `original-designs` FlowStepper + Diagnose→Handoff chrome  
**Out of scope:** Full BL-017 8-state orchestration machine · BL-018 QA engine · Handoff Send live · Engineering writeback execute rules (WB-02/03) · inventing pilots outside the 16  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WF-02 — customer journey stages + honest Fix→Studio routing.

Read:
- docs/engineering/PRD_WF_02_FIX_FLOW_STAGES_AND_CHECK_ROUTING.md
- docs/engineering/PRD_WF_01_WORKFLOW_BLUEPRINT_STUDIO.md (§3 gates, §5 CTAs, §7.5)
- Pack: 04_MVP1_Pilot_Blueprints/*_blueprint.json gates.gating_check_ids
- FE: FlowStepper.tsx, fix.tsx, data-consistency.tsx, use-cases.ts

Ship:
1. Derive (and optionally persist) journey stage per working issue — stepper reflects it.
2. Stage clicks redirect to the correct page WITH issue/uc context (§4).
3. Fix “Proceed to Workflow Studio” ONLY if check gates ≥1 pack pilot (§5–6).
4. Rename misleading “Approve fix → Proceed…” — Approve writeback ≠ Studio.
5. DCS: FAIL/WARN → Fix only; never Build on integrity FAIL (§7).
6. After Fix, Build step enabled only when routing rules say so (§5).

Acceptance: §12.
```

---

## 1. Why

Today:

- FlowStepper is **cosmetic** (`current` hard-coded per route); stages don’t mean “you’re allowed here.”  
- Fix primary CTA says **“Approve fix → Proceed to Workflow Studio”** but is only a `<Link>` — does not approve.  
- **Proceed** shows for checks that **gate no pilot** (e.g. **CI-01**, **WB-SHOP-01**) — dead / confusing Studio jump.  
- Data Consistency does not show logical next stage (Fix vs Build) from journey state.  

Pack + WF-01 already define the truth: **checks gate pilots; Fix repairs data; Build is Studio when gates allow.** This PRD wires **stages, buttons, and redirects** to that truth.

---

## 2. References (authoritative)

| Source | Use |
|--------|-----|
| Pack `04_MVP1_Pilot_Blueprints/UC-*_blueprint.json` → `gates.gating_check_ids` | Which check opens which UC |
| Pack `pilot_manifest.json` + supplemental list | Provisional vs hard gate (WF-01 §3.2) |
| Pack Implementation Blueprint stages (Diagnose→…→Build & QA→Handoff) | Phase vocabulary |
| `docs/engineering/PRD_WF_01_WORKFLOW_BLUEPRINT_STUDIO.md` | Studio, Fix vs Build CTAs, Flow D |
| `docs/engineering/PRD_UC_01_USE_CASE_LIBRARY_AND_PILOTS.md` | `ready` / `ready_provisional` / blocked |
| `docs/engineering/PRD_WB_02_*` / FE-08 | Fix writeback is **data** path — orthogonal to Studio eligibility |
| FE `fixFlowStages` / `FlowStepper.tsx` | UI chrome to harden |

---

## 3. Vocabulary

| Term | Meaning |
|------|---------|
| **Working issue** | `check_id` in URL (`?issue=CC-03`) — the DCS check being worked |
| **Journey stage** | One of: `diagnose` · `fix` · `build` · `qa` · `handoff` |
| **Gates a pilot** | `check_id ∈ pilot.gates.gating_check_ids` (pack) |
| **Studio-eligible check** | Gates ≥1 of the 16 MVP1 pilots |
| **Buildable pilot** | Recommendation `status ∈ {ready, ready_provisional}` |
| **Writeback-eligible check** | Engineering allowlist (CI-01, CC-03, WB-SHOP-01, …) — **independent** of Studio |

**Critical:** Writeback eligibility ≠ Studio eligibility.

| Check | Writeback (Engineering) | Gates a UC? | Show “Proceed to Workflow Studio”? |
|-------|--------------------|-------------|--------------------------------------|
| **CC-03** | Yes (sandbox/execute) | Yes → UC-02, UC-04, UC-05 | **Yes** |
| **CI-01** | Yes | **No** | **No** |
| **WB-SHOP-01** | Yes | **No** | **No** |
| **LE-04** | No (disabled) | Yes → UC-23 | **Yes** (Studio when allowed; not writeback) |
| **LE-05** | No (evidence/download) | Yes → UC-06B | **Yes** |
| Random FAIL not in any gate list | Maybe download only | **No** | **No** |

---

## 4. Journey stages — pages & redirects

### 4.1 Stage → route (locked)

| Stage | Page | Required search (when working issue set) |
|-------|------|------------------------------------------|
| **diagnose** | `/data-consistency` | `?issue=<check_id>` (scroll/highlight row) |
| **fix** | `/fix` | `?issue=<check_id>` |
| **build** | `/workflow` | `?uc=<UC>&issue=<check_id>` when Studio-eligible; else stage **disabled** |
| **qa** | `/qa` | `?uc=<UC>&issue=<check_id>&package_id=<id>` when package exists; else disabled or soft “generate first” |
| **handoff** | `/handoff` | Same context when QA cleared; else disabled (BL-018 later may unlock) |

### 4.2 FlowStepper behaviour (locked)

For the **working issue**:

1. **Current stage** = derived (§5), not “whatever page prop says” alone. Page may pass a hint; derivation wins for enabled/disabled.  
2. Clicking a stage:
   - **Enabled** → `navigate` to that stage’s route + search (§4.1).  
   - **Disabled** → no navigation; tooltip explains why (§4.3).  
3. Stages with `phase < current` show **done** styling only if derivation says that phase was completed (§5).  
4. Build/QA/Handoff links must **never** use legacy `/workflow/wf-*` fixture ids.

### 4.3 Disable tooltips (examples)

| Stage | Disabled when | Tooltip |
|-------|---------------|---------|
| fix | No `issue` selected | “Pick an issue in Data Consistency first” |
| build | Check does not gate any UC | “This check doesn’t gate a workflow blueprint — Fix / evidence only” |
| build | Gates UC but all blocked & no preview path | Optional: still allow open Studio preview with gates card (WF-01) — **v1 lock: allow Build click if Studio-eligible even when blocked**, so user sees gates; Generate stays locked |
| qa | No `package_id` for this UC | “Generate a build package in Workflow Studio first” |
| handoff | QA not cleared / no package | “Clear QA before handoff” (honest stub OK until BL-018) |

**v1 Build click rule (locked):** If Studio-eligible → Build step **enabled** (opens Studio brief, even if Generate locked). If **not** Studio-eligible → Build step **disabled** + Fix must **hide** Proceed CTA.

---

## 5. Deriving the current stage (no heavy DB required for v1)

### 5.1 Inputs

- URL: path + `issue` + `uc` + `package_id`  
- Live: worklist result for `issue`, recommendations for pilots gated by `issue`  
- Optional client: `package_id` last generated for `uc` (session/localStorage OK in v1)

### 5.2 Derivation (priority order)

```text
if no issue selected:
  current = diagnose

else if path is /fix OR (issue FAIL/WARN AND no explicit later stage in URL):
  # User is repairing data
  current = fix

else if path is /workflow OR (Studio-eligible AND user opened build):
  current = build

else if path is /qa OR package_id present and path qa:
  current = qa

else if path is /handoff:
  current = handoff

else if issue FAIL/WARN:
  current = fix   # default resume

else if Studio-eligible AND primary gated pilot is buildable:
  current = build  # data clear → next logical is Build

else:
  current = diagnose
```

**Resume default when landing on DCS with `?issue=`:**  
- FAIL/WARN → highlight Fix CTA (stage fix).  
- PASS + Studio-eligible + buildable pilot → show secondary “Build {UC}” (§7).  
- PASS + not Studio-eligible → no Build; copy “Check passed — no workflow gated.”

### 5.3 Optional persistence (v1.1 — nice)

`localStorage` key `klints.journey.{companyId}.{checkId}` = `{ stage, uc, package_id, updated_at }`.  
Update on: open Fix, open Studio, generate package, open QA.  
**Not required** for acceptance if derivation + honest buttons pass.

BE journey table = **out of scope** unless product later needs cross-device resume.

---

## 6. Fix screen — buttons & conditions

### 6.1 Split CTAs (locked)

| Control | When visible | Action |
|---------|--------------|--------|
| **Approve writeback** | Writeback-eligible + sheet/mapping allow (Engineering rules) | Execute writeback only — **never** navigates to Studio |
| **Download evidence** | Live issue with exportable evidence (FE-12) | CSV download |
| **Proceed to Workflow Studio** | **Studio-eligible only** (`pilotsGatedByCheck(issue).length ≥ 1`) | Navigate `/workflow?uc=<primary>&issue=<check_id>` |
| Primary footer CTA label | Studio-eligible | **“Proceed to Workflow Studio”** only — **remove** “Approve fix →” wording |
| Primary footer CTA | **Not** Studio-eligible | **Hide** Proceed; optional: “Back to Data Consistency” or “Download evidence” only |

### 6.2 Primary UC pick (same as WF-01)

Reuse `pickPrimaryPilotForCheck` / `workflowStudioFromFix`:

1. All pilots where `check_id` ∈ `gating_check_ids`  
2. Prefer buildable (`ready` / `ready_provisional`)  
3. Else lowest `pilot_rank` among gated (opens Studio with gates card)  
4. If none → **not Studio-eligible** → no Proceed button  

### 6.3 After successful writeback

- Stay on Fix (Written + Rollback).  
- Do **not** auto-jump to Studio (operator may still need evidence).  
- If Studio-eligible: keep Proceed enabled; helper: “Data write done — continue to Workflow Studio when ready.”  
- Re-score may be needed before Generate unlocks — show that honesty on Studio.

---

## 7. Data Consistency — CTAs by row

### 7.1 Per worklist row (locked)

| Condition | Primary CTA | Secondary |
|-----------|-------------|-----------|
| FAIL / WARN | **Fix this issue** → `/fix?issue=<id>` | If Studio-eligible: text link “Blocks {UC-xx}” (educational, not Build) |
| PASS + Studio-eligible + primary pilot buildable | Optional **Build {UC}** → `/workflow?uc=` | Fix not needed |
| PASS + not Studio-eligible | None / “Passed” | — |
| Opportunity fixture-style (if any remain) | Build | Per WF-01 §5.1 |

**Never:** Build button on FAIL implying workflow can ship.

### 7.2 Score strip

Keep “build-ready” / pts-to-70 copy aligned with pack `min_dcs=70` (WF-01 §5.3).

---

## 8. Pack gate matrix (routing SoT)

Implement routing from **live recommendations API** (which already loads blueprint gates). Pack snapshot for tests/docs:

| Pilot | min_dcs | gating_check_ids |
|-------|---------|------------------|
| UC-02 | 70 | CC-03, CC-06, CI-08 |
| UC-04 | 70 | PT-13, CC-03 |
| UC-05 | 70 | CC-06, CC-03 |
| UC-06B | 70 | LE-01, LE-05, PT-04, CC-01, CC-02, SP-10 |
| UC-08 | 70 | PT-01, BR-09 |
| UC-09 | 70 | LE-01, LE-10, PT-01 |
| UC-10 | 70 | CI-02, LE-01 |
| UC-11 | 70 | SP-04, PT-01, BR-09 |
| UC-12 | 70 | PT-01, PT-06, BR-02 |
| UC-13 | 70 | PT-05, PT-01 |
| UC-16 | 70 | LE-01, PT-04, SP-08 |
| UC-17 | 70 | LE-01, PT-04, CC-01 |
| UC-21 | 70 | LE-07, CC-01, PT-06 |
| UC-23 | 70 | PT-04, LE-04, SP-07 |
| UC-28 | 70 | PT-01, PT-11, BR-03 |
| UC-36 | 70 | LE-01, PT-01, BR-01 |

**Checks that appear as gates** (Studio-eligible if present on worklist):  
`BR-01, BR-02, BR-03, BR-09, CC-01, CC-02, CC-03, CC-06, CI-02, CI-08, LE-01, LE-04, LE-05, LE-07, LE-10, PT-01, PT-04, PT-05, PT-06, PT-11, PT-13, SP-04, SP-07, SP-08, SP-10`

**Explicit non-Studio examples (hide Proceed):**  
`CI-01`, `WB-SHOP-01`, and any FAIL not in the gate set (still Fix + evidence).

Supplemental policy for readiness: **WF-01 §3.2** (unchanged).

---

## 9. End-to-end flows (customer journey)

### Flow J1 — Integrity FAIL that gates a UC (e.g. CC-03 → UC-02)

```text
1. DCS: CC-03 FAIL → Fix this issue
2. FlowStepper: current=fix; Build enabled (Studio-eligible)
3. Fix: Approve writeback (if eligible) and/or evidence
4. Proceed to Workflow Studio → /workflow?uc=UC-02&issue=CC-03
5. Studio: brief + gates; Generate when ready/provisional
6. Stepper Build=current; QA enabled after package_id
```

### Flow J2 — Writeback check that gates nothing (CI-01)

```text
1. DCS: CI-01 FAIL → Fix this issue
2. Fix: Approve writeback / download — NO “Proceed to Workflow Studio”
3. FlowStepper: Build step DISABLED for this issue
4. After written: Back to DCS / Activity — not Studio
```

### Flow J3 — Gate FAIL without writeback (e.g. LE-05 → UC-06B)

```text
1. Fix LE-05 (evidence download / manual)
2. Proceed → /workflow?uc=UC-06B&issue=LE-05
3. Generate when pilot buildable after re-score
```

### Flow J4 — Already buildable

```text
1. DCS or Opportunities: Build UC-02
2. Stepper may show build current with issue optional
3. No fake Fix requirement
```

---

## 10. FE / BE touch list

### Frontend (required)

| Area | Change |
|------|--------|
| `use-cases.ts` | `isStudioEligibleCheck(pilots, checkId)`; export for Fix/DCS/Stepper |
| `fix.tsx` | Hide Proceed if not eligible; rename CTA; keep Approve writeback separate |
| `fix-live-plan.ts` | Stop `ctaLabel: "Approve fix → Proceed…"` — use Proceed-only or contextual |
| `FlowStepper.tsx` | Derive enabled stages; Build search uses `workflowStudioFromFix`; disable + tooltip |
| `data-consistency.tsx` | CTA rules §7; optional “Blocks UC-xx” |
| `AppShell` / pages | Pass working issue into stepper; use derivation for `current` |
| verify script | `verify:wf02` static checks: CI-01 has no Proceed string path; CC-03 does |

### Backend (optional v1)

None required if recommendations already expose gates.  
Optional: `GET …/journey/?check_id=` returning `{ studio_eligible, primary_uc, stage_hint }` — only if FE duplication hurts.

---

## 11. Explicit non-goals

- Auto-redirect after Approve writeback to Studio  
- Showing Build on DCS FAIL rows  
- Persisting 8-state ORCH task machine (BL-017)  
- Inventing UC links for CI-01 / WB-SHOP-01  
- Changing Engineering writeback allowlist  

---

## 12. Acceptance

- [ ] CC-03 (and any gate check): Proceed visible → lands `/workflow?uc=…&issue=…`  
- [ ] CI-01 / WB-SHOP-01: **no** Proceed to Workflow Studio; Build stepper disabled for that issue  
- [ ] CTA copy never implies Approve writeback navigates to Studio  
- [ ] FlowStepper stage click → correct page + context; disabled stages don’t navigate  
- [ ] DCS FAIL/WARN → Fix only; Build not primary on FAIL  
- [ ] PASS + buildable gated pilot → optional Build {UC}  
- [ ] verify script covers eligible vs non-eligible checks  
- [ ] Written right/gap note in PR (Working / Gaps)  

---

## 13. PR title / branch

- Branch: `feature/wf-02-journey-stages-routing`  
- Title: `feat(WF-02): journey stages, check→UC routing, hide Studio CTA when check gates no pilot`  

---

## 14. Traceability

| Item | |
|------|--|
| Parent | WF-01 Studio · UC-01 gates · FE-08 Fix |
| Pack | Pilot blueprints `gating_check_ids` |
| Bug triggers | Misleading Approve→Studio CTA; Studio button on CI-01; stepper not redirecting logically |
| Engineering | Writeback buttons unchanged; Studio eligibility independent |
