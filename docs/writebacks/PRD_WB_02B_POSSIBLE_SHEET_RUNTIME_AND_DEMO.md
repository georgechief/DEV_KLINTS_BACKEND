# PRD-WB-02B — Possible-sheet runtime path + Zoom demo (writeback + download)

**Status:** Ready for implementation — **P0 follow-up** (prod Fix Approve blocked)  
**Owner track:** Engineering   
**Surfaces:** `GET /api/v1/writebacks/possible/` · `/fix?issue=<check_id>` · Zoom recording delivered to Rohan  
**Depends on:** WB-01C · WB-02 · FE-12 (already merged to `main`)  
**Out of scope:** Prod `WRITEBACKS_ENABLED=True` · new mappings · LE-04 enable · MCP · Workflow Studio · generating the possible sheet as a progress job · removing `.dockerignore` `docs` wholesale  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-02B — unblock prod /writebacks/possible/ and demo proof.

Read:
- docs/engineering/PRD_WB_02B_POSSIBLE_SHEET_RUNTIME_AND_DEMO.md
- docs/engineering/PRD_WB_02_FIX_APPROVE_WRITEBACK_EXECUTE.md
- docs/engineering/PRD_FE_12_FIX_EVIDENCE_EXCEL_DOWNLOAD.md
- .dockerignore (line: docs)

Ship:
1. Move runtime SoT CSV to dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv
2. possible_sheet.py loads Path(__file__).parent / that file first — never require /app/docs/
3. docs/engineering copy may remain as human mirror only; update PRD-WB-01C path note
4. Deploy BE; prove GET …/possible/ → 200 on apis.klints.io
5. Record Zoom (§6) showing writeback Approve AND evidence Download on live issues
6. Post Zoom link + issue URLs in PR / Slack to Rohan

Acceptance: §7.
```

---

## 1. Why (prod incident 2026-08-18)

WB-02 + FE-12 shipped, but **Approve writeback stays disabled** on production Fix.

### Evidence

| Check | Result |
|-------|--------|
| UI | `/fix?issue=CI-01` → “Write surfaces could not be loaded.” · “No automated writeback…” · Approve greyed |
| API | `GET https://apis.klints.io/api/v1/writebacks/possible/` → **500** |
| Body | `"Possible/not sheet not found: /app/docs/engineering/WRITEBACK_POSSIBLE_NOT_SHEET.csv"` |
| Cause | `possible_sheet.py` resolves `docs/engineering/…csv`; **`.dockerignore` excludes `docs/`** so the file never enters the image |

Local checkout works. Docker prod does not. FE honestly locks Approve when `/possible/` fails.

**This is not an FE bug.** Do not “generate the sheet with progress UI.” It is a ~12-row static honesty catalog that must load instantly from a **shipped** path.

---

## 2. Locked direction

### 2.1 Runtime SoT (required)

| Location | Role |
|----------|------|
| **`dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv`** | **Authoritative at runtime** — must be in the Docker image |
| `docs/engineering/WRITEBACK_POSSIBLE_NOT_SHEET.csv` | Optional human mirror / PRD companion — **not required in `/app`** |

Loader order (locked):

1. `Path(__file__).resolve().parent / "WRITEBACK_POSSIBLE_NOT_SHEET.csv"`  
2. Optional fallback: docs path for laptop-only edits  
3. Never fail solely because `/app/docs/...` is missing  

Response `source` field should report the package-relative path, e.g.  
`dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv`.

### 2.2 Explicit non-goals

- Do **not** remove the entire `docs` ignore just to ship PRDs into prod.  
- Do **not** invent a Celery/progress job to “generate” this sheet.  
- Do **not** unlock Approve in FE without a successful `/possible/` payload.  
- Do **not** claim WB-02 done without the Zoom proof in §6.

### 2.3 Docs patch

Update **PRD-WB-01C** (short note + path table): authoritative runtime path = `dataruns/writebacks/…`. Docs path = editorial mirror only.

---

## 3. Code / deploy checklist

1. Add/copy CSV under `dataruns/writebacks/`.  
2. Patch `dataruns/writebacks/possible_sheet.py` per §2.1.  
3. Keep tests green (`test_writeback_01c` — `source` may end with package path).  
4. Merge + deploy backend to `apis.klints.io`.  
5. Smoke: `GET /api/v1/writebacks/possible/` → **200**, `count >= 10`, CI-01 / CC-03 rows `write_possible_today=sandbox_only`.  
6. Restart workers only if your deploy already restarts API; no Celery change required for this file.

---

## 4. After deploy — Fix path (writeback)

Use **Admin** on production (or staging that mirrors prod).

| Step | Action | Pass |
|------|--------|------|
| 1 | Data Consistency → open live **FAIL/WARN** **CI-01** or **CC-03** → **Fix this issue** | Lands `/fix?issue=CI-01` or `CC-03` |
| 2 | No “Write surfaces could not be loaded” | Surfaces table or disclosure OK |
| 3 | Open **Writeback preview** → run preview | Ready intents / diff |
| 4 | **Approve writeback** enabled → click | Trust → **Written** only after execute success |
| 5 | Optional | Confirm Manago sandbox field (`klints_backfill` / `klints_consent_evidence`) |
| 6 | Negative | `/fix?issue=LE-04` → Approve still disabled |

---

## 5. After deploy — Fix path (download / FE-12)

From **current live issues** on Data Consistency (any FAIL/WARN with row evidence):

| Step | Action | Pass |
|------|--------|------|
| 1 | Open `/fix?issue=<check_id>` for a **non-writable** live check (e.g. LE-05, CI-03, or whatever is FAIL today) | Honesty: Approve off or “not available” |
| 2 | **Download evidence** | CSV downloads (Excel-openable OK) |
| 3 | Filename shape | `klints-evidence-{check_id}-{yyyyMMdd-HHmm}.csv` |
| 4 | Also on writable CI-01/CC-03 | Download still works (optional but preferred in Zoom) |
| 5 | Empty evidence | Button disabled + honest copy — do not fake rows |

---

## 6. Zoom recording — required deliverable

Engineering must **record a Zoom** (or Loom) and send the **share link** to Rohan in the PR description **and** Slack.

### 6.1 Recording contents (one continuous take preferred)

1. **Intro (10s)** — “WB-02B prod proof: possible sheet + Approve + Download.”  
2. **API proof** — Network or curl: `GET …/writebacks/possible/` → **200** (show status + snippet of CI-01/CC-03).  
3. **Writeback path** — From Data Consistency → Fix on **current** CI-01 or CC-03 → preview → Approve → Written.  
4. **Download path** — From Data Consistency → Fix on **another current** live issue (prefer non-writable) → Download evidence → open/show file name + a few rows.  
5. **Negative (30s)** — LE-04 or clearly blocked check: Approve disabled.

### 6.2 Links Engineering must paste with the Zoom

In PR / Slack message, include:

```text
Zoom / Loom: <url>

Writeback issue URL:
https://klints-frontend.vercel.app/fix?issue=CI-01   # or CC-03 — whichever used

Download issue URL:
https://klints-frontend.vercel.app/fix?issue=<check_id>   # current live FAIL used

Possible API (optional screenshot):
GET https://apis.klints.io/api/v1/writebacks/possible/ → 200
```

Use **real current worklist issues** from the demo tenant — not fixtures (`iss-*`).

### 6.3 Length / quality

- Target **3–6 minutes**.  
- Screen share browser + Network tab for the 200.  
- Audio OK; captions optional.  
- Unlisted Zoom/Loom is fine; must be viewable by Rohan without login friction if possible.

---

## 7. Acceptance

- [ ] Runtime CSV under `dataruns/writebacks/` and loaded without `/app/docs/`  
- [ ] Prod `GET /api/v1/writebacks/possible/` → **200**  
- [ ] Fix CI-01 or CC-03: Approve → Written on sandbox (Admin)  
- [ ] Fix current live issue: Download evidence CSV works  
- [ ] LE-04 (or blocked) still cannot Approve  
- [ ] **Zoom link + both Fix URLs** delivered to Rohan  
- [ ] PRD-WB-01C path note updated  

---

## 8. PR title / branch suggestion

- Branch: `fix/wb-02b-possible-sheet-runtime`  
- Title: `fix(WB-02B): ship possible sheet in package + prod demo Zoom`  

---

## 9. Traceability

| Item | Link |
|------|------|
| Incident | Prod 500 on `/writebacks/possible/` · path `/app/docs/engineering/WRITEBACK_POSSIBLE_NOT_SHEET.csv` |
| Parent | PRD-WB-01C · PRD-WB-02 · PRD-FE-12 |
| Docker | `.dockerignore` → `docs` |
| FE symptom | “Write surfaces could not be loaded.” → Approve locked |
