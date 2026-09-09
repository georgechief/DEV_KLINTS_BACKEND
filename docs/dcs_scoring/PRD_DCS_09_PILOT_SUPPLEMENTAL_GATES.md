# PRD-DCS-09 — Pilot supplemental preflight gates (M2)

**Status:** Steps 0–12 done; Step 13 PR ready (manual commit) — **P0 for M2 claim** · see [DCS_09_WORKING_GAPS.md](./DCS_09_WORKING_GAPS.md) §Step 13  
**Owner track:** Engineering  — **BE primary · FE light**  
**Backlog:** Pack **BL-003**  
**Depends on:** DCS 42-check path + snapshot · UC-01 / WF-01 recommend + Studio · OPS-UC-01 pilots seeded  
**Parallel:** Engineering [M2-OPS-01](../engineering/PRD_M2_OPS_01_STAGING_HARDEN.md) (staging + Fix smoke — does not implement these gates)  
**Out of scope:** Changing headline **42** / `assemble_dcs_score` · HO-02 MCP Send · CAP-01B discovery · Engineering writeback mappings for these 12 · BL-017 ORCH · inventing PASS  

**Pack SoT:** sheet **11 Pilot Supplemental Gates** + Catalogue **02** for the 12 IDs · `pilot_manifest.json` → `supplemental_preflight_checks`  
**Supersedes for implementation:** [`docs/dcs_scoring/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES-FUTURE-PRD.md`](../dcs_scoring/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES-FUTURE-PRD.md) (kept as archive / long appendix)

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-DCS-09 — evaluate the 12 pack supplemental gates; wire into pilot readiness.

Read:
- docs/engineering/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md (this file)
- Pack sheet 11 + pilot_manifest.json supplemental_preflight_checks
- dataruns/use_cases/recommend.py (ready_provisional when supplemental missing)
- dataruns/use_cases/constants.py SUPPLEMENTAL_PREFLIGHT_CHECKS
- dataruns/dcs/ — CheckMaster stays 42; do NOT add these to assemble

Ship:
1. Static master + UC↔gate map for the 12 (§3).
2. On-demand evaluate using latest DCS snapshot/DB; persist scope=pilot_supplemental (§4–5).
3. Merge results into recommend gate labels so PASS → ready; FAIL → blocked_checks; missing → provisional (§6).
4. APIs: evaluate + latest + readiness (§7).
5. FE: Studio/Opportunities show supplemental FAIL blockers; optional “Evaluate pilot gates” (§8).
6. M2 demo: UC-02 can become ready (not forever provisional) when CI-08+CC-06 PASS (§9).

Acceptance: §10. Never change EXPECTED_CHECK_COUNT=42.
```

---

## 1. Why (pack + code today)

### Pack

| Rule | Source |
|------|--------|
| Exactly **12** on-demand preflights | Sheet 11 · `pilot_manifest.supplemental_preflight_checks` |
| **Outside** the 42 headline score | Sheet 09 vs 11 — no overlap |
| FAIL blocks **dependent pilot only** | Sheet 11 Failure Behavior |
| Pilot needs headline **and** supplemental PASS to plan/build/activate | Sheet 11 governance |

### Code today (gap)

| Piece | Behavior |
|-------|----------|
| `SUPPLEMENTAL_PREFLIGHT_CHECKS` | ID set locked in `constants.py` |
| `recommend.evaluate_pilot` | Missing supplemental → `not_evaluated` → **`ready_provisional`** forever |
| DCS pipeline | Runs **42 only** — no executors for the 12 |
| Studio | Allows Generate on provisional (WF-01 §3.2) — honest but not “fully ready” |

**DCS-09** makes the 12 **real PASS/FAIL** so M2 can claim hard-green Ready (esp. **UC-02**: CI-08, CC-06).

---

## 2. Product rules (non-negotiable)

1. Headline `EXPECTED_CHECK_COUNT` stays **42** — never feed supplementals into `assemble_dcs_score()`.  
2. Supplemental FAIL must **not** set DCS `run_state=BLOCKED`.  
3. Strict readiness: supplemental **PASS** required (WARN / UNKNOWN / NOT_CONNECTED / FAIL ⇒ not ready).  
4. Missing evaluation still → `not_evaluated` → `ready_provisional` (WF-01 policy kept until evaluated).  
5. Stop-and-flag: do not invent Catalogue thresholds — document cutovers in code comments / PR.

---

## 3. Inventory (locked — pack)

### 3.1 The 12

| Check ID | Required by (sheet 11) |
|----------|-------------------------|
| BR-03 | UC-28 |
| BR-09 | UC-08, UC-11 |
| CC-06 | UC-02, UC-05 |
| CI-08 | UC-02 |
| LE-07 | UC-21 |
| LE-10 | UC-09 |
| PT-05 | UC-13 |
| PT-06 | UC-12, UC-21 |
| PT-11 | UC-28 |
| PT-13 | UC-04 |
| SP-04 | UC-11 |
| SP-10 | UC-06B |

Must match `SUPPLEMENTAL_PREFLIGHT_CHECKS` and `pilot_manifest.json` (same set).

### 3.2 M2 ship slices

| Slice | Scope | Goal |
|-------|--------|------|
| **A (P0)** | **CI-08 + CC-06** + evaluate API + recommend merge | **UC-02 → `ready`** when hard gates + these PASS |
| **B (P0)** | Remaining 10 executors + full map | All 16 pilots can clear supplemental side |
| **C (P1)** | FE CTA + blocker copy | Operator can run gates without Postman |

Ship A+B in one PR if fast; **A alone unblocks M2 demo path**.

---

## 4. Architecture

```text
Existing DCS score (42) → snapshot / company DB
                              ↓
         POST pilot-gates/evaluate  (subset of 12)
                              ↓
         persist scope=pilot_supplemental (not worklist)
                              ↓
         recommend.evaluate_pilot merges labels
                              ↓
         ready | ready_provisional | blocked_checks
```

Reuse: DCS snapshot / `db_context` / executor patterns (`PRD_DCS_04`).  
Do **not**: add IDs to `check_master_mvp1.json`; do **not** show as default Data Center ranked score issues.

---

## 5. Persistence

**Prefer:** `DataRun` with `metadata.kind = "pilot_gate_eval"` (or equivalent) holding:

```json
{
  "scope": "pilot_supplemental",
  "results": [
    {
      "check_id": "CI-08",
      "status": "PASS",
      "severity": "Medium",
      "evidence": [],
      "required_by": ["UC-02"],
      "evaluated_at": "…"
    }
  ],
  "data_run_id_score": 123,
  "gate_catalog_version": "MVP1-SUPP-12-v1.4.1"
}
```

Latest eval per company is what recommend merges.  
Optional: also keep `check_master_supplemental_mvp1.json` + `pilot_supplemental_gate_map.json` under `dataruns/dcs/`.

---

## 6. Wire `recommend.py` (critical)

Today `_gate_result_label`: supplemental + no DCS row → `not_evaluated`.

**After DCS-09:**

1. Load latest supplemental results for company.  
2. For each blueprint `gating_check_ids` that is supplemental:  
   - result **PASS** → label `PASS`  
   - result present ≠ PASS → label that status → **`blocked_checks`**  
   - no result → `not_evaluated` → provisional (unchanged)  
3. Hard (42-scoped) gates unchanged.  
4. `provisional_supplemental=true` only when ≥1 supplemental still `not_evaluated`.  
5. When all required supplementals PASS and hard gates PASS → status **`ready`** (not provisional).

QA `data_gates_pass` / `qa_normalize` already allow `not_evaluated` under provisional — keep that; after PASS, provisional flag clears on new packages.

---

## 7. API (v1)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/dcs/pilot-gates/master/` | 12 defs + UC map |
| `POST` | `/api/v1/dcs/pilot-gates/evaluate/` | On-demand eval |
| `GET` | `/api/v1/dcs/pilot-gates/latest/` | Latest bundle |
| `GET` | `/api/v1/dcs/pilots/{use_case_id}/readiness/` | Optional convenience |

**POST evaluate** body:

```json
{
  "use_case_ids": ["UC-02"],
  "check_ids": null,
  "data_run_id": null,
  "erp_in_scope": false
}
```

- `use_case_ids` → union of gates for those UCs  
- `check_ids` → exact subset of the 12  
- both null → all 12  
- default snapshot = latest **succeeded** DCS score run  

**Roles:** Admin (+ Analyst) evaluate; Viewer read latest.  

**Response:** `results[]` + `readiness[]` with `supplemental_ready` + `blocked_by[]`.

Optional hook: after DCS score complete, enqueue evaluate-all — **not required** for v1.

---

## 8. Frontend (light)

| Surface | Change |
|---------|--------|
| Opportunities / Studio | Show supplemental blockers from recommendation `blockers` / `supplemental_status` when FAIL |
| Studio provisional banner | Keep when `ready_provisional`; when `ready`, drop provisional copy |
| CTA (slice C) | “Evaluate pilot gates” → POST evaluate → refresh recommendations |

No Data Center score-tile pollution.

---

## 9. Executors (build notes)

Same contract as DCS-04: read-only vs snapshot; missing → `UNKNOWN` + `MISSING_INPUT`; ERP out of scope → `NOT_CONNECTED` for BR-09 / PT-06.

| Priority | IDs | Notes |
|----------|-----|--------|
| **A** | CI-08, CC-06 | UC-02 — email validity + DOI integrity (Catalogue 02) |
| **B** | SP-10, PT-13, LE-07, … | Rest of sheet 11 |

Detection: paraphrase Catalogue **02** + sheet **11** Detection Logic. Thresholds: start measurable; `STOP_AND_FLAG` if contested.  
Long per-check appendix remains in the archive FUTURE PRD §8 if needed — do not duplicate walls of text here.

---

## 10. Acceptance

- [x] Static 12 IDs match pack + `SUPPLEMENTAL_PREFLIGHT_CHECKS`  
- [x] Evaluate does not change headline score / 42 worklist  
- [x] UC-02: after CI-08+CC-06 PASS (+ hard CC-03 etc.) → recommendation **`ready`**, `provisional_supplemental=false`  
- [x] Supplemental FAIL → `blocked_checks`, Generate locked  
- [x] Unevaluated still → `ready_provisional` (regression)  
- [x] ERP-out checks degrade honestly  
- [x] Tests: isolation from assemble; recommend merge; evaluate API  
- [x] Verify script: `scripts/verify_dcs09_backend.py` (optional but preferred)

---

## 11. Explicitly next

| Later | Why |
|-------|-----|
| **E2E-01** | Loom + M2 submission after Ready path works |
| Fix/writeback for supplemental IDs | Engineering / later — download + human fix OK for M2 |
| Auto-eval after every DCS | Convenience |
| HO-02 | MCP Send |

---

## 12. PR title / branch

- Branch: `feature/dcs-09-pilot-supplemental-gates`  
- Title: `feat(DCS-09): pilot supplemental gates + recommend Ready (UC-02 first)`  
- Manual checklist: [DCS_09_WORKING_GAPS.md](./DCS_09_WORKING_GAPS.md) §Step 13  

---

## 13. Traceability

| Item | Note |
|------|------|
| Milestone | M2 — hard-green Build readiness before T2 claim |
| Pack | BL-003 · sheet 11 · sheet 02 · pilot_manifest |
| Parents | WF-01 §3.2 · UC-01 recommend · DCS-04 executors |
| Independent of | HO-02 · CAP-01B · Engineering WB catalogue wave |
