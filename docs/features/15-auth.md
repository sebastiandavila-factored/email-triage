# Feature 15 — Google OAuth2 SSO

## Summary

Adds Google OAuth2 Authorization Code Flow with PKCE for browser-based login. Each founder signs in with their Google account, gets a per-tenant API key (shown once), and can rotate it at any time. The existing `X-API-Key` header auth is extended: keys are now per-tenant and stored as bcrypt hashes. The app continues to work with the static `API_KEY` from `.env` when no database is configured (local dev / tests).

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/auth/login` | No | Redirects to Google consent page. Sets PKCE state cookie (5 min TTL). |
| `GET` | `/auth/callback` | No | Receives Google code, verifies state, exchanges code, upserts tenant, sets session cookie. Rate-limited: 5/min per IP. |
| `GET` | `/auth/me` | Session cookie | Returns `{email, display_name, plan, tenant_id}`. |
| `POST` | `/auth/logout` | Session cookie | Clears session cookie. |
| `POST` | `/auth/rotate-key` | Session cookie | Issues a new API key (shown once). Invalidates the previous key within 60 s (cache TTL). |

## Security design

| Control | Implementation |
|---|---|
| PKCE (RFC 7636) | `code_verifier` stored in a signed cookie; `code_challenge=S256(cv)` sent to Google; `cv` sent at token exchange |
| CSRF | `state` embedded in the signed PKCE cookie; verified in `/auth/callback` before token exchange |
| Session cookie | `HttpOnly`, `SameSite=Lax`, `Secure` (production only), `max_age=86400` |
| API key storage | `bcrypt.hashpw(key, gensalt(rounds=12))` — never stored in plaintext |
| bcrypt performance | LRU cache keyed by `sha256(api_key)` with 60 s TTL avoids bcrypt on every request |
| ID token verification | `joserfc.jwt.decode` with Google's JWKS (`/oauth2/v3/certs`) |
| Scrubbing | `google_client_secret` and `session_secret` added to Logfire scrub list |

## New files

| Path | Role |
|---|---|
| `email_triage/auth/pkce.py` | PKCE helpers: `generate_code_verifier`, `code_challenge` |
| `email_triage/auth/state.py` | PKCE cookie: `generate_pkce_cookie`, `unpack_pkce_cookie` |
| `email_triage/auth/session.py` | Session cookie: `sign_session`, `unsign_session` |
| `email_triage/db/repos/tenants.py` | `TenantRepo`: get, upsert, rotate key |
| `email_triage/routers/auth.py` | All `/auth/*` endpoints |

## Modified files

| Path | Change |
|---|---|
| `email_triage/config.py` | Added `google_client_id/secret`, `google_redirect_uri`, `session_secret`, `bcrypt_rounds` |
| `email_triage/deps.py` | `verify_api_key` now async; bcrypt check against DB; LRU cache; fallback to static key |
| `email_triage/main.py` | Register auth router; add `google_client_secret`, `session_secret` to scrub set |
| `.env.example` | Added Google OAuth2 vars |

## Google Cloud Console setup

1. Go to https://console.cloud.google.com → **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth 2.0 Client ID** → type **Web application**.
3. Under **Authorized redirect URIs** add:
   - `http://localhost:8000/auth/callback` (dev)
   - `https://your-app.domain/auth/callback` (prod)
4. Copy **Client ID** and **Client Secret** to `.env`:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
   SESSION_SECRET=<output of: python -c "import secrets; print(secrets.token_hex(32))">
   ```
5. Configure the **OAuth consent screen**: app name, support email, scopes (`openid`, `email`, `profile`). Add test users while the app is unverified.
6. Run `make db-migrate` to ensure the `tenants` table exists.

## Login flow (end-to-end)

```
GET /auth/login
  → 302 accounts.google.com (with code_challenge, state)
  → user grants consent
  → 302 /auth/callback?code=X&state=Y
GET /auth/callback
  → verifies state + code_verifier
  → exchanges code for id_token with Google
  → upserts tenant row in DB
  → sets session cookie (24 h)
  → returns JSON {email, display_name, plan, api_key (first login only)}
```

From this point the client uses either:
- The **session cookie** for browser-based calls to `/auth/me`, `/auth/logout`, `/auth/rotate-key`.
- The **API key** (`X-API-Key` header) for programmatic calls to `/triage`.
