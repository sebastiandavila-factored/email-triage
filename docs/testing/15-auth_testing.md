# Testing Plan — Feature 15: Google OAuth2 SSO

## Automated tests (`tests/test_auth.py`)

All automated tests mock Google and the DB. No real OAuth2 flow or network calls.

| Test | What it verifies |
|---|---|
| `test_pkce_verifier_length` | `generate_code_verifier()` produces 43–128 chars |
| `test_pkce_challenge_matches_s256` | `code_challenge(v)` == `base64url(sha256(v))` |
| `test_pkce_cookie_round_trip` | Cookie signed and unpacked with same secret |
| `test_pkce_cookie_expired` | `max_age=-1` returns `None` |
| `test_pkce_cookie_tampered` | Appending chars returns `None` |
| `test_session_cookie_round_trip` | `sign_session` / `unsign_session` roundtrip |
| `test_session_cookie_wrong_secret` | Wrong secret returns `None` |
| `test_session_cookie_tampered` | Tampered value returns `None` |
| `test_login_redirects_to_google` | `GET /auth/login` → 302 with PKCE params and PKCE cookie |
| `test_login_503_when_not_configured` | No `GOOGLE_CLIENT_ID` → 503 |
| `test_callback_missing_code_returns_400` | Missing `code` param → 400 |
| `test_callback_missing_pkce_cookie_returns_400` | No PKCE cookie → 400 |
| `test_callback_state_mismatch_returns_400` | Wrong `state` → 400 "State mismatch" |
| `test_callback_creates_tenant_on_first_login` | Mocked Google response → tenant row created, `api_key` in response, session cookie set |
| `test_me_unauthenticated_returns_401` | No cookie → 401 |
| `test_me_with_valid_session` | Valid session cookie → 200 with tenant data |

Run with:
```bash
uv run pytest tests/test_auth.py -v
```

## Manual tests (browser)

### TC-M01 — Full login flow

1. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET` in `.env`.
2. Run `make db-migrate && make dev`.
3. Open `http://localhost:8000/auth/login` in a browser.
4. Verify redirect to Google consent page with `code_challenge` and `state` in URL.
5. Sign in with a Google account listed as test user in Cloud Console.
6. Verify redirect back to `/auth/callback`.
7. Check response JSON: `email`, `display_name`, `api_key` (only on first login), `message`.
8. Open DevTools → Application → Cookies. Verify:
   - `session` cookie exists
   - `HttpOnly` ✓
   - `SameSite: Lax` ✓

### TC-M02 — `GET /auth/me` with session

After TC-M01, call:
```bash
curl http://localhost:8000/auth/me --cookie "session=<cookie value>"
```
Expected: `{"email": "...", "display_name": "...", "plan": "free", "tenant_id": "..."}`.

### TC-M03 — API key works for `/triage`

Use the `api_key` from TC-M01:
```bash
curl -X POST http://localhost:8000/triage \
  -H "X-API-Key: <api_key from callback>" \
  -H "Content-Type: application/json" \
  -d '{"subject": "test", "body": "test", "sender": "a@b.com"}'
```
Expected: 200 with triage result.

### TC-M04 — Key rotation invalidates old key

1. `POST /auth/rotate-key` (with session cookie). Save new key.
2. Wait up to 60 s (cache TTL).
3. Use old key → 403. Use new key → 200.

### TC-M05 — Secrets scrubbed from Logfire

Check Logfire UI after a login. Verify `google_client_secret` and `session_secret` fields show `[REDACTED]`.

### TC-M06 — Logout

```bash
curl -X POST http://localhost:8000/auth/logout --cookie "session=<value>"
```
Expected: 200 `{"message": "Logged out"}`. Subsequent `GET /auth/me` → 401.
