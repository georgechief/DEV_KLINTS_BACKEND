# PRD-WB-06 — Fix writeback provenance (persist run · restore Written UI)

**Status:** Ready for implementation — **P0 companion to WB-04**  
**Owner track:** Engineering  — **BE + FE**  
**Surfaces:** Fix `/fix` · `GET` writeback status API · Activity deep-link  
**Depends on:** WB-02 · WB-03 · **WB-04** (gate + `dcs_data_run_id` on execute — may land as one combined PR if preferred)  
**Out of scope:** Engineering Studio / QA / Handoff · new mappings · LE-04 · inventing banked revenue · full BL-017 ORCH SM  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-06 — Fix writeback provenance + restore Written on reload.

Read:
- docs/engineering/PRD_WB_06_FIX_WRITEBACK_PROVENANCE.md
- docs/engineering/PRD_WB_04_ONCE_PER_DCS_RUN_WRITEBACK_GATE.md
- dataruns/models.py WritebackJob
- frontend src/routes/fix.tsx (written / executeResult / Approve)

Ship:
1. Ensure execute jobs store dcs_data_run_id (+ rolled_back_at if WB-04).
2. GET latest writeback status for company + check_id (+ optional data_run_id) (§3).
3. FE on Fix load: if executed for current score and not rolled back →
   restore Written UI (trust steps, disable Approve) (§4).
4. Show provenance line: check · run id · job id · link to Activity (§4.2).
5. After rollback: clear Written; allow preview again (§4.3).

Acceptance: §7.
```

---

## 1. Why

WB-04 blocks a second execute on the server. Without provenance:

- Refresh loses `written` / `executeResult` → UI looks unlocked until 409  
- Operators cannot see **which score** was written  
- Activity exists but Fix does not surface “last job”

This PRD makes the gate **visible and durable** on Fix.

---

## 2. Data model (align with WB-04)

On `WritebackJob` (execute rows):

| Field | Required | Notes |
|-------|----------|-------|
| `dcs_data_run_id` | Yes | Latest terminal DCS `DataRun.id` at job create |
| `rolled_back_at` | Yes (nullable) | Set on successful rollback of **this** execute job |
| Existing | — | `id`, `check_id`, `mode`, `status`, `diff_hash`, `summary`, `actor_user`, `created_at` |

Serialize `data_run_id` in API as integer matching worklist `data_run_id`.

---

## 3. Backend API

### 3.1 Latest status for Fix

```http
GET /api/v1/writebacks/status/?check_id=CC-03
Authorization: Bearer …
```

Optional query: `data_run_id=` — default = company’s latest terminal DCS run.

**200 example:**

```json
{
  "check_id": "CC-03",
  "data_run_id": 128,
  "gate": "locked",
  "latest_execute": {
    "job_id": "a1b2c3d4-…",
    "status": "executed",
    "diff_hash": "…",
    "summary": { "executed": 3, "skipped": 0, "errors": 0 },
    "created_at": "2026-08-24T03:10:00Z",
    "rolled_back_at": null,
    "actor_email": "rohan1@mailinator.com"
  },
  "latest_preview": {
    "job_id": "…",
    "created_at": "…"
  }
}
```

| `gate` | Meaning |
|--------|---------|
| `open` | No successful non-rolled-back execute for this check on this `data_run_id` |
| `locked` | Successful execute exists → Approve must stay off |
| `rolled_back` | Last execute for this run was rolled back → open for new preview/approve |

**404** only if check_id invalid format; empty execute → `gate: open`, `latest_execute: null`.

Roles: same as Fix read (Admin / Analyst / Viewer read-only status).

### 3.2 Execute / rollback responses

Include `data_run_id` on execute success payload (and keep `job_id`) so FE can set state without an extra GET.

### 3.3 Audit

Reuse existing `writeback.executed` / `writeback.rollback`. Prefer payload includes `data_run_id` when missing (small enrichment OK).

---

## 4. Frontend — Fix

### 4.1 On issue load

When `writebackCheckId` is set and mappings allow writeback:

1. `GET …/writebacks/status/?check_id=…`  
2. If `gate === "locked"` and `latest_execute`:  
   - Set `written = true`  
   - Hydrate `executeResult` enough for trust steps + Rollback (job_id, summary, check_id, diff_hash if present)  
   - Disable Approve  
3. If `gate === "open"` or `rolled_back`: existing preview → Approve flow  

Do **not** depend only on React state after refresh.

### 4.2 Provenance strip (honest, minimal)

Near writeback trust / Current State:

```text
Written on DCS run #<data_run_id> · job <short uuid>
[View in Activity]
```

Activity link: existing audit deep-link patterns (FE-13) filtered or scrolled to writeback events when possible; else `/activity`.

### 4.3 Rollback

On successful rollback mutation:

- Clear Written / enable preview again  
- Refetch status (`gate` → `rolled_back` or `open`)  
- Toast unchanged honesty from WB-02  

### 4.4 Error mapping

| API | FE |
|-----|-----|
| 409 `writeback_already_executed_for_run` | Toast + set locked from status refetch |
| Status `locked` | `already_executed_for_run` block reason |

---

## 5. Interaction with WB-04

| Concern | Owner |
|---------|--------|
| Deny second execute | WB-04 |
| Store `dcs_data_run_id` | WB-04 (required) / verified here |
| GET status + Fix hydrate | **This PRD** |
| Combined PR allowed | Yes — title must list **WB-04 + WB-06** |

---

## 6. Tests

| Case | Expect |
|------|--------|
| GET status after execute | `gate=locked`, job id present, `data_run_id` set |
| GET after rollback | `gate` open or `rolled_back`; Approve path available |
| GET with no jobs | `gate=open`, null execute |
| FE unit/hook (optional) | Hydrate written from status fixture |

---

## 7. Acceptance

- [ ] Execute jobs expose `data_run_id`  
- [ ] `GET /writebacks/status/` returns gate + latest execute  
- [ ] Fix reload shows Written / Approve disabled when locked  
- [ ] Provenance line shows run id + job + Activity affordance  
- [ ] Rollback clears Written and unlocks preview/Approve  
- [ ] No Studio / QA / Handoff changes  

---

## 8. PR title / branch

- Branch: `feature/wb-06-fix-writeback-provenance`  
- Title: `feat(WB-06): writeback status API + restore Written on Fix reload`  
- Or combined: `feat(WB-04+WB-06): once-per-run gate + Fix provenance`

---

## 9. Traceability

| Item | Note |
|------|------|
| Milestone | M2 — Fix writeback honesty |
| Parents | WB-02 · WB-03 · WB-04 |
| Independent of | Engineering HO-01 · CAP-01 · QA |
| Related FE | FE-13 Activity deep-links (reuse, don’t redesign) |
