# PRD-WB-04 — Once-per-DCS-run writeback gate

**Status:** Ready for implementation — **P0 (M2 Fix honesty)**  
**Owner track:** Engineering  — **BE + FE**  
**Surfaces:** Fix `/fix?issue=<check_id>` · `POST /api/v1/writebacks/run/` (execute) · Activity (existing audits)  
**Depends on:** WB-02 · WB-03 (Settings `writeback_execute_enabled` + allowlist CI-01 / CC-03 / WB-SHOP-01)  
**Pairs with:** [PRD_WB_06](./PRD_WB_06_FIX_WRITEBACK_PROVENANCE.md) (persist `data_run_id` + restore Written UI — ship **with or immediately after** this PR)  
**Out of scope:** Engineering Studio / QA / Handoff · new check mappings · LE-04 enable · BL-017 8-state ORCH machine · changing Settings toggle UX · inventing banked €  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-04 — once-per-DCS-run writeback gate.

Read:
- docs/engineering/PRD_WB_04_ONCE_PER_DCS_RUN_WRITEBACK_GATE.md
- docs/engineering/PRD_WB_06_FIX_WRITEBACK_PROVENANCE.md (fields + GET; do not skip)
- dataruns/writebacks/pipeline.py, gates.py
- dataruns/models.py WritebackJob
- frontend src/routes/fix.tsx (written / canApprove)

Ship:
1. On execute success: persist dcs data_run_id on WritebackJob (§3).
2. Gate: block execute if a successful execute already exists for
   (company, check_id, same latest terminal DCS data_run_id) (§4).
3. Unlock only when a NEWER terminal DCS run exists (or prior execute
   was rolled back — §4.2).
4. FE: disable Approve + honest copy when gated; survive page refresh (§5).
5. Tests for gate + unlock (§7).

Do NOT touch Studio, QA, or Handoff. No new mappings.

Acceptance: §8.
```

---

## 1. Why

Today Fix `written` is **React session state only**. Refresh → Approve is available again. Backend does not bind execute to the DCS run that produced the issue. Operators (and demos) can re-write the same check repeatedly on the same score.

**Product rule (M2):**

```text
One successful writeback execute per (company, check_id, DCS data_run)
until a newer DCS score exists (or rollback clears the gate).
```

---

## 2. Vocabulary

| Term | Meaning |
|------|---------|
| **Latest terminal DCS run** | Newest succeeded/failed-complete score `DataRun` used for worklist (same helper as writeback preflight / worklist) |
| **data_run_id** | Integer PK of that `DataRun` |
| **Successful execute** | `WritebackJob` with `mode=execute` (or equivalent) and status indicating executed/partial-with-writes — **not** preview |
| **Gate locked** | Execute denied with stable error code; FE Approve disabled |

---

## 3. Persist run binding (minimum for the gate)

Extend `WritebackJob` (or execute metadata — prefer first-class column):

| Field | Type | When set |
|-------|------|----------|
| `dcs_data_run_id` | `IntegerField` null=True | On **preview** and **execute** create: current latest terminal DCS `DataRun.id` for the company |
| (optional) `rolled_back_at` | datetime null | Set when rollback succeeds for this execute job |

Index: `(company_id, check_id, dcs_data_run_id, mode, -created_at)`.

Preview may store the id for diagnostics; **gate uses successful execute jobs only**.

Full GET/provenance UI → **WB-06**. This PR must at least **write** `dcs_data_run_id` on execute.

---

## 4. Execute gate (backend)

### 4.1 When blocking

Before running execute (after company flag / allowlist / approval / diff_hash checks):

```text
latest = get_latest_terminal_dcs_run(company)
IF latest is None → existing preflight behavior (no invent)

IF exists WritebackJob WHERE
  company = company
  AND check_id = check_id (normalized upper)
  AND mode = execute
  AND status IN successful execute statuses
  AND dcs_data_run_id = latest.id
  AND NOT rolled back (§4.2)
THEN
  raise / return 409 with code writeback_already_executed_for_run
```

Response shape (match existing writeback errors):

```json
{
  "detail": "Writeback already executed for this check on the current Data Consistency Score. Re-run the score if the issue appears again.",
  "code": "writeback_already_executed_for_run",
  "check_id": "CC-03",
  "data_run_id": 128,
  "execute_job_id": "<uuid>"
}
```

### 4.2 Unlock conditions

| Event | Effect |
|-------|--------|
| **New terminal DCS run** with `id >` prior execute’s `dcs_data_run_id` (or different id that is now “latest”) | Gate opens for that check on the new run |
| **Successful rollback** of the execute job that held the gate | Gate opens for same run (re-Approve allowed after fresh preview) |
| Preview-only / failed execute / zero `executed` count | Does **not** lock the gate |

Do **not** unlock merely because evidence rows still look dirty after a successful write — force **re-score** (or rollback) so DCS is source of truth.

### 4.3 Diff hash / approval tokens

Unchanged: still require fresh preview + approval + matching `diff_hash`. Gate is an **additional** check, not a replacement.

### 4.4 Idempotency vs gate

Adapter chunk idempotency keys remain `{company}:{check}:{diff_hash}:{chunk}`.  
Gate is **product** “already done for this score,” even if a new preview produces a new `diff_hash`.

---

## 5. Frontend (Fix)

| State | UI |
|-------|-----|
| Gate locked (API or WB-06 status) | Approve **disabled**; copy: “Already written on this score · Re-run Data Consistency Score if the issue returns” |
| After successful execute this session | Keep Written trust step (existing) |
| Page refresh while gated | Must still show locked / Written — **requires WB-06 status endpoint**; if WB-06 not merged yet, at minimum call execute and show 409 toast honestly |

Block reason enum (extend `writebacks.ts`):

```text
already_executed_for_run
```

Map `writeback_already_executed_for_run` / 409 into that reason.

---

## 6. Checks in scope

Same allowlist as WB-03: **CI-01**, **CC-03**, **WB-SHOP-01**.  
Gate logic is generic for any future allowlisted check_id.

---

## 7. Tests

| Case | Expect |
|------|--------|
| Execute once for CC-03 on run 100 | 200/201 executed; job has `dcs_data_run_id=100` |
| Second execute same check, still latest=100 | **409** `writeback_already_executed_for_run` |
| New DCS run 101 is latest; execute again | Allowed (other gates pass) |
| Rollback execute on run 100; execute again on 100 | Allowed |
| Preview does not lock | Second preview OK; execute still gated only after success |
| Company flag OFF | Existing disable still wins (not this code path) |

---

## 8. Acceptance

- [ ] Successful execute stores `dcs_data_run_id`  
- [ ] Second execute for same check + same latest run → **409** + stable code  
- [ ] Newer DCS run unlocks  
- [ ] Rollback unlocks same run  
- [ ] FE Approve disabled / honest when gated (with WB-06 or interim 409 handling)  
- [ ] No Studio / QA / Handoff code changes  
- [ ] Unit/API tests for §7  

---

## 9. PR title / branch

- Branch: `feature/wb-04-once-per-dcs-run-writeback-gate`  
- Title: `feat(WB-04): gate writeback execute once per check per DCS run`

---

## 10. Traceability

| Item | Note |
|------|------|
| Milestone | M2 Activation — Fix writeback honesty |
| Parents | WB-02 · WB-03 |
| Companion | WB-06 provenance / Fix restore |
| Independent of | Engineering HO-01 · CAP-01 · QA-01 |
