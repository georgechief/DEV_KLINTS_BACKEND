# PRD-AUTH-01 — Capture company website on signup

**Status:** Ready for implementation  
**Depends on:** existing `POST /api/v1/auth/register/` + `Company.domain` (`tenants/models.py`); workspace domain normalize helper (`tenants/workspace/services.py`)  
**Repos:** `klints_frontend` signup form + small register normalization on backend  
**Scope:** collect customer website at account creation and persist it on the tenant’s company; no new DB column

## 1. Problem

Register already requires `company_domain` and writes it to `companies.domain` (the tenant’s company). Settings already edits that field as **Website**.

Signup today **does not ask the user** — it hardcodes a stub:

```ts
// klints_frontend/src/routes/signup.tsx
company_domain: "localhost",
```

So every new workspace gets a fake domain until an admin fixes it in Settings. Downstream product (tenant identity, future DCS/email/reporting) should start with the real customer website.

## 2. Goal

1. On **Create workspace** (`/signup`), collect a required **Website** (customer site / brand domain).
2. Send it as `company_domain` on `POST /api/v1/auth/register/`.
3. Persist normalized value on **`Company.domain`** for that new tenant’s company.
4. Align register normalization with workspace PATCH so signup and Settings store the same shape (e.g. `lumera.skin`, not `https://Lumera.skin/`).

## 3. Source of truth (current code)

| Artifact | Path / field |
|----------|----------------|
| Storage | `Company.domain` (`tenants.models.Company`) — one company per new signup tenant |
| Register API | `POST /api/v1/auth/register/` — body field `company_domain` (already required) |
| Register impl | `tenants/auth_views.py` → `RegisterView` — creates `Tenant` + `Company` + admin `User` |
| Normalize helper | `normalize_company_domain` in `tenants/workspace/services.py` (used by workspace PATCH today; **not** used by register yet) |
| Settings edit | `klints_frontend/src/routes/settings.tsx` — label **Website** → `company_domain` |
| FE bug | `klints_frontend/src/routes/signup.tsx` hardcodes `"localhost"` |

**Do not** add a separate `website` column on `Tenant` or `Company`. Website ≡ company domain.

## 4. Product rules

| Rule | Decision |
|------|----------|
| Required on signup | **Yes** — cannot create account without website |
| Where stored | `Company.domain` for the company created in the register transaction |
| Label in UI | **Website** (match Settings) |
| Placeholder example | `https://lumera.skin` or `lumera.skin` |
| Unique across companies | **No** (same domain may appear for different tenants; out of scope) |
| Editable later | Yes — existing Settings / `PATCH` workspace (`company_domain`) |
| Invited users | Out of scope — invites join an existing company; they do not set website at register |

## 5. Normalization & validation

Reuse / share `normalize_company_domain`:

```text
strip → lowercase → strip leading http:// or https:// → strip trailing /
```

Examples:

| Input | Stored |
|-------|--------|
| `https://Lumera.skin/` | `lumera.skin` |
| `http://www.example.com` | `www.example.com` |
| `lumera.skin` | `lumera.skin` |

**Register must normalize before save** (today it stores the raw string). Prefer calling the same helper as workspace so behavior cannot drift.

**Reject (400)** after normalize if:

- empty / whitespace only
- longer than 255 chars
- contains whitespace
- looks like a path-only value with no host (optional hardening: require at least one `.` in host, e.g. reject `localhost` for new signups)

Recommended reject for product quality:

```text
normalized in {"localhost", "127.0.0.1"} → 400 company_domain invalid
```

Error shape (match existing field errors):

```json
{ "company_domain": ["Enter a valid website or domain."] }
```

FE should mirror: required + basic client check (non-empty; optionally warn if no `.`).

## 6. Backend contract

### `POST /api/v1/auth/register/`

Unchanged request shape (already documented in `docs/API_AUTH_CONNECTORS.md`):

```json
{
  "email": "george@lumera.skin",
  "password": "Str0ngPass!word",
  "name": "George L.",
  "company_name": "Lumera Skin",
  "company_domain": "https://lumera.skin",
  "tenant_name": "Lumera Skin"
}
```

Changes vs today:

1. Normalize `company_domain` before `Company.objects.create(...)`.
2. Validate normalized value (reject empty / localhost stub / invalid).
3. `201` response `company.domain` is the **normalized** value.

No new endpoint. No migration if `Company.domain` already exists.

### `/auth/me/` and workspace

No change required — `company.domain` already returned. After signup + verify + login, Settings should show the website the user entered.

## 7. Frontend behavior

File: `klints_frontend/src/routes/signup.tsx`

1. Add state `companyWebsite` (or `companyDomain`).
2. Add form field after **Company**, label **Website**, placeholder e.g. `lumera.skin` or `https://lumera.skin`, `autoComplete="url"`, icon `Globe` (or existing design system equivalent).
3. Client validation: include website in “all fields required”.
4. Submit body:

```ts
{
  email,
  password,
  name,
  company_name: companyName,
  company_domain: companyWebsite.trim(),
}
```

5. **Remove** the hardcoded `company_domain: "localhost"`.
6. Surface API `company_domain` field errors in the existing error banner (same as other fields).

Optional: light client normalize for UX (strip protocol) before send; server remains authoritative.

## 8. Acceptance scenarios

| # | Scenario | Expect |
|---|----------|--------|
| 1 | User signs up with Website `https://Lumera.skin/` | `Company.domain == "lumera.skin"`; Settings shows that website |
| 2 | User omits Website | FE blocks submit; if API called empty → `400` on `company_domain` |
| 3 | User tries `localhost` | `400` (if BE reject rule shipped) |
| 4 | Existing Settings edit of Website | Unchanged; still updates same `Company.domain` |
| 5 | Old accounts that registered with `localhost` | Unchanged; admin can fix in Settings (no backfill required in this PRD) |

## 9. Out of scope

- New `website` column on Tenant/Company
- Enforcing global uniqueness of company domains
- Scraping / verifying that the website resolves
- Changing invite accept flow
- Auto-deriving domain from email (`@lumera.skin` → `lumera.skin`) as a substitute for the field (nice-to-have later; not required)

## 10. Implementation checklist

### Backend

- [ ] In `RegisterView`, normalize via `normalize_company_domain` (shared helper)
- [ ] Validate normalized domain; reject empty / `localhost` / `127.0.0.1`
- [ ] Persist normalized value on `Company.domain`
- [ ] Tests: register stores normalized domain; rejects missing / localhost

### Frontend

- [ ] Website field on `/signup`
- [ ] Send real `company_domain`; remove `"localhost"` stub
- [ ] Required-field + API error handling

### Docs / series

- [ ] Indexed in `docs/maheep/README.md` (this PRD)
