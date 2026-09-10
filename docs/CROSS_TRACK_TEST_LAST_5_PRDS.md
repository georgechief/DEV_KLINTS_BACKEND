# Cross-track polish — last 5 PRDs each (common test cases)

**Status:** Active team process  
**Audience:** Maheep · Sahil · Rohan (review)  
**Goal:** Cross-test each other’s **last 5 PRDs** — code honesty + UI polish. Not a new-feature sprint.  
**Env:** Production preferred — `https://klints-frontend.vercel.app` + `https://apis.klints.io`  
**Rule:** Live Data Consistency issues only. **No fixtures** (`iss-*`).  
**Deliverable:** Written **right / gap report** (§5) — **no Zoom / Loom recording required**.

---

## 0. How to run

| Step | Who | Action |
|------|-----|--------|
| 1 | Both | Read this doc + PRD acceptance sections for the 5 items you will test |
| 2 | Tester | Drive UI + Network (author may watch, does not click) |
| 3 | Tester | Fill **§5 report**: what works · what gaps · what’s broken (per TC) |
| 4 | Author | Fix P0/P1 before claiming that track “demo ready” |
| 5 | Both | Post report in Slack / PR comment to Rohan |

**Severity**

| Level | Meaning |
|-------|---------|
| **P0** | Blocks demo / wrong write / crash / 500 on core path |
| **P1** | Honesty gap, broken CTA, missing download, wrong Elements |
| **P2** | Copy / layout polish |

---

## 1. Pairing (locked)

| Tester | Tests | Track |
|--------|-------|--------|
| **Sahil** | Maheep’s last 5 (§2) | Fix · writeback · evidence |
| **Maheep** | Sahil’s last 5 (§3) | Plan · PDF · AI · blueprint API |

---

## 2. Common test cases — Maheep track (Sahil executes)

PRDs: **FE-11B** · **WB-01C** · **WB-02** · **FE-12** · **WB-02B**  
Docs: `docs/maheep/PRD_*` (see `docs/maheep/README.md` #23–27).

### TC-M1 — Elements show platform api_key (FE-11B)

| | |
|--|--|
| **Pre** | Latest scored run; open any live FAIL with mismatch rows |
| **Steps** | Data Consistency → Fix this issue → Evidence table → **Elements** column |
| **Pass** | Values look like platform field/api keys from map — not “—” / humanized side labels only |
| **Fail** | Blank junk, wrong side label, or JSON dumped in Details |

### TC-M2 — Possible sheet loads in prod (WB-01C / WB-02B)

| | |
|--|--|
| **Pre** | Signed-in Admin or Analyst |
| **Steps** | Network: `GET /api/v1/writebacks/possible/` while on `/fix?issue=CI-01` |
| **Pass** | **200**; `count >= 10`; CI-01 / CC-03 rows with `write_possible_today=sandbox_only`; LE-04 `disabled` |
| **Fail** | **500** / “sheet not found” / “Write surfaces could not be loaded” |

### TC-M3 — Approve writeback on live CI-01 or CC-03 (WB-02)

| | |
|--|--|
| **Pre** | Admin; TC-M2 pass; CI-01 or CC-03 FAIL/WARN on worklist |
| **Steps** | `/fix?issue=CI-01` (or CC-03) → Writeback preview → run preview → **Approve writeback** |
| **Pass** | Button enables after ready preview; trust → **Written** only after successful execute; no fake Written on click |
| **Fail** | Approve stuck disabled after 200 possible; Written without execute; fixture execute |

### TC-M4 — LE-04 / non-writable honesty (WB-02)

| | |
|--|--|
| **Pre** | `/fix?issue=LE-04` or other non-allowlisted live check |
| **Steps** | Observe Approve + honesty banner |
| **Pass** | Approve disabled / honest “not available”; no sandbox write |
| **Fail** | Approve enabled or fake success |

### TC-M5 — Download evidence on current live issue (FE-12)

| | |
|--|--|
| **Pre** | Live FAIL/WARN with row evidence (prefer non-writable, e.g. LE-05 / CI-03 if present) |
| **Steps** | Fix → **Download evidence** → open file |
| **Pass** | CSV downloads; name like `klints-evidence-{check_id}-{yyyyMMdd-HHmm}.csv`; rows match on-screen evidence |
| **Fail** | Button missing; empty fake file; download replaces Approve on CI-01/CC-03 incorrectly |

### TC-M6 — Combined bar (WB-02B)

| | |
|--|--|
| **Steps** | Same session: TC-M3 on one issue + TC-M5 on another current issue |
| **Pass** | Both work on prod; both URLs listed in §5 report |
| **Fail** | Only one path works |

**Sahil polish notes (while testing Maheep)**  
- Trust steps don’t jump ahead  
- Fix footer CTAs readable on narrow width  
- Activity / bell after approve if PRD claims it  
- No silent Network failures  

---

## 3. Common test cases — Sahil track (Maheep executes)

PRDs: **ORCH-01** · **RPT-01** · **RPT-01B** · **AI-01** · **WF-01**  
Docs: `docs/sahil/PRD_*` (see `docs/sahil/README.md` #6–10).

### TC-S1 — Orchestration plan surfaces (ORCH-01)

| | |
|--|--|
| **Pre** | Scored company with plan/NBA data |
| **Steps** | Overview NBA → Data Consistency plan sort → Opportunities plan queue → open Fix |
| **Pass** | Live plan data; deep-links land on real `/fix?issue=<check_id>` |
| **Fail** | Mock queue only; broken links; empty with no honest empty state |

### TC-S2 — Assessment PDF export (RPT-01)

| | |
|--|--|
| **Steps** | Overview → **Export brief** (or equivalent) → PDF downloads |
| **Pass** | File opens; score / checks present; no crash |
| **Fail** | 500; spinner forever; empty PDF |

### TC-S3 — PDF polish (RPT-01B)

| | |
|--|--|
| **Steps** | Open PDF from TC-S2 → “What to fix” / remediation tables |
| **Pass** | Real suggested-fix copy where available; no wall of “See Data Center” placeholders only |
| **Fail** | Unreadable tables; all-placeholder remediation |

### TC-S4 — AI suggestion boxes (AI-01)

| | |
|--|--|
| **Steps** | Fix and/or Diagnose/Overview AI boxes on a live issue |
| **Pass** | Suggestion renders or honest fail; no raw PII dump; shell stays usable if model errors |
| **Fail** | Hard crash; blank forever with no message |

### TC-S5 — Build package API (WF-01 BE)

| | |
|--|--|
| **Pre** | Pilot ready or `ready_provisional` (UC-02 preferred) |
| **Steps** | `POST /api/v1/use-cases/UC-02/build-package/` (auth) → `GET /api/v1/build-packages/{id}/` |
| **Pass** | **201** then **200**; package has human_guide / agent_spec; route human fallback / staged not live as PRD |
| **Fail** | 500; hard-block when only supplementals missing (should be provisional) |

### TC-S6 — Studio FE honesty (WF-01 known gap)

| | |
|--|--|
| **Steps** | Open `/workflow` and `/workflow/$id` |
| **Pass for cross-test** | Report clearly: **Studio still fixture** — do **not** mark WF-01 product-complete |
| **Fail** | Claiming live Studio bind / generate button when still `getStudioBlueprint` fixtures |

**Maheep polish notes (while testing Sahil)**  
- Empty / loading / error states  
- Fix vs Build CTA confusion on Data Consistency  
- PDF/AI timeouts don’t break app shell  

---

## 4. Pass bar (track-level)

| Track | Cross-test pass means |
|-------|------------------------|
| **Maheep** | Sahil completes **TC-M3 + TC-M5** on prod without `/possible/` 500 **and** files §5 report |
| **Sahil** | Maheep completes **TC-S2 + TC-S5**; **TC-S6** listed under Gaps; §5 report filed |

---

## 5. Required deliverable — right / gap report (no recording)

Each tester posts **one written report** (Slack or PR comment). No Zoom/Loom.

### 5.1 Template (paste and fill)

```text
## Cross-test report
Date:
Tester:
Track tested: Maheep | Sahil
Env: prod | staging

### Working (right)
- TC-__: PASS — <short note> — URL: <link>
- TC-__: PASS — …

### Gaps / not working
- TC-__: FAIL | PARTIAL — Severity P0|P1|P2
  Expected:
  Actual:
  URL:
  Network (status / error if any):

### Known accepted gaps (do not hide)
- e.g. WF-01 Studio FE still fixture (TC-S6)

### Top 3 polish asks for author
1.
2.
3.
```

### 5.2 Per-TC status words (locked)

| Status | Meaning |
|--------|---------|
| **PASS** | Meets Pass column in this doc |
| **PARTIAL** | Mostly works; honesty/UX gap |
| **FAIL** | Broken / blocked / wrong behavior |
| **BLOCKED** | Could not run (env, missing FAIL issue, auth) — say why |
| **N/A** | Not applicable this tenant — say why |

Optional: one screenshot per FAIL is enough; video not required.

---

## 6. Finding log (optional detail under a FAIL)

```text
PRD / TC-id:
Severity: P0 | P1 | P2
URL:
Steps:
Expected:
Actual:
Owner to fix:
```

---

## 7. Slack kickoff (paste)

```text
Cross-test: docs/CROSS_TRACK_TEST_LAST_5_PRDS.md

Sahil → Maheep TC-M1…M6
Maheep → Sahil TC-S1…S6

Deliverable = written right/gap report (§5). No Zoom recording.
Live issues only. WF-01 Studio FE = known gap (TC-S6) — list it under Gaps.
```

---

## 8. Related PRDs

| Track | Index |
|-------|--------|
| Maheep | [docs/maheep/README.md](./maheep/README.md) |
| Sahil | [docs/sahil/README.md](./sahil/README.md) |
| WB-02B (P0 unblock) | [maheep/PRD_WB_02B_POSSIBLE_SHEET_RUNTIME_AND_DEMO.md](./maheep/PRD_WB_02B_POSSIBLE_SHEET_RUNTIME_AND_DEMO.md) |
