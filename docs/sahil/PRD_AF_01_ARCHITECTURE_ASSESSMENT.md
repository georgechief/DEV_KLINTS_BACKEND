# PRD-AF-01 — Architecture Assessment (BL-008 + BL-009)

**Status:** Ready for implementation sequencing  
**Owner track:** Sahil (`docs/sahil/`)  
**Backlog:** `BL-008` (asset + dependency graph) → `BL-009` (per-asset + architecture verdicts)  
**Milestone:** MVP1-B (after DCS headline score)  
**MCP:** Deferred — use REST / documented fallbacks; destructive verdicts blocked when graph incomplete  

---

## 0. Original references (authoritative)

**Canonical pack in this repo:**

`klints_backend/Klints_MVP1_Rohan_Build_Pack_v1.2_20260718/`

(Also mirrored under `DataPack/…` — same files; prefer the backend copy for paths below.)

| Need | File | Sheet / tab | Notes |
|------|------|-------------|--------|
| Backlog BL-008 / BL-009 | `06_Implementation/implementation_backlog_v1.2.xlsx` | **01 Backlog**, **02 Milestones** | Exit: no destructive verdict without graph; golden verdict fixture · MVP1-B |
| Framework overview | `01_Specifications/Klints_Spec_ArchitectureAssessmentFramework_v1.4.1_20260718.xlsx` | **01 Overview** | Onboarding position, governance stance |
| 31 probes | same workbook | **02 Assessment Probes** | WF / TAG / PROP / CHAN catalogue |
| 5 asset verdicts | same | **03 Verdict Model** | Keep → Retire candidate + gates |
| Agent vs API | same | **04 MCP-A2A Query Map** | Prefer REST while MCP = DISCOVERY_REQUIRED |
| Dependency edges | same | **05 Dependency Rules** | DEP-01…DEP-10 |
| Account mode rollup | same | **06 Architecture Verdict** | AUGMENT / SELECTIVE_REBUILD / REBUILD / INCOMPLETE |
| 16 lifecycle stages | same | **07 Lifecycle Model** | Coverage gaps → UC Library later |
| Capability fallbacks | same | **08 Capability Requirements** | REST vs MCP vs HUMAN · “Normalize time windows” = **stats windows**, not UI Quarter/Year |
| Asset JSON contract | `03_Machine_Contracts/architecture_asset.schema.json` | — | Persist / validate assets |
| Verdict JSON contract | `03_Machine_Contracts/architecture_verdict.schema.json` | — | Persist / validate assessment |
| Finding shape (optional) | `03_Machine_Contracts/finding.schema.json` | — | Fix-first links to DCS checks |
| DCS inputs this joins | `01_Specifications/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx` | check results API | WF-05 / TAG-02 / PROP-02 cross-checks |
| Pilots later | `04_MVP1_Pilot_Blueprints/pilot_manifest.json` | — | Consumes gaps (WF-12), not BL-008 itself |
| Orchestration later | `01_Specifications/Klints_Spec_OnboardingOrchestrationBlueprint_v1.4.1_20260718.xlsx` | **01**, **03**, **04** | Waves after AF + DCS |

**Stop-and-flag:** If live Manago REST cannot supply a probe’s evidence, mark coverage incomplete — do **not** invent Retire/Consolidate (sheet **01**, **06**, **08**).

---

## 0.1 Codebase rematch (current truth)

Rematched against live code + pack (2026-08-07). PRD describes **to-build**; this table is **what exists today**.

| Layer | Pack / PRD expect | Codebase today |
|-------|-------------------|----------------|
| BL-008 / BL-009 | READY · MVP1-B | **Not started** — no Django models, APIs, Celery tasks, or `kind=architecture_assessment` |
| Schemas | `architecture_asset` / `architecture_verdict` in pack | Present as JSON only under Build Pack — **not validated in app** |
| DCS | Score + snapshot + FAIL/WARN | **Live** — `dataruns/dcs/orchestrate.py` → `SUCCEEDED` then email + audit only |
| Post-DCS AF enqueue | §5.1 locked | **Missing** — wire next to `_notify_dcs_completed` / `_audit_dcs_completed` |
| DataRun kinds | free string in `metadata.kind` | Live: `dcs_score`, `connector_bootstrap`, `connector_fetch` — AF kind not used |
| Manago + fresh import | AF introspection reuses auth | Live for DCS (`fresh_import.py`) — reusable |
| FE `/lifecycle` | Primary AF surface | **Mock only** — `klints-data.ts` + “Live demo data”; **no** architecture API calls |
| FE Quarter / Year | Display horizon (see §9.1.1) | Local `period: "q" \| "y"` swaps `impactQ`/`impactY` strings — **not** a backend filter |
| FE “Run architecture” | None | Confirmed absent; dashboard CTA is “Open architecture →” → `/lifecycle` |
| Sheet **07** stages | 16 stages · 5 phases · 7 UC groups | FE mock uses **5 phase cards** (acq/act/exp/loy/ret) with partial substages — map to sheet 07 when binding |
| Contact `lifecycle_stage` | — | Unrelated import metric (`new`/`repeat`) — **not** AF sheet 07 |

---

## 1. Vision (simple)

| Layer | Question |
|-------|----------|
| **DCS (done)** | Is the **data** sound? |
| **Architecture (this PRD)** | What is already **running** in Manago, and what should happen to it? |

Klints **inventories** workflows / tags / segments / properties (/ channels), builds a **dependency graph**, then assigns **recommendations**.  
Klints **never** stops, pauses, edits, or deletes a live Manago asset (sheet **01 Overview** — governance stance).

---

## 2. Where it sits in product workflow

### 2.1 Pack onboarding sequence (sheet **01**)

```text
1 Connectivity gate          → /integrations
2 DCS data check             → /data-consistency   ← DONE
3 Architecture Assessment    → this PRD            ← BUILD NOW
4 Use Case Library           → /opportunities      ← later
5 Orchestration (one plan)   → Fix / waves         ← later
```

### 2.2 App journey (Klints UI today)

```text
Connect (/integrations)
  → Overview (/dashboard)           [summary chip later]
  → Data Center (/data-consistency) [DCS only — unchanged]
  → ★ Lifecycle cockpit (/lifecycle) [PRIMARY AF surface]
  → Opportunity tracker             [after gaps/mode]
  → Fix → Build → QA → Handoff      [approved AF tasks later]
```

### 2.3 UI ownership (value per screen)

| Route | Today | After this PRD |
|-------|--------|----------------|
| `/data-consistency` | Live DCS score + FAIL/WARN worklist | **No AF inventory** (data issues only) |
| `/lifecycle` | Fixture/`klints-data` “Live demo data” | **Primary:** stages from sheet **07**, assets, verdicts, gaps; status only (no user Run button — see §5) |
| `/dashboard` Overview | DCS live; lifecycle block empty/chrome | **Summary:** mode (AUGMENT/…), coverage %, top Fix-first / Consolidate counts, link to Lifecycle |
| `/opportunities` | Fixture tracker | Later: filter by coverage gaps (WF-12) + mode |
| `/fix`, `/workflow` | Fix-flow | Later: only **approved** AF recommendations become tasks |
| `/integrations` | Connectors | Prerequisite: Manago `connected`/`degraded` |

**Not shown as DCS worklist rows:** AF verdicts are architecture recommendations, not DCS score issues.  
**May deep-link:** Fix-first asset → Data Center check IDs (e.g. CC-07, SP-01).

---

## 3. What we already have (reuse)

| Existing | Reuse for AF |
|----------|----------------|
| Manago connector + fresh import (`dataruns/dcs/fresh_import.py`) | Auth/token; optional dedicated AF introspection import |
| DCS score DataRun + `run_snapshot` + check results | **Required input** for WF-05 / measurement / consent cross-checks |
| `Company`, `Connector`, `Tenant` | Scoping |
| `DataRun` + `metadata.kind` pattern | New kind `architecture_assessment` |
| `Run` / `RunIssue` (DCS) | Optional: emit AF findings separately — **do not** mix into DCS worklist query |
| FE `/lifecycle`, Overview shell | Bind live API; remove “Live demo data” when ready |
| Schemas in Build Pack | Validate payloads before persist |

**Does not exist yet:** architecture models, probe runners, AF APIs, graph persistence.

---

## 4. Schemas & proposed tables

### 4.1 Machine contracts (validate JSON)

**Asset** — `architecture_asset.schema.json` `schema_version: 1.0.0`

Required: `asset_id`, `tenant_id`, `asset_type`, `name`, `status`, `dependencies[]`, `provenance`  
`asset_type` enum: `WORKFLOW | SEGMENT | TAG | PROPERTY | SURFACE | RECOMMENDATION | CHANNEL | METRIC`  
Each dependency: `{ target_asset_id, edge_type }`

**Verdict bundle** — `architecture_verdict.schema.json` `schema_version: 1.0.0`

Required: `assessment_id`, `tenant_id`, `mode`, `asset_verdicts[]`, `evidence_coverage`, `created_at`  
`mode`: `AUGMENT | SELECTIVE_REBUILD | REBUILD | INCOMPLETE`  
Per asset verdict enum: `KEEP | KEEP_IMPROVE | FIX_FIRST | CONSOLIDATE | RETIRE_CANDIDATE`

### 4.2 Suggested Django tables (company-scoped)

Align names to implementation; JSON must round-trip to schemas above.

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `architecture_assessments` | One assessment run | `id`, `company_id`, `tenant_id`, `data_run_id` (AF job), `source_dcs_data_run_id`, `status` (pending/running/succeeded/failed), `mode`, `weighted_score`, `critical_defects`, `evidence_coverage`, `probe_coverage` JSON, `created_at`, `finished_at` |
| `architecture_assets` | Inventory rows for an assessment | `assessment_id`, `asset_id` (stable external key), `asset_type`, `name`, `status`, `definition` JSON, `lifecycle_stage` nullable, `capability_path`, `provenance` JSON |
| `architecture_edges` | Graph (normalized) | `assessment_id`, `source_asset_id`, `target_asset_id`, `edge_type` (USES/READS/WRITES/SENDS/TARGETS/COLLIDES_WITH/REPLACES/…) , `rule_id` (DEP-0x), `evidence` JSON |
| `architecture_asset_verdicts` | BL-009 labels | `assessment_id`, `asset_id`, `verdict`, `evidence_ids` JSON, `blocked_reason` / `failure_code`, `dcs_check_ids` JSON (for FIX_FIRST) |
| `architecture_probe_results` | Optional audit | `assessment_id`, `probe_id` (WF-01…), `status`, `evidence` JSON |

**Also:** `DataRun` row with `metadata.kind = "architecture_assessment"` for job tracking (same pattern as DCS / connector fetch).

### 4.3 Edge types (sheet **05**)

| Rule | Edge | Blocks |
|------|------|--------|
| DEP-01 | Workflow → Segment `USES` | Retire segment |
| DEP-02 | Workflow → Tag/Property `READS` | Rename/delete field |
| DEP-03 | Workflow → Channel `SENDS` | Channel disable |
| DEP-04 | Surface → Segment `TARGETS` | Retire segment |
| DEP-05 | Recommendation → Catalog field `READS` | Schema change |
| DEP-06 | Metric → Workflow `ATTRIBUTES` | Retire workflow |
| DEP-07 | Use case → DCS check `GATED_BY` | Build UC (later) |
| DEP-08 | Task → Task `DEPENDS_ON` | Orchestration (later) |
| DEP-09 | Workflow ↔ Workflow `COLLIDES_WITH` | Simultaneous activation |
| DEP-10 | Asset → Asset `REPLACES` | Unsafe consolidation |

---

## 5. When it runs / when it does not

### 5.1 Locked trigger (no user “Run” in UI)

**Product reality:** Lifecycle / Overview have **no** manual “Run architecture” control for operators. AF must not depend on a button the UI does not offer.

| Trigger | Behavior | MVP1 |
|---------|----------|------|
| **After every DCS job that finishes `SUCCEEDED`** (re-run checks, daily beat, on-connect score) | Worker enqueues AF as a **separate** Celery task with `source_dcs_data_run_id` = that DCS DataRun | **LOCKED — primary** |
| DCS finishes `FAILED` / hard `BLOCKED` with no usable snapshot | **Do not** enqueue AF | Locked |
| DCS `SUCCEEDED` but `headline_score` null (`INCOMPLETE`) | Still enqueue AF inventory; expect `mode=INCOMPLETE`, limited Fix-first joins | Locked |
| Internal/ops `POST /api/v1/architecture/assessments/` | Same enqueue (tests, support) — **not** exposed in product UI | Allowed |
| User clicks anything on Lifecycle | **Never starts** a run — UI only **reads** latest AF | Locked |

**User-visible path:** whatever already starts DCS (Connect → score, **Re-run checks**, daily beat) **also** refreshes Architecture afterward. No extra click.

```text
DCS SUCCEEDED
  → enqueue architecture_assessment (async, separate DataRun)
  → Lifecycle/Overview poll latest AF
       show "Updating architecture…" while AF running
       show verdicts when AF SUCCEEDED
```

**Prerequisites to enqueue:**

1. Manago connector `connected` or `degraded` (else skip AF with log/metric; DCS may still have run on Shopify-only)  
2. DCS DataRun `SUCCEEDED`  
3. No AF already `running` for that company — if yes, **coalesce** (skip duplicate or replace queue with newest `source_dcs_data_run_id`)

### 5.2 When it **does not** run

| Condition | Behavior |
|-----------|----------|
| Inside the DCS assemble/score function | **Never** — always a **follow-on** job after DCS persists |
| User opens Lifecycle / Overview | **Read only** — never start AF on page load |
| Shopify-only / no Manago | Skip AF (nothing to invent) |
| DCS failed before snapshot | Skip AF |
| Pilot / BL-003 | Separate (deferred) |
| MCP unavailable | Still run AF via REST; incomplete graph → `INCOMPLETE` |

### 5.3 Cadence (revisited)

| Event | AF |
|-------|-----|
| Every successful DCS (including daily beat) | **Yes — auto re-run** |
| Between DCS runs | Show last AF; optional stale hint: “Based on score from {time}” |
| Manual UI re-run | **Not in v1** (no control). Future: optional admin-only if product adds it |

**Cost note:** AF introspection is heavier than score-only. If daily DCS + full AF is too heavy in production, **v1.1** may debounce (e.g. skip AF if last AF &lt; N hours and DCS check fingerprint unchanged). **v1 locked behavior = after every DCS SUCCEEDED** so the UI always has a path without a Run button.

---

## 6. Pipeline (how BL-008 then BL-009 work)

```text
DCS DataRun SUCCEEDED (end of existing pipeline / Celery chord)
  → enqueue architecture_assessment (new DataRun, async)
  → Introspect Manago (REST, paged)     ## sheet 02 / 04 / 08
  → Persist assets + edges              ## BL-008
  → Run probes (inventory → graph → health)
  → Join that DCS check results         ## WF-05, TAG-02, …
  → Assign per-asset verdicts           ## BL-009 + sheet 03 order
  → Roll up mode + scores               ## sheet 06
  → Persist architecture_verdict JSON
  → SUCCEEDED → Lifecycle/Overview GET latest
```

**Wire point:** after DCS worker marks score DataRun `SUCCEEDED` (same place emails/audit fire) — `delay()` AF task; do not block DCS response on AF finish.

### 6.1 BL-008 exit criteria (backlog)

- Asset register + dependency graph persisted  
- **No** `RETIRE_CANDIDATE` / `CONSOLIDATE` emitted without graph evidence (sheet **01**, **05**, WF-09)  
- `evidence_coverage` computed  

### 6.2 BL-009 exit criteria (backlog)

- Every inventoried asset has exactly one verdict (sheet **03**)  
- Account `mode` assigned per sheet **06** decision order  
- Golden / fixture verdict path passes  

### 6.3 Per-asset verdict assignment order (sheet **03** + **06**)

```text
1) FIX_FIRST if compliance / DCS-impaired (hard)
2) Else CONSOLIDATE if overlap cluster AND graph allows merge
3) Else RETIRE_CANDIDATE if dormant AND zero dependents (graph hard gate)
4) Else KEEP_IMPROVE if active but weak/incomplete
5) Else KEEP
```

Account mode decision order (sheet **06**):

```text
1) evidence_coverage < 0.80 → INCOMPLETE
2) consent/compliance critical → mark assets FIX_FIRST; continue
3) dependency graph incomplete → INCOMPLETE; forbid Retire/Consolidate
4) else weighted score → AUGMENT / SELECTIVE_REBUILD / REBUILD
```

Weighted inputs (sheet **06**): lifecycle coverage 25%, data-safe assets 25% (critical), collision 15% (critical), measurement 15%, maintainability 20%.

| Mode | Rule (sheet 06) |
|------|-----------------|
| AUGMENT | score ≥ 70, &lt;2 critical defects, no unmitigated consent breach |
| SELECTIVE_REBUILD | 50–69.99 OR one bounded critical cluster |
| REBUILD | score &lt; 50 OR ≥2 critical defects OR graph cannot be established |
| INCOMPLETE | required evidence missing |

---

## 7. Probe catalogue — what to implement

Full list: sheet **02** (31 probes).  
**MVP1-A build priority from sheet 01:** Workflows 8 P0, Tags 4, Props 3, Channels 0 → implement CHAN later as UNKNOWN/skip.

### 7.1 P0 for BL-008 (must ship)

| Probe | Class | Job | Feeds |
|-------|-------|-----|--------|
| **WF-01** | Workflow | Inventory all active automations (4 engines) | Register |
| **WF-04** | Workflow | Trigger → data primitive edges | Graph |
| **WF-09** | Workflow | Full dependency graph | Gate all verdicts |
| **TAG-01** | Tag/Segment | Inventory | Register |
| **TAG-04** | Tag/Segment | Where-used | Graph |
| **PROP-01** | Property | Inventory | Register |
| **PROP-04** | Property | Where-used | Graph |

### 7.2 P0 for BL-009 (verdicts)

| Probe | Job | Verdict |
|-------|-----|---------|
| **WF-02 / WF-03** | Performance + dormancy | Keep / Improve / Retire candidate |
| **WF-05** | Join DCS broken data | **FIX_FIRST** |
| **WF-06** | Consent guard (↔ DCS CC-07 if present) | FIX_FIRST |
| **WF-07 / WF-08** | Overlap + pressure | CONSOLIDATE / Improve |
| **WF-10** | Measurement (↔ DCS ME-02) | KEEP_IMPROVE |
| **WF-12** | Coverage vs sheet **07** stages | Gaps → Opportunities later |
| **TAG-02 / TAG-03 / TAG-05 / TAG-06** | Hygiene, sanity, orphan, overlap | Consolidate / Fix / Retire |
| **PROP-02 / PROP-03 / PROP-05 / PROP-06** | Format, coverage, orphan, duplicate | Fix / Improve / Retire / Consolidate |

### 7.3 P1 / incomplete-tolerant

| Probe | Note |
|-------|------|
| WF-11 | Transactional message mapping — needs Shopify+Manago |
| TAG-07 / TAG-08 | RFM / consent segments — join DCS SP-10 / CC-* |
| PROP-07 | Zero-party utilisation |
| CHAN-01…04 | Sheet marks P0 build priority **0** — stub as not assessed → lowers coverage |

### 7.4 Data access without MCP (sheet **04** + **08**)

| Surface | Confirmed / fallback | MVP1 choice |
|---------|----------------------|-------------|
| Workflow list/stats | RESTV2.WORKFLOW.* | **REST + paging** |
| Segments / where-used | MCP preferred; HUMAN / MANUAL fallback | REST if available; else incomplete graph |
| Tags/properties catalog | MCP / MANUAL | REST contact schema + documented list endpoints if any; else MANUAL_CONFIG incomplete |
| Surfaces | HUMAN_OPERATOR | Skip CHAN or mark incomplete |

**Safety rule (sheet 08):** Do not assign Retire/Consolidate without full graph.

---

## 8. API (v1)

Base `/api/v1/` · JWT · company from user.

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/architecture/assessments/` | **Internal/ops/tests only** — not wired in product UI; body: `{ "source_dcs_data_run_id": null }` |
| `GET` | `/architecture/assessments/latest/` | Latest assessment + mode + counts (Lifecycle/Overview) |
| `GET` | `/architecture/assessments/{id}/` | Full detail |
| `GET` | `/architecture/assessments/{id}/assets/` | Filter `asset_type`, `verdict`, `lifecycle_stage` |
| `GET` | `/architecture/assessments/{id}/graph/` | Nodes + edges for UI |
| `GET` | `/architecture/assessments/{id}/coverage/` | Sheet **07** stage coverage map |

Roles: admin start; admin/analyst/viewer read (match DCS read roles).

---

## 9. UI — what to show (value mapping)

### 9.1 Lifecycle cockpit `/lifecycle` (primary)

Replace fixture banner (“Live demo data”) with live AF state.

| UI block (current shell) | Live binding |
|--------------------------|--------------|
| Page actions | **No Run button.** Status chip only: `Up to date` / `Updating…` / `Waiting for score` / `Incomplete map` · as-of timestamp |
| **Quarter / Year toggle** | **Display only** — see §9.1.1 (does **not** re-run AF or filter inventory) |
| Gaps band | Count of FIX_FIRST + CONSOLIDATE + coverage gaps; € figures scale with period when economics exist — **do not invent AF money in v1** |
| Phase cards (Acquisition → …) | Map sheet **07** phases (FE today: 5 cards; pack: 5 phases / 7 UC groups); per card: # Keep / Improve / Fix-first / gaps |
| Expand sub-stages | Stages 1–16; list assets tagged to stage; verdict chip |
| Workflow line (`lc-wf`) | “N workflows · M blocked (Fix-first)” — **same for Q and Y** |
| Gap → issue link | If FIX_FIRST → link `/data-consistency?check=CC-07` (example) |
| Empty | No assessment yet → copy: “Architecture updates automatically after your Data Consistency Score finishes.” Link to Data Center if no score yet |

#### 9.1.1 How Quarter / Year connects (important)

**Today (FE mock):** `lifecycle.tsx` keeps `period: "q" | "y"` and swaps hardcoded `impactQ`↔`impactY`, `gapValueQ`↔`gapValueY` (demo often ≈ ×4). Workflows, substages, and issue links do **not** change.

**Pack:** Sheet **07** defines the **canonical stage map** (what WF-12 coverage measures). It does **not** define a Quarter/Year control. Sheet **08** “Normalize time windows” and WF-02/WF-03 “trailing window” are **probe stats windows** (dormancy / performance lookback) — backend config on the AF job, **not** the UI toggle.

| Concern | Driven by | Quarter/Year? |
|---------|-----------|---------------|
| When AF runs | After DCS `SUCCEEDED` (§5) | **No** |
| Inventory, graph, verdicts, mode | Latest AF assessment | **No** — same snapshot for both |
| Stage coverage map (WF-12) | Sheet **07** mapping | **No** |
| Probe activity/revenue lookback | AF job config (e.g. 90-day trailing) | **No** — fixed per run, not the toggle |
| € / margin “impact” & “gap” labels on cards | **Presentation horizon** of opportunity economics | **Yes** — only this layer |

**Product rule (locked):**

1. AF assessment is **one snapshot** (auto after DCS).  
2. Quarter/Year is a **client-side (or query) presentation switch**: show the same architecture facts, rescale or re-label **business-impact figures** for “this quarter” vs “annualized / this year.”  
3. Until real economics exist (DCS revenue impact, UC blueprint `economics`, report `business_impact`), keep Q/Y as cosmetic or hide € and show counts only — **never** invent money from AF probes.  
4. Optional later API: `GET …/coverage/?horizon=quarter|year` returns the same coverage + optional `impact` fields already computed for both horizons — still **does not** trigger a new assessment.

**Verdict chips (sheet 03 → UI labels):**

| Enum | UI label | Color intent |
|------|----------|--------------|
| KEEP | Keep | Neutral / revenue |
| KEEP_IMPROVE | Improve | Info |
| FIX_FIRST | Fix data first | Loss / risk |
| CONSOLIDATE | Consolidate | Risk |
| RETIRE_CANDIDATE | Retire candidate | Muted — never “Retired” |

Copy must say **candidate / recommendation**, never “we retired this.”

### 9.2 Overview `/dashboard`

| Element | Value |
|---------|--------|
| Architecture mode badge | AUGMENT / SELECTIVE_REBUILD / REBUILD / INCOMPLETE |
| One line | “{n} assets · {fix_first} fix-first · coverage {p}%” |
| CTA | “Open Lifecycle cockpit” |
| If INCOMPLETE | “Architecture map incomplete — Retire/Consolidate hidden” |
| If no AF yet | Empty state: “Updates automatically after scoring” + link to Data Center |

### 9.3 Data Center

- No change to ranked DCS issues.  
- Optional footnote on Fix-first deep links only.

### 9.4 What we explicitly do **not** show in v1

- Auto-execute retire/consolidate  
- Pilot supplemental gates (BL-003) mixed into AF  
- Fake € architecture impact (use DCS revenue later if needed)  
- MCP-only features as if live  

---

## 10. Connection to DCS (bridge probes)

| AF probe | DCS input | Effect |
|----------|-----------|--------|
| WF-05 | FAIL/WARN check results + WF-04 edges | FIX_FIRST on workflows |
| WF-06 | Consent-related checks (e.g. CC-07 if in run) | FIX_FIRST |
| WF-10 | ME-02 | Prefer IMPROVE over false Retire |
| TAG-02 | SP-01 logic / results | Consolidate hygiene |
| TAG-03 | SP-08 | Fix / Retire |
| PROP-02 | SP-03/04/05 | Fix / Improve |

AF **does not** recalculate DCS score.

---

## 11. Implementation phases

| Phase | Deliverable | BL |
|-------|-------------|----|
| **A** | Models + DataRun kind + GET latest + enqueue hook on DCS SUCCEEDED | 008 scaffold |
| **B** | REST inventory WF-01, TAG-01, PROP-01 + persist assets | 008 |
| **C** | Edges WF-04/09, TAG-04, PROP-04 + graph API | 008 done |
| **D** | Verdict engine + mode rollup + DCS join | 009 |
| **E** | Lifecycle + Overview bind | FE |
| **F** | WF-12 coverage → Opportunities (later) | BL-010 prep |

---

## 12. Acceptance criteria

### Trigger / UX (locked)

- [ ] DCS `SUCCEEDED` enqueues AF asynchronously; DCS HTTP response does not wait on AF  
- [ ] Lifecycle / Overview never expose a “Run architecture” control in v1  
- [ ] Lifecycle shows status chip (`Updating…` / `Up to date` / …) from GET latest + running job  
- [ ] Empty AF copy points to scoring path, not a missing Run button  

### BL-008

- [ ] Assessment job creates assets + edges for a connected Manago company  
- [ ] Graph API returns nodes/edges  
- [ ] Attempting Retire/Consolidate without graph → blocked (`INCOMPLETE` or verdict downgraded)  
- [ ] MCP absence does not crash; coverage reflects gaps  

### BL-009

- [ ] Every asset has one verdict from sheet **03** enum  
- [ ] Mode matches sheet **06** decision order on fixtures  
- [ ] FIX_FIRST assets list responsible DCS check IDs when join hits  
- [ ] Lifecycle shows live data (no “demo” badge when AF succeeded)  
- [ ] DCS worklist query unchanged  

---

## 13. Out of scope

- MCP discovery tests (BL-007)  
- Pilot supplemental gates (BL-003 / DCS-09) — separate  
- Orchestration waves / approval tokens (BL-011+)  
- Assessment Report PDF (BL-013+) — will **consume** AF snapshot later  
- Auto-write to Manago (retire/merge)  

---

## 14. One-page summary

| Question | Answer |
|----------|--------|
| What? | Inventory + graph (008) then Keep/Improve/Fix-first/Consolidate/Retire + AUGMENT/REBUILD (009) |
| Why? | Safely decide what to do with existing Manago setup after data is scored |
| When? | **Auto after every DCS SUCCEEDED** (no UI Run button) — separate async job, not inside assemble |
| Where UI? | **Lifecycle** primary (status chip only); Overview summary; not Data Center worklist |
| Quarter/Year? | **Display horizon for €/gap labels only** — does not re-run AF; pack sheet 07 = stages, not this toggle |
| Schemas? | Pack `architecture_asset` + `architecture_verdict` (not wired in app yet) |
| Tables? | assessments, assets, edges, asset_verdicts (+ optional probe_results) — **to build** |
| Already have? | Manago connect, DCS results + post-SUCCEEDED email/audit hook point, Lifecycle mock shell |
| Code today? | AF models/APIs/tasks = **none**; enqueue after DCS = **none** |
| Never? | Auto-delete/stop workflows; Retire without graph; treat Q/Y as a run trigger |

**Backlog:** BL-008 → BL-009 · **PRD:** AF-01 · **Workbook:** Architecture Assessment Framework v1.4.1 sheets **01–08**
