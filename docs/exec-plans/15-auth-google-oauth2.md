# 15. Google OAuth2 SSO — Authentication & Authorization

**Status:** 📋 proposed
**Estimate:** 5 hrs
**Depends on:** Plan 14 (PostgreSQL + SQLAlchemy) — `tenants` table must exist.

## Intent

The product currently uses a single static API key for all callers. As it grows to multiple founders (mailboxes), each customer needs their own identity, their own API key, and a secure login experience. This plan implements Google OAuth2 SSO using the Authorization Code Flow with PKCE — the current best practice for web applications — so that founders can sign in with their Google account, get a scoped API key for their mailbox, and eventually access a personal dashboard of triage metrics.

The scope is deliberately narrow: this plan covers authentication (who are you?) and per-tenant API key issuance. Authorization (what can you see?) beyond "your own data" is post-MVP.

All code, comments, and documentation produced by this plan are written in **English**.

## Prior reading

**OAuth2 / OpenID Connect fundamentals:**
- **RFC 6749 — The OAuth 2.0 Authorization Framework** — https://www.rfc-editor.org/rfc/rfc6749
- **RFC 7636 — PKCE for OAuth Public Clients** — https://www.rfc-editor.org/rfc/rfc7636
- **OpenID Connect Core 1.0** — https://openid.net/specs/openid-connect-core-1_0.html
- **Google OAuth2 for Web Apps** — https://developers.google.com/identity/protocols/oauth2/web-server

**Security best practices:**
- **OWASP OAuth2 Cheat Sheet** — https://cheatsheetseries.owasp.org/cheatsheets/OAuth2_Cheat_Sheet.html
- **OWASP Session Management Cheat Sheet** — https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- **OWASP HttpOnly** — https://owasp.org/www-community/HttpOnly

**Library docs:**
- **Authlib — FastAPI OAuth2 integration** — https://docs.authlib.org/en/latest/integrations/fastapi.html
- **Authlib — OAuth2 client** — https://docs.authlib.org/en/latest/client/httpx.html
- **python-jose — JWT** — https://python-jose.readthedocs.io/en/latest/
- **itsdangerous — signed cookies** — https://itsdangerous.palletsprojects.com/en/stable/

**FastAPI patterns:**
- **FastAPI — Security: OAuth2** — https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- **FastAPI — Middleware** — https://fastapi.tiangolo.com/tutorial/middleware/
- **Starlette — Sessions** — https://www.starlette.io/middleware/#sessionmiddleware

**Google Cloud Console:**
- **Create OAuth 2.0 credentials** — https://console.cloud.google.com/apis/credentials
- **Scopes reference** — https://developers.google.com/identity/protocols/oauth2/scopes

## Scope

**Included:**
- New deps: `authlib>=1.3`, `itsdangerous>=2.2`, `python-jose[cryptography]>=3.3`.
- Google Cloud Console setup instructions (no code, just configuration guide in the feature doc).
- `src/email_triage/routers/auth.py`: `/auth/login`, `/auth/callback`, `/auth/logout`, `/auth/me`.
- `src/email_triage/auth/` sub-package: session management, PKCE helpers, JWT issuance.
- Session via signed `HttpOnly; Secure; SameSite=Lax` cookie (no `localStorage`, no `sessionStorage`).
- On first login: create `tenants` row, generate and return API key (shown once, then only the hash is stored).
- On subsequent logins: look up existing `tenants` row by `google_sub`.
- `/auth/me` endpoint: returns `{email, display_name, plan}` for the authenticated tenant.
- `Depends(get_current_tenant)` — injectable dependency for protected routes.
- Existing API key flow (`X-Api-Key` header) is **kept and extended**: the key is now per-tenant and stored as a bcrypt hash in `tenants.api_key_hash`.
- Rate limiting on `/auth/callback` (5 req/min per IP via slowapi).
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET`, `JWT_SECRET` config fields.
- `docs/features/15-auth.md` and `docs/testing/15-auth_testing.md`.

**Out of scope:**
- Multi-tenant data isolation at the row level (post-MVP).
- Refresh token rotation (access token TTL = 1 h; re-login required after expiry for MVP).
- SAML / other SSO providers.
- Email + password authentication.
- Admin panel or user management UI.
- Two-factor authentication.

## Authorization Code Flow with PKCE — sequence

```
Browser                   FastAPI                    Google OAuth2
  |                          |                              |
  |-- GET /auth/login ------>|                              |
  |                          | generate code_verifier       |
  |                          | code_challenge = S256(cv)    |
  |                          | state = signed(random_token) |
  |<-- 302 → accounts.google.com/o/oauth2/v2/auth?         |
  |          client_id&redirect_uri&scope&state&            |
  |          code_challenge&code_challenge_method=S256      |
  |                          |                              |
  |-- user grants permission --------------------------->   |
  |<-- 302 → /auth/callback?code=XXX&state=YYY ------------|
  |                          |                              |
  |-- GET /auth/callback --->|                              |
  |                          | verify state (CSRF check)    |
  |                          | POST /token with code +      |
  |                          |   code_verifier ------------>|
  |                          |<-- {access_token, id_token}  |
  |                          | verify id_token (JWT RS256)  |
  |                          | extract sub, email, name     |
  |                          | upsert tenants row           |
  |                          | issue session cookie         |
  |<-- 302 / (+ Set-Cookie) -|                              |
```

## New endpoints

| Method | Path | Auth required | Description |
|---|---|---|---|
| `GET` | `/auth/login` | No | Redirects to Google OAuth2 consent page. Sets `state` and `code_verifier` in a short-lived signed cookie. |
| `GET` | `/auth/callback` | No | Receives `code` + `state` from Google. Verifies state, exchanges code for tokens, upserts tenant, sets session cookie, redirects to `/auth/me`. |
| `POST` | `/auth/logout` | Yes | Clears session cookie. |
| `GET` | `/auth/me` | Yes | Returns `{email, display_name, plan, created_at}`. |
| `POST` | `/auth/rotate-key` | Yes | Generates a new API key for the tenant. Returns the plaintext key once. Invalidates the previous key. |

## Session design

Two layers:

1. **Session cookie** (`session`): signed with `itsdangerous.URLSafeTimedSerializer(SESSION_SECRET)`. Contains `{tenant_id: UUID}`. TTL = 24 h (server-side: cookie max-age). Cookie flags: `HttpOnly=True`, `Secure=True` (enforced in production), `SameSite="Lax"`.

2. **API key** (existing flow, extended): a 32-byte random token (`secrets.token_urlsafe(32)`) — shown to the tenant **once** after first login. Stored as `bcrypt.hash(api_key)` in `tenants.api_key_hash`. The `verify_api_key` dependency in `deps.py` now does `bcrypt.checkpw(provided_key, stored_hash)` instead of a plain equality check.

No JWTs are issued for the browser session — signed cookies are simpler and safer for a server-side app. JWTs could be added later if a native mobile client is needed.

## PKCE implementation

```python
# src/email_triage/auth/pkce.py
import hashlib, base64, secrets

def generate_code_verifier() -> str:
    # RFC 7636 §4.1: 43–128 chars, URL-safe alphabet
    return secrets.token_urlsafe(64)

def code_challenge(verifier: str) -> str:
    # RFC 7636 §4.2: S256 method
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
```

`code_verifier` is stored in a short-lived signed cookie (TTL = 5 min) during the `/auth/login` → `/auth/callback` round trip. It never touches the DB.

## State / CSRF protection

```python
# src/email_triage/auth/state.py
from itsdangerous import URLSafeTimedSerializer
from email_triage.config import settings

_signer = URLSafeTimedSerializer(settings.session_secret)

def generate_state() -> str:
    return _signer.dumps(secrets.token_urlsafe(16))

def verify_state(state: str, max_age: int = 300) -> bool:
    try:
        _signer.loads(state, max_age=max_age)
        return True
    except Exception:
        return False
```

Storing the state in a signed cookie (not in the DB or in-memory) makes the check stateless — safe for multi-worker deploys on Render.

## Dependency injection

```python
# src/email_triage/deps.py (addition)
from email_triage.db.repos.tenants import TenantRepo

async def get_current_tenant(
    request: Request,
    session: DbSession,
) -> Tenant:
    raw = request.cookies.get("session")
    if not raw:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = _signer.loads(raw, max_age=86400)
        tenant_id = uuid.UUID(payload["tenant_id"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    tenant = await TenantRepo().get_by_id(session, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant not found")
    return tenant

CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
```

The existing `verify_api_key` dependency is extended to do a bcrypt check against `tenants.api_key_hash` instead of a plain string comparison.

## Config additions

```python
# src/email_triage/config.py (additions)
class Settings(BaseSettings):
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    session_secret: str          # random 32-byte hex; used for signing cookies
    jwt_secret: str              # reserved for future native clients; not used in Plan 15
    bcrypt_rounds: int = 12      # work factor for API key hashing
```

## Directory structure

```
src/email_triage/
├── auth/
│   ├── __init__.py
│   ├── pkce.py          # generate_code_verifier, code_challenge
│   ├── state.py         # generate_state, verify_state
│   └── session.py       # sign_session, unsign_session
├── db/
│   └── repos/
│       └── tenants.py   # TenantRepo: get_by_id, get_by_google_sub, upsert, update_api_key_hash
└── routers/
    └── auth.py          # /auth/* endpoints
```

## Concrete changes

| File | Change |
|---|---|
| `pyproject.toml` | Add `authlib>=1.3`, `itsdangerous>=2.2`, `bcrypt>=4.2`. |
| `src/email_triage/config.py` | Add `google_client_id`, `google_client_secret`, `google_redirect_uri`, `session_secret`, `bcrypt_rounds`. |
| `src/email_triage/auth/pkce.py` | PKCE code verifier + challenge. |
| `src/email_triage/auth/state.py` | CSRF state generation + verification. |
| `src/email_triage/auth/session.py` | Cookie signing with `itsdangerous`. |
| `src/email_triage/db/repos/tenants.py` | `get_by_id`, `get_by_google_sub`, `upsert_from_google`, `update_api_key_hash`. |
| `src/email_triage/routers/auth.py` | All five `/auth/*` endpoints. |
| `src/email_triage/main.py` | Register `auth_router` under prefix `/auth`. |
| `src/email_triage/deps.py` | Add `get_current_tenant`, extend `verify_api_key` with bcrypt check. |
| `src/email_triage/main.py` | Add `logfire` scrubbing for `google_client_secret`, `session_secret`. |
| `.env.example` | Add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `SESSION_SECRET`. |
| `docs/features/15-auth.md` | Feature doc incl. Google Cloud Console setup guide. |
| `docs/testing/15-auth_testing.md` | Testing doc. |
| `docs/exec-plans/README.md` | Add entry #15. |

## Security checklist

| Control | Implementation |
|---|---|
| PKCE (RFC 7636) | `code_verifier` generated locally, `code_challenge=S256(cv)` sent to Google, `cv` sent in token exchange |
| CSRF protection | `state` parameter signed with `itsdangerous`; verified in callback before token exchange |
| Secure cookie | `HttpOnly=True`, `Secure=True`, `SameSite="Lax"` |
| No secret in URL | `code_verifier` travels in a short-lived cookie, not in query params |
| bcrypt for API keys | `bcrypt.hashpw(api_key, bcrypt.gensalt(rounds=12))`; never store plaintext |
| Minimal scopes | `openid email profile` only — no access to Gmail, Drive, etc. |
| Short-lived PKCE cookie | TTL = 5 min; only survives the login round trip |
| Rate limit on callback | 5 req/min per IP via slowapi — prevents code replay brute force |
| Secrets scrubbed from spans | `google_client_secret`, `session_secret` added to Logfire scrubbing callback |
| `Secure` flag conditional | `Secure=True` only when `settings.environment == "production"` — allows HTTP in local dev |

## Google Cloud Console setup (manual, pre-deploy)

Steps documented in `docs/features/15-auth.md`:

1. Create a project at https://console.cloud.google.com.
2. Enable the **Google Identity** API (OAuth2).
3. Create an **OAuth 2.0 Client ID** of type "Web application".
4. Add authorized redirect URIs:
   - `http://localhost:8000/auth/callback` (dev)
   - `https://your-app.onrender.com/auth/callback` (prod)
5. Copy `client_id` and `client_secret` to `.env`.
6. Configure the **OAuth consent screen**: app name, support email, scopes (`openid`, `email`, `profile`), add test users.

The consent screen must be reviewed by Google before going public; for MVP, test users are sufficient.

## Testing strategy

Auth flows require a real Google account, so the test suite uses mocks for the OAuth layer:

- **Unit tests** (`tests/test_auth.py`):
  - `test_pkce_challenge_matches_s256`: verify the S256 computation.
  - `test_state_verify_rejects_expired`: tamper with TTL.
  - `test_state_verify_rejects_tampered`: mutate the state string.
  - `test_session_cookie_round_trip`: sign + unsign with correct secret.
  - `test_login_redirects_to_google`: `GET /auth/login` → 302 with expected query params.
  - `test_callback_invalid_state_returns_400`: simulate CSRF attempt.
  - `test_callback_creates_tenant_on_first_login`: mock Google token exchange, assert `tenants` row created.
  - `test_me_unauthenticated_returns_401`: no cookie → 401.
  - `test_rotate_key_invalidates_old_key`: verify old API key stops working.

- **Integration test** (manual, in testing doc): log in with a real Google account in a browser, verify session cookie is set, call `GET /auth/me`, verify JSON response.

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| PKCE + Authorization Code Flow | Implicit flow | Implicit flow is deprecated (RFC 9700); PKCE is the current standard for all client types |
| `itsdangerous` signed cookies for session | JWT session token | Signed cookies are simpler, opaque to the browser, and revocable server-side; JWTs require a revocation list |
| `authlib` for OAuth2 client | `httpx` + manual OAuth2 | authlib handles token endpoint, ID token verification, and JWKS caching; ~200 lines saved |
| bcrypt for API key hashing | SHA-256, Argon2 | bcrypt is battle-tested, natively supported, and the `bcrypt` Python package has no C compile step on Render; Argon2 is marginally better but adds a dep |
| Show API key once on first login | Store in DB, always retrievable | Never store secrets in plaintext; UX tradeoff is acceptable for a technical user base (founders) |
| `SameSite=Lax` (not `Strict`) | `SameSite=Strict` | `Strict` blocks the cookie on the OAuth redirect back from Google (cross-site navigation), breaking the flow; `Lax` allows top-level GET navigations |
| Rate limit only on `/auth/callback` | Rate limit all auth endpoints | `/auth/login` is idempotent; `/auth/logout` is low-risk; the callback is the only endpoint that processes external codes |
| `google_sub` as the stable identifier | `email` | Google guarantees `sub` is unique and stable; email can be changed by the user |

## Risks

- **Google consent screen review delay**: apps not yet verified by Google can only be used by test users (up to 100). Mitigation: add all founder emails as test users during MVP; submit for verification before public launch.
- **`itsdangerous` secret rotation**: rotating `SESSION_SECRET` invalidates all existing sessions. Mitigation: use a `TimestampSigner` with a fallback list of old secrets during the rotation window.
- **bcrypt timing**: bcrypt at rounds=12 takes ~200 ms per check. Applied to API key verification on every authenticated request, this could be a bottleneck under load. Mitigation: cache the verification result in a short-lived in-process LRU cache keyed by `hash(api_key)` — valid for 60 s. Do not cache the tenant ID to avoid stale data.
- **`SameSite=Lax` and some browsers**: older mobile browsers may not support `SameSite`; they will send the cookie on all requests (less restrictive, not more). Acceptable for MVP.
- **PKCE cookie lost before callback**: if the browser clears cookies between `/auth/login` and `/auth/callback` (very rare), the login fails gracefully with a 400. User must retry.

## Execution order

1. **Config + deps** (20 min): add packages, `uv sync`, config fields, `.env.example`, scrubbing.
2. **Auth sub-package** (30 min): `pkce.py`, `state.py`, `session.py`.
3. **TenantRepo** (20 min): `repos/tenants.py` with `upsert_from_google` and `update_api_key_hash`.
4. **Auth router** (45 min): all five endpoints, rate limit on callback.
5. **Deps extension** (20 min): `get_current_tenant`, bcrypt check in `verify_api_key`.
6. **Register router + scrubbing** (10 min): `main.py` additions.
7. **Tests** (40 min): `tests/test_auth.py` — unit tests with mocked Google.
8. **Docs** (20 min): feature doc (incl. Cloud Console setup guide), testing doc, README update.
9. **Close** (15 min): `make check`, manual browser login test.

## Done when

- [ ] `GET /auth/login` redirects to Google with `code_challenge`, `state`, and correct scopes
- [ ] `GET /auth/callback` with a valid Google code creates a `tenants` row and sets a session cookie
- [ ] `GET /auth/me` with a valid session cookie returns `{email, display_name, plan}`
- [ ] `GET /auth/me` without a cookie returns 401
- [ ] `POST /auth/rotate-key` returns a new API key (plaintext, once) and the old key stops working
- [ ] `POST /triage` with the new per-tenant API key returns 200; with the old key returns 403
- [ ] `tests/test_auth.py` — all unit tests pass (mocked Google)
- [ ] `make check` passes (ruff + pyright + all tests)
- [ ] `GOOGLE_CLIENT_SECRET` and `SESSION_SECRET` are scrubbed from Logfire spans
- [ ] `docs/features/15-auth.md` and `docs/testing/15-auth_testing.md` created (incl. Cloud Console setup guide)
- [ ] `docs/exec-plans/README.md` updated with entry #15
- [ ] Manual browser test: log in with real Google account, verify session cookie flags in DevTools
