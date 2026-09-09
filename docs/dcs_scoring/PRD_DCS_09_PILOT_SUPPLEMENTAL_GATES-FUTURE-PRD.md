# PRD-DCS-09 — Pilot supplemental preflight gates (archive / long appendix)

> **Implementation SoT (M2):**  
> **[`docs/engineering/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md`](../engineering/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md)**  
> Owner: **Engineering**. Use that file for Cursor briefs, acceptance, and PRs.

This file is retained as a **long-form appendix** (per-check detection notes, historical API sketches). Prefer the Engineering PRD for scope locks against **current** code (`recommend.py` provisional policy, 42-only CheckMaster, CAP-01/HO-01 already shipped).

---

## Original references (authoritative pack)

| Artifact | Path / location | Use for |
|----------|-----------------|--------|
| Backlog row BL-003 | Build Pack `06_Implementation/implementation_backlog_v1.2.xlsx` → sheet **01 Backlog** | Acceptance: “Every pilot gate resolves; supplemental FAIL blocks dependent pilot only” |
| Gate inventory + UC map | `01_Specifications/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx` → sheet **11 Pilot Supplemental Gates** | IDs, Required By, Failure Behavior |
| Detection + fix detail | Same workbook → sheet **02 Check Catalogue** | Detection logic, Suggested Fix |
| Headline scope (do not mix) | Sheet **09 MVP1 Check Scope** | The **42** only |
| Pilot list | `04_MVP1_Pilot_Blueprints/pilot_manifest.json` | `supplemental_preflight_checks` |
| Code today | `dataruns/use_cases/recommend.py` · `constants.SUPPLEMENTAL_PREFLIGHT_CHECKS` | Missing → `not_evaluated` → `ready_provisional` |

**Stop-and-flag:** If code or tenant data disagrees with sheet **11** / **02**, do not invent thresholds silently.

---

## Vision (summary)

The **42-check DCS** = data health / headline score.  
The **12 supplemental gates** = safe to plan/build/activate a **specific** pilot. Not scored; FAIL blocks dependent pilot only.

---

## The 12 (sheet 11)

BR-03, BR-09, CC-06, CI-08, LE-07, LE-10, PT-05, PT-06, PT-11, PT-13, SP-04, SP-10.

UC map (invert): UC-02→CI-08,CC-06 · UC-04→PT-13 · UC-05→CC-06 · UC-06B→SP-10 · UC-08→BR-09 · UC-09→LE-10 · UC-11→BR-09,SP-04 · UC-12→PT-06 · UC-13→PT-05 · UC-21→LE-07,PT-06 · UC-28→BR-03,PT-11.

---

## Per-check build notes (appendix)

Use Catalogue sheet **02** + sheet **11** Detection Logic. Shared executor contract: read-only vs snapshot; missing → UNKNOWN; ERP out of scope → NOT_CONNECTED (BR-09, PT-06).

| ID | Focus |
|----|--------|
| CI-08 | Email format validity (Manago) — UC-02 |
| CC-06 | Double opt-in state integrity — UC-02, UC-05 |
| SP-10 | RFM computability — UC-06B |
| PT-13 | Coupon/discount consistency — UC-04 |
| LE-07 | Cart event coverage — UC-21 |
| LE-10 | Event type discipline — UC-09 |
| PT-05 | Price parity — UC-13 |
| PT-06 | Stock parity — UC-12, UC-21 |
| PT-11 | Product attribute completeness — UC-28 |
| BR-03 | OOS in active surfaces — UC-28 |
| BR-09 | Replenishment inputs — UC-08, UC-11 |
| SP-04 | Date-prefixed detail validity — UC-11 |

Full narrative tables from the prior draft are omitted here to keep a single SoT; expand in implementation PRs with `STOP_AND_FLAG` comments where thresholds are qualitative.

---

## Explicitly not this appendix

Implementation sequencing, Cursor brief, recommend merge rules, APIs, FE, and acceptance → **Engineering PRD-DCS-09**.
