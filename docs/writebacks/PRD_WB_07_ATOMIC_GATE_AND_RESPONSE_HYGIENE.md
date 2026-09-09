# PRD-WB-07 — Atomic once-per-run gate + writeback response hygiene

**Status:** Ready for implementation — **P0 (M2 Fix harden)** after POLISH-01  
**Owner track:** Engineering  — **BE primary · FE only if Entity column needs masked display**  
**Surfaces:** `POST /api/v1/writebacks/run/` (execute) · `WritebackJob` create order · serialize intents · Fix preview Entity column  
**Depends on:** WB-04 · WB-06 · POLISH-01 (honest denial copy + executed audit already fixed)  
**Out of scope:** Engineering CAP-01 / Studio / QA / Handoff · new Catalogue mappings · LE-04 · Shopify metafield execute · Celery audit verify · changing Settings toggle UX · inventing banked revenue  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-07 — atomic WB-04 gate + writeback PII / error hygiene.

Read:
- docs/engineering/PRD_WB_07_ATOMIC_GATE_AND_RESPONSE_HYGIENE.md
- docs/engineering/PRD_WB_04_ONCE_PER_DCS_RUN_WRITEBACK_GATE.md
- dataruns/writebacks/pipeline.py (check gate → _execute_intents → then WritebackJob.create — RACE)
- dataruns/writebacks/run_gate.py
- dataruns/writebacks/serializers.py (full entity_key today)
- dataruns/writebacks/pii.py (mask_entity_key unused)
- dataruns/writebacks/views.py (diff_hash 409 returns expected/actual)

Ship:
1. Claim execute job + lock BEFORE adapter I/O; re-check gate under lock; consume approval at claim (§3).
2. Block execute when no terminal DCS run (dcs_data_run_id null) — no unlimited writes (§3.4).
3. Mask entity_key (+ email-like before/after) in API serialize via pii.mask_* (§4).
4. Stop leaking adapter str(exc) / diff hashes to clients (§5).
5. Tests for concurrent double-Approve + mask + error codes (§7).
6. FE: Entity column shows masked keys; still usable (§6).

Acceptance: §8. Do not touch Studio/QA/Handoff.
```

---

## 1. Why

WB-04/06 + POLISH-01 made the gate **visible** and denials **honest**. Two hard faults remain:

### 1.1 Race (P0)

Current execute order in `pipeline.py`:

```text
check_execute_run_gate  →  _execute_intents (live Manago/Shopify writes)  →  WritebackJob.objects.create
```

Two concurrent Approves (or crash between write and job create) can **double-write** the same check on the same DCS run. Approval is validated early and **consumed after** write — pairs with the race.

### 1.2 Response hygiene (P0)

| Issue | Today |
|-------|--------|
| `serialize_intent` | Returns **full** `entity_key` (emails); `pii.mask_entity_key` is **dead** — contradicts WB-01 “mask in API” |
| Adapter / rollback errors | `str(exc)` / platform bodies can land in `execute_result` / API `detail` |
| DiffHashMismatch 409 | Returns `expected` + `actual` hashes (oracle / debug leak) |

---

## 2. Product rules

```text
1. At most one in-flight or successful execute claim per
   (company, check_id, dcs_data_run_id) until rollback or newer terminal DCS run.
2. Adapter I/O never starts until the claim row exists under a DB lock.
3. API responses never return raw emails / full entity keys or platform exception strings.
4. No terminal DCS run ⇒ execute denied (stable code) — do not leave gate wide open.
```

---

## 3. Atomic claim-before-write

### 3.1 Target order

```text
resolve dcs_data_run_id
  → if null: deny execute (code: dcs_run_required) — §3.4
transaction.atomic:
  lock (company + check_id + data_run_id)   # select_for_update claim row or advisory
  re-check find_blocking_execute_job / in-flight claim
  if blocked → raise WritebackAlreadyExecutedForRunError (409)
  create WritebackJob status=executing (or equivalent) with dcs_data_run_id, diff_hash, intents preview snapshot
  consume_approval_token (if approval_id) under same lock — fail closed if already consumed
THEN (still preferably inside same atomic only for DB; adapter I/O may be outside after claim committed):
  _execute_intents …
  update same job → executed | partial | failed + summary
```

**Locked semantics:**

| Phase | Gate behavior for second Approve |
|-------|----------------------------------|
| Claim `executing` exists, not rolled back | **409** same as successful execute (`writeback_already_executed_for_run` **or** new code `writeback_execute_in_flight` — pick one; prefer **same 409 code** so FE Written UX stays simple) |
| Job `executed`/`partial` with `executed > 0` | 409 (existing WB-04) |
| Job `failed` with `executed == 0` | Gate **open** (allow retry) — mark clearly; do not treat as successful |
| `rolled_back_at` set | Gate open |

### 3.2 Lock mechanism (implementation choice — document in PR)

Pick **one** and test it:

| Option | Approach |
|--------|----------|
| **A (preferred)** | `select_for_update()` on a per-company “gate row” or the latest blocking/`executing` `WritebackJob`; create `executing` job before release |
| **B** | Postgres advisory lock `hashtext(company_id || check_id || data_run_id)` inside `atomic` |
| **C** | Partial **UniqueConstraint** on `(company, check_id, dcs_data_run_id)` where `mode in execute modes AND rolled_back_at IS NULL AND status = 'executing'` plus unique successful path — harder with failed retries; use with care |

Minimum: **no adapter call** before an `executing` (or successful) job row is visible to concurrent transactions.

### 3.3 Job status

Extend `WritebackJob.status` (or reuse existing) so FE/status API can show in-flight:

| Status | Meaning |
|--------|---------|
| `executing` | Claimed; adapter running or about to run |
| `executed` / `partial` / `failed` | Terminal (existing) |

`is_successful_execute_job` stays **`executed > 0` only**.  
`find_blocking_execute_job` must also treat **`status=executing`** (same company/check/run, not rolled back) as blocking.

### 3.4 No DCS run ⇒ deny

Today `dcs_data_run_id is None` → gate never locks → unlimited executes.

**v1 lock:** If `resolve_latest_dcs_data_run_id` is `None`, execute returns **409 or 403** with:

```json
{
  "detail": "Run a Data Consistency Score before approving writebacks.",
  "code": "dcs_run_required",
  "action": "execute"
}
```

Preview may still run if product already allows it without a score — do **not** change preview unless needed; this rule is for **execute** only.

### 3.5 Crash / orphan `executing`

If worker dies after claim:

| Policy (v1) | |
|-------------|---|
| Stale `executing` older than **N minutes** (default **15**, settings knob OK) | Treat as failed / clearable — allow new claim **or** admin-only rollback of claim; document choice |
| Prefer | On next execute attempt: if stale executing → mark `failed` with `executed=0` + audit `writeback.execute_failed` reason `stale_executing_reclaimed`, then proceed with new claim |

Do not leave eternal locks.

### 3.6 Approval consume

Move `consume_approval_token` to **claim time** (under lock), before adapter I/O.  
If adapter later writes 0 rows → job `failed`; token already consumed (operator must re-preview/approve) — acceptable; document in Fix copy if needed.

---

## 4. PII masking in API

### 4.1 Wire dead helpers

Use `dataruns/writebacks/pii.py`:

- `serialize_intent`: `entity_key` → `mask_entity_key(...)`  
- Recursively mask email-shaped strings in `before` / `after` / `execute_result` **returned to clients** (keep full values only in server logs if needed — never in AuditLog metadata if emails appear; audit already sanitizes secrets)

### 4.2 Evidence download / Fix match

| Surface | Rule |
|---------|------|
| REST preview/execute JSON | **Masked** |
| Evidence CSV/Excel download | **Masked** in v1 (same mask) — operators still correlate via masked local-part + domain; if product insists on full email in file, Admin-only + audit — **default = mask** |
| Fix Entity column | Show masked `entity_key` from API (no client-side unmask) |

Update the comment in `serializers.py` that currently says full keys are intentional.

### 4.3 Diff hash

`diff_hash` remains full hex (not PII). Do not mask.

---

## 5. Error hygiene

| Case | Client sees | Server |
|------|-------------|--------|
| DiffHashMismatch | `detail`: generic “Preview changed — run preview again.” · `code`: `diff_hash_mismatch` · **no** `expected`/`actual` | Log both hashes |
| Adapter / Manago / Shopify failure | Stable `error_reason` codes on intents (`upstream_error`, `timeout`, …); no raw `str(exc)` in JSON | `logger.exception` with exc |
| Rollback failure | Same — stable detail | Log internals |

Touch: `adapters/manago.py`, `rollback.py`, `views._handle_execute` / `_handle_rollback` as needed.

---

## 6. Frontend (minimal)

| Item | Change |
|------|--------|
| Fix Entity / intent list | Render masked keys from API (should “just work”) |
| In-flight execute | If status API or execute returns in-flight 409, keep Approve disabled + “Write in progress / already applied” |
| Tests / verify scripts | Update any assertions expecting full emails in JSON |

No Studio/Handoff changes.

---

## 7. Tests (required)

| Case | Expect |
|------|--------|
| Two overlapping execute calls (threads or concurrent requests) for same company/check/run | Exactly **one** successful write path; second **409**; adapter mock call count ≤ 1 successful batch |
| Claim then adapter raises | Job `failed` / executed 0; gate open for retry (after claim cleared per §3.5 if still executing) |
| Execute with no terminal DCS run | `dcs_run_required` — no adapter call |
| Serialize preview with email entity_key | Response contains masked form (`a***@…`), not full local part |
| DiffHashMismatch | 409 without `expected`/`actual` keys |
| Existing WB-04/06 / POLISH-01 tests | Still green |
| Rollback after success | Clears gate (existing) |

Optional: `scripts/verify_wb07_backend.py` for smoke.

---

## 8. Acceptance

- [ ] Execute path claims `WritebackJob` **before** adapter I/O  
- [ ] Concurrent double-Approve cannot double-write  
- [ ] `executing` blocks second Approve; successful execute still blocks; failed 0-write does not  
- [ ] No terminal DCS run → execute denied with `dcs_run_required`  
- [ ] Stale `executing` policy implemented + tested  
- [ ] Approval consumed at claim (not after write)  
- [ ] API intents use `mask_entity_key` / masked emails  
- [ ] No `expected`/`actual` hash fields on 409; no raw platform `str(exc)` in client JSON  
- [ ] CI-01 / CC-03 / WB-SHOP-01 happy path + rollback still work  
- [ ] FE Entity column readable with masks  

---

## 9. Explicitly next (not this PRD)

| Later | Why |
|-------|-----|
| New Catalogue mappings wave | Pack coverage (CI-03, SP-01, LE-01…) |
| Unify writeback caps with Engineering CAP-01 registry | Shared Matrix |
| Celery `verify_audit_chain` | AUDIT v1.1 |
| Prefer Shopify metafield over native note | Surface matrix residual |

---

## 10. PR title / branch

- Branch: `fix/wb-07-atomic-gate-response-hygiene`  
- Title: `fix(WB-07): atomic once-per-run claim + mask writeback PII/errors`

---

## 11. Traceability

| Item | Note |
|------|------|
| Parents | WB-04 · WB-06 · POLISH-01 §7 leftovers · WB-01 mask rule |
| Milestone | M2 Fix harden — demo-safe concurrent Approve |
| Independent of | Engineering CAP-01 · HO-02 |
| Pack | Stop-and-flag; no fabricated writes; PII minimization on API |
