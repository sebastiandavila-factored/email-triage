# Gmail sync — today's triaged inbox (F2)

## What it does

Pulls the **day's unread emails** from a connected Gmail account (Plan 36) and triages each
one with the existing per-tenant `LLMService` — **the triage engine is unchanged**. Each Gmail
message is mapped to a `TriageRequest` and classified; the endpoint returns the inbox ready to
render (Plan 38). Emails are **ephemeral**: nothing but the existing `TriageLog` (chars, not
content) is persisted.

Two endpoints, both under `/gmail`:
- `GET /gmail/status` → `{connected, google_email, last_synced_at}` (any member).
- `POST /gmail/sync` → `{items: [...], synced_at}` (any member, `triage:write`).

## How it works

```
POST /gmail/sync (Bearer, triage:write)
  → GmailRepo.get_by_user → connection (404 if none)
  → TokenCipher.decrypt(refresh_token_enc)         (409 if key/row unusable)
  → GmailClient.refresh_access_token               (409 if invalid_grant → reconnect)
  → GmailClient.list_today("in:inbox is:unread newer_than:1d", max_results)
        messages.list → ids → messages.get(full) → parse (subject/from/date/text-plain body)
  → svc = get_triage_service(TenantContext(tenant_id))   # "published wins" / dynamic / fallback
  → for each message: svc.triage(TriageRequest) → InboxItem
  → touch last_synced_at
```

- **`GmailClient`** ([services/gmail.py](../../email_triage/services/gmail.py)) owns the Google
  calls: refresh the ~1h access token from the stored refresh token, list + fetch messages, and
  parse MIME. `parse_message` prefers a `text/plain` part anywhere in the tree, falling back to
  any `text/*`, then to the Gmail `snippet`. 429/503 get a short exponential backoff (2 retries).
- **Reuses the triage path:** `get_triage_service(TenantContext(...))` returns the same service
  `/triage` uses, so per-workspace taxonomy, published prompts and the legacy fallback all apply.
- **Ephemeral + observable:** a `gmail.sync` span carries `tenant_id` and message count; the
  per-message triage runs inside `logfire.set_baggage(tenant_id=...)` so child spans are tagged
  (same pattern as Plan 33). Only the existing `TriageLog` (via the triage call path) records
  anything; email bodies are never stored.

## Files involved

| File | Role |
|---|---|
| `email_triage/services/gmail.py` | `GmailClient` (refresh, list_today, `parse_message`), `GmailMessage`, `GmailError`/`GmailAuthError` |
| `email_triage/routers/inbox.py` | `GET /gmail/status`, `POST /gmail/sync`; message→`TriageRequest` coercion; error mapping |
| `email_triage/schemas.py` | `GmailStatusResponse`, `InboxItem`, `SyncResponse` |
| `email_triage/deps.py` | `WriteTriageDep` (session + `triage:write`) |
| `email_triage/db/repos/gmail.py` | `touch_last_synced` |
| `email_triage/main.py` | register the inbox router |
| `tests/test_gmail_sync.py` | parse, client (mocked httpx), and router (404/409/503/empty/items) |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Map message → `TriageRequest` and reuse `LLMService` | A separate Gmail triage engine | The per-tenant engine is already in prod; zero regression, one path |
| Emails ephemeral (no body persisted) | Store fetched emails | Privacy: the model already avoids storing content; less legal/attack surface |
| `invalid_grant`/401 → 409 "reconnect" | Generic 500 | It's a user-actionable state (reconnect), not a server fault |
| Prefer `text/plain` anywhere, then any `text/*`, then snippet | Take the first `text/*` part | An HTML sibling would otherwise win over the plain-text body |
| All-messages-failed → 503 (else skip a bad one) | Always 200 with partial items | One odd email shouldn't fail the batch, but a full outage shouldn't look like an empty inbox |
| Sequential per-message triage | Parallel with a semaphore | Simplicity + determinism at `max_results=25`; parallelism is a follow-up |
| `newer_than:1d` (rolling 24h) | `after:<local-midnight-epoch>` | Simple and good enough for v1; strict local-midnight is a follow-up |

## Gotchas / Edge cases

- **Sender coercion:** a `From: "Name" <a@b.com>` header isn't a valid `EmailStr`; the router
  extracts the address (`parseaddr`) for classification and keeps the raw header for display.
  Unparseable senders fall back to a placeholder so one email never 422s the batch.
- **Empty body:** falls back to subject/snippet and is truncated to the `TriageRequest` limits.
- **Rate limits:** `GmailClient` retries 429/503 twice with backoff, then raises → 502.
- **Cost/latency:** N triage calls per sync, bounded by `GMAIL_SYNC_MAX_RESULTS` (default 25);
  watch `gmail.sync` in Logfire.

## Verified

- `make check` green: ruff + pyright (0) + **227 tests** (15 new in `tests/test_gmail_sync.py`).
- No network in tests: Google (token/list/get) and the DB are mocked; the triage service is
  patched. Parsing, retry-auth mapping, and the 404/409/503/empty/items paths are all covered.

## Testing

📋 [Testing guide](../testing/37-gmail-sync-inbox_testing.md)
