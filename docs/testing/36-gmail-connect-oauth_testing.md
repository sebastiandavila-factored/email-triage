# Testing — Gmail connect (Plan 36)

## Automated

```bash
uv run pytest tests/test_gmail_connect.py -v
```

Covers (no real network — Google and the DB are mocked):

- `TokenCipher` round-trip; decrypt with the wrong key raises `TokenCipherError`.
- `generate_connect_cookie` / `unpack_connect_cookie` round-trip; tampered cookie → None.
- `POST /gmail/connect`: 401 unauthenticated · 403 for `member` (no `gmail:connect`) · 200 for
  `owner` returning an `authorization_url` with `gmail.readonly` + `access_type=offline` +
  `prompt=consent` and a `Set-Cookie` · 503 when `GMAIL_TOKEN_ENC_KEY` is unset.
- `GET /gmail/callback`: 400 on missing cookie / state mismatch · 302 to `?gmail=denied` when the
  user declines · **stores an encrypted refresh token** (persisted value ≠ plaintext, decrypts
  back) and redirects to `?gmail=connected` · 502 when Google returns no `refresh_token`.
- `DELETE /gmail/connection`: owner disconnect returns `disconnected: true`.

Full gate:

```bash
make check
```

## Manual (real Google, one-time setup)

Requires a Google Cloud project and a mailbox to connect.

1. **Google Cloud Console**
   - Use the existing OAuth 2.0 Client ID (Web application).
   - Add an Authorized redirect URI: `http://localhost:8000/gmail/callback`.
   - Enable the **Gmail API** for the project.
   - OAuth consent screen: add the `https://www.googleapis.com/auth/gmail.readonly` scope and add
     your Google account under **Test users** (the app stays in *testing* mode).

2. **`.env`**
   ```
   GOOGLE_CLIENT_ID=...            # same as login
   GOOGLE_CLIENT_SECRET=...
   GMAIL_REDIRECT_URI=http://localhost:8000/gmail/callback
   GMAIL_TOKEN_ENC_KEY=<paste output of the generator below>
   ```
   Generate the key:
   ```bash
   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. **Run** the API (`fastapi dev` / uvicorn) with a real `DATABASE_URL` and apply migrations
   (`alembic upgrade head` → includes `0006`).

4. **Connect** (until the Inbox UI lands in Plan 38, drive it with curl + a session JWT):
   ```bash
   # POST /gmail/connect with your Bearer token → returns {authorization_url} and sets the cookie
   curl -i -X POST http://localhost:8000/gmail/connect -H "Authorization: Bearer <JWT>"
   ```
   Open the `authorization_url` in a browser, consent, and confirm the callback redirects to
   `http://localhost:5173/inbox?gmail=connected`.

5. **Verify** the row exists and the token is encrypted:
   - `select google_email, left(refresh_token_enc, 12), connected_at from gmail_connections;`
   - The `refresh_token_enc` must be a `gAAAAA…` Fernet blob, not a readable token.

6. **Disconnect**:
   ```bash
   curl -X DELETE http://localhost:8000/gmail/connection -H "Authorization: Bearer <JWT>"
   ```
   The row is gone.

## Checklist

- [ ] `uv run pytest tests/test_gmail_connect.py` green
- [ ] `make check` green
- [ ] Real connect stores a `gAAAAA…` (encrypted) refresh token, never plaintext
- [ ] `member` role cannot connect (403); owner/admin can
- [ ] With `GMAIL_TOKEN_ENC_KEY` empty, `/gmail/connect` returns 503
- [ ] Disconnect removes the row
