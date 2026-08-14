# PRD-FE-02 — Onboarding route guard (signed in + no connectors)

**Status:** Ready for implementation  
**Repos:** `klints_frontend` (+ small backend flag optional)  
**Depends on:** [PRD_FE_01_SIGNIN_ROUTE_GUARD.md](./PRD_FE_01_SIGNIN_ROUTE_GUARD.md)  
**Related backend:** login `needs_connector`, `GET /api/v1/connectors/`

## 1. Problem

`/onboarding` (`src/routes/onboarding.tsx`) currently has **no** `beforeLoad` auth/connector guard:

```ts
export const Route = createFileRoute("/onboarding")({
  head: () => ({ meta: [{ title: "Connect your stack — Klints" }] }),
  component: Onboarding,
});
```

Root `beforeLoad` calls `requireAuth` for non-public paths, and `/onboarding` is **not** in `PUBLIC_ROUTES`, so unsigned users are sent to `/signin`. Good.

Missing:

1. Signed-in users who **already have a connected connector** can still open `/onboarding` and reconnect / confuse the funnel.  
2. No explicit “must be signed in” documentation at the route level (relies only on root).

## 2. Goal

`/onboarding` is a **protected, first-time connect** route:

| User state | `/onboarding` behavior |
|------------|------------------------|
| Not signed in | Redirect `/signin` |
| Signed in, **no** connected connector | Show onboarding |
| Signed in, **has** connected connector (`connected` or `degraded`) | Redirect `/dashboard` |

Integrations page remains the place to add/reconnect after onboarding.

## 3. Process

```text
Navigate /onboarding
  → beforeLoad requireOnboarding()
  → no token → redirect /signin
  → GET /auth/me/ (or rely on requireAuth already run)
  → resolve needs_connector (same rule as FE-01)
  → if needs_connector === false → redirect /dashboard
  → else allow Onboarding component
```

Share `resolveAppHomePath` / `needsConnector` helper from FE-01 so sign-in and onboarding never disagree.

## 4. Code changes

### Frontend

| File | Change |
|------|--------|
| `src/lib/auth.ts` | Add `requireOnboarding()` |
| `src/routes/onboarding.tsx` | `beforeLoad: () => requireOnboarding()` |

```ts
export async function requireOnboarding() {
  if (typeof window === "undefined") return;
  if (!isAuthenticated()) {
    throw redirect({ to: "/signin" });
  }
  const home = await resolveAppHomePath();
  if (home === "/dashboard") {
    throw redirect({ to: "/dashboard" });
  }
}
```

### After successful first connect

Existing flows already leave onboarding (Shopify redirect `return_to`, Manago success navigate). No change required beyond guards.

When the **last** connector is disconnected (`needs_connector: true` from delete response), user may return to onboarding — **allowed**.

## 5. Edge cases

| Case | Expected |
|------|----------|
| User mid-OAuth, returns to onboarding URL with session | If connector now `connected` → dashboard; else stay |
| Only connector `status=error` | Treat as needs onboarding / reconnect → **allow** onboarding (or Integrations — product: allow onboarding) |
| Analyst vs admin | Same guard; connect APIs already enforce roles |

**Locked:** `error`-only or no rows → allow onboarding.  
`connected` / `degraded` → block onboarding → dashboard.

## 6. Acceptance

1. Signed-out `/onboarding` → `/signin`.  
2. Signed-in, zero connectors → onboarding renders.  
3. Signed-in, Manago or Shopify `connected` → `/dashboard` (no flash of onboarding form if avoidable).  
4. After disconnect last connector, `/onboarding` works again.  
5. Integrations page still reachable when connectors exist (not forced through onboarding).

## 7. Out of scope

- Multi-step onboarding wizard persistence  
- Blocking Integrations until both Shopify + Manago exist  
- Backend middleware that rejects HTML — this is FE routing only
