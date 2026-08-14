# PRD-AUDIT-02 — Audit notifications (unread bell + mark read)

**Status:** Ready for implementation  
**Owner track:** Maheep (`docs/maheep/`)  
**Depends on:** PRD-AUDIT-01 (company audit log + `GET /api/v1/audit/events/` shipped in backend #20 / FE #12)  
**Repos:** AppShell bell + `NotificationsPanel`; Activity timeline remains full history  
**Scope:** expose latest unread audit events in the notifications dropdown (top 5), unread count badge, `audit_read` flag, mark-one / mark-all-read APIs + FE wiring

## 1. What exists today

### Backend (AUDIT-01)

`AuditLog` (`audit_logs`) is company-scoped, append-only with hash chain. List API:

`GET /api/v1/audit/events/` → `{ results[], next_cursor }`

Serialized fields today: `id`, `action`, `tone`, `summary`, `performed_by`, `actor`, `meta`, `created_at`, `run_id`.

**Gap:** no read/unread state; no notifications-shaped endpoint; no mark-read APIs.

### Frontend

| Surface | Current behavior |
|---------|------------------|
| AppShell bell | Hardcoded `unread = 3`; badge shows that number |
| `NotificationsPanel` | Renders mock `activityFeed.slice(0, 5)` from `klints-data.ts` |
| “Mark all read” | Local `setUnread(0)` + toast only — no API |
| Row click | Links to `/activity` |
| Footer | “View full timeline” → `/activity` |

Activity page (AUDIT-01 FE) already loads live audit events; notifications still use mocks.

## 2. Problem

Operators get governance events in Activity, but the bell still shows fake items and a fake count. We need the same audit stream as **unread notifications** in the header, with a real unread count and mark-as-read.

## 3. Goal

1. Add **`audit_read`** (`true` | `false`) on each audit event (default `false` = unread).  
2. Bell badge = **company unread count** (cap display e.g. `9+` if useful).  
3. Notifications panel shows **latest 5 unread** audit events (newest first). If fewer than 5 unread, show unread only (do not pad with read events). Optional empty state when zero unread.  
4. **Mark all read** persists via API and clears badge.  
5. Optional: mark a single event read when opened / clicked.  
6. Hash chain unchanged — `audit_read` is **not** part of `entry_hash` input (mutable after append).

**Out of v1:** per-user read receipts, push/email, realtime websockets, non-audit notification types (writeback/QA still out of scope).

## 4. Read model semantics

### 4.1 Field

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `audit_read` | boolean | `false` | `false` = unread (show in bell); `true` = read |

User asked for the key name **`audit_read`** — use that in DB + API (not `is_read`).

### 4.2 Scope (v1)

**Company-scoped** read state: one flag per `AuditLog` row. When any entitled user marks read / mark-all, it updates for the whole company workspace.

Rationale: matches current single-workspace MVP and keeps schema simple.  
**v1.1 (optional):** per-user `AuditLogRead` (`user_id`, `audit_log_id`, `read_at`) if multi-analyst inboxes are needed.

### 4.3 Who can mutate

Same roles as list: `admin`, `analyst`, `viewer` may mark read (viewers already see the timeline).

## 5. Data model / migration

On `dataruns.AuditLog`:

```python
audit_read = models.BooleanField(default=False, db_index=True)
```

Index for notifications:

```text
Index(fields=["company", "audit_read", "-created_at"])
```

`append_audit_event` always creates rows with `audit_read=False`.  
Do **not** include `audit_read` in `compute_entry_hash` / verify chain.

Backfill: existing rows → `audit_read=False` (all appear unread once) — acceptable for early tenants; or set `True` for rows older than N days if noise is high (default: all unread).

## 6. API

Base path remains `/api/v1/audit/`. Auth: Bearer. Company from current user.

### 6.1 Extend list serializer

Every event in `GET /api/v1/audit/events/` (and new endpoints) includes:

```json
"audit_read": false
```

Optional query on existing list: `unread_only=true` (filter `audit_read=false`).

### 6.2 `GET /api/v1/audit/notifications/`

Purpose-built for the bell (thin wrapper over unread audits).

Query: `limit` default **5**, max 10.

**200**

```json
{
  "unread_count": 12,
  "results": [
    {
      "id": "uuid",
      "action": "connector.bootstrap_succeeded",
      "tone": "info",
      "summary": "Shopify bootstrap succeeded · 13 contacts · 20 orders",
      "performed_by": "system",
      "actor": "system",
      "meta": "shopify",
      "created_at": "2026-08-01T04:16:20Z",
      "run_id": null,
      "audit_read": false
    }
  ]
}
```

Rules:

- `results` = newest unread only, length ≤ `limit` (5).  
- `unread_count` = total unread for company (not capped to 5).  
- Empty unread → `{ "unread_count": 0, "results": [] }`.

### 6.3 `POST /api/v1/audit/notifications/mark-all-read/`

Body: empty `{}`.

Effect: set `audit_read=true` for all company rows where `audit_read=false`.

**200**

```json
{
  "updated": 12,
  "unread_count": 0
}
```

Idempotent if already all read (`updated: 0`).

### 6.4 `POST /api/v1/audit/events/{id}/mark-read/` (recommended)

Mark one event read (row click / optional).

**200**

```json
{
  "id": "uuid",
  "audit_read": true,
  "unread_count": 11
}
```

404 if not in user’s company. Idempotent if already read.

### 6.5 Hash / integrity

Mark-read updates must not rewrite `entry_hash` / `prev_hash`. Only `audit_read` (+ `updated_at` if added). Prefer **no** `updated_at` unless already present — single-field update is enough.

## 7. Frontend

### 7.1 Files

| File | Change |
|------|--------|
| `src/lib/audit.ts` | types + `listAuditNotifications`, `markAllAuditRead`, `markAuditEventRead`; extend `AuditEvent` with `audit_read` |
| `src/components/klints/NotificationsPanel.tsx` | live data props; empty state; drop mock `activityFeed` |
| `src/components/klints/AppShell.tsx` | fetch unread count + panel data; wire mark-all; remove hardcoded `useState(3)` |

### 7.2 Bell badge

- Query `GET /api/v1/audit/notifications/?limit=5` on shell mount (and when panel opens / after mark-all / after window focus optional).  
- Badge shows `unread_count` when `> 0` (display `9+` if `> 9` — optional polish).  
- Hide badge when `0`.

### 7.3 Panel

Keep existing layout (header, list, footer link to Activity).

- Subtitle: e.g. “Governance activity” (replace mock “Writebacks, drift…”).  
- List: up to 5 unread; tone dot from `tone`; title = `summary`; meta line = relative time · actor · meta.  
- Empty: “You’re all caught up.” + still show “View full timeline”.  
- Row click: optionally `POST .../mark-read/` then navigate to `/activity` (or `/activity` with hash/query later).  
- **Mark all read:** call mark-all API → invalidate queries → badge 0 → toast.

### 7.4 Activity page

Keep listing all events (read + unread). Show subtle unread affordance optional (dot if `audit_read === false`) — not required for v1.

### 7.5 DCS lock

Notifications bell stays available whenever AppShell is shown (same as Activity always visible). No new lock rules.

## 8. Acceptance

1. New audit events appear with `audit_read: false`.  
2. Bell badge equals company unread count.  
3. Panel shows at most **5** newest unread; not mocks.  
4. Mark all read → API updates rows → badge 0 → panel empty / caught up.  
5. Mark one read → that id disappears from panel; count decrements.  
6. Company A cannot see or mark Company B events.  
7. `verify_audit_chain` still passes after mark-read (hash ignores `audit_read`).  
8. Activity timeline still lists full history including read events.

## 9. Files to change

| Area | File |
|------|------|
| Model + migration | `dataruns/models.py`, new migration |
| Append helper | `dataruns/audit.py` (default unread) |
| API | `dataruns/audit_views.py`, `audit_urls.py` |
| Tests | mark-all, unread count, notifications limit 5, company isolation, hash unchanged after mark-read |
| FE | `audit.ts`, `NotificationsPanel.tsx`, `AppShell.tsx` |

## 10. Out of scope

- Separate notification product types (non-audit)  
- Per-user read state  
- Email / push / websocket push of new audits  
- Changing AUDIT-01 instrumentation set  

## 11. Related

| Doc / artifact | Relation |
|----------------|----------|
| AUDIT-01 | Source events + Activity page |
| FE AppShell + NotificationsPanel | Consumer UI (mock → live) |
| Backend #20 / FE #12 | Prerequisite audit APIs |
