# PRD-POLISH-01 — Fix / shell / notifications harden + audit DB immutability

**Status:** Ready for implementation — **P0 polish after WB-04/06**  
**Owner track:** Engineering  — **BE + FE**  
**Surfaces:** Fix · Settings writebacks · Notifications bell · Spotlight · Activity · `audit_logs` (Postgres) · possible sheet honesty  
**Depends on:** AUDIT-01 · AUDIT-02 · WB-03 · WB-04 · WB-06 · FE-13  
**Out of scope:** Engineering HO-01 / CAP-01 / Studio · new Catalogue writeback mappings (CI-03/SP-01/LE-01…) · MCP discovery evidence · Shopify metafield execute · full `capability_record` Matrix import · email prefs product · blockchain / external audit anchor  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-POLISH-01 — Fix/shell/notifications polish + Postgres audit immutability.

Read:
- docs/engineering/PRD_POLISH_01_FIX_SHELL_AUDIT_IMMUTABLE.md
- docs/engineering/PRD_AUDIT_01_GOVERNANCE_ACTIVITY.md (§8 integrity)
- docs/engineering/PRD_AUDIT_02_AUDIT_NOTIFICATIONS.md (audit_read not in hash)
- dataruns/audit.py · dataruns/models.py AuditLog
- frontend: fix.tsx · settings.tsx · AppShell.tsx · NotificationsPanel.tsx · SpotlightSearch.tsx

Ship (one PR OK if FE+BE together):
1. Postgres migration-only: trigger + function — immutable audit columns auto-REVERT on UPDATE; DELETE forbidden; audit_read still mutable (§2).
2. Tests + staging Loom for immutability (§2.4–2.5).
3. FE/BE polish checklist §3 (P0 then P1).
4. Pack honesty: possible-sheet / Fix copy not “sandbox_only” when Settings toggle is SoT (§4).

Acceptance: §6.
```

---

## 1. Why

WB-04/06 + FE #39 shipped Fix writebacks. Demo/staging still shows:

- Native browser `confirm` on rollback (Integrations already uses themed `AlertDialog`)
- Bell errors look like “all caught up”
- Writeback load/error → false “No automated writeback yet”
- Settings Allow writebacks looks ON before Save
- Execute denials collapse to “Writebacks are disabled.”
- False `writeback.executed` audits when zero rows wrote
- Spotlight deep-links lag FE-13
- Possible sheet still says `sandbox_only` after Settings gate became SoT

AUDIT-01 shipped hash chain + `verify_audit_chain` (detect only). Contract gap: a DBA/`UPDATE` on `audit_logs` can alter rows and leave a broken chain with **no automatic restore**. This PRD closes that with a **Postgres function + trigger via Django migration only** (no app-layer cron “revert”).

---

## 2. Audit immutability — Postgres (migration only)

### 2.1 Product rule

| Operation | Rule |
|-----------|------|
| `INSERT` | Allowed (append via `append_audit_event`) |
| `UPDATE` of `audit_read` only | Allowed (AUDIT-02 mark-read) |
| `UPDATE` of any other column | **Auto-revert** those columns to `OLD` (row stays as before tamper) |
| `DELETE` | **Forbidden** — `RAISE EXCEPTION` (cannot reconstruct deleted rows from hash alone) |

Hash fields (`prev_hash`, `entry_hash`) are immutable like payload fields. If an attacker changes `summary` / `metadata` / hashes, the trigger **reverts** protected columns to `OLD` before the update commits. Mark-read still works.

Do **not** implement revert in Python Celery. Do **not** require `verify_audit_chain` to rewrite rows. Detection command stays; DB enforces.

### 2.2 Migration deliverable

One Django migration under `dataruns/migrations/` that runs **raw SQL** (`migrations.RunSQL` with reverse SQL):

1. **Function** e.g. `audit_logs_enforce_immutability()`  
   - Language: `plpgsql`  
   - `BEFORE UPDATE ON audit_logs FOR EACH ROW`  
   - If any protected column differs (`id`, `company_id`, `run_id`, `action`, `tone`, `summary`, `performed_by`, `actor_user_id`, `metadata`, `prev_hash`, `entry_hash`, `created_at`): set `NEW.<col> = OLD.<col>` for each protected column  
   - Always allow `NEW.audit_read` (and only that mutable flag)  
   - Optionally `RAISE NOTICE` / log when a revert happened (do not fail the transaction on UPDATE-of-payload — **revert**, don’t error, so careless SQL “succeeds” but leaves row unchanged)  
   - Locked alternative (also acceptable if documented): `RAISE EXCEPTION 'audit_logs is append-only'` when protected columns change — prefer **revert** per product ask  

2. **Function** e.g. `audit_logs_forbid_delete()`  
   - `BEFORE DELETE ON audit_logs FOR EACH ROW`  
   - `RAISE EXCEPTION 'audit_logs rows cannot be deleted'`  

3. **Triggers** bound to table `audit_logs` (confirm actual DB table name from model `Meta.db_table`).

4. **Reverse migration:** `DROP TRIGGER` + `DROP FUNCTION`.

Use `IF NOT EXISTS` / idempotent patterns where Postgres version allows, or drop-then-create in forward SQL.

### 2.3 Explicit non-goals (immutability)

- No blockchain / external anchor  
- No shadow history table in this PRD  
- No revoke of superuser who `DISABLE TRIGGER` / drop function (document residual risk in Loom notes)  
- No change to `compute_entry_hash` inputs (`audit_read` stays out of hash)

### 2.4 Tests (required)

Django tests (TransactionTestCase or similar so triggers fire):

| Case | Expect |
|------|--------|
| Append two events | Chain links; `verify_audit_chain` clean |
| `UPDATE audit_logs SET audit_read=true` | Persists; hash unchanged; verify still clean |
| `UPDATE … SET summary='tampered'` | Row `summary` **unchanged** after statement (reverted) |
| `UPDATE … SET entry_hash='0'*64` | `entry_hash` **unchanged** (reverted) |
| `DELETE FROM audit_logs WHERE id=…` | Raises / fails; row still present |
| Mark-read API | Still 200; `audit_read=true` |

Also keep existing `test_audit.py` green.

### 2.5 Loom (required — immutability slice)

Short staging Loom (~2–3 min):

1. App: open Activity / bell → mark one unread → shows read (proves `audit_read` allowed).  
2. Shell/psql (or `manage.py dbshell`): show `SELECT id, summary, entry_hash FROM audit_logs … LIMIT 1`.  
3. Attempt `UPDATE audit_logs SET summary = 'hacked' WHERE id = …;` then re-`SELECT` — summary **unchanged**.  
4. Attempt `DELETE` — error; row remains.  
5. Voiceover: “Hash chain + Postgres trigger; mark-read still works; payload cannot stick.”

Link Loom in PR description.

---

## 3. Polish checklist (same PR)

### 3.1 P0 — must ship

| # | Item | Where | Fix |
|---|------|--------|-----|
| P0-1 | Bell errors look like “all caught up” | `AppShell` · `NotificationsPanel` | Pass `isError`; empty success copy only when fetch OK; show retry |
| P0-2 | Writeback load/error → “not available” | `fix.tsx` · `writebacks.ts` | Keep pending as unknown; on error show retry — don’t coerce to empty sheet honesty |
| P0-3 | Allow writebacks toggle looks saved | `settings.tsx` | Persist on toggle **or** clear dirty/Save-required affordance + leave warning |
| P0-4 | False `writeback.executed` audit | `pipeline.py` `_audit` | Emit `writeback.executed` only when `executed > 0`; else failed/denied action + RISK tone |
| P0-5 | All denials → “Writebacks are disabled.” | `writebacks/views.py` | Map `blocked_reason` to accurate `detail` + status |

### 3.2 P1 — same PR if time; else follow-up commit on same branch

| # | Item | Where | Fix |
|---|------|--------|-----|
| P1-1 | Native `window.confirm` on rollback | `fix.tsx` | Themed `AlertDialog` (match Integrations disconnect) |
| P1-2 | Spotlight issue/audit hrefs | `dataruns/search.py` | Issues → `/fix?issue=`; audits → `resolve_audit_href` |
| P1-3 | Spotlight drops `#hash` | `SpotlightSearch.tsx` | Preserve hash in navigate |
| P1-4 | Unread rows look like read | `NotificationsPanel` | Visual unread (dot / weight) |
| P1-5 | Verify-email Resend fake | `verify.tsx` | Wire real resend **or** remove dishonest CTA (no fake toast) |
| P1-6 | Spotlight “QA/Handoff soon” when unlocked | `SpotlightSearch` | Match shell honesty |

### 3.3 P2 — optional / defer

Team invite admin-gate · revoke confirm · themed `<select>` · silent mark-read toast · once-per-run atomic claim-before-write (separate hardening PRD if large).

---

## 4. Pack honesty (Engineering slice only)

| Item | Action |
|------|--------|
| `WRITEBACK_POSSIBLE_NOT_SHEET.csv` `write_possible_today=sandbox_only` | Align wording with Settings company gate (e.g. `company_gated` / note in `evidence_note`) — **both** runtime CSV under `dataruns/writebacks/` and docs copy if duplicated |
| Fix / trust copy claiming “sandbox only” when toggle is SoT | Honest: “Writebacks follow workspace Allow writebacks” |
| Do **not** enable new Catalogue Automated writeback rows | Coverage debt stays stubs (CI-03, SP-01, LE-01, …) |
| Do **not** invent Matrix MCP CONFIRMED without evidence | Keep `capabilities.json` as-is unless fixing a false overclaim |

---

## 5. Files (expected)

| Area | Files |
|------|--------|
| Migration | `dataruns/migrations/00xx_audit_logs_immutability_triggers.py` (+ SQL) |
| Tests | `dataruns/tests/test_audit_immutability.py` (new) · extend `test_audit.py` if needed |
| Writeback honesty | `dataruns/writebacks/pipeline.py` · `views.py` · possible sheet CSV |
| Search | `dataruns/search.py` |
| FE | `fix.tsx` · `settings.tsx` · `AppShell.tsx` · `NotificationsPanel.tsx` · `SpotlightSearch.tsx` · `verify.tsx` (if P1-5) · `writebacks.ts` |

---

## 6. Acceptance

### Immutability
- [ ] Migration applies cleanly; reverse drops triggers/functions  
- [ ] Mark-read API + FE bell still work  
- [ ] SQL `UPDATE` of `summary` / `entry_hash` does not persist (reverted)  
- [ ] SQL `DELETE` fails; row remains  
- [ ] `verify_audit_chain` still passes on healthy company after mark-read  
- [ ] Loom linked in PR (§2.5)

### Polish
- [ ] P0-1…P0-5 done  
- [ ] P1-1 (themed rollback confirm) done  
- [ ] P1-2…P1-4 done or explicitly listed under Gaps in PR with ticket  
- [ ] Pack sheet / Fix copy no longer mislabel Settings-gated writes as sandbox-only theater  

### Regression
- [ ] Existing audit + writeback tests green  
- [ ] Approve / rollback / 409 once-per-run still work on staging smoke  

---

## 7. Explicitly next (not this PRD)

| Later | Why |
|-------|-----|
| Atomic WB-04 claim-before-adapter-write | Race hardening — larger than polish |
| Mask `entity_key` PII in writeback serialize | WB-01 residual |
| CAP-01 / Matrix resolver | Engineering (+ shared) |
| HO-01 FE live `/handoff` | Engineering |
| Celery periodic `verify_audit_chain` | AUDIT-01 v1.1 detect (optional after triggers) |
| New writeback mappings wave | Pack Catalogue coverage |

---

## 8. PR title / branch

- Branch: `fix/polish-01-shell-audit-immutable`  
- Title: `fix(POLISH-01): audit DB immutability + Fix/shell/notifications harden`

---

## 9. Traceability

| Item | Note |
|------|------|
| Parents | AUDIT-01 §8 · AUDIT-02 · WB-03/04/06 · FE-13 |
| Pack | Append-only governance; stop-and-flag honesty; Settings gate ≠ invent Matrix |
| Milestone | M2 polish / demo honesty — not a new feature track |
| Independent of | Engineering HO-01 FE · CAP-01 |
