# Testing Plan — Feature 16: Users + Password Auth + Role-Scoped Security

## Automated tests (`tests/test_auth.py`)

All tests mock the DB. No real network calls. bcrypt rounds reduced to 4 in test fixtures for speed.

### New tests — signup

| Test | What it verifies |
|---|---|
| `test_signup_creates_user_and_personal_tenant` | Valid email + password → 200, session cookie set, `api_key` in response, `tenant_type = 'personal'` |
| `test_signup_duplicate_email_returns_409` | Same email twice → 409 |
| `test_signup_weak_password_returns_422` | Password shorter than 8 chars → 422 |
| `test_signup_invalid_email_returns_422` | Malformed email → 422 |

### New tests — password login

| Test | What it verifies |
|---|---|
| `test_login_password_success` | Valid credentials → 200, session cookie set, no `api_key` in response |
| `test_login_wrong_password_returns_401` | Wrong password → 401, same message as unknown email |
| `test_login_unknown_email_returns_401` | Unknown email → 401 |
| `test_login_google_only_account_returns_401` | User has `password_hash = NULL` → 401 with SSO hint |

### New tests — scope enforcement

| Test | What it verifies |
|---|---|
| `test_rotate_key_as_owner_succeeds` | Session with `owner` role → 200 |
| `test_rotate_key_as_admin_succeeds` | Session with `admin` role → 200 (`workspace:manage` granted) |
| `test_rotate_key_as_member_returns_403` | Session with `member` role → 403 (missing `workspace:manage`) |

### Existing tests that must remain green

All 36 tests from Plans 14 and 15:
- `tests/test_triage.py` — 11 triage/health tests
- `tests/test_db.py` — 3 DB fixture tests
- `tests/test_auth.py` — 16 PKCE + Google SSO tests (pkce, session cookies, /auth/login Google, /auth/callback, /auth/me, /auth/me unauthenticated)

Run all:
```bash
uv run pytest -v
```

## Manual tests (browser + curl)

### TC-M01 — Email + password signup (new user, new personal workspace)

```bash
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@acme.com", "password": "hunter2hunter", "display_name": "Alice"}' \
  -c cookies.txt -v
```

Expected response:
```json
{
  "email": "alice@acme.com",
  "display_name": "Alice",
  "tenant_id": "...",
  "tenant_name": "Alice's workspace",
  "tenant_type": "personal",
  "plan": "free",
  "api_key": "<shown once>"
}
```

Verify: `session` cookie set, `HttpOnly`, `SameSite: Lax`.

### TC-M02 — Duplicate signup returns 409

Repeat TC-M01 with same email. Expected: `409 Conflict`.

### TC-M03 — Password login

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@acme.com", "password": "hunter2hunter"}' \
  -c cookies.txt
```

Expected: `200`, session cookie set, no `api_key` in response.

### TC-M04 — Wrong password returns 401

Change password to `"wrongpass"`. Expected: `401`. Verify the response message is identical to TC-M05 (no user enumeration).

### TC-M05 — Unknown email returns 401

Use `"email": "nobody@example.com"`. Expected: `401` with same message as TC-M04.

### TC-M06 — GET /auth/me returns full context

```bash
curl http://localhost:8000/auth/me -b cookies.txt
```

Expected:
```json
{
  "user_id": "...",
  "email": "alice@acme.com",
  "display_name": "Alice",
  "email_verified": false,
  "tenant_id": "...",
  "tenant_name": "Alice's workspace",
  "tenant_type": "personal",
  "plan": "free",
  "role": "owner"
}
```

### TC-M07 — API key works for /triage

```bash
curl -X POST http://localhost:8000/triage \
  -H "X-API-Key: <api_key from TC-M01>" \
  -H "Content-Type: application/json" \
  -d '{"subject": "test", "body": "test", "sender": "a@b.com"}'
```

Expected: `200` with triage result.

### TC-M08 — rotate-key scope enforcement

Create two sessions: one as `owner` (Alice from TC-M01), and manually set one as `member` via DB:
```sql
UPDATE memberships SET role = 'member' WHERE user_id = '<alice uuid>';
```

Then:
```bash
# With owner session → 200
curl -X POST http://localhost:8000/auth/rotate-key -b cookies.txt

# After changing role to member → 403
curl -X POST http://localhost:8000/auth/rotate-key -b cookies.txt
```

Expected: `403` with `"Scope required: workspace:manage"`.

Reset: `UPDATE memberships SET role = 'owner' WHERE ...`.

### TC-M09 — Google SSO user cannot use password login

1. Sign in via `GET /auth/login` (Google SSO).
2. Attempt:
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "<google email>", "password": "anything"}'
```

Expected: `401` with message hinting at Google SSO. Message must match the generic "invalid credentials" pattern (no different phrasing).

### TC-M10 — Migration: existing Plan 15 users preserved

1. Before `make db-migrate`: note existing `tenants` rows and their UUIDs in Neon.
2. `make db-migrate`.
3. Query:

```sql
-- Old tenant data now in users
SELECT id, email, display_name, google_sub IS NOT NULL AS has_google FROM users;

-- Tenants reshaped as personal workspaces (same UUIDs)
SELECT id, domain, name, type FROM tenants;

-- Memberships created (role = owner)
SELECT u.email, t.name, m.role
FROM memberships m
JOIN users u ON u.id = m.user_id
JOIN tenants t ON t.id = m.tenant_id;

-- triage_logs still reference valid tenant_ids
SELECT COUNT(*) FROM triage_logs tl
LEFT JOIN tenants t ON t.id = tl.tenant_id
WHERE tl.tenant_id IS NOT NULL AND t.id IS NULL;
-- Expected: 0 (no orphaned logs)
```

4. Sign in with the same Google account → should succeed and return the existing `tenant_id`.

## Database queries for verification

Connect with `make db-shell`:

```sql
-- All users
SELECT id, email, display_name,
       google_sub IS NOT NULL AS has_google,
       password_hash IS NOT NULL AS has_password,
       email_verified
FROM users;

-- All workspaces
SELECT id, domain, name, type, plan,
       api_key_hash IS NOT NULL AS has_key
FROM tenants;

-- All memberships with context
SELECT u.email, t.name, t.type, m.role
FROM memberships m
JOIN users u ON u.id = m.user_id
JOIN tenants t ON t.id = m.tenant_id
ORDER BY u.email;
```
