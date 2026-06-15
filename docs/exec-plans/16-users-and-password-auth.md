# 16. Users + Password Auth — User/Tenant Models + JWT Security

**Status:** ✅ delivered
**Estimate:** 6 hrs
**Depends on:** Plan 14 (PostgreSQL + SQLAlchemy), Plan 15 (Google OAuth2 SSO)

## Intent

Plan 15 conflated the *person* (who logs in) with the *tenant* (the paying organisation), and used a single static `API_KEY`. This plan separates the two concepts and adds email + password signup, following the B2B SaaS model used by GitHub, Vercel, and Linear.

**Three core ideas:**

1. **User** — the individual with credentials (email + password, Google OAuth, or both).
2. **Workspace** (`Tenant`) — the billing/API unit. Every user always gets a **personal workspace** auto-created on signup. Company workspaces are a future plan (Plan 17).
3. **Membership + Roles + Scopes** — a `Membership` row links a user to a workspace with a `role` (`owner`, `admin`, `member`). Each role maps to a set of OAuth2 scopes enforced via FastAPI's `Security(get_current_user, scopes=[...])` dependency — the pattern from the [FastAPI Advanced Security guide](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/).

The personal-workspace-first model removes the "gmail problem" entirely: domain is irrelevant at signup — every user owns their own workspace, and they can invite colleagues to a team workspace later (Plan 17).

All code, comments, and documentation produced by this plan are written in **English**.

## Prior reading

**JWT and Bearer tokens — primary references:**
- **RFC 7519 — JSON Web Token (JWT)** — https://datatracker.ietf.org/doc/html/rfc7519
- **PyJWT documentation** — https://pyjwt.readthedocs.io/en/stable/
- **FastAPI — OAuth2 with Password (and hashing), Bearer with JWT tokens** — https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- **FastAPI Advanced — OAuth2 scopes** — https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/
- **FastAPI — SecurityScopes** — https://fastapi.tiangolo.com/reference/security/#fastapi.security.SecurityScopes

**Password auth:**
- **OWASP Password Storage Cheat Sheet** — https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- **OWASP Authentication Cheat Sheet** — https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- **bcrypt Python library** — https://pypi.org/project/bcrypt/

**Role-based access control:**
- **OWASP Access Control Cheat Sheet** — https://cheatsheetseries.owasp.org/cheatsheets/Access_Control_Cheat_Sheet.html

**SQLAlchemy relationships:**
- **SQLAlchemy 2.x — Many-to-Many** — https://docs.sqlalchemy.org/en/20/orm/basic_relationships.html#many-to-many

**Existing plans (required reading):**
- [Plan 14 — PostgreSQL + SQLAlchemy](14-database-postgresql.md)
- [Plan 15 — Google OAuth2 SSO](15-auth-google-oauth2.md)

## Scope

**Included:**
- `User` model (email, password_hash nullable, google_sub nullable, email_verified)
- `Tenant` refactor: add `type` (`personal` | `team`), make `domain` nullable, preserve existing UUIDs
- `Membership` model: `user_id`, `tenant_id`, `role` (`owner` | `admin` | `member`)
- `email_triage/auth/scopes.py` — scope constants + `ROLE_SCOPES` mapping
- `email_triage/auth/session.py` — JWT creation + decoding with PyJWT (HS256, `sub` + `exp` + `iat`)
- Updated `deps.py` — `OAuth2PasswordBearer` + `SecurityScopes`-aware `get_current_user` → `SessionContext`
- Alembic migration `0002`: create users + memberships; reshape tenants; migrate existing rows as personal workspaces
- `POST /auth/signup` — email + password → User + personal Tenant + Membership → JWT access token
- `POST /auth/login` — email + password → bcrypt verify → JWT access token
- Updated `GET /auth/callback` (Google) — creates User + personal Tenant + Membership → JWT access token
- Updated `GET /auth/me` — reads Bearer token; returns User + Workspace context + role
- Protected endpoints use `Security(get_current_user, scopes=[...])`; client sends `Authorization: Bearer <token>`
- Tests for all new endpoints; existing tests remain green

**Out of scope:**
- Team workspace creation (`POST /workspaces`) — Plan 17
- Inviting members to a team workspace — Plan 17
- Email sending (verification link, password reset)
- Token refresh / refresh tokens
- Frontend / UI

## Data model

```
User
  id              UUID PK
  email           TEXT UNIQUE NOT NULL
  display_name    TEXT NOT NULL
  password_hash   TEXT NULL          — null for Google-only users
  google_sub      TEXT UNIQUE NULL   — null for password-only users
  email_verified  BOOL NOT NULL DEFAULT FALSE
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()

Tenant  (replaces old Tenant schema)
  id              UUID PK            — existing UUIDs preserved through migration
  domain          TEXT UNIQUE NULL   — null for personal workspaces; company domain for team
  name            TEXT NOT NULL      — display name ("Alice's workspace" or "Acme")
  type            TEXT NOT NULL DEFAULT 'personal'   — 'personal' | 'team'
  plan            TEXT NOT NULL DEFAULT 'free'
  api_key_hash    TEXT NULL          — bcrypt hash of the API key
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()

Membership
  user_id         UUID FK → users.id ON DELETE CASCADE
  tenant_id       UUID FK → tenants.id ON DELETE CASCADE
  role            TEXT NOT NULL DEFAULT 'owner'   — 'owner' | 'admin' | 'member'
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  PRIMARY KEY (user_id, tenant_id)
```

`TriageLog.tenant_id → tenants.id` is unchanged in semantics. Migration preserves existing tenant UUIDs so no `triage_logs` rows need to be updated.

## JWT token structure

Every access token is a signed HS256 JWT with the standard claims:

```json
{
  "sub": "uuid-of-the-user",
  "iat": 1234567890,
  "exp": 1234569690
}
```

- **`sub`** (subject) — identifies the user. Decoded to `uuid.UUID` in `get_current_user`.
- **`iat`** (issued at) — Unix timestamp when the token was created.
- **`exp`** (expiration) — Unix timestamp when the token expires. `PyJWT` rejects expired tokens automatically.
- **Algorithm**: `HS256` (HMAC-SHA256) signed with `settings.session_secret`.
- **Expiry**: `settings.access_token_expire_minutes` (default 30 min).

Clients send the token in every request:

```
Authorization: Bearer <jwt>
```

## Role → Scope mapping

```
Scope                Description
─────────────────────────────────────────────────────────────────
triage:write         Call POST /triage and POST /triage/stream
workspace:manage     Rotate API key, view workspace settings
workspace:delete     Delete the workspace (owner only)

Role       Scopes granted
────────────────────────────────────────────────────────────────
owner      triage:write  workspace:manage  workspace:delete
admin      triage:write  workspace:manage
member     triage:write
```

Personal workspace users always have the `owner` role (all scopes).

### FastAPI implementation pattern

```python
# email_triage/auth/scopes.py
TRIAGE_WRITE:       Final = "triage:write"
WORKSPACE_MANAGE:   Final = "workspace:manage"
WORKSPACE_DELETE:   Final = "workspace:delete"

ROLE_SCOPES: dict[str, frozenset[str]] = {
    "owner":  frozenset({TRIAGE_WRITE, WORKSPACE_MANAGE, WORKSPACE_DELETE}),
    "admin":  frozenset({TRIAGE_WRITE, WORKSPACE_MANAGE}),
    "member": frozenset({TRIAGE_WRITE}),
}
```

```python
# email_triage/auth/session.py
def create_access_token(secret: str, user_id: uuid.UUID, expire_minutes: int = 30) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=expire_minutes)}
    return jwt.encode(payload, secret, algorithm="HS256")

def decode_access_token(secret: str, token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return uuid.UUID(str(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
```

```python
# email_triage/deps.py — Bearer token dependency
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_current_user(
    security_scopes: SecurityScopes,
    token: Annotated[str, Depends(_oauth2_scheme)],
    settings: SettingsDep,
) -> SessionContext:
    user_id = decode_access_token(settings.session_secret, token)
    if user_id is None:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    # ... load user + membership from DB
    user_scopes = ROLE_SCOPES.get(membership.role, frozenset())
    for scope in security_scopes.scopes:
        if scope not in user_scopes:
            raise HTTPException(403, headers={"WWW-Authenticate": f'Bearer scope="{scope}"'})
    return SessionContext(...)
```

```python
# Usage in routers
CurrentUserDep     = Annotated[SessionContext, Security(get_current_user, scopes=[])]
ManageWorkspaceDep = Annotated[SessionContext, Security(get_current_user, scopes=["workspace:manage"])]
DeleteWorkspaceDep = Annotated[SessionContext, Security(get_current_user, scopes=["workspace:delete"])]

@router.post("/auth/rotate-key")
async def rotate_key(ctx: ManageWorkspaceDep) -> RotateKeyResponse:
    ...
```

## Concrete changes

| File | Change |
|---|---|
| `email_triage/db/models.py` | Add `User`, `Membership`; add `type`, make `domain` nullable on `Tenant` |
| `alembic/versions/0002_users_and_tenants.py` | Create users + memberships; add type + nullable domain to tenants; migrate rows as personal workspaces |
| `email_triage/auth/scopes.py` | New: scope string constants + `ROLE_SCOPES` dict |
| `email_triage/auth/session.py` | New: `create_access_token` + `decode_access_token` using PyJWT |
| `email_triage/db/repos/users.py` | New `UserRepo`: `get_by_email`, `get_by_google_sub`, `create_with_password`, `create_from_google`, `get_membership` |
| `email_triage/db/repos/tenants.py` | Updated: `create_personal`, remove `upsert_from_google`, keep `get_by_id` + `update_api_key_hash` + `all_key_hashes` |
| `email_triage/deps.py` | Add `_oauth2_scheme`, `SessionContext`, `get_current_user(SecurityScopes, Bearer token, ...)` |
| `email_triage/routers/auth.py` | Add `POST /auth/signup`, `POST /auth/login`; return `access_token` in body; update callback + me + rotate-key |
| `pyproject.toml` | Add `PyJWT>=2.9` |
| `tests/test_auth.py` | New tests for signup, login, JWT claims, scope enforcement; Bearer header pattern |
| `docs/exec-plans/16-users-and-password-auth.md` | This file |
| `docs/features/16-users-and-password-auth.md` | Feature doc |
| `docs/testing/16-users-and-password-auth_testing.md` | Testing guide |
| `docs/exec-plans/README.md` | Entry #16 |

## Endpoint table (full picture after this plan)

| Method | Path | Auth | Required scope | Returns |
|---|---|---|---|---|
| `GET` | `/auth/login` | — | — | Redirect to Google |
| `GET` | `/auth/callback` | — | — | `{access_token, token_type, email, ...}` |
| `POST` | `/auth/signup` | — | — | `{access_token, token_type, email, api_key, ...}` |
| `POST` | `/auth/login` | — | — | `{access_token, token_type, email, role, ...}` |
| `GET` | `/auth/me` | Bearer | *(any)* | `{user_id, email, tenant_id, role, ...}` |
| `POST` | `/auth/logout` | Bearer | *(any)* | `{message}` — client discards token |
| `POST` | `/auth/rotate-key` | Bearer | `workspace:manage` | `{api_key}` |

### Why JWT is stateless

Logout with JWT does not invalidate the token server-side — the server has no token store to consult. The client simply discards the token. The token remains technically valid until `exp`. For short-lived tokens (30 min default), this is acceptable. Token revocation (block list, Redis) is a Plan 18+ concern.

## Migration strategy (`0002`)

All existing `tenants` rows (created by Plan 15's Google SSO) become **personal workspaces**.

1. Create `users` table.
2. Add `type TEXT NOT NULL DEFAULT 'personal'` and make `domain` nullable on `tenants` (via `ALTER TABLE`).
3. Create `memberships` table.
4. For each row in `tenants`:
   - `INSERT INTO users (new UUID, email, display_name, google_sub, email_verified = google_sub IS NOT NULL)`.
   - Update the `tenants` row: `SET domain = NULL, name = display_name, type = 'personal'`.
   - `INSERT INTO memberships (user_id = new UUID, tenant_id = existing tenant UUID, role = 'owner')`.
5. Remove now-redundant columns from `tenants`: `DROP COLUMN email`, `DROP COLUMN google_sub`, `DROP COLUMN display_name`.

`triage_logs.tenant_id` FK remains valid throughout — same tenant UUIDs, same table name, no FK drop needed.

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| JWT Bearer tokens (HS256) | `itsdangerous` signed cookies | Industry standard; stateless; client holds the token; works across mobile/SPA/API; `sub`/`exp`/`iat` claims are universally understood |
| `PyJWT` | `python-jose`, `joserfc` | Official PyJWT is the most-used Python JWT library; well-typed; minimal deps; matches FastAPI docs examples |
| `OAuth2PasswordBearer` | `HTTPBearer` | FastAPI-native; adds Swagger lock icon + OpenAPI `securitySchemes`; `tokenUrl` documents where to get tokens |
| `HS256` over `RS256` | `RS256` | No key-pair management needed for single-service deployment; `RS256` is for distributed services where multiple verifiers need the public key |
| 30-min expiry | 24 h, 7 days | Short enough to limit exposure if a token leaks; long enough for normal use without refresh tokens |
| No refresh tokens | Refresh token rotation | Refresh tokens add complexity (store, rotate, revoke). Acceptable for MVP; add in Plan 18+ if needed |
| Personal workspace for every user | Domain-based team auto-join | Eliminates gmail.com collision; user always has a working workspace immediately |
| `SecurityScopes` + `Security(get_current_user, scopes=[...])` | Custom decorator / middleware RBAC | Native FastAPI pattern; `security_scopes.scopes` is populated at route definition time, not runtime |
| `ROLE_SCOPES` as `frozenset` | Flat list | `in` check is O(1); immutable prevents accidental mutation |
| `SessionContext` dataclass | Pass `user_id` as raw UUID | Carries role + tenant_id so downstream code doesn't need extra DB calls |
| `POST /auth/login` accepts JSON | `OAuth2PasswordRequestForm` (form) | Consistent with the rest of the API; `tokenUrl` in `OAuth2PasswordBearer` is Swagger metadata only |

## Execution order

1. **Scopes module** (15 min): `email_triage/auth/scopes.py` — constants + `ROLE_SCOPES`.
2. **JWT module** (15 min): `email_triage/auth/session.py` — `create_access_token` + `decode_access_token`.
3. **Models + migration** (60 min): update `db/models.py`; write and test `0002`.
4. **Repos** (45 min): `UserRepo` + updated `TenantRepo`.
5. **`get_current_user` dep** (45 min): `OAuth2PasswordBearer` + `SessionContext` + `SecurityScopes`.
6. **Endpoints** (60 min): `POST /auth/signup`, `POST /auth/login`; update callback, me, rotate-key.
7. **Tests** (45 min): new tests for signup, login, JWT claims, scope enforcement; Bearer header pattern.
8. **Docs** (15 min): update feature doc + testing guide.
9. **Close** (15 min): `uv run pre-commit run --all-files`; `make db-migrate` against Neon.

## Done when

- [x] `uv run pytest` — all tests pass (48 tests)
- [x] `uv run pyright` — 0 errors
- [x] `uv run ruff check` / `ruff format --check` — clean
- [ ] `make db-migrate` — `0002` runs cleanly against Neon
- [x] `POST /auth/signup` returns `{access_token, token_type: "bearer", api_key, ...}`
- [x] `POST /auth/login` returns `{access_token, token_type: "bearer", ...}`
- [x] `GET /auth/callback` (Google) returns `{access_token, token_type: "bearer", ...}`
- [x] `GET /auth/me` reads `Authorization: Bearer <token>` and returns user + workspace context
- [x] `POST /auth/rotate-key` returns 403 for `member` role, 200 for `owner`/`admin`
- [x] JWT payload contains `sub`, `exp`, `iat` claims
- [ ] Human validated with the testing guide
