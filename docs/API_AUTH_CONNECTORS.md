# Auth + Connectors API

Implement in **`tenants/`** only. Base: `/api/v1/`  
JWT access only (no refresh). Verify = one `POST`.  
Packages: `djangorestframework-simplejwt`, `cryptography`

---

## Endpoints

| Method | Path | Auth | Action |
|--------|------|------|--------|
| `POST` | `/auth/register/` | — | Create tenant, company, user · send verify email |
| `POST` | `/auth/verify-email/` | — | Body `{ token, email }` · activate user |
| `POST` | `/auth/login/` | — | Return `{ access, user, connectors, needs_connector }` |
| `POST` | `/auth/resend-verification/` | — | Resend verify email |
| `GET` | `/auth/me/` | Bearer | Current user + tenant + company |
| `POST` | `/connectors/` | Bearer | Add Manago.ai |
| `GET` | `/connectors/` | Bearer | List company connectors |

Header on protected routes: `Authorization: Bearer <access>`

---

## Settings (`core/settings/base.py`)

```python
INSTALLED_APPS += ["rest_framework_simplejwt"]

AUTH_USER_MODEL = "tenants.User"

REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] = [
    "rest_framework_simplejwt.authentication.JWTAuthentication",
    "rest_framework.authentication.SessionAuthentication",
]

from datetime import timedelta
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CONNECTOR_FERNET_KEY = env("CONNECTOR_FERNET_KEY")
FRONTEND_VERIFY_URL = env("FRONTEND_VERIFY_URL", default="http://localhost:5173/verify-email")
EMAIL_VERIFICATION_TTL_HOURS = env.int("EMAIL_VERIFICATION_TTL_HOURS", default=24)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@klints.ai")
```

`.env`:

```env
FRONTEND_VERIFY_URL=http://localhost:5173/verify-email
EMAIL_VERIFICATION_TTL_HOURS=24
DEFAULT_FROM_EMAIL=noreply@klints.ai
CONNECTOR_FERNET_KEY=
```

Generate key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

---

## Tables (`tenants/models.py` · set `db_table`)

**`users`** (`AUTH_USER_MODEL`)  
`id` uuid · `email` unique · `name` · `password` · `tenant_id` → `tenants` · `role` (`admin`/`analyst`/`viewer`) · `email_verified` bool · `is_active` bool · `created_at` · `updated_at`

**`companies`**  
`id` uuid · `tenant_id` → `tenants` · `name` · `domain` · `created_at`

**`email_verification_tokens`**  
`id` uuid · `user_id` → `users` · `email` · `token` unique · `expires_at` · `used_at` null · `created_at`

**`connectors`**  
`id` uuid · `company_id` → `companies` · `name` · `type` · `config` jsonb · `status` · `created_at` · `updated_at`  
Unique: `(company_id, name)`. Encrypt `config.api_key`.

**`connector_snapshots`**  
`id` uuid · `connector_id` → `connectors` · `version` int · `snapshot_data` jsonb · `created_at`

Keep existing `tenants` model. Migrate after models.

---

## URLs (`core/urls.py`)

```python
path("api/v1/tenants/", include("tenants.urls")),
path("api/v1/dataruns/", include("dataruns.urls")),
path("api/v1/auth/", include("tenants.auth_urls")),
path("api/v1/connectors/", include("tenants.connector_urls")),
```

Files: `tenants/auth_views.py`, `auth_urls.py`, `connector_views.py`, `connector_urls.py`, `emails.py`, `crypto.py`

---

## 1. `POST /auth/register/`

**Request**

```json
{
  "email": "george@lumera.skin",
  "password": "Str0ngPass!word",
  "name": "George L.",
  "company_name": "Lumera Skin",
  "company_domain": "lumera.skin",
  "tenant_name": "Lumera Skin"
}
```

`tenant_name` optional → default `company_name`.

**Transaction**

1. Insert `tenants`
2. Insert `companies`
3. Insert `users` (`role=admin`, `email_verified=false`, `is_active=false`)
4. Insert `email_verification_tokens` (`secrets.token_urlsafe(32)`, expires +24h)
5. Email link: `{FRONTEND_VERIFY_URL}?token=...&email=...`
6. Return `201` — no JWT, no token in body

**201**

```json
{
  "detail": "Account created. Check your email to verify before signing in.",
  "user": {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "email": "george@lumera.skin",
    "name": "George L.",
    "role": "admin",
    "email_verified": false,
    "tenant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "created_at": "2026-07-14T10:00:00Z"
  },
  "tenant": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "Lumera Skin",
    "slug": "lumera-skin"
  },
  "company": {
    "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "name": "Lumera Skin",
    "domain": "lumera.skin",
    "tenant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
  }
}
```

**400:** `{ "email": ["A user with this email already exists."] }`

---

## 2. `POST /auth/verify-email/`

Frontend reads `token` + `email` from the link query and POSTs them.

**Request**

```json
{
  "token": "v3r1fy_TokEn_abcXYZ0123456789",
  "email": "george@lumera.skin"
}
```

**Logic**

1. Find `email_verification_tokens` by `token` + `email`
2. Fail if missing, `used_at` set, or past `expires_at`
3. Set `users.email_verified=true`, `users.is_active=true`
4. Set `email_verification_tokens.used_at=now()`
5. Return `200` — no JWT

**200**

```json
{
  "detail": "Email verified. You can sign in.",
  "email": "george@lumera.skin",
  "email_verified": true
}
```

**400:** `{ "detail": "Invalid or expired verification link." }`

---

## 3. `POST /auth/login/`

**Request**

```json
{
  "email": "george@lumera.skin",
  "password": "Str0ngPass!word"
}
```

**Logic**

- Bad credentials → `401`
- `email_verified=false` → `403` `{ "detail": "...", "code": "email_not_verified" }`
- OK → access token + user + company connectors (masked secrets)
- Set `needs_connector=true` when the company has **zero** rows in `connectors` (or none with `status=connected`)
- Frontend: if `needs_connector` → send user to Add Connector; else → app home

**200 — no connectors yet**

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "needs_connector": true,
  "user": {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "email": "george@lumera.skin",
    "name": "George L.",
    "role": "admin",
    "email_verified": true,
    "tenant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "company_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
  },
  "connectors": []
}
```

**200 — has connected connector(s)**

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "needs_connector": false,
  "user": {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "email": "george@lumera.skin",
    "name": "George L.",
    "role": "admin",
    "email_verified": true,
    "tenant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "company_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
  },
  "connectors": [
    {
      "id": "c56a4180-65aa-42ec-a945-5fd21dec0538",
      "name": "manago_ai",
      "type": "cdp",
      "display_name": "Manago.ai",
      "status": "connected",
      "config": {
        "base_url": "https://app2.manago.ai",
        "workspace_id": "ws_lumera_prod_eu",
        "api_key": "mnago_live_sk_****",
        "region": "eu"
      },
      "created_at": "2026-07-14T10:15:00Z"
    }
  ]
}
```

`needs_connector` = `true` when `connectors` is empty (or no `status=connected`). On later `401`, frontend sends user to login again.
---

## 4. `POST /auth/resend-verification/`

**Request:** `{ "email": "george@lumera.skin" }`

Always `200`:

```json
{ "detail": "If an account exists and is unverified, a new link has been sent." }
```

If unverified user exists: invalidate old unused tokens, create new token, send email.

---

## 5. `GET /auth/me/`

**200**

```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "email": "george@lumera.skin",
  "name": "George L.",
  "role": "admin",
  "email_verified": true,
  "tenant": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "Lumera Skin",
    "slug": "lumera-skin"
  },
  "company": {
    "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "name": "Lumera Skin",
    "domain": "lumera.skin"
  }
}
```

---

## 6. `POST /connectors/`

Auth: JWT · role `admin` or `analyst` only.  
Use user’s company — do not accept `company_id` from body.

**Request**

```json
{
  "name": "manago_ai",
  "type": "cdp",
  "display_name": "Manago.ai",
  "config": {
    "workspace_id": "ws_lumera_prod_eu",
    "api_key": "mnago_live_sk_****************",
    "a2a_endpoint": "https://a2a.manago.ai/v1",
    "scopes": ["contacts.read", "contacts.write", "segments.read", "workflows.read"],
    "region": "eu"
  }
}
```

Required `config`: `workspace_id`, `api_key`.

The backend sets `base_url` to `https://app2.manago.ai` automatically (`MANAGO_API_BASE_URL`); clients must not send `endpoint` or `base_url`.

**Logic**

1. Require `name=manago_ai`
2. Encrypt `api_key` · insert `connectors` · `status=connected`
3. If `(company_id, manago_ai)` exists → `409`
4. Insert `connector_snapshots` v1 without secrets
5. Response masks `api_key` as `****`

**201**

```json
{
  "id": "c56a4180-65aa-42ec-a945-5fd21dec0538",
  "company_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "name": "manago_ai",
  "type": "cdp",
  "display_name": "Manago.ai",
  "status": "connected",
  "config": {
    "base_url": "https://app2.manago.ai",
    "workspace_id": "ws_lumera_prod_eu",
    "api_key": "mnago_live_sk_****",
    "a2a_endpoint": "https://a2a.manago.ai/v1",
    "scopes": ["contacts.read", "contacts.write", "segments.read", "workflows.read"],
    "region": "eu"
  },
  "snapshot": {
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "version": 1,
    "created_at": "2026-07-14T10:15:00Z"
  },
  "created_at": "2026-07-14T10:15:00Z"
}
```

**403** viewer · **409** already connected · **400** missing `config` fields

---

## 7. `GET /connectors/`

Company-scoped list. Mask secrets. Paginated.

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "c56a4180-65aa-42ec-a945-5fd21dec0538",
      "name": "manago_ai",
      "type": "cdp",
      "display_name": "Manago.ai",
      "status": "connected",
      "config": {
        "base_url": "https://app2.manago.ai",
        "workspace_id": "ws_lumera_prod_eu",
        "api_key": "mnago_live_sk_****",
        "region": "eu"
      },
      "created_at": "2026-07-14T10:15:00Z"
    }
  ]
}
```

---

## 7b. Manago owners / primary (FD-06)

After Manago is connected, frontend should call this before relying on DCS scores.

### `GET /api/v1/connectors/manago_ai/owners/`

Lists Manago users (`listByClient`) and whether the tenant must pick a primary.

**200**
```json
{
  "platform": "manago_ai",
  "connector_id": "…",
  "owners": [
    {"email": "noreply@example.com", "is_primary": true},
    {"email": "other@example.com", "is_primary": false}
  ],
  "primary_owner": "noreply@example.com",
  "owner_count": 2,
  "needs_primary_selection": false,
  "topology_configured": true
}
```

- If **1** owner and none saved yet → backend **auto-selects** primary (admin/analyst GET).
- If **2+** and no primary → `needs_primary_selection: true` → show picker.

### `PUT /api/v1/connectors/manago_ai/owners/`

Admin/analyst. Body:
```json
{ "owner": "noreply@example.com" }
```

Writes `config.owner` + `config.topology` (chosen in scope; others `in_scope: false`). Same response shape as GET.

`GET /connectors/` Manago items also include `primary_owner` and `topology_configured`.

---

## Implement order

1. Settings + packages + `AUTH_USER_MODEL`
2. Models + migrate
3. Register → verify → login → resend → me
4. Connectors create + list (Fernet)
