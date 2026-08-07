# Gmail connect — OAuth flow + encrypted refresh token (F1)

## What it does

Lets an owner/admin **connect their Gmail account** to a workspace so the app can later pull
the day's emails (Plan 37). This first phase delivers only the connection: a separate OAuth
consent flow (incremental, apart from login) and the **encrypted storage of the `refresh_token`**.

Reuses the login's OAuth2 + PKCE machinery ([routers/auth.py](../../email_triage/routers/auth.py))
but with `scope=gmail.readonly`, `access_type=offline` and `prompt=consent`, so Google returns a
long-lived `refresh_token`. That token is stored **encrypted at rest** (Fernet) and never leaves
the backend. Without a configured `GMAIL_TOKEN_ENC_KEY` the endpoints degrade to 503.

## How it works

Identity binding is the subtle part. The Google redirect back to `GET /gmail/callback` is a
top-level browser navigation with **no Authorization header**, so the callback can't authenticate
the caller the usual way. We bind identity into the OAuth **`state`** itself — **encrypted**, so
it needs no cookie and works across the SPA/API origin split (third-party cookies are blocked by
Safari and, increasingly, Chrome):

1. **`POST /gmail/connect`** is authenticated (Bearer + `gmail:connect` scope via
   `ConnectGmailDep`). It generates PKCE and mints an **encrypted `state`** (Fernet) carrying
   `code_verifier` + the caller's `(user_id, tenant_id)`, then returns the Google
   `authorization_url` for the SPA to navigate to. Encryption keeps the `code_verifier`
   confidential in the URL; the `ttl` (600 s) bounds replay.
2. The user consents; Google echoes `state` to **`GET /gmail/callback?code&state`**. The callback
   **decrypts `state`** to recover `(code_verifier, user_id, tenant_id)` — an attacker can't forge
   or read it without the key — exchanges the code for tokens, reads the mailbox address from the
   Gmail profile endpoint, **encrypts the `refresh_token`**, upserts the `gmail_connections` row,
   and redirects to `{frontend}/inbox?gmail=connected`.
3. **`DELETE /gmail/connection`** (Bearer + `gmail:connect`) removes the stored connection. CORS
   allows `DELETE` for the cross-origin SPA.

```
SPA (Bearer) --POST /gmail/connect--> backend: PKCE + encrypt state{cv,uid,tid} → {authorization_url}
SPA --window.location--> accounts.google.com (consent)
browser <--302 /gmail/callback?code&state-- Google
browser --GET /gmail/callback?state--> backend: decrypt state → token exchange (offline)
                                                → encrypt refresh_token → upsert → 302 /inbox?gmail=connected
```

## Files involved

| File | Role |
|---|---|
| `email_triage/services/crypto.py` | `TokenCipher` (Fernet) — encrypt/decrypt secrets at rest |
| `email_triage/db/models.py` | `GmailConnection` model (`refresh_token_enc`, unique `(tenant_id,user_id)`) |
| `alembic/versions/0006_gmail_connections.py` | migration for the table + indexes |
| `email_triage/db/repos/gmail.py` | `GmailRepo` (upsert / get_by_user / delete / touch_last_synced) |
| `email_triage/auth/scopes.py` | `gmail:connect` scope (owner + admin) |
| `email_triage/services/crypto.py` | `TokenCipher.decrypt(ttl=…)` for the time-bounded encrypted `state` |
| `email_triage/deps.py` | `ConnectGmailDep` (session + `gmail:connect` enforcement) |
| `email_triage/config.py` | `gmail_redirect_uri`, `gmail_token_enc_key`, `gmail_sync_max_results` |
| `email_triage/routers/gmail.py` | `POST /gmail/connect`, `GET /gmail/callback`, `DELETE /gmail/connection`; `encode/decode_connect_state` |
| `email_triage/main.py` | register router; add gmail secrets to Logfire scrubbing; allow `DELETE` in CORS |
| `.env.example` | `GMAIL_REDIRECT_URI`, `GMAIL_TOKEN_ENC_KEY`, `GMAIL_SYNC_MAX_RESULTS` |
| `tests/test_gmail_connect.py` | cipher round-trip, cookie, RBAC, 503, callback stores ciphertext |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Identity in an **encrypted OAuth `state`** (no cookie) | A signed identity cookie carried to the callback | The SPA/API are different origins in prod; a cross-site cookie is blocked by Safari/Chrome. The state round-trips through Google with no cookie at all |
| `POST /gmail/connect` returns a URL | `GET /gmail/connect` redirect requiring a Bearer header | A top-level browser navigation can't carry a Bearer header; the SPA fetches the URL, then navigates |
| Encrypt (not just sign) the `state` | Signed-but-readable state | Keeps the PKCE `code_verifier` confidential in the URL; Fernet also authenticates + timestamps (ttl → replay bound) |
| `refresh_token` encrypted with Fernet (`GMAIL_TOKEN_ENC_KEY`) | Storing it in the clear | A DB leak would otherwise expose every connected inbox |
| Separate connect flow, not part of login | Adding `gmail.readonly` to the login scopes | Incremental consent: login stays light, Gmail is opt-in |
| 503 when `GMAIL_TOKEN_ENC_KEY` is unset | Booting with a default key | Never encrypt with a placeholder; explicit degradation (`CLAUDE.md`) |

## Gotchas / Edge cases

- **`refresh_token` only on consent:** Google returns a `refresh_token` only with
  `access_type=offline` **and** a fresh consent — we force `prompt=consent`, so reconnects also
  get one. A missing `refresh_token` in the exchange → 502 with a "reconnect" message.
- **Redirect URI must be registered:** `GMAIL_REDIRECT_URI` is a *different* URI from the login's
  and must be added in Google Cloud Console, or Google returns `redirect_uri_mismatch`.
- **Restricted scope:** `gmail.readonly` is RESTRICTED. Production (>100 users) needs Google
  verification + CASA; in *testing* mode it works for up to 100 added test users. v1 targets that.
- **Key rotation:** rotating `GMAIL_TOKEN_ENC_KEY` invalidates all stored tokens (users reconnect).
- The `refresh_token` never reaches the client; `main.py` scrubbing also redacts it from logs.

## Verified

- `make check` green: ruff + format + pyright (0 errors) + **212 tests** (14 new in
  `tests/test_gmail_connect.py`).
- Tests never hit the network: Google token/profile calls and the DB layer are mocked; the
  callback test asserts the persisted value is **ciphertext** that decrypts back to the original.

## Testing

📋 [Testing guide](../testing/36-gmail-connect-oauth_testing.md)
