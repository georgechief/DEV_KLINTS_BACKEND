# PRD-FE-01 — Sign-in route guard (redirect if already signed in)

**Status:** Ready for implementation  
**Repos:** `klints_frontend`  
**Depends on:** `GET /api/v1/auth/me/`, login `needs_connector`, connectors list  
**Related:** [PRD_FE_02_ONBOARDING_ROUTE_GUARD.md](./PRD_FE_02_ONBOARDING_ROUTE_GUARD.md)

## 1. Problem

`/signin` uses `beforeLoad: () => requireGuest()` (`src/routes/signin.tsx`).

Current `requireGuest()` in `src/lib/auth.ts`:

1. If access token exists and `/api/v1/auth/me/` is OK → **always** `redirect({ to: "/dashboard" })`
2. It ignores whether the company still needs a connector

Also: after a successful **login submit**, navigation is already correct:

```ts
to: data.needs_connector === true ? "/onboarding" : "/dashboard"
```

The bug is only for **already signed-in** users who visit `/signin` (bookmark, back button, etc.).

## 2. Goal

`/signin` remains a **guest** route:

- Signed **out** → show sign-in form  
- Signed **in** → never stay on sign-in; redirect:
  - **No connected connector** → `/onboarding`
  - **At least one connected connector** → `/dashboard`

## 3. Definition: “connector connected”

Match backend login logic (`tenants/auth_views.py`):

```text
needs_connector = not any(c.status == "connected" for c in company.connectors)
```

So:

| Condition | Destination |
|-----------|-------------|
| No company / no connectors / none `status=="connected"` | `/onboarding` |
| Any connector with `status=="connected"` | `/dashboard` |

Treat `degraded` as **connected for routing** (user already onboarded; send to dashboard). Only pure absence of a usable connect counts as onboarding.

**Locked rule for this PRD:**

- `connected` **or** `degraded` → dashboard  
- otherwise → onboarding  

(Align FE helper with this; if product prefers only `connected`, document in one place — recommended: both count.)

## 4. Process

```text
User navigates to /signin
  → beforeLoad requireGuest()
  → no access_token → allow page
  → access_token present
       → GET /api/v1/auth/me/  (must be 200)
       → if 401/403 → clearAuth(), allow sign-in page
       → GET /api/v1/connectors/  (or embed needs_connector on /me later)
       → if any connector status in {connected, degraded}
            → redirect /dashboard
         else
            → redirect /onboarding
```

### 4.1 Prefer extending `/auth/me/` (optional but cleaner)

Today `/auth/me/` does not return `needs_connector`. Login does.

**Option A (FE-only, faster):** after `/me` OK, call `GET /api/v1/connectors/`.  
**Option B (better):** add `needs_connector: bool` to `/auth/me/` using the same logic as login.

This PRD accepts either; Option B avoids a second round-trip and keeps one source of truth.

## 5. Code changes

### Frontend

| File | Change |
|------|--------|
| `src/lib/auth.ts` | Update `requireGuest()` to choose onboarding vs dashboard |
| `src/lib/auth.ts` | Optional helper `resolvePostAuthPath(needsConnector \| connectors)` |
| `src/routes/signin.tsx` | Keep `beforeLoad: requireGuest` (behavior changes via helper) |

Suggested helper:

```ts
export async function requireGuest() {
  // ... validate token via /auth/me/
  // path = await resolveAppHomePath()  // /onboarding | /dashboard
  throw redirect({ to: path });
}

export async function resolveAppHomePath(): Promise<"/onboarding" | "/dashboard"> {
  // needs_connector from /me or connectors list
}
```

Reuse `resolveAppHomePath` from login success and invite accept for consistency.

### Backend (if Option B)

| File | Change |
|------|--------|
| `tenants/auth_views.py` (or `tenants/auth/views.py` Me view) | Include `needs_connector` boolean |
| Auth tests | Assert true/false with/without connected connector |

## 6. Acceptance

1. Signed-out user opens `/signin` → form visible.  
2. Signed-in user, **no** connected connector, opens `/signin` → lands on `/onboarding`.  
3. Signed-in user, Shopify or Manago `connected`, opens `/signin` → lands on `/dashboard`.  
4. Stale token → cleared, sign-in form shown (no redirect loop).  
5. Fresh login submit still uses `needs_connector` (regression).

## 7. Out of scope

- Changing signup/verify redirects (unless they share the same helper)  
- Role-based landing (admin vs analyst)  
- Forcing onboarding when connectors exist but bootstrap failed (`error`) — those users go dashboard and fix via Integrations
