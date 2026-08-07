# Testing — Gmail sync + inbox (Plan 37)

## Automated

```bash
uv run pytest tests/test_gmail_sync.py -v
```

Covers (no real network — Google, the DB, and the triage service are mocked):

- `GmailClient.parse_message`: extracts a `text/plain` body + headers; prefers `text/plain`
  over an HTML sibling; falls back to the Gmail `snippet` when no text part exists.
- `GmailClient` (mocked httpx): `refresh_access_token` success; `invalid_grant` (400) →
  `GmailAuthError`; `list_today` lists ids then fetches + parses each message.
- `GET /gmail/status`: 401 unauthenticated · `connected: false` when no row · `connected: true`
  with `google_email` when connected.
- `POST /gmail/sync`: 404 when not connected · **returns triaged items** (category/confidence/
  draft per email, `touch_last_synced` called) · empty inbox → `items: []` · revoked token → 409
  · all-triage-fail → 503 · unconfigured (`GMAIL_TOKEN_ENC_KEY` unset) → 503.

Full gate:

```bash
make check
```

## Manual (real Gmail)

Prerequisite: a connected mailbox from the Plan 36 flow (see
[36 testing](36-gmail-connect-oauth_testing.md)) and today's inbox has ≥1 unread email.

1. Run the API with a real `DATABASE_URL` (migrations at head incl. `0006`) and a valid
   `GROQ_API_KEY` (real triage).
2. **Status:**
   ```bash
   curl http://localhost:8000/gmail/status -H "Authorization: Bearer <JWT>"
   ```
   → `{"connected": true, "google_email": "...", "last_synced_at": null}` before the first sync.
3. **Sync:**
   ```bash
   curl -X POST http://localhost:8000/gmail/sync -H "Authorization: Bearer <JWT>"
   ```
   → `{"items": [ {message_id, sender, subject, received_at, category, confidence, draft_reply}, ... ],
   "synced_at": ...}`. Each item should have a plausible category + a drafted reply.
4. **Re-check status** → `last_synced_at` is now populated.
5. **Revocation path:** revoke the app's access at
   [myaccount.google.com/permissions](https://myaccount.google.com/permissions), then sync again
   → **409** ("reconnect"), not a 500.
6. **Observability:** confirm a `gmail.sync` span in Logfire tagged with `tenant_id` and
   `gmail.messages.count`, with child triage spans under it.

## Checklist

- [ ] `uv run pytest tests/test_gmail_sync.py` green
- [ ] `make check` green
- [ ] Real sync returns today's unread emails, each triaged (category + draft)
- [ ] Empty inbox → `items: []` (200, not an error)
- [ ] Revoked access → 409, and the UI can prompt a reconnect (Plan 38)
- [ ] No email body is persisted (only the existing `TriageLog` char counts)
- [ ] `gmail.sync` span visible in Logfire with `tenant_id`
