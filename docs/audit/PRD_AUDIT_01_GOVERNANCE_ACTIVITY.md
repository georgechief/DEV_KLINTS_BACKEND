# PRD-AUDIT-01 — Governance activity / audit timeline

**Status:** Ready for implementation  
**Module:** see folder path  
**Depends on:** existing stub `dataruns.models.AuditLog`; FE `/activity` page  
**Repos:** Activity UI (`klints_frontend/src/routes/activity.tsx`) + Settings/admin later  
**Scope (v1):** company-scoped append-only audit events + list API + replace mock Activity feed; lightweight hash chain for integrity (timeline Week 5 foundation); **Activity nav always visible** — never disabled by DCS lock (amend FE-03 allowlist)

## 1. What exists today

### Backend

[`dataruns.models.AuditLog`](../../dataruns/models.py) (`db_table=audit_logs`):

| Field | Notes |
|-------|--------|
| `id` | UUID PK |
| `run` | FK → `Run` (required today) |
| `action` | text |
| `performed_by` | text |
| `metadata` | JSON |
| `created_at` | auto |

**Gap:** never written (`AuditLog.objects` unused). Tied only to a domain `Run`, so connector/workspace/DCS events without a Run cannot be logged cleanly. No `company`, no hash chain, no API.

### Frontend

[`/activity`](../../../klints_frontend/src/routes/activity.tsx) — **UI exists**, labeled “Governance timeline”:

- Nav: Reference → **Activity**
- Renders mock `activityFeed` from [`klints-data.ts`](../../../klints_frontend/src/lib/klints-data.ts)
- Row shape used by UI:

```ts
{
  id: string
  time: string          // display relative / clock
  tone: "revenue" | "info" | "risk" | "loss"
  actor?: string
  text: string
  meta?: string
}
```

FE-03 currently **locks** `/activity` when DCS is not unlocked (`LOCKED_ALLOWED_ROUTES` = dashboard / integrations / settings only — Activity disabled). This PRD **fixes that**: Activity is **always visible and clickable** after auth/onboarding, whether DCS is locked or unlocked (same as Dashboard / Integrations / Settings).

## 2. Problem

Activity is demo-only. Operators cannot see real governance verbs (connect, bootstrap, DCS score, workspace changes). MVP Week 5 also needs a tamper-evident audit log before approvals/writeback.

Separately: while DCS is not calculated / scoring, the Activity tab is **locked (inactive)** today — exactly when connect + bootstrap events matter most.

## 3. Goal (v1)

1. Evolve audit storage to support **company-scoped** events (not only `run`).  
2. Append-only write helper used from key product paths.  
3. `GET` API for the Activity timeline (newest first).  
4. Replace mock `activityFeed` on `/activity` with live data.  
5. Store **hash chain** fields so integrity can be verified (verify command in v1; full “detect tamper” Celery can be v1.1).  
6. **Activity always available:** never gated by DCS `hard_locked` / `soft_locked_running`. Nav + deep link work in both locked and unlocked states.

**Out of v1:** approval state machine UI, writeback audit depth, AI agent eval logs, PDF export.

## 4. Data model

Keep table `audit_logs`. Migrate / extend (prefer evolve stub rather than a second table):

| Field | Type | Notes |
|-------|------|--------|
| `id` | UUID | existing |
| `company` | FK → `Company` | **required**; tenant isolation |
| `run` | FK → `Run` | **nullable** (optional link) |
| `action` | slug string | e.g. `connector.connected`, `dcs.score_completed` |
| `tone` | string | `info` \| `risk` \| `loss` \| `revenue` (maps FE badge) |
| `summary` | text | human line for `text` in UI |
| `performed_by` | string | user email / `system` / service name |
| `actor_user_id` | UUID null | optional FK/soft ref to `User` |
| `metadata` | JSON | ids, platforms, counts, error snippets (no secrets) |
| `prev_hash` | char(64) | hex SHA-256 of previous company entry (or genesis) |
| `entry_hash` | char(64) | hex SHA-256 of this row canonical payload |
| `created_at` | datetime | existing |

Indexes: `(company_id, created_at DESC)`, unique `(company_id, entry_hash)` optional.

**Genesis:** first event for a company uses `prev_hash = "0" * 64` (or documented constant).

**Canonical hash input (v1):**  
`prev_hash | company_id | action | summary | performed_by | created_at_iso | stable_json(metadata)`

Do **not** put tokens, API keys, or full connector config in `metadata`.

## 5. Write helper

```python
append_audit_event(
    *,
    company: Company,
    action: str,
    summary: str,
    performed_by: str,
    tone: str = "info",
    actor_user_id: str | None = None,
    run: Run | None = None,
    metadata: dict | None = None,
) -> AuditLog
```

Rules:

- Always append (no update/delete API for product users).  
- Compute `prev_hash` from latest row for that company (row lock / `select_for_update` on last entry).  
- Fail closed on hash write errors (log + raise in request path; for Celery prefer retry).

### v1 instrumented events (minimum)

| When | `action` | `tone` (default) |
|------|----------|------------------|
| Manago / Shopify connector created or reconnected | `connector.connected` | `info` |
| Connector disconnected | `connector.disconnected` | `risk` |
| Bootstrap succeeded | `connector.bootstrap_succeeded` | `info` |
| Bootstrap failed | `connector.bootstrap_failed` | `loss` |
| DCS score run completed | `dcs.score_completed` | `info` / `risk` if BLOCKED |
| DCS score run failed | `dcs.score_failed` | `loss` |
| Workspace / company domain updated | `workspace.updated` | `info` |
| Team invite sent / accepted | `team.invite_sent` / `team.invite_accepted` | `info` |

Expand later for fix plans / approvals without changing the list API shape.

## 6. API

### `GET /api/v1/audit/events/`

Auth: Bearer. Scope: current user’s company only.  
Roles: `admin`, `analyst`, `viewer` (read).

Query: `limit` (default 50, max 100), `cursor` / `before` optional.

**200**

```json
{
  "results": [
    {
      "id": "uuid",
      "action": "connector.bootstrap_succeeded",
      "tone": "info",
      "summary": "Manago bootstrap succeeded · 14 contacts · 8 orders",
      "performed_by": "system",
      "actor": "system",
      "meta": "manago_ai",
      "created_at": "2026-07-30T12:13:49Z",
      "run_id": null
    }
  ],
  "next_cursor": null
}
```

Map to FE:

| API | FE |
|-----|-----|
| `id` | `id` |
| `summary` | `text` |
| `performed_by` / `actor` | `actor` |
| `meta` (short string from metadata) | `meta` |
| `tone` | `tone` |
| `created_at` | format as `time` client-side |

No public update/delete. Integrity verify is admin/ops only (management command).

### `POST` / mutate

None for FE v1.

## 7. Frontend

### 7.1 Activity page (live data)

File: `klints_frontend/src/routes/activity.tsx`

1. Fetch `GET /api/v1/audit/events/` on mount (same auth as other app pages).  
2. Map rows into existing list UI (keep layout/tones).  
3. Empty state: “No governance activity yet.”  
4. Loading / error states.  
5. Remove dependency on mock `activityFeed` for this page (may leave mock export unused or delete later).

Optional: light filter chips by `tone` / `action` prefix — not required for v1.

### 7.2 Activity always visible (FE-03 amendment)

Today FE-03 / `LOCKED_ALLOWED_ROUTES` excludes `/activity`, so when DCS is locked the nav item is **inactive** and deep links redirect to `/dashboard`.

**Change:** Activity is **always** clickable after the user is in the app shell — locked or unlocked. Same tier as Dashboard / Integrations / Settings.

| Clickable when locked | Path |
|-----------------------|------|
| Dashboard (gated) | `/dashboard` |
| Connected stack | `/integrations` |
| Account / settings | `/settings` |
| **Activity (governance timeline)** | **`/activity`** |

Still disabled when locked: `/data-consistency`, Fix/Workflow menus, `/lifecycle`, `/opportunities`, etc.

**Implement:**

1. Add `"/activity"` to `LOCKED_ALLOWED_ROUTES` in `klints_frontend/src/lib/dcs.ts` (and any mirror in `app-access.ts`).  
2. Confirm AppShell / SpotlightSearch use `isNavRouteAllowed` so Activity is no longer `pointer-events-none` when locked.  
3. Do **not** redirect `/activity` to gated dashboard while locked — render the Activity page normally (live audit feed or empty state).  
4. Update FE-03 doc §6.1 / acceptance to match (this PRD owns the product change).

## 8. Integrity (Week 5 slice)

1. On each append, set `prev_hash` / `entry_hash`.  
2. Management command: `python manage.py verify_audit_chain --company-id <uuid>`  
   - Walk ascending `created_at`  
   - Fail if broken link or recomputed hash mismatch  
3. Celery periodic “detect tampered audit logs” can be **v1.1** (same verifier).

## 9. Files to change

| Area | File |
|------|------|
| Model + migration | `dataruns/models.py` (`AuditLog`), new migration |
| Service | `dataruns/audit.py` or `tenants/audit.py` (`append_audit_event`) |
| Instrument | connector views/tasks, DCS orchestrate, workspace patch, invites |
| API | `dataruns/audit_views.py` + urls under `/api/v1/audit/` |
| Command | `verify_audit_chain` |
| FE | `activity.tsx`, small `lib/audit.ts`, `lib/dcs.ts` (`LOCKED_ALLOWED_ROUTES`) |
| Docs | Amend FE-03 §6.1 locked allowlist |
| Tests | append hash chain, list isolation by company, FE mapping; locked shell still allows `/activity` |

## 10. Acceptance

1. Connect Manago → Activity shows `connector.connected` / bootstrap success (after worker) with actor `system` or user.  
2. Run DCS → Activity shows `dcs.score_completed` with run_state in meta.  
3. Company A never sees Company B events.  
4. `/activity` no longer uses mock `activityFeed` for primary content.  
5. `verify_audit_chain` passes on a healthy company; fails if a middle row’s `entry_hash` is mutated in DB.  
6. Secrets never appear in `metadata`.  
7. Whether DCS is `hard_locked`, `soft_locked_running`, or `unlocked`: **Activity is always visible and clickable**; `/activity` never redirects to gated dashboard for lock reasons. Fix/Workflow menus remain disabled only while locked.

## 11. Out of scope

- Full approval workflow / writeback audit depth  
- Blockchain / external anchoring  
- Editing or deleting audit rows from product UI  
- Unlocking other FE-03-gated routes (Fix, Workflow, lifecycle, etc.)

## 12. Related

| Doc / artifact | Relation |
|----------------|----------|
| MVP timeline Week 5 | Tamper-proof audit log + detect-tamper check |
| FE `/activity` | Consumer UI (mock → live) |
| FE-03 | Amended: Activity always visible (joins locked allowlist; never DCS-gated) |
| Existing `AuditLog` stub | Evolve, don’t ignore |
