# PRD-FE-07 — Onboarding Manago API v3 key + Settings honesty

**Status:** Ready for implementation  
**Module:** see folder path  
**Depends on:** CONN-06 APIs + `ManagoApiV3KeySection` (already on `/integrations`); Settings Account / Workspace / Team already live  
**Surfaces:** `/onboarding` · `/settings`  
**Out of scope:** CONN-07 primary owner · Data Center Re-run (FE #17) · Lifecycle / Architecture · building real Klints API-key or Billing backends  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-FE-07 (frontend only — reuse existing CONN-06 APIs).

Read: docs/frontend/PRD_FE_07_ONBOARDING_V3_AND_SETTINGS_HONESTY.md

Part A — Onboarding Manago API v3 (after connect):
1. After successful Manago connect on /onboarding, do NOT jump straight home.
2. Show a short “Add API v3 key” step (optional but recommended).
3. Reuse setManagoApiV3Key / same UX copy as ManagoApiV3KeySection (or extract shared component).
4. Skip → goToAppHomeAfterConnect(); Save success → toast + go home.
5. Copy must say step is optional AND note that Manago’s Shopify integration
   must be installed in Manago (separate from Klints Shopify OAuth).
6. Do not change Shopify onboarding OAuth flow.

Part B — Settings honesty:
1. Account, Workspace, Team stay LIVE (existing APIs). No regressions.
2. Replace fake API keys + Billing chrome with Coming soon empty states (no Rotate toast, no fake Growth plan).
3. Timezone on Account stays read-only placeholder OR label “Coming soon” — do not invent a timezone API.
4. Optional: badge “Soon” on API keys / Billing tabs.

Acceptance: checklist in §8.
```

---

## 1. Product decisions (locked)

### 1.1 Settings — what stays live vs static

| Tab / field | v1 decision | Notes |
|-------------|-------------|--------|
| **Account** — name, email, role | **Live** | Existing `GET/PATCH` me |
| **Account** — change password, sign out | **Live** | Existing APIs |
| **Account** — Timezone | **Static / non-editable** | Today hardcodes `Europe/Berlin (CET)`. Keep as read-only display **or** “Timezone · Coming soon”. **No** timezone API in this PRD |
| **Workspace** — tenant / company / domain | **Live** | Admin-only mutate (already) |
| **Team** — members, invites, roles | **Live** | Existing team APIs |
| **API keys** | **Coming soon** (static empty) | Remove fake Production/Staging keys + Rotate toasts |
| **Billing** | **Coming soon** (static empty) | Remove fake Growth / invoice / card chrome |

**Answer to “rest should be live?”:** Yes — **Account (except timezone), Workspace, and Team stay live.** Only **API keys** and **Billing** become honest empty “Coming soon” surfaces. Do not hide those tabs unless design prefers hide; default = keep tabs, empty state inside.

### 1.2 Onboarding v3 key

- **Optional** step after Manago connect (user can **Skip for now**).  
- Same backend as CONN-06: `PUT /api/v1/connectors/manago_ai/api-v3-key/`.  
- Goal: collect catalog key **before** first score when possible, without blocking connect if they skip (they can still add on `/integrations`).  
- **Must show a note** that catalog scoring also needs the **Manago ↔ Shopify integration installed inside Manago** (Manago’s own Shopify app / integration — not the Klints Shopify OAuth alone). Klints cannot install that for them; we guide only.

---

## 2. Why

| Gap | Problem |
|-----|---------|
| Onboarding | Merchants connect Manago with v2 client id + secret only, then land in app. Catalog checks (PT-01 / PT-03) stay weak until they discover v3 key on Connected stack |
| Settings | API keys + Billing look real (rotate, Growth €499, Visa) but are fixtures — erodes trust |

---

## 3. Part A — Onboarding flow

### 3.1 Today

```text
Manago form → verify → POST connector → toast → goToAppHomeAfterConnect()
```

No v3 key.

### 3.2 Target

```text
Manago form → verify → POST connector → toast “connected”
  → screen: “Add Manago API v3 key (recommended)”
       [paste key] [Save & continue]   [Skip for now]
  → home (dashboard / lock as today)
```

Shopify path unchanged (OAuth redirect).

### 3.3 UX copy (suggested)

```text
Manago.ai connected

Add an API v3 key (optional)
Recommended so Klints can read your Manago product catalog
for Data Consistency Score checks (PT-01 / PT-03).

You can skip and add this later under Connected stack.

How to get the key
1. In Manago → API access details → API v3, create a key and paste it below.
2. Also install Manago’s Shopify integration in Manago
   (Integrations / Apps → Shopify) so catalog and commerce data
   stay linked. Klints’ Shopify connect alone is not enough.

[ •••••••••• ]
[ Save & continue ]   [Skip for now]
```

**Locked notes on the step:**

| Note | Required? |
|------|-----------|
| Step is **optional** — Skip never blocked | Yes |
| Where to create API v3 key (Manago API v3, not v2 Client ID/Secret) | Yes |
| Install **Manago’s Shopify integration** inside Manago (operator action in Manago UI) | Yes — short callout / helper text |
| Klints Shopify OAuth is separate (other onboarding card) | Mention briefly so they don’t confuse the two |

Do **not** auto-detect whether Manago’s Shopify app is installed in v1 — copy-only guidance.

- Admin/analyst only can Save (same as Integrations). If viewer somehow hits onboarding — Skip only (edge).  
- Reuse `PasswordInput` + `setManagoApiV3Key` from `connectors.ts`.  
- Prefer extracting shared UI from `ManagoApiV3KeySection` (empty-state only) to avoid drift — optional if faster to inline once.  
- Optionally mirror a one-line Shopify-integration reminder on Integrations `ManagoApiV3KeySection` helper (nice-to-have; not required for this PRD).

### 3.4 Errors

- Save failure → inline error + `toast.error` (existing Sonner). Stay on step.  
- Skip always succeeds (navigate home).

---

## 4. Part B — Settings honesty

### 4.1 API keys tab

Replace fake list with empty state, e.g.:

```text
API keys
Programmatic access to Klints is not available yet.

Coming soon — we’ll notify workspace admins when keys ship.
```

No Rotate button. No fake `klt_prod_…` strings.

### 4.2 Billing tab

Replace fake plan cards with empty state, e.g.:

```text
Billing
Plan and invoicing are not available in this workspace yet.

Coming soon — your current pilot access is managed by Klints.
```

No fake €499, DCS points, or Visa.

### 4.3 Page chrome

- Page description may say “Account, workspace, and team” (drop “keys and billing” as live claims) or keep tabs listed with Soon.  
- Do **not** break `?tab=api-keys` / `?tab=billing` deep links — show Coming soon content.

### 4.4 Timezone

Leave field read-only with current string **or** change label to make non-live obvious. Do not wire a new API.

---

## 5. Backend

**No new endpoints.** Reuse:

| API | Use |
|-----|-----|
| `PUT /api/v1/connectors/manago_ai/api-v3-key/` | Onboarding Save |
| Existing auth / workspace / team | Unchanged Settings live tabs |

---

## 6. Explicitly out of scope

- Real Klints developer API keys product  
- Stripe / billing / entitlements  
- CONN-07 primary owner picker  
- Changing Integrations CONN-06 behavior (already shipped)  
- FE #17 Data Center Re-run  
- Architecture / Lifecycle  

---

## 7. Implementation notes

| Area | Touch |
|------|--------|
| `src/routes/onboarding.tsx` | Post-Manago-connect step state machine |
| `src/components/klints/ManagoApiV3KeySection.tsx` | Optional extract empty-state for reuse |
| `src/lib/connectors.ts` | Already has `setManagoApiV3Key` — reuse |
| `src/routes/settings.tsx` | Replace API keys + Billing sections; tweak copy; timezone honesty |

---

## 8. Acceptance checklist

### Onboarding

- [ ] After Manago connect, v3 step appears before home  
- [ ] Copy marks step **optional** / Skip available  
- [ ] Copy notes installing **Manago’s Shopify integration** in Manago (not only Klints Shopify)  
- [ ] Save calls CONN-06 PUT; success toast; then home  
- [ ] Skip goes home without PUT  
- [ ] Shopify connect path unchanged  
- [ ] Key still editable later on `/integrations`  

### Settings

- [ ] Account name/password/workspace/team still work against live APIs  
- [ ] API keys tab: no fake keys, no Rotate success toast  
- [ ] Billing tab: no fake plan/invoice/card  
- [ ] Timezone not presented as a saved live preference  
- [ ] Viewer/admin role behavior for Team/Workspace unchanged  

---

## 9. One-page summary

| Question | Answer |
|----------|--------|
| What? | Onboarding optional Manago v3 key step + honest Settings empty states |
| Live Settings? | **Account / Workspace / Team = live**; API keys + Billing = Coming soon; Timezone = static |
| New BE? | None |
| Reuse? | CONN-06 APIs + existing Settings APIs |
| Not this PRD? | Owner picker, Re-run, Billing product, API keys product |

**PRD:** FE-07 · **Track:** delivery · **After:** CONN-06 on Integrations (done)
