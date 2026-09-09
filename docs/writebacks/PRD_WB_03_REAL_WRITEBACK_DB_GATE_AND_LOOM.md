# PRD-WB-03 — Real writeback via UI gate (default OFF, Fix approve, Loom)

**Status:** Ready for implementation — **P0 follow-up to PR #46**  
**Owner track:** Engineering  — **BE + FE**  
**Surfaces:**  
- **Settings → Workspace** (Admin toggle: enable/disable writebacks for **this** company)  
- Fix `/fix` Approve → real Manago/Shopify write when ON  
- Loom: UI toggle + reflect + rollback for **all** allowlisted checks  
**Depends on:** WB-02 / WB-02B / FE-12 · PR [#46](https://github.com/georgechief/klints_backend/pull/46) (must correct default-ON)  
**Out of scope:** `manage.py` as the operator path · Global `WRITEBACKS_ENABLED=True` for all tenants · LE-04 enable · new mappings · MCP · Workflow Studio · Engineering tracks  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-03 — real writebacks, gated in the PRODUCT UI (not manage.py).

Read:
- docs/engineering/PRD_WB_03_REAL_WRITEBACK_DB_GATE_AND_LOOM.md
- dataruns/writebacks/gates.py
- frontend src/routes/settings.tsx (Workspace section — admin-only edits today)

Ship:
1. DB: writeback execute default OFF; migrate ALL companies → False (§2)
2. BE API: expose flag on company; Admin PATCH to turn ON/OFF (§3)
3. FE Settings → Workspace: Admin toggle “Allow writebacks” (§4) — PRIMARY path
4. Fix UI: when OFF, Approve disabled + honest copy; when ON, real execute (§5)
5. Kill sandbox theater / unused env/commands as primary ops (§6)
6. Sheet sandbox_only → yes; FE drop “sandbox only” copy
7. Loom: toggle ON in Settings → for CI-01, CC-03, WB-SHOP-01 each:
   Approve → show in Manago/Shopify → Rollback → show reversed (§8)

Do NOT tell operators to run manage.py. Commands are emergency-only or delete.

Acceptance: §9.
```

---

## 1. Why

PR [#46](https://github.com/georgechief/klints_backend/pull/46) turned **`writeback_sandbox_enabled=True` for every company** (default + migration). That is unsafe and still framed as “sandbox.”

Product direction:

- **Real writebacks** to the company’s **connected** Manago/Shopify  
- **Default OFF**  
- Operator turns writebacks **ON/OFF in the Klints UI** (Settings) — **not** shell/`manage.py`  
- Same customer Approve flow on Fix  

```text
Settings (Admin)  →  writebacks ON for this workspace
Fix               →  Preview → Approve → real write → Rollback
Manago / Shopify  →  field visible, then reversed after rollback
```

---

## 2. DB (backend)

| Before (PR #46) | After |
|-----------------|--------|
| `writeback_sandbox_enabled` default **True** | Prefer rename → `writeback_execute_enabled` default **False** |
| Migration forced all → True | New migration: **all companies → False** |

Keep `WritebackAllowedCheck` (CI-01, CC-03, WB-SHOP-01).

```text
execute_allowed =
  check allowlisted
  AND company.writeback_execute_enabled == True
  AND Admin for execute
  AND preview / approval / diff_hash OK (as today)
```

Global `WRITEBACKS_ENABLED` may stay False; **company UI flag** is the M2 opt-in.

---

## 3. Backend API (for the UI)

Expose the flag on the **current company** (same auth as Settings workspace).

### 3.1 Read (already on me/company payload if easy)

Include on company JSON returned to the app (e.g. `/api/v1/...` used by Settings / `currentUser.company`):

```json
"writeback_execute_enabled": false
```

(Name must match FE; if keeping legacy column temporarily, serialize as `writeback_execute_enabled` in API.)

### 3.2 Update — Admin only

```http
PATCH /api/v1/company/   # or existing workspace/company update endpoint
Authorization: Bearer …
Content-Type: application/json

{ "writeback_execute_enabled": true }
```

| Rule | |
|------|--|
| Role | **Admin** only (Analyst/Member → 403) |
| Body | boolean `writeback_execute_enabled` |
| Effect | Persists on `Company`; gates Fix Approve execute |
| Audit | Append audit event e.g. `writeback.execute_toggled` with actor + old/new |

Reuse the existing Settings workspace save path if it already PATCHes company name/domain — **extend that same API** rather than inventing a one-off.

### 3.3 Fix / writeback APIs

No manage command required. When flag is False → execute returns blocked (`writebacks_disabled` or `company_execute_disabled`). When True → real `execute` to connected connectors.

---

## 4. Frontend — Settings UI (PRIMARY operator path)

**File:** `src/routes/settings.tsx` · **Workspace** section (already Admin-gated for edits).

### 4.1 Control

Add under Workspace (Admin only):

| UI | Spec |
|----|------|
| Label | **Allow writebacks** |
| Control | Toggle / switch (or checkbox) bound to `writeback_execute_enabled` |
| Helper | “When on, Admins can Approve writebacks on Fix. Writes go to your connected Manago and Shopify accounts.” |
| Off helper | “Writebacks are off. Fix can preview and download evidence; Approve will not write.” |
| Save | Same Workspace **Save** as name/domain **or** immediate toggle with toast — pick one; document in PR. Prefer **explicit Save** if other workspace fields use Save. |
| Non-admin | Toggle hidden or disabled + “Only workspace admins can change this.” |

### 4.2 Honesty

- Do **not** label this “Sandbox mode.”  
- Do **not** say “test account only” unless product later adds a separate badge.  
- Coming-soon / Billing patterns elsewhere stay unchanged.

### 4.3 Load

On Settings load, read flag from company payload. If missing → treat as `false` and still show toggle (fail closed).

---

## 5. Frontend — Fix page

| Flag | Behavior |
|------|----------|
| **OFF** | Approve writeback disabled; copy: writebacks off for this workspace — enable in **Settings → Workspace** (Admin). Preview + Download evidence still OK. |
| **ON** | Existing WB-02 chain: preview → Approve → Written only after execute; Rollback when supported. |
| Copy | Remove “sandbox only” / “Sandbox mapping” for allowlisted checks; use normal honesty. |

Deep-link from Fix disabled reason → `/settings` (optional nice-to-have).

---

## 6. Remove unused / wrong ops paths

| Item | Action |
|------|--------|
| **`manage.py set_writeback_sandbox` as the way to enable** | **Not the product path.** Delete **or** leave as emergency break-glass only — must not appear in Loom / README as how to turn on |
| Env `WRITEBACK_SANDBOX_COMPANY_ID` | Remove if unused after DB+UI |
| Default-True / “sandbox for everyone” | Gone |
| Dual `sandbox_execute` naming | Prefer `execute` when company enabled |
| Sheet `sandbox_only` | → **`yes`** for CI-01, CC-03, WB-SHOP-01 |
| FE “sandbox” strings on Fix | Strip for allowlisted path |

Django admin checkbox is OK as backup for Klints staff; **customer/demo operators use Settings UI.**

---

## 7. Real write + reflect + rollback (all checks)

| check_id | Related account in Loom | After Approve | After Rollback |
|----------|-------------------------|---------------|----------------|
| **CI-01** | **Manago** | upsert / `klints_backfill` visible | reversed |
| **CC-03** | **Manago** | `klints_consent_evidence` visible | reversed |
| **WB-SHOP-01** | **Shopify** admin | customer **note** written | note restored |

WB-SHOP-01: use Fix `?issue=WB-SHOP-01` or documented entry — still must appear in Loom with Shopify UI.  
LE-04: Approve stays off (negative).

---

## 8. Loom — required (UI-first)

Video **must** start from the **product UI**, not a terminal.

### 8.1 Script

**A. Settings (required)**  
1. Login as **Admin** on demo company.  
2. **Settings → Workspace**.  
3. Show **Allow writebacks** was **OFF** (or turn OFF first).  
4. Turn **ON** → Save (if needed) → toast/success.  
5. Optional: Analyst cannot toggle (if quick).

**B. Each check: CI-01 → CC-03 → WB-SHOP-01**  
1. Fix → preview → **Approve writeback** → Written.  
2. Network execute OK.  
3. Open **related account** (Manago or Shopify) — field visible.  
4. Fix → **Rollback**.  
5. Same account — write reversed.

**C. Negative**  
- LE-04 Approve disabled.  
- Optional: turn writebacks **OFF** in Settings again → Approve blocked.

### 8.2 PR comment

```text
Loom(s): <url>
Settings toggle shown: Y/N
Demo company: <name/domain>

CI-01: Manago reflect Y/N · rollback Y/N
CC-03: Manago reflect Y/N · rollback Y/N
WB-SHOP-01: Shopify reflect Y/N · rollback Y/N
LE-04 blocked: Y/N
manage.py NOT used to enable: Y/N
```

---

## 9. Acceptance

- [ ] All companies default/migrated execute **OFF**  
- [ ] **Settings → Workspace** Admin toggle works (GET + PATCH)  
- [ ] Non-admin cannot enable  
- [ ] Fix respects flag (OFF = no execute; ON = real write)  
- [ ] No manage.py required in happy path / Loom  
- [ ] CI-01 / CC-03 / WB-SHOP-01: write + platform reflect + rollback reflect (Loom)  
- [ ] LE-04 blocked  
- [ ] Sandbox theater copy / sheet `sandbox_only` cleaned  
- [ ] Loom link + checklist on PR  

---

## 10. PR title / branch

- Branch: `feature/wb-03-writeback-settings-toggle`  
- BE + FE PRs OK if linked; titles must say **WB-03** (not `merge: update from main`)  
- Title example: `feat(WB-03): Settings toggle for writebacks; default off; real Fix execute`

---

## 11. Traceability

| Item | Note |
|------|------|
| Bad default | PR #46 · `default=True` · all companies ON |
| Operator path | **Settings UI**, not manage.py |
| Parents | WB-02 · WB-02B · FE-12 · Settings workspace Admin edit |
| FE SoT | `klints_frontend` `src/routes/settings.tsx` Workspace section |
