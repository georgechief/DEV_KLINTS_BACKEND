# PRD-RPT-01B — Assessment PDF content & design polish

**Status:** Ready for implementation  
**Module:** see folder path  
**Depends on:** RPT-01 merged ([BE #38](https://github.com/Rohan070/klints_backend/pull/38) / [FE #26](https://github.com/Rohan070/klints_frontend/pull/26))  
**Trigger:** Live sample `docs/reports/klints-assessment-lumera-skin-13-2026-08-12.pdf` — structure OK, **content/UX not stakeholder-ready**  
**Out of scope:** Free/paid gating · storing PDF bytes · LLM narratives · changing Overview Export brief wiring · FE redesign beyond what PDF needs

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-RPT-01B — Assessment PDF polish (BE render + payload).

Read: docs/reports/PRD_RPT_01_FULL_ASSESSMENT_REPORT_PDF.md
Read: docs/reports/PRD_RPT_01B_ASSESSMENT_PDF_POLISH.md
Sample gap: docs/reports/klints-assessment-lumera-skin-13-2026-08-12.pdf

Must-fix vs sample:
1. What to fix: NEVER show "-" for suggested_fix / fix_owner / fix_type
   when CheckMaster has values — wire enrichment into remediation rows.
2. What's wrong table: add Dimension, Systems, Revenue (when present).
3. Humanize check messages (no rate=50%, gaps=['history'], cluster=True).
4. Humanize generated timestamp; hide "localhost" domain (use company name only).
5. Page-1 incomplete callout when coverage low / state INCOMPLETE.
6. Architecture: explain INCOMPLETE; show weighted score when available.
7. Scope: connector status strip; fix AF snapshot id line-break.
8. Title Case check titles in PDF (same spirit as FE-09).
9. Visual pass: clearer hero score, spacing, tables — still ReportLab.
   Prefer dataruns/reports/humanize.py for helpers (avoid naming copy.py).

Ship a before/after PDF sample in the PR description.

Acceptance: §6.
```

---

## 1. Why

RPT-01 delivered compose → payload → stream PDF → audit. The Lumera sample proves plumbing, but:

| Problem in sample | Impact |
|-------------------|--------|
| What to fix = all `-` | Report tells *what’s wrong* but not *what to do* |
| Raw executor strings | Looks like logs, not a client brief |
| INCOMPLETE / 48% coverage buried | Score can mislead |
| Architecture thin / `localhost` | Unprofessional |

This PRD is **content + presentation only** — keep API, audit, Export brief as-is.

---

## 2. Must-fix (content)

### 2.1 What to fix — populate from CheckMaster

For every open FAIL/WARN remediation row:

| Column | Source | Rule |
|--------|--------|------|
| Suggested fix | `CheckMaster.suggested_fix` (or enriched worklist) | Required text; if truly empty → `"See Data Center for this check"` — **never** lone `-` |
| Owner | `fix_owner` | Same |
| Type | `fix_type` | Same |
| Path | `/fix?issue={id}` | Keep |
| Bonus | Short rollback note if master has it | One line under fix or extra column |

**Root cause:** payload `_build_remediation` likely not copying master fields — fix in `payload.py`, add unit test that remediation rows are non-empty when master is seeded.

### 2.2 What’s wrong — richer table

| Add | Source |
|-----|--------|
| Dimension | issue / master |
| Systems | `systems_compared` (friendly: Shopify · Manago.ai) |
| Impact | `revenue_impact` formatted with currency, or `—` if null |

Keep: ID, Title, Status, Sev, What’s wrong, Priority.

### 2.3 Humanize “What’s wrong” / top risks copy

Transform executor detail before PDF (shared helper OK):

| Avoid | Prefer |
|-------|--------|
| `Duplicate PURCHASE rate=50.00% clusters=8` | `About half of purchases look duplicated (8 clusters).` |
| `gaps=['history']` | `Baseline needs more history.` |
| `cluster=True` | `Dead-state contacts spike on one day.` |
| `provenance_share=0.00% weak_or_missing=1/1` | Short plain sentence |

Rules: no Python `repr` lists; percentages as “~50%” or “21%”; Title Case titles (FE-09 spirit). Exact phrasing can be heuristic — **no LLM required**.

### 2.4 Executive page — incomplete honesty

When `state` is INCOMPLETE **or** coverage &lt; ~70%:

> **Incomplete assessment** — score {n} with {coverage}% coverage. {N} checks UNKNOWN / NOT_CONNECTED. Treat this score as directional until connectors and history are complete.

Place **above** or beside the big score, not only in appendix.

### 2.5 Architecture block

- If mode INCOMPLETE / weighted null: one sentence why (e.g. assessment incomplete / insufficient inventory).  
- When weighted score exists: show it.  
- Keep verdict counts table.  
- Optional: top 3 fix-first asset names if present (no PII).

### 2.6 Scope & method

- **Connector strip:** Manago connected / Shopify connected / ERP (yes·no·unknown) at run time.  
- Snapshot ids: no mid-UUID spaces (`af:bec8e58f-…` on one line; smaller font or wrap at hyphen only).  
- Generated time: `12 Aug 2026, 14:19 UTC` (not full ISO with microseconds).  
- Domain: omit if `localhost` / empty; show real domain only.

### 2.7 Healthy / coverage appendix

Keep. Optionally group coverage callouts: NOT_CONNECTED vs UNKNOWN.

---

## 3. Design polish (still ReportLab)

| Item | Guidance |
|------|----------|
| Hero | Larger score + state chip; at-stake secondary |
| Hierarchy | Clear H1/H2; less muted walls of text |
| Tables | Consistent column widths; avoid crushing “What’s wrong” |
| Brand | Existing Klints colors OK — tighten padding, avoid purple AI clichés |
| Length | Prefer readable 3–5 pages over cramming |

No FE visual redesign required.

---

## 4. Tests & evidence

- [ ] Unit: remediation row has non-empty suggested_fix when CheckMaster seeded  
- [ ] Unit: what’s-wrong row includes dimension + systems keys  
- [ ] Unit: humanize helper covers the sample LE-04 / ME-08 / CI-13 style strings  
- [ ] Unit: localhost domain omitted from cover line  
- [ ] PDF fixture or golden snippet asserts “What to fix” ≠ `- - -`  
- [ ] PR description: attach **before** (existing sample) + **after** PDF  

---

## 5. Files (expected)

```text
dataruns/reports/payload.py      # enrichment, humanize inputs
dataruns/reports/render_pdf.py   # tables, hero, incomplete banner, date format
dataruns/reports/humanize.py     # NEW: humanize_check_detail() (+ title/domain helpers)
dataruns/tests/test_report_*.py  # extend
```

FE: **no change** unless a bug blocks Export brief.

---

## 6. Acceptance checklist

- [ ] What to fix populated from CheckMaster (no blank `-` when data exists)  
- [ ] What’s wrong includes Dimension · Systems · Impact  
- [ ] Top risks / detail messages humanized (no `gaps=[…]` / `cluster=True`)  
- [ ] Incomplete/low-coverage callout on page 1  
- [ ] Architecture incomplete explained; weighted score when available  
- [ ] Scope: connectors + fixed snapshot formatting + human datetime  
- [ ] localhost not shown as domain  
- [ ] Titles Title-cased in PDF  
- [ ] Before/after PDF in PR  
- [ ] Existing audit / stream / no-PDF-storage behavior unchanged  

---

## 7. One-page summary

| Question | Answer |
|----------|--------|
| What? | Make the Assessment PDF a real client brief |
| Biggest gap? | Empty What to fix + raw log copy |
| API/FE? | Unchanged |
| Who? | Engineering |

**PRD:** RPT-01B · **Track:** delivery · **Bar:** stakeholder-readable full PDF  
