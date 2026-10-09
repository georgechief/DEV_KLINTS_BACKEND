# PRD-REAL-01 — Real path only (no demo gates) + clear steps when not Klints Approve

**Status:** **Phase A–C shipping** · P0 · honesty + operator guidance  
**Owner track:** Writebacks / Engineering — **BE gates · FE Fix / Studio / Handoff honesty**  
**Surfaces:** `.env` REQUIRE_* · Studio pilot readiness · Fix `/fix` · Handoff stage · Architecture Lifecycle  
**Depends on:** WB-02 / WB-03 / WB-21 · FE-13 fixture gate · CheckMaster ownership · `WRITEBACK_POSSIBLE_NOT_SHEET.csv` · `WRITEBACK_FIX_OWNERSHIP_MVP1_42.md` · AF `graph_complete` / MCP  
**PRD path:** `docs/writebacks/`  
**Source audit:** Product Honesty / Real-Path Audit (chat · 2026-09-29) — §1a embeds the gap map  

**Phase A (2026-09-29):** local `.env` REQUIRE_* → **True**; `M3_DEMO_01_WORKING_GAPS` writeback table corrected; prototype verify Continue gated to DEV; `.env.example` REAL-01 comments. **Restart API + Celery** for flags to apply.  

**Phase B (2026-09-29):** Fix `writebackNonExecutableHonesty` returns Owner / Steps / download labels (PRD §5); Fix panel `data-testid=writeback-steps-to-pass`; wires `formatCustomerSuggestedFix` + sheet pack fields; `verify:wb02` asserts REAL-01 strings.  
**Phase B audit fixes:** PT-03 Preview advertised while sheet `write=no` + PRODUCT.IMPORT blocker (WB-20 Preview OK); plan_only / preview_gated badge+gov copy (not “Evidence only”); SP-01 stub steps; `verify:wb02` 180/180.  

**Phase C (2026-09-29):** `buildPilotUnlockGuide` / `buildHandoffQaUnlockGuide`; Opportunities + Workflow Studio **Steps to unlock**; Handoff QA blocked empty with steps; gating check deep-links prefer Fix; Architecture copy cites graph_complete / MCP (no Flag=False bypass). **Deep recheck:** Studio primary CTA routes by status (`blocked_mode`→Lifecycle, checks→Fix); unlock lists merge `check_results`; mode-not-allowed / AF-not-finished branches; QA page shows unlock when FAIL + `REQUIRE_HANDOFF_QA_PASS`; failing hard tests listed on Handoff/QA.  

**Supersedes (ops intent):** Local/demo use of:

```text
REQUIRE_ARCHITECTURE_PILOT_GATES=False
REQUIRE_PILOT_GATING_CHECKS=False
REQUIRE_HANDOFF_QA_PASS=False
```

Those flags remain in code for **tests / explicit override only** (`@override_settings`). Product default and real tenant path = **all True**. No fake Studio unlock, no fake Handoff, no fake Fix “Passed”.

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-REAL-01 — real path only + clear pass steps for non–Klints-Approve FAILs.

Read:
- docs/ops/PRD_REAL_01_NO_DEMO_GATES_AND_PASS_STEPS.md (this file)
- docs/writebacks/WRITEBACK_FIX_OWNERSHIP_MVP1_42.md
- dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv
- dataruns/use_cases/recommend.py (REQUIRE_* helpers L31–43)
- dataruns/use_cases/handoff_stage.py (~L117 QA gate)
- FE: src/lib/writebacks.ts writebackNonExecutableHonesty
- FE: src/routes/fix.tsx honesty block (~L967, ~L1931)
- FE: src/lib/dcs.ts DcsIssue.suggested_fix / fix_owner / fix_type
- FE: src/lib/fix-flow.ts isFixtureIssueId / fixturesAllowedInBuild (FE-13 — already shipped)

Ship in phases (§6). Do NOT invent PASS. Do NOT weaken DCS thresholds.
Do NOT reopen WB-21 sandbox contract. Do NOT regress mapping-only → “sandbox passed”.
Do NOT treat Frontend_design fixtures as product proof.
Do NOT claim Klints Approve for PT-01 / BR-01 / LE-08 / plan-only / Manual / Config.
When Approve cannot write: show Owner + Why + numbered Steps to pass + re-run DCS.
Wire existing API fields (pack_* + DcsIssue.*) into Fix — do not invent a second SoT.
```

---

## 1. Why

| Old demo behaviour | Real-path rule |
|--------------------|----------------|
| Flags `False` → Studio opens while AF INCOMPLETE / PT FAIL | Flags **True** → block with honest status + next steps |
| Handoff opens while QA FAIL | Handoff stages only on **QA PASS** |
| Fix honesty = one paragraph “download evidence” | Fix shows **Owner · Why Approve won’t write · Steps 1…n · Re-run DCS** |
| Fixture / badge “Passed” as proof | Forbidden as product proof (WB-21 Phase D + FE-13) |
| Operator stuck on External / Data lead / CRM checks | Clear human path without pretending Klints wrote |
| Diagnose has `suggested_fix`; Fix does not | Fix honesty panel consumes the same fields |

**Product lock:** Everything real. If something fails and it is **not** Klints Approve execute, the product must show **clear steps to pass** — never a fake green path.

---

## 1a. Current-state gap map (from Real-Path Audit — SoT for “what exists”)

### A. Demo bypasses found

| ID | Finding | Location | Effect today | REAL-01 action |
|----|---------|----------|--------------|----------------|
| A1 | All three `REQUIRE_*=False` in local `.env` | `klints_backend/.env` | Studio opens while PT-01/PT-04/BR-01 FAIL; Handoff stages without QA PASS — **API-level gate suppression**, not a UX toggle | **Phase A done** → set **True** (restart required) |
| A2 | Defaults already True | `core/settings/base.py` L23–29; `.env.example` | Safe when env unset; `.env` overrides to False | Keep defaults True; fix real `.env` |
| A3 | Consumers | `recommend.py` L31–43; `handoff_stage.py` ~L117 | Flags gate Studio + Handoff | No code change to meaning — enforce True |
| A4 | `Frontend_design` = full fixture app | `Frontend_design/src/lib/klints-data.ts` | Hardcoded Lumera demo; no API | **Out of prod path** (D7); optional Phase A polish on `Continue (demo)` |
| A5 | Fixture badges already disclose | `fixPlans` `testBadge`: “Fixture demo (not live writeback proof)…” | Honest within prototype | Do not treat as writeback proof |
| A6 | `Continue (demo)` on verify | `Frontend_design/.../verify.tsx` L45 | Skips email verify in prototype | Phase A: DEV-only or remove; **not** `klints_frontend` |
| A7 | Fixture path in prod FE | `fix-flow.ts` `isFixtureIssueId` / `fixturesAllowedInBuild` | `iss-*` blocked when `import.meta.env.PROD` (FE-13 §8.2) | **Already shipped** — cite; don’t rebuild. Honesty panel skipped for fixtures by design (`fix.tsx` ~967) |
| A8 | `mapping-only` Fix target | `fix-flow.ts` / WB-21 Phase D | Not “sandbox passed” | **Do not regress** |

### B. Fix UI today (FAIL / non-Approve)

| check_id | Sheet `write_possible_today` | FE | What Fix shows today | Gap |
|----------|------------------------------|----|----------------------|-----|
| **PT-01** | Not in sheet | Not allowlisted | Generic “No automated writeback yet — Download evidence…” | **No numbered steps** |
| **BR-01** | Not in sheet | Not allowlisted | Same generic | **No steps** |
| **LE-08** | Not in sheet | Not allowlisted | Same generic | **No steps** |
| **CI-03** | `preview_only` | Plan-only | Good honesty: CRM executes; Approve won’t merge (`ci03_plan_only`) | Sentence, **not** Step 1…n |
| **CC-01** | `preview_only` | Plan-only | Data lead executes; Approve blocked | Same |
| **CC-02** | `preview_only` | Plan-only | SMS Data lead; Approve blocked | Same |
| **PT-03** | `no` + `requires_product_import_confirmed` | Execute blocked | Generic + blocker note one sentence | **No discrete Preview→Loom→Approve steps** |
| Approve-live set | `yes` + allowlist | Executable | Preview → Approve path | Out of honesty panel (§5.1) |

### C. Remediation copy that already exists (underused on Fix)

| Source | Contains | Where rendered today | Fix honesty today |
|--------|----------|----------------------|-------------------|
| Sheet `pack_fix_owner` | CRM / Data lead / External / Klints | `/writebacks/possible/` → **Write surfaces** accordion | **Not** in honesty block |
| Sheet `pack_suggested_fix_summary` | One-line non-auto path | API returns; **not rendered** in Fix honesty | Unused |
| Sheet `blocker` | e.g. `requires_product_import_confirmed` | Via `writebackSheetBlockerNote` inside honesty detail | One sentence only |
| `DcsIssue.suggested_fix` | Executor / CheckMaster suggested fix | **DiagnoseEvidence** / Data Consistency | **Not on Fix** |
| `DcsIssue.fix_owner` / `fix_type` | Excel ownership | Worklist / routing / Diagnose | **Not on Fix honesty** |
| `writebackNonExecutableHonesty()` | Title + paragraph (CI-03/CC-01/02 bespoke) | Fix ~L1931 | No `steps[]` |
| Prototype `issueEvidence[].fixes[]` | Tagged step bodies | `Frontend_design` only | Not wired to real API — **do not copy as SoT** |

### D. Gap summary (what REAL-01 must close)

1. ~~Real `.env` demo bypass (A1)~~ → **Phase A done** (REQUIRE_* = True; restart running processes).  
2. ~~Prod FE unlocks Studio/Handoff via Flag=False~~ → **Phase A done** for local; staging/prod env must also stay True (Q4 hard-pin optional).  
3. Fix has **no “Steps to pass this check”** for External / Manual / plan_only / Preview-blocked → **Phase B done** (Fix panel + `WRITEBACK_PASS_STEPS`).  
4. `pack_suggested_fix_summary` + `DcsIssue.suggested_fix` / `fix_owner` exist but are **not** composed into Fix honesty → **Phase B done** (wired into Steps panel).  
5. ~~Stale `M3_DEMO_01_WORKING_GAPS` SP-03 / PT-03 / CC-01/02~~ → **Phase A done** (table corrected 2026-09-29).

---

## 2. Locked product decisions

| # | Decision |
|---|----------|
| D1 | **No demo bypass for real tenants.** All three `REQUIRE_*` = **True** in real `.env` / staging / prod. |
| D2 | **No fake PASS.** DCS / AF / QA / writeback results reflect real connectors + scoring. No new invent-evidence paths. Legacy CC-03/LE-01 invent (WB-21 Phase D) stays documented-only — not a demo PASS story. |
| D3 | **Klints Approve path** (allowlisted + sheet yes + mapping enabled): Preview → request approval → Admin Approve → execute → rollback when supported → **re-run DCS**. |
| D4 | **Not Klints Approve** (External / Data lead / CRM / Manual / Config / plan-only / Preview-until-Loom / not built): Fix **must not** enable Approve write. Show structured **Steps to pass**. |
| D5 | **Architecture INCOMPLETE is real.** Do not bypass with Flag 1 = False. Surface `blocked_mode` + steps until MCP unlocks `graph_complete`. |
| D6 | **SoT for ownership / suggested fix:** CheckMaster + worklist `fix_owner` / `fix_type` / `suggested_fix` + sheet `pack_*` / `blocker`. Prefer live `DcsIssue` for owner/suggested; sheet for blocker + pack summary. Do not invent conflicting owners. |
| D7 | **`Frontend_design` stays prototype** — not production proof. Production app = `klints_frontend`. |
| D8 | **Tests may override flags** via `@override_settings` — not product demo mode. |
| D9 | **FE-13 fixture gate already shipped** (`fixturesAllowedInBuild` = !PROD). REAL-01 does not rebuild it; documents that fixtures skip honesty panel by design. |
| D10 | **Steps panel owns operator guidance on Fix.** Write surfaces accordion stays technical sheet truth; Diagnose keeps evidence + suggested fix. Do not duplicate three competing step UIs — Fix honesty is the Steps SoT for non-Approve. |
| D11 | **WB-21 closed.** No second sandbox mode; no regress of `mapping-only` / fixture badge honesty. |

---

## 3. Flag contract (real path)

| Flag | True means | Block surface | Operator must achieve |
|------|------------|---------------|------------------------|
| `REQUIRE_ARCHITECTURE_PILOT_GATES` | Enforce AF mode for pilots | Studio `blocked_mode` | Succeeded AF; mode ≠ `INCOMPLETE`; mode ∈ pilot `architecture_modes` → needs `evidence_coverage ≥ 0.80` **and** `graph_complete` (rich workflow defs + segments; MCP preferred) |
| `REQUIRE_PILOT_GATING_CHECKS` | Enforce blueprint gating checks | Studio `blocked_checks` | Headline gating checks **PASS** on latest DCS; supplementals PASS or `not_evaluated` → `ready_provisional` |
| `REQUIRE_HANDOFF_QA_PASS` | Enforce QA before stage | Handoff 409 `qa_not_pass` | `WorkflowQaResult.status = PASS` (score ≥ 80, hard tests pass) |

**Always required (not flag-gated):** latest DCS headline ≥ pilot `min_dcs` (usually 70) or `blocked_dcs_score`.

**Code pointers:**

- Readers: `dataruns/use_cases/recommend.py` — `architecture_pilot_gates_required`, `pilot_gating_checks_required`, `handoff_qa_pass_required`  
- Handoff: `dataruns/use_cases/handoff_stage.py` — QA PASS when flag True  
- Schema defaults: `core/settings/base.py` (True)

**Local `.env` target (real path):**

```env
REQUIRE_ARCHITECTURE_PILOT_GATES=True
REQUIRE_PILOT_GATING_CHECKS=True
REQUIRE_HANDOFF_QA_PASS=True
```

Restart API + Celery after change. Expect Studio/Handoff to **block** until real conditions pass — that is correct.

**Pilot gating pointer:** Blueprint JSONs under `Klints_MVP1_Rohan_Build_Pack_*/04_MVP1_Pilot_Blueprints/` → `gates.gating_check_ids`. Many UCs gate on **PT-01** (no Klints Approve — External steps in §5.4). Operators unblock Studio by clearing those check FAILs (or picking a pilot whose gates they can pass), not by setting flags False.

---

## 4. Fix UI contract — “Steps to pass”

### 4.1 When to show

Show the **Steps to pass** panel on Fix for **live** issues when:

- Check is FAIL or WARN (or plan-only Preview with no execute), **and**
- Structural writeback is **not** executable (not allowlisted / sheet not yes / mapping disabled / plan_only / LE-04 blocked / load error), **or**
- Owner ≠ `Klints (automated)` for execute (pipeline already denies), **or**
- Execute is capability-blocked (e.g. PT-03 until PRODUCT.IMPORT confirmed)

Do **not** show as a substitute for Approve when the check **is** Klints Approve-ready — then show Preview → Approve.  
Do **not** compute for fixture `iss-*` issues (existing behaviour).

### 4.2 Panel shape (required fields)

```text
Cannot auto-write · {CHECK_ID}
Owner: {fix_owner}          ← DcsIssue.fix_owner, else pack_fix_owner
Fix type: {fix_type}        ← DcsIssue.fix_type, else pack_fix_type
Why Approve won’t write: …   ← honesty (plan_only / External / blocker / not built)
What Klints found: …         ← DcsIssue.suggested_fix (customer-safe; same as Diagnose)
What to do (sheet): …        ← pack_suggested_fix_summary when present
Steps to pass:
  1. …
  2. …
  3. …
  N. Re-run Data Consistency Score — this check PASSes when evidence clears
[Download evidence / merge plan / consent plan]  ← existing export; label by check
```

**UI note:** Prefer one structured block (audit Phase 3 shape) that **extends** `writebackNonExecutableHonesty` — not a second competing banner below Write surfaces.

### 4.3 Step authorship rules

| Priority | Source | Use for |
|----------|--------|---------|
| 1 | Authored steps in this PRD §5 (per `check_id`) | Known non-Approve / plan-only / Preview-blocked |
| 2 | Sheet `pack_suggested_fix_summary` + `blocker` | Fallback when no authored list |
| 3 | `DcsIssue.suggested_fix` | “What Klints found” (not a fake Approve) |
| 4 | Generic template | Owner role + Download evidence + fix in system of record + re-run DCS |

**Forbidden:** Steps that say “Approve in Klints” when execute is not available.  
**Forbidden:** Steps that claim PASS without re-score.  
**Forbidden:** Using `Frontend_design` `issueEvidence[].fixes[]` as production SoT.

### 4.4 Download CTA labels (plan-only)

| check_id | Button label |
|----------|----------------|
| CI-03 | Download merge plan |
| CC-01 | Download consent plan |
| CC-02 | Download SMS consent plan |
| Other non-executable | Download evidence (existing) |

---

## 5. Per-check Steps to pass (SoT for implementation)

### 5.1 Klints Approve live (reference — not the honesty panel)

**Checks (FE allowlist):** CI-01, CI-05, CC-03, WB-SHOP-01, LE-01, LE-02, LE-05, LE-09, SP-07, SP-03, PT-04.

**CC-03 note:** Excel Fix Owner is **Data lead**; product exception keeps **Approve live** (Settings + allowlist). Steps for operators remain Klints Approve path — do not label as External.

Steps (already shipped):

1. Connect Manago + Shopify; Settings **Allow writebacks** ON; Admin available for Approve.  
2. Open Fix → run **writeback preview** (dry-run).  
3. Analyst **Request approval** → Admin **Approve & write**.  
4. **Re-run DCS**; check PASSes when treated rows clear (partial batch may still FAIL).  
5. Rollback when sheet/mapping supports it if needed; then re-preview.

### 5.2 Plan-only (Preview + Download; CRM / Data lead)

#### CI-03 — Duplicate contacts (CRM manager)

1. Run Preview — review survivor / loser / `safety_class`.  
2. **Download merge plan**.  
3. CRM manager merges or clears losers **in Manago** (Klints does **not** auto-merge; no email-delete).  
4. Tombstone / clean Klints Contact DB as required by plan notes.  
5. Re-run DCS — CI-03 PASSes when duplicates are resolved.

#### CC-01 — Email consent (Data lead)

1. Preview + **Download consent plan** (FORCE_OPT_OUT / FORCE_OPT_IN / SKIP_UNEVIDENCED).  
2. Data lead applies policy **in Manago** (Phase A: Klints does not auto-apply `forceOpt*`).  
3. Prefer CC-03 evidence clean where plan requires Shopify evidence.  
4. Re-run DCS — CC-01 PASSes when email consent parity clears.

#### CC-02 — SMS / mobile consent (Data lead)

1. Preview + **Download SMS consent plan** (forcePhoneOpt* / SKIP; unreachable Download-only).  
2. Data lead applies policy **in Manago**.  
3. Re-run DCS — CC-02 PASSes when SMS consent parity clears.

### 5.3 Preview live · Approve after capability / Loom

#### PT-03 — Catalog completeness (Klints automated · execute blocked today)

Sheet: `write_possible_today=no`, blocker `requires_product_import_confirmed`, registry enabled, Preview OK.

1. Confirm Shopify products + Manago catalog connected.  
2. Use Fix **Preview** for upsert / archive plan (Download attribute-empty as needed).  
3. **Approve stays off** until `RESTV2.PRODUCT.IMPORT` is capability-confirmed (Loom) + FE allowlist / DB allowlist enabled.  
4. After execute unlock: Approve upsert missing + archive surplus (no hard-delete).  
5. Re-run DCS — PT-03 PASSes when catalog vs commerce band clears (archived excluded from surplus per WB-20).

### 5.4 Not Klints execute (External / Data lead / not built)

#### PT-01 — Event product IDs resolve (External integrator)

*Not on writeback sheet. No Klints Approve.*

1. Owner: **External integrator**.  
2. Agree product ID convention (events ↔ catalog; often Shopify `product.id` = Manago `productId`).  
3. Fix dangling IDs in Manago events and/or catalog (integrator tools / historical map).  
4. Re-run DCS — PT-01 PASSes when event product IDs resolve.  
5. Do **not** use PT-03 upsert as a substitute for PT-01 ID convention.  
6. Do **not** treat “connectors healthy” alone as the fix — ID convention is the driver.

#### BR-01 — Margin data coverage (Data lead)

*Not on writeback sheet. No Klints Approve in MVP1.*

1. Owner: **Data lead**.  
2. Provide margin / cost coverage into Manago product catalog (ERP or agreed feed — not “flip a Shopify setting” alone).  
3. Re-run DCS — BR-01 PASSes when margin coverage meets CheckMaster band.  
4. No Klints writeback mapping in MVP1 — do not show Approve.

#### LE-08 — Cart / stale CART (External integrator)

1. Owner: **External integrator**.  
2. Close or update stale CART via integration (not Klints Approve).  
3. Re-run DCS.  
4. No Klints execute path in MVP1.

#### LE-04 — Disabled mapping

1. Intentionally **off** (pack / registry `enabled=false`).  
2. Download evidence for manual / integration fix.  
3. Do not enable Approve without a new product decision + sheet/registry change.

#### SP-01 — Disabled stub (not in MVP1-42)

1. Not in CHECK_MASTER_42; no DCS executor.  
2. Do not advertise Fix Approve.  
3. Out of operator Fix path for MVP1 scored issues.

### 5.5 Manual / Config / not a writeback (generic)

For remaining FAIL checks with `fix_type` Manual (guided) or Configuration:

1. Show **Owner** and **suggested_fix** from DCS.  
2. Steps: follow suggested fix in named system(s) → re-run DCS.  
3. Never offer Approve unless sheet + allowlist + registry say yes.

### 5.6 Studio / Architecture / Handoff (not Fix Approve)

| Block | Steps to pass (operator) |
|-------|---------------------------|
| `blocked_dcs_score` | Treat FAIL writebacks / manual gaps → re-run DCS until headline ≥ `min_dcs` |
| `blocked_checks` | Open each gating `check_id` (blueprint `gating_check_ids`) on Fix / Data Consistency → follow §5 → re-run DCS / `evaluate_pilot_gates` |
| `blocked_mode` (AF INCOMPLETE) | Connect Manago → run Architecture assess → need rich workflows + segments (`graph_complete`) — **MCP / Manago inventory gap**; Lifecycle shows incomplete honestly until then |
| Handoff `qa_not_pass` | Build package only when pilot `ready` / `ready_provisional` → run QA until PASS → then stage |

---

## 6. Phased delivery

Aligns with Real-Path Audit Phases 1–3 + MCP track.

### Phase A — Ops + contract (no Fix UI feature yet) ≈ Audit Phase 1

1. [x] Set all three REQUIRE_* = **True** in local real `.env`; restart API + Celery (**operator must restart**).  
2. [ ] Optional ops: pin True in `production.py` if team agrees (see §9 Q4) — defaults in `base.py` already True.  
3. [x] Update `M3_DEMO_01_WORKING_GAPS`: SP-03 Approve live; PT-03 Preview; CC-01/02 plan_only; demote “set flags False” to historical demo only.  
4. [x] Document FE-13: fixtures blocked in PROD; honesty N/A for `iss-*` (in WORKING_GAPS traps + this PRD D9).  
5. [x] `Frontend_design` `Continue (demo)` → DEV-only (`Continue (prototype · DEV)`).  
6. [x] `.env.example` documents REAL-01 True defaults.  
7. **Acceptance:** With flags True (after restart), Studio/Handoff block when AF incomplete / checks FAIL / QA FAIL — no silent unlock. **Smoke after restart left to operator.**

### Phase B — Fix “Steps to pass” (FE primary) ≈ Audit Phase 2 + 3 combined

1. [x] Extend `writebackNonExecutableHonesty` to return  
   `{ title, detail, owner?, fixType?, suggestedFix?, packSummary?, steps: string[], downloadLabel?, retry? }`.  
2. [x] Inputs: `checkId`, `possibleRows`, `mappings`, load errors, plus **`DcsIssue` fields** (`suggested_fix`, `fix_owner`, `fix_type`).  
3. [x] Seed §5 authored steps for CI-03, CC-01, CC-02, PT-03, PT-01, BR-01, LE-08, LE-04 + generic fallback from sheet + DCS.  
4. [x] Render **one structured panel** on `fix.tsx` (`data-testid=writeback-steps-to-pass`) — Owner · Why · What Klints found · Steps · Download CTA.  
5. [x] Do **not** treat Write surfaces accordion as the Steps UI (D10).  
6. [x] Verify script asserts panel fields / key strings (`verify:wb02` REAL-01 Phase B checks).  
7. **Acceptance:** Fix on PT-01 / CI-03 / BR-01 / PT-03 shows numbered steps; never implies Approve wrote. **UI smoke left to operator.**

### Phase C — Studio / Lifecycle blocker steps (FE)

1. [x] For `blocked_checks` / `blocked_mode` / `blocked_dcs_score`, show short **Steps to unlock** (link to Fix issue or Lifecycle) — Opportunities + Workflow Studio.  
2. [x] Architecture incomplete: explicit “graph incomplete — MCP / rich workflow + segments required” — no Generate bypass.  
3. [x] Handoff QA blocked empty shows **Steps to unlock Handoff** (`handoff-steps-to-unlock`).  
4. [x] Gating check deep-links prefer Fix (supplementals stay unlinked to worklist).  
5. [x] Deep recheck (2026-09-29): Studio CTA by status; unlock merges `check_results`; AF not-finished / mode-not-allowed copy; QA FAIL unlock panel (`qa-steps-to-unlock-handoff`); hard-test ids on Handoff/QA guides.  
6. **Acceptance:** Operator navigates pilot card → correct next surface without demo flags. **UI smoke left to operator.**

### Phase D — MCP / graph_complete (separate track)

1. Fix Manago MCP OAuth (`Invalid client_id` — `MANAGO_MCP_OAUTH_DIAGNOSTIC.md`).  
2. Discovery: workflow_read + segment inventory → Architecture inventory/graph.  
3. Re-assess AF until `graph_complete=True` and mode ≠ INCOMPLETE.  
4. **Acceptance:** With Flag 1 True, ≥1 pilot leaves `blocked_mode` on real Manago evidence.

**Do not start Phase D coding until OAuth works and Phase A–B are agreed.**

---

## 7. Non-goals / anti-patterns

| Anti-pattern | Why forbidden |
|--------------|---------------|
| Flag=False as real-path runbook | Fake Studio/Handoff unlock |
| Weakening DCS bands / inventing PASS | Lies to operators |
| New invent-evidence product paths | WB-21 Phase D: legacy CC-03/LE-01 only; no expansion |
| Claiming fixture / `Frontend_design` badges as live writeback proof | Not production |
| `seed_demo_tenant` as real-tenant / DP1 AC | M3-DEMO: live Shopify import is SoT |
| Reopening WB-21 / new sandbox mode | Contract closed |
| Regressing `mapping-only` to “sandbox passed” | WB-21 Phase D honesty |
| Building Klints Approve for PT-01 / BR-01 / LE-08 here | Ownership: External / Data lead |
| CI-03 / CC-01 / CC-02 Phase B mutate | Separate PRDs + Loom |
| PT-03 Approve before PRODUCT.IMPORT confirmed | Sheet blocker |
| Global `WRITEBACKS_ENABLED=True` for all tenants | Kill switch remains |
| Copying prototype `issueEvidence[].fixes[]` as API SoT | Fixture-only |

---

## 8. Acceptance checklist

### Product / ops (Phase A)

- [x] Real `.env` has all three REQUIRE_* = True  
- [x] Restart backend/Celery documented; expect blocks until real clear  
- [x] No runbook teaches Flag=False as the real path  
- [x] `M3_DEMO_01_WORKING_GAPS` writeback rows corrected (SP-03 / PT-03 / CC-01/02)  
- [x] FE-13 fixture PROD gate cited (already shipped)  
- [ ] Operator smoke after restart: Studio/Handoff block as expected  

### Fix honesty (Phase B)

- [x] Non-executable checks show Owner + Why + numbered Steps + re-run DCS  
- [x] `DcsIssue.suggested_fix` / `fix_owner` appear on Fix (not only Diagnose)  
- [x] `pack_suggested_fix_summary` used when authored steps absent or as “What to do”  
- [x] CI-03 / CC-01 / CC-02 steps match §5.2 + Download labels §4.4  
- [x] PT-01 / BR-01 / LE-08 steps match §5.4 (no Approve)  
- [x] PT-03 steps mention Preview OK / Approve after capability  
- [x] Approve live checks unchanged; `verify:wb02` still green (177/177)  
- [ ] Operator UI smoke on live FAIL PT-01 / CI-03 / PT-03  

### Studio / Handoff (Phase A then C)

- [ ] Flag True → no Generate while AF INCOMPLETE (ops smoke)  
- [ ] Flag True → no Generate while gating checks FAIL (ops smoke)  
- [ ] Flag True → no Handoff stage while QA ≠ PASS (ops smoke)  
- [x] Blockers link to Fix / Lifecycle / Data Consistency with actionable **Steps to unlock** copy  

### Always

- [ ] Ownership doc + sheet remain SoT; update §5 when owner/path changes  
- [ ] No new invent-evidence paths  

---

## 9. Open questions (resolve → then status = Contract locked)

| # | Question | Proposal | Status |
|---|----------|----------|--------|
| 1 | Flip Flag 1 True **before** MCP works? | **Yes (D5)** — Studio `blocked_mode` + Architecture steps; no fake unlock | **Accepted** (Phase A) |
| 2 | Authored steps: FE map vs BE `pass_steps[]`? | **Phase B: FE map keyed by check_id + sheet/DCS fields.** Optional later BE field | **Accepted** |
| 3 | Update `M3_DEMO_01_WORKING_GAPS`? | **Yes** — Phase A | **Accepted** (done) |
| 4 | Hard-pin REQUIRE_*=True in `production.py`? | Prefer env True + document; hard-pin only if ops agree | Open (ops) |
| 5 | Prototype `Continue (demo)` change in scope? | DEV-only in Phase A | **Accepted** (done) |

**Contract for Phase B+:** Q1–Q3 + Q5 locked. Q4 optional.

---

## 10. Related

- `docs/writebacks/WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`  
- `docs/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` · `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv`  
- `docs/writebacks/PRD_WB_21_SANDBOX_TEST_ALL_WRITEBACKS.md`  
- `docs/frontend/PRD_FE_13_SHELL_HONESTY_AND_DEEP_LINKS.md` (fixture PROD gate)  
- `docs/ops/M3_DEMO_01_WORKING_GAPS.md` (REAL-01 Phase A: writeback table + flag note corrected)  
- `MANAGO_MCP_OAUTH_DIAGNOSTIC.md` (repo root)  
- `dataruns/use_cases/recommend.py` · `handoff_stage.py`  
- `dataruns/writebacks/transform.py` (legacy invent CC-03/LE-01 — do not expand)  
- FE `src/lib/writebacks.ts` · `src/routes/fix.tsx` · `src/lib/dcs.ts` · `src/lib/fix-flow.ts`  
- FE `src/components/klints/DiagnoseEvidence.tsx` · `WritebackPossibleSurfaces.tsx`  
- Blueprints: `…/04_MVP1_Pilot_Blueprints/*.json` → `gates.gating_check_ids`  

---

## 11. Key file paths (implementation)

| File | Role |
|------|------|
| `klints_backend/.env` | Flip REQUIRE_* → True (Phase A) |
| `klints_backend/core/settings/base.py` | Defaults True |
| `klints_backend/.env.example` | Keep True documentation |
| `dataruns/use_cases/recommend.py` | Flag readers + Studio evaluation |
| `dataruns/use_cases/handoff_stage.py` | Handoff QA gate |
| `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` | pack_* / blocker SoT |
| `klints_frontend/src/lib/writebacks.ts` | Extend honesty → steps |
| `klints_frontend/src/routes/fix.tsx` | Render Steps panel |
| `klints_frontend/src/lib/dcs.ts` | `suggested_fix` / `fix_owner` / `fix_type` |
| `klints_frontend/src/lib/fix-flow.ts` | Fixture gate (shipped) |
| `Frontend_design/.../verify.tsx` | Optional demo button hygiene |

---

## 12. Suggested commits / PRs (when coding starts)

| PR | Scope |
|----|--------|
| REAL-01A | This PRD + `.env` True + gaps doc honesty (+ optional prototype verify) |
| REAL-01B | FE Steps to pass on Fix + verify script |
| REAL-01C | Studio / Handoff blocker steps |
| REAL-01D | MCP → graph_complete (separate; after OAuth) |
