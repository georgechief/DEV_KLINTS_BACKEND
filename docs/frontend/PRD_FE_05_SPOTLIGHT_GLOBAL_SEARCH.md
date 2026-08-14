# PRD-FE-05 — Spotlight global search (Cmd+K) + search API

**Status:** Ready for implementation  
**Module:** see folder path  
**Depends on:** FE-03 DCS app lock (`isNavRouteAllowed` / `dcsStatus`); AUDIT-01 events API; CONN-04 connectors list; DCS status API  
**Surfaces:**  
- FE: AppShell search trigger + `SpotlightSearch` (`cmdk` dialog, ⌘/Ctrl+K)  
- BE: new `GET /api/v1/search/`  
**Scope:** replace mock Issues/Workflows in Spotlight with live, company-scoped search results; keep Navigate + Account local

---

## 1. What exists today

### Frontend

| Piece | Path | Behavior |
|-------|------|----------|
| Trigger | `AppShell.tsx` | Header “Search issues, workflows…” + mobile icon |
| Dialog | `SpotlightSearch.tsx` | `cmdk` Command palette |
| Shortcut | same | ⌘/Ctrl+K toggles open |
| **Navigate** | hardcoded `pages[]` | Filtered by `isNavRouteAllowed(dcsStatus, route)` |
| **Issues** | `@/lib/klints-data` mock | Shown only if `/workflow` allowed |
| **Workflows** | `@/lib/klints-data` mock | Same gate |
| **Account** | local | Settings (if allowed) + Log out |
| Filtering | `cmdk` client `value=` | **No API call**, no debounce |

Placeholder copy: `Search issues, workflows, pages…`

### Backend

- **No** global / Spotlight search endpoint.  
- Usable list surfaces (no `q` today):  
  - `GET /api/v1/audit/events/`  
  - `GET /api/v1/connectors/`  
  - `GET /api/v1/dataruns/` (tenant/status filters only)  
  - DCS latest run / checks (via status + score pipeline; full “list checks” may be partial)  
- `RunIssue` exists in DB for DCS findings; **no** product search API yet.  
- Contact / Order models exist; **no** product search API — **out of v1**.

---

## 2. Problem

Operators open Spotlight expecting to find real governance issues and product entities. Issues and workflows are fake. There is no single search API to plug into. Navigate pages already work locally and should stay fast/offline.

---

## 3. Goal

1. Add **`GET /api/v1/search/`** — authenticated, company-scoped, typed results.  
2. Wire Spotlight to call it when the user types (debounced).  
3. Keep **Navigate** + **Account** fully client-side.  
4. Respect **DCS app lock**: do not show or return types whose destination routes are locked.  
5. Ship in **clear phases** so v1 is useful without waiting for full Workflow Studio APIs.

**Out of v1:** Elasticsearch / vector search; contact/order PII search; workflow blueprint library; keyboard result prefetch analytics; empty-query “recents” persistence.

---

## 4. Product behavior (Spotlight UX)

### 4.1 Open / close

Unchanged: header click, ⌘/Ctrl+K, Esc closes, Enter opens selection.

### 4.2 Query rules (FE)

| Input | Behavior |
|-------|----------|
| `q` length 0–1 | Show **Navigate** (+ Account). Do **not** call search API. |
| `q` length ≥ 2 | Debounce **200ms**, call search API; show loading row optional |
| New keystroke | Abort previous in-flight request |
| API error | Show empty + soft message “Search unavailable”; Navigate still works |
| No hits | `CommandEmpty`: “No matches. Try a page, check id, or connector name.” |

### 4.3 Groups (final layout)

| Group | Source | When shown |
|-------|--------|------------|
| **Navigate** | Local `pages[]` | Always (filtered by DCS lock) |
| **Checks / issues** | API `type=issue` | If `/data-consistency` (or `/workflow` — see §4.4) allowed **and** API returned items |
| **Activity** | API `type=audit` | If `/activity` allowed |
| **Connectors** | API `type=connector` | If `/integrations` allowed |
| **Runs** | API `type=run` | If `/data-consistency` allowed |
| **Workflows** | API `type=workflow` | **v1.1 only** — omit group in v1 (remove mock) |
| **Account** | Local | Always (settings gated) |

**v1 locked:** drop mock Issues + mock Workflows groups entirely. Do not leave fake data in the palette.

### 4.4 Issue → href (v1)

Real DCS findings are check-level (`RunIssue.issue_type` = `CI-01`, etc.), not mock workflow cards.

**v1 navigation target (locked):**

```text
/data-consistency?check={check_id}
```

(or `/data-consistency?issue={run_issue_id}` if FE already supports id — prefer **check_id** for stable deep links)

Do **not** link mock `/workflow/$id?issue=` in v1.

When FE-04 / DCS pages support highlighting a check from query param, wire that. Until then, landing on Data Consistency with `?check=` is enough; page may ignore unknown param without error.

### 4.5 DCS lock

FE already filters Navigate via `isNavRouteAllowed`.

Also pass allowed types to API **or** filter results client-side:

```text
types = intersection(requested, types_allowed_for_dcs_status)
```

| Result type | Requires route allowed |
|-------------|------------------------|
| `issue`, `run` | `/data-consistency` |
| `audit` | `/activity` |
| `connector` | `/integrations` |
| `workflow` | `/workflow` (v1.1) |

BE should still enforce company scope; FE enforces lock UX.

---

## 5. API contract

### 5.1 Endpoint

```http
GET /api/v1/search/?q={string}&types={csv}&limit={int}
Authorization: Bearer <access>
```

Mount under e.g. `dataruns` or `tenants` search urls; register in `core/urls.py`:

```text
path("api/v1/search/", ...)
```

### 5.2 Query params

| Param | Required | Default | Rules |
|-------|----------|---------|-------|
| `q` | yes | — | Trimmed; if `< 2` chars after trim → `400` or empty `{ results: [] }` (**locked:** return `200` + `results: []`) |
| `types` | no | all v1 types | CSV: `issue,audit,connector,run` (v1); `workflow` ignored until v1.1 |
| `limit` | no | `6` | Per-type max; clamp `1…10` |

### 5.3 Response

```json
{
  "q": "guest",
  "results": [
    {
      "type": "issue",
      "id": "a1b2c3d4-…",
      "title": "Guest checkout identity share",
      "subtitle": "CI-02 · FAIL · Customer Identity",
      "href": "/data-consistency?check=CI-02",
      "meta": {
        "check_id": "CI-02",
        "status": "FAIL",
        "dimension": "01 Customer Identity",
        "run_id": "…"
      }
    },
    {
      "type": "audit",
      "id": "…",
      "title": "Shopify connector connected",
      "subtitle": "connector.connected · 2h ago",
      "href": "/activity",
      "meta": { "action": "connector.connected", "tone": "info" }
    },
    {
      "type": "connector",
      "id": "…",
      "title": "Shopify",
      "subtitle": "connected · klints-dev.myshopify.com",
      "href": "/integrations",
      "meta": { "platform": "shopify", "status": "connected" }
    },
    {
      "type": "run",
      "id": "58",
      "title": "DCS score",
      "subtitle": "succeeded · 1 Aug",
      "href": "/data-consistency",
      "meta": { "kind": "dcs_score", "status": "succeeded", "data_run_id": 58 }
    }
  ]
}
```

**Result item schema (locked):**

| Field | Type | Notes |
|-------|------|-------|
| `type` | enum | `issue` \| `audit` \| `connector` \| `run` (\| `workflow` later) |
| `id` | string | Stable id for React key |
| `title` | string | Primary line |
| `subtitle` | string | Secondary line (may be empty) |
| `href` | string | App path (+ query); FE navigates with router |
| `meta` | object | Type-specific; ignore unknown keys |

Order: group by type in this order — `issue`, `run`, `connector`, `audit` — then relevance within type (simple: most recent / best icontains rank).

### 5.4 Auth / errors

| Case | Response |
|------|----------|
| Unauthenticated | `401` |
| Authenticated, no company | `403` or empty results (match other tenant APIs) |
| Success | `200` always when auth OK (including zero hits) |

---

## 6. Backend search implementation

### 6.1 Service shape

```python
def search_company(
    *,
    company: Company,
    q: str,
    types: set[str],
    limit: int,
) -> list[SearchHit]:
    ...
```

Fan-out per type; concatenate. Keep each query cheap (indexed `icontains` / `iexact` where possible). **No** cross-company leakage.

### 6.2 Type: `issue` (v1 = DCS findings)

Source: `RunIssue` for the company’s **latest** DCS score domain `Run` (or latest DataRun `metadata.kind=dcs_score` → its issues).

Match `q` against (any):

- `issue_type` (check id, e.g. `CI-02`)  
- `details.message` / `details.check_id` if present  
- optional CheckMaster display name if loaded  

Prefer FAIL/WARN over PASS when ranking. Cap `limit`.

```text
title    = CheckMaster name or details message or issue_type
subtitle = "{check_id} · {status} · {dimension?}"
href     = "/data-consistency?check={check_id}"
```

If no DCS run / no issues → contribute nothing (not an error).

### 6.3 Type: `audit`

Source: `AuditLog` for `company`.

Match `q` against `summary`, `action`, `performed_by` (icontains).

```text
href = "/activity"
```

Optional later: `/activity?event={id}` if FE supports scroll-to.

### 6.4 Type: `connector`

Source: `Connector` for company.

Match `q` against `name`, `display_name`, shop domain / account fields in non-secret config (`shop_domain`, etc.).

```text
href = "/integrations"
```

### 6.5 Type: `run`

Source: `DataRun` for company tenant with `metadata.kind=dcs_score` (and optionally connector fetch).

Match `q` against name, status, stringified id, `metadata.kind`.

```text
href = "/data-consistency"
```

### 6.6 Type: `workflow` (v1.1 — stub)

Return `[]` until Workflow Studio / blueprint API exists. Do not reintroduce FE mocks.

---

## 7. Frontend wiring

### 7.1 Files

| File | Change |
|------|--------|
| `src/lib/search.ts` | **New** — `searchGlobal(q, types?)` → typed client |
| `src/components/klints/SpotlightSearch.tsx` | Debounced fetch; render API groups; remove `issues`/`workflows` from `klints-data` |
| `AppShell.tsx` | Optional: pass `dcsStatus` only (already) |

### 7.2 Client sketch

```ts
// search.ts
export type SearchHit = {
  type: "issue" | "audit" | "connector" | "run" | "workflow";
  id: string;
  title: string;
  subtitle: string;
  href: string;
  meta?: Record<string, unknown>;
};

export async function searchGlobal(q: string, opts?: { types?: string[]; limit?: number }) {
  // GET /api/v1/search/?q=&types=&limit=
}
```

In `SpotlightSearch`:

1. Local state `query` from `CommandInput` `onValueChange`.  
2. `useQuery` / `useEffect` + debounce when `query.trim().length >= 2`.  
3. Map hits → `CommandGroup` by `type` with stable headings.  
4. `onSelect` → parse `href` (path + search params) → existing `go()` helper.  
5. While fetching: optional muted “Searching…” item (not selectable).

### 7.3 Placeholder copy (v1)

Update to match reality:

```text
Search checks, activity, connectors, pages…
```

Empty: `No matches. Try a page, check id (CI-02), or connector name.`

---

## 8. Phased delivery

| Phase | Deliver |
|-------|---------|
| **v1** | BE search: `issue`, `audit`, `connector`, `run`. FE wire + remove mocks. Navigate/Account local. |
| **v1.1** | `workflow` type when blueprint/issue product APIs exist; richer `/activity?event=` deep links |
| **v2** | Contacts / orders (PII rules, separate PRD) |

---

## 9. Acceptance

### Backend

1. Auth required; results only for caller’s company.  
2. `q=""` or `q="a"` → `200` `{ results: [] }`.  
3. `q` matching a known FAIL check id returns `type=issue` with correct `href`.  
4. `q` matching connector name returns `type=connector`.  
5. `limit=2` returns ≤2 hits **per type**.  
6. Unknown `types` values ignored safely.  
7. Unit tests for service matching + company isolation.

### Frontend

1. ⌘K still opens Spotlight; Navigate works offline / without API.  
2. Typing ≥2 chars calls `/api/v1/search/` once per debounce window.  
3. Mock issues/workflows **gone**.  
4. Selecting an issue navigates to `/data-consistency?check=…`.  
5. When DCS locks `/integrations`, connector hits not shown (FE filter and/or omitted types).  
6. Activity allowed when FE-03 allowlist includes `/activity` (already).  
7. Mobile + desktop triggers both work.

---

## 10. Files to change

| Area | File |
|------|------|
| BE | `dataruns/search.py` (or `tenants/search.py`) — service |
| BE | `dataruns/search_views.py` + `search_urls.py` |
| BE | `core/urls.py` — mount `/api/v1/search/` |
| BE | `dataruns/tests/test_search.py` |
| FE | `src/lib/search.ts` |
| FE | `src/components/klints/SpotlightSearch.tsx` |
| FE | Stop importing `issues`/`workflows` from `klints-data` in Spotlight |

---

## 11. Out of scope

- Changing AppShell visual design beyond placeholder/empty copy  
- Server-driven Navigate page list  
- Recents / favorites  
- Full-text Postgres `SearchVector` (nice follow-up; v1 = `icontains` / exact check id)  
- Engineering DCS-08 revenue impact (unrelated)

---

## 12. Handoff note for Engineering

1. **v1 is checks + audit + connectors + runs** — not mock workflows.  
2. Keep Navigate local so the palette stays useful while locked / offline.  
3. One aggregator endpoint beats N fan-out calls from the browser.  
4. Deep link issues to **Data Consistency**, not fake Workflow Studio ids.  
5. Remove `klints-data` from Spotlight in the same PR as the API wire-up.
