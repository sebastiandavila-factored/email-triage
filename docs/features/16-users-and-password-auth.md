# Feature 16 — Users + Password Auth + Role-Scoped Security

## Summary

Separates the *person* (`User`) from the *workspace* (`Tenant`) and adds email + password signup alongside Google SSO. Every user automatically receives a **personal workspace** on signup — no domain detection needed. A `Membership` row links users to workspaces with a `role` (`owner`, `admin`, `member`). Each role maps to a set of OAuth2 scopes enforced via FastAPI's `Security(get_current_user, scopes=[...])` dependency. Programmatic callers using `X-API-Key` are unaffected.

## Data model

### User

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | TEXT UNIQUE | |
| `display_name` | TEXT | |
| `password_hash` | TEXT NULL | null for Google-only users |
| `google_sub` | TEXT UNIQUE NULL | null for password-only users |
| `email_verified` | BOOL | auto-true for Google; false until verified for password signup |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

### Tenant (workspace)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | existing UUIDs preserved through migration |
| `domain` | TEXT UNIQUE NULL | null for personal workspaces; company domain for team |
| `name` | TEXT | e.g. `"Alice's workspace"` or `"Acme"` |
| `type` | TEXT | `personal` \| `team` |
| `plan` | TEXT | `free` \| `pro` |
| `api_key_hash` | TEXT NULL | bcrypt hash of the API key |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

### Membership

| Column | Type | Notes |
|---|---|---|
| `user_id` | UUID FK → users | CASCADE delete |
| `tenant_id` | UUID FK → tenants | CASCADE delete |
| `role` | TEXT | `owner` \| `admin` \| `member` |
| `created_at` | TIMESTAMPTZ | |

PK is `(user_id, tenant_id)`.

## Role → Scope mapping

| Role | Scopes |
|---|---|
| `owner` | `triage:write` `workspace:manage` `workspace:delete` |
| `admin` | `triage:write` `workspace:manage` |
| `member` | `triage:write` |

Personal workspace users always hold the `owner` role (all scopes).

## Endpoints

| Method | Path | Required scope | Description |
|---|---|---|---|
| `POST` | `/auth/signup` | — | email + password → User + personal Tenant + Membership + session cookie + api_key |
| `POST` | `/auth/login` | — | email + password → bcrypt verify → session cookie |
| `GET` | `/auth/login` | — | Unchanged — redirects to Google |
| `GET` | `/auth/callback` | — | Updated — creates/finds User; creates personal Tenant + Membership |
| `GET` | `/auth/me` | *(any authenticated)* | `{user_id, email, display_name, email_verified, tenant_id, tenant_name, tenant_type, plan, role}` |
| `POST` | `/auth/logout` | *(any authenticated)* | Clears session cookie |
| `POST` | `/auth/rotate-key` | `workspace:manage` | Rotates Tenant api_key_hash |

## New files

| Path | Role |
|---|---|
| `email_triage/auth/scopes.py` | Scope string constants + `ROLE_SCOPES: dict[str, frozenset[str]]` |
| `email_triage/db/repos/users.py` | `UserRepo`: get_by_email, get_by_google_sub, create_with_password, create_from_google, get_membership |
| `alembic/versions/0002_users_and_tenants.py` | Migration: create users + memberships; reshape tenants; migrate existing rows as personal workspaces |

## Modified files

| Path | Change |
|---|---|
| `email_triage/db/models.py` | Add `User`, `Membership`; add `type` + nullable `domain` on `Tenant`; drop `email`/`google_sub`/`display_name` from `Tenant` |
| `email_triage/db/repos/tenants.py` | Add `create_personal`; remove `upsert_from_google` |
| `email_triage/deps.py` | Add `SessionContext` dataclass + `get_current_user(SecurityScopes, ...)` |
| `email_triage/routers/auth.py` | New endpoints; callback + me use `get_current_user`; `rotate-key` uses `Security(..., scopes=["workspace:manage"])` |

## Signup flow (email + password)

```
POST /auth/signup  {email, password, display_name}
  → validate: email format, password ≥ 8 chars
  → get_by_email → 409 Conflict if duplicate
  → bcrypt.hashpw(password, gensalt(rounds=12)) via asyncio.to_thread
  → INSERT users (email_verified = FALSE)
  → INSERT tenants (type='personal', domain=NULL, name="{display_name}'s workspace")
  → INSERT memberships (role='owner')
  → generate api_key → bcrypt hash → store in tenant
  → set session cookie (user_id, HttpOnly, SameSite=Lax, 24 h)
  → return {email, display_name, tenant_id, tenant_type, plan, api_key}
```

## Login flow (email + password)

```
POST /auth/login  {email, password}
  → get_by_email → 401 if not found (same message as wrong password — no user enumeration)
  → if password_hash is NULL → 401 "Use Google SSO for this account"
  → bcrypt.checkpw(password, password_hash) via asyncio.to_thread → 401 if mismatch
  → get_membership → 401 if none
  → set session cookie
  → return {email, display_name, tenant_id, tenant_type, plan, role}
```

## Google SSO flow (updated)

```
GET /auth/callback?code=X&state=Y
  → verify PKCE state (unchanged)
  → exchange code → id_token → {sub, email, name}
  → get_by_google_sub → create_from_google if new (email_verified = TRUE)
  → get_membership → if none: create personal Tenant + Membership (role='owner')
  → if tenant is new: generate api_key → bcrypt hash → store in tenant
  → set session cookie (user_id)
  → return JSON {email, display_name, plan, api_key (only if new tenant)}
```

## FastAPI Security dependency

```python
# email_triage/deps.py
from fastapi.security import SecurityScopes

async def get_current_user(
    security_scopes: SecurityScopes,
    session_cookie: Annotated[str | None, Cookie(alias="session")] = None,
    settings: SettingsDep = ...,
) -> SessionContext:
    user_id = unsign_session(settings.session_secret, session_cookie or "")
    if user_id is None:
        raise HTTPException(401, ...)
    # load user + membership from DB
    user_scopes = ROLE_SCOPES.get(membership.role, frozenset())
    for scope in security_scopes.scopes:
        if scope not in user_scopes:
            raise HTTPException(403, detail=f"Scope required: {scope}")
    return SessionContext(user_id=..., tenant_id=..., role=..., email=...)

# Type aliases for router use
CurrentUserDep     = Annotated[SessionContext, Security(get_current_user, scopes=[])]
ManageWorkspaceDep = Annotated[SessionContext, Security(get_current_user, scopes=["workspace:manage"])]
```

## Security notes

| Control | Detail |
|---|---|
| Password hashing | `bcrypt` rounds=12, `asyncio.to_thread` — never blocks event loop |
| User enumeration | 401 "invalid credentials" for both unknown email and wrong password |
| Google-only accounts | `POST /auth/login` returns 401 with SSO hint — never reveals that `password_hash` is NULL |
| Scope enforcement | `SecurityScopes.scopes` populated at route definition; 403 includes the missing scope name |
| Session cookie | `HttpOnly`, `SameSite=Lax`, `Secure` (production), 24 h TTL — unchanged from Plan 15 |
| Email verification | Flag stored, not enforced — allows future gating without re-migration |
