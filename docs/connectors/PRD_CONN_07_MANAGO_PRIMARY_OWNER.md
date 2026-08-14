# PRD-CONN-07 — Manago primary owner picker (FD-06)

**Status:** Backend done — **frontend implementation only**  
**Module:** see folder path  
**Depends on:** Manago connect on `/integrations`; connector list API; DCS foundation gate FD-06  
**Surface:** `/integrations` (Manago card) + optional post-connect onboarding step  
**Scope:** When Manago has **2+ users**, let the operator **pick the primary owner**. Persist via backend. Unblocks FD-06 / RC-11 multi-account ambiguity.

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-CONN-07 frontend only (backend APIs already ship).

Read: docs/connectors/PRD_CONN_07_MANAGO_PRIMARY_OWNER.md

Do:
1. Add API helpers in src/lib/connectors.ts:
   - getManagoOwners()
   - setManagoPrimaryOwner(ownerEmail)
2. On Integrations → Manago connected card:
   - After Manago is linked, call GET owners
   - If needs_primary_selection === true, show primary-owner picker UI (§4)
   - On Save, PUT { owner } then refresh connectors list
3. Also check after successful Manago connect (same flow)
4. Match existing Integrations patterns (CONN-04 / CONN-06): toasts, loading, admin/analyst only for mutate
5. Do NOT invent new backend routes. Use exact paths in §6.
6. Do NOT change Shopify card.

Acceptance: checklist in §9.
```

---

## 1. Why this exists (plain English)

Manago accounts can have **more than one login (user email)** under the same client id.

Klints DCS check **FD-06** needs to know which login is the **primary shop owner**. If it doesn’t know, the whole DCS run stays **BLOCKED** (RC-11).

| Manago users | What should happen |
|--------------|--------------------|
| 1 | Backend auto-selects — FE usually shows nothing |
| 2+ | FE shows picker → user picks one → PUT → FD-06 can pass |

Secondary users are marked out of scope (not deleted).

---

## 2. Backend status (do not re-implement)

Already live on API:

| Piece | Status |
|-------|--------|
| `GET /api/v1/connectors/manago_ai/owners/` | Done |
| `PUT /api/v1/connectors/manago_ai/owners/` | Done |
| Connector list fields `primary_owner`, `topology_configured` | Done |
| Auto-select when exactly 1 owner (on GET) | Done |
| FD-06 reads `config.owner` + `config.topology` | Done |

FE only needs to **call** these and render UI.

Reference: `docs/auth/API_AUTH_CONNECTORS.md` §7b  
Backend service: `tenants/manago_topology_service.py`  
Views: `ManagoOwnersView` in `tenants/connector_views.py`

---

## 3. Goal (frontend)

1. After Manago is **connected**, know whether primary selection is required.  
2. If `needs_primary_selection === true`, show a clear picker on the Manago card.  
3. Save selection via PUT; refresh UI; toast success.  
4. If already configured (`needs_primary_selection === false`), show read-only primary (optional) or nothing.  
5. Viewer: can GET / see state; cannot PUT (403) — hide Save or disable.

**Out of v1**

- Multi-account classification UI (`geo_variant` / `independent_business_line` / `segment_variant`) — both in-scope  
- Editing topology for ERP  
- Blocking entire app shell solely for this (FD-06 already blocks score; Integrations can still open)

---

## 4. UX

### 4.1 When to show the picker

Show the block when **all** are true:

1. Manago connector exists and `status ∈ {connected, degraded}` (same “linked” as CONN-04 / CONN-06).  
2. `GET …/owners/` returned `needs_primary_selection: true`.

Hide / collapse when `needs_primary_selection: false`.

### 4.2 Picker copy (Connected stack — Manago card)

```text
Primary Manago owner
This Manago account has more than one user. Pick the login that owns
this Shopify shop so Klints scores the right data (required for FD-06).

( ) noreplyklints@gmail.com
( ) george.chief@icloud.com

[ Save primary owner ]
```

Optional helper under selected radio:

```text
Other users stay connected in Manago but are ignored for scoring.
```

### 4.3 Already configured (optional read-only)

```text
Primary Manago owner
noreplyklints@gmail.com
[ Change ]
```

`Change` re-opens the radio list (still PUT on save). Nice-to-have; v1 can skip Change and only show picker when needed.

### 4.4 Loading / errors

| State | UI |
|-------|-----|
| GET loading | Skeleton / spinner in Manago card section |
| GET 404 | Manago not connected — don’t show block |
| GET 502 | “Couldn’t load Manago users. Retry.” + Retry button |
| PUT 400 | Show field error under radios (`owner` message) |
| PUT 403 | Toast: no permission |
| PUT success | Toast + invalidate connectors query + hide picker |

### 4.5 When to fetch

1. Integrations page load, if Manago linked.  
2. Immediately after successful Manago **connect** response (before user leaves).  
3. After PUT success (refetch GET or use PUT response body).

Do **not** fetch on every render; cache like other connector queries.

---

## 5. API contracts (exact)

Base: `/api/v1/connectors/`  
Auth: `Authorization: Bearer <access>`

### 5.1 List owners

```http
GET /api/v1/connectors/manago_ai/owners/
```

**200**

```json
{
  "platform": "manago_ai",
  "connector_id": "c56a4180-65aa-42ec-a945-5fd21dec0538",
  "owners": [
    { "email": "noreplyklints@gmail.com", "is_primary": true },
    { "email": "george.chief@icloud.com", "is_primary": false }
  ],
  "primary_owner": "noreplyklints@gmail.com",
  "owner_count": 2,
  "needs_primary_selection": false,
  "topology_configured": true
}
```

| Field | FE use |
|-------|--------|
| `needs_primary_selection` | Show picker when `true` |
| `owners[].email` | Radio labels |
| `owners[].is_primary` | Pre-select if any |
| `primary_owner` | Display / default selection |
| `owner_count` | Optional badge (“2 users”) |

**Errors**

| Code | Meaning |
|------|---------|
| 401 | Not signed in |
| 400 | No company for user |
| 404 | Manago connector missing |
| 502 | Manago `listByClient` failed — show retry |

### 5.2 Set primary owner

```http
PUT /api/v1/connectors/manago_ai/owners/
Content-Type: application/json

{ "owner": "noreplyklints@gmail.com" }
```

(`primary_owner` is also accepted by backend; prefer `owner`.)

**200** — same shape as GET (updated).

**400** example

```json
{
  "owner": ["Owner must be one of the Manago users on this account."],
  "owners": ["a@x.com", "b@x.com"]
}
```

**403** — viewer / no permission.

### 5.3 Connector list hints (optional)

`GET /api/v1/connectors/` Manago item may include:

```json
{
  "name": "manago_ai",
  "primary_owner": "noreplyklints@gmail.com",
  "topology_configured": true,
  "has_api_v3_key": true
}
```

Use for badge (“Primary set”) without calling GET owners every time.  
**Still call GET owners** when `topology_configured` is false/missing **or** when you need `needs_primary_selection` (list alone does not return that flag).

---

## 6. Frontend wiring (files to change)

| File | Change |
|------|--------|
| `src/lib/connectors.ts` (or equivalent) | `getManagoOwners()`, `setManagoPrimaryOwner(owner: string)` |
| `src/routes/integrations.tsx` (or Manago card component) | Picker UI §4; wire after connect |
| Types | `ManagoOwnersResponse` matching §5.1 |

Suggested helpers:

```ts
// GET /api/v1/connectors/manago_ai/owners/
export async function getManagoOwners(): Promise<ManagoOwnersResponse>;

// PUT /api/v1/connectors/manago_ai/owners/  body: { owner }
export async function setManagoPrimaryOwner(owner: string): Promise<ManagoOwnersResponse>;
```

Reuse existing authenticated `apiFetch` / axios instance (same as CONN-06 v3 key).

---

## 7. Flow diagrams

### 7.1 After connect / on Integrations

```text
Manago linked?
  └─ no → stop
  └─ yes → GET /manago_ai/owners/
        ├─ needs_primary_selection false → optional show primary; done
        └─ needs_primary_selection true → show radio picker
              └─ user Save → PUT { owner }
                    ├─ 200 → toast, hide picker, refresh connectors
                    └─ 4xx/5xx → show error
```

### 7.2 Relation to DCS

```text
Primary not set + 2 owners → FD-06 FAIL → run BLOCKED
Primary set                 → FD-06 can PASS → score can proceed (other gates aside)
```

FE does **not** need to call `run_dcs_score` automatically on save (v1). Optional: “Run score” CTA if product already has one on Integrations.

---

## 8. Permissions

| Role | GET owners | PUT primary | See picker |
|------|------------|-------------|------------|
| Admin | Yes | Yes | Yes |
| Analyst | Yes | Yes | Yes |
| Viewer | Yes | No (403) | Read-only / no Save |

Match CONN-06 Manago v3 key permissions.

---

## 9. Acceptance checklist

1. [ ] With Manago connected and 2+ users and no primary → picker visible on Manago card.  
2. [ ] Selecting an email + Save → PUT succeeds → `needs_primary_selection` becomes false.  
3. [ ] With 1 Manago user → picker **not** required (backend auto-set; FE may show nothing).  
4. [ ] Shopify card unchanged.  
5. [ ] Viewer cannot save (Save hidden or 403 handled).  
6. [ ] 502 from GET shows retry, does not crash page.  
7. [ ] After Manago connect success, owners check runs without requiring full page reload.  
8. [ ] No plaintext Manago `api_key` / secrets in UI or logs.  
9. [ ] Types match §5.1 response fields.

---

## 10. Copy for FE (i18n-ready strings)

| Key | English |
|-----|---------|
| Title | Primary Manago owner |
| Body | This Manago account has more than one user. Pick the login that owns this Shopify shop so Klints scores the right data. |
| Helper | Other users stay in Manago but are ignored for scoring. |
| CTA | Save primary owner |
| Success toast | Primary Manago owner saved |
| Error load | Couldn’t load Manago users. Try again. |
| Change | Change |

---

## 11. Out of scope / later

| Item | Notes |
|------|--------|
| Multi-in-scope classification UI | Excel classes for true multi-brand; separate PRD |
| Auto-run DCS after save | Nice-to-have |
| Email deep-link to Integrations | Optional |

---

## 12. Handoff note for Engineering → Cursor

**Backend is complete.** This PRD is **frontend-only**.

Priority: Integrations Manago card blocker for multi-user Manago accounts (FD-06).

Related: CONN-06 (API v3 key) sits on the same card — keep sections distinct (v3 key ≠ primary owner).
