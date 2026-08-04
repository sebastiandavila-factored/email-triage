# Testing: Triage Studio F1 — Per-workspace categories

## Prerequisites

- App running with a real database (`DATABASE_URL` set, migrations applied):
  ```bash
  uv run alembic upgrade head
  uv run uvicorn email_triage.main:app --reload
  ```
- A logged-in user with a Bearer token (via `/auth/signup` or `/auth/login`) and a
  workspace id `{tid}`. The examples below use `$TOKEN` and `$TID`.
- Automated suite: `uv run pytest tests/test_triage_config.py -v`.

## Test Cases

### TC-01: List seeded categories (member+)
**Action**: `GET /workspaces/$TID/categories` with any member's Bearer token.
**Expected**: 200, exactly the 5 legacy categories (`status`, `refunds`,
`availability`, `shipments`, `prices`), each `is_active: true`.

### TC-02: Create category (owner/admin)
**Action**:
```bash
curl -X POST localhost:8000/workspaces/$TID/categories \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"slug":"returns","name":"Returns","description":"Return/exchange requests"}'
```
**Expected**: 201, body echoes the category with `sort_order: 5`.

### TC-03: Member cannot create
**Action**: TC-02 with a `member` token.
**Expected**: 403, detail contains `triage:configure`.

### TC-04: Reserved slug rejected
**Action**: POST with `"slug":"unknown"`.
**Expected**: 422, "reserved slug".

### TC-05: Duplicate slug rejected
**Action**: POST `"slug":"status"` (already seeded).
**Expected**: 409.

### TC-06: Edit display copy, slug immutable
**Action**: `PATCH /workspaces/$TID/categories/{cid}` with
`{"name":"Returns & Exchanges","description":"..."}`.
**Expected**: 200, `name` updated, `slug` unchanged. (No `slug` field is accepted.)

### TC-07: Last-active guard
**Action**: Deactivate every category but one, then `PATCH` the last one with
`{"is_active": false}` (or `DELETE` it).
**Expected**: 409, "last active category".

### TC-08: New workspace is seeded
**Action**: `POST /workspaces` (create team), then `GET .../categories`.
**Expected**: the new workspace already has the 5 legacy categories.

### TC-09: `/triage` unaffected (regression)
**Action**: Call `POST /triage` with a workspace API key as before.
**Expected**: identical behavior to pre-F1 — still classifies into the 5 legacy
categories. F1 does not change the classification path.

## Edge Cases

| Scenario | Expected |
|---|---|
| Slug with spaces / dashes / uppercase-only-invalid chars / >50 chars | 422 |
| Slug `"  Returns "` | 201, normalized to `returns` |
| Non-member calls any category endpoint on `$TID` | 403 (IDOR covered) |
| Owner edits a category id that belongs to another workspace | 404 (no existence leak) |
| `?active=true` filter | Only `is_active: true` rows returned |

## Migration verification

```bash
# Against a DB that already had tenants before 0004:
uv run alembic upgrade head
# Each pre-existing tenant now has 5 categories:
psql "$DATABASE_URL" -c \
  "SELECT tenant_id, count(*) FROM categories GROUP BY tenant_id;"
# Idempotency: re-stamping/re-running the data step must NOT duplicate.
```

## Log verification

- `category.created` / `category.updated` / `category.deleted` structured logs carry
  `tenant_id` and `slug`.
- `triage_config.seeded` logs on workspace creation with `n=5`.

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| 500 on signup in a unit test | Mocked session hits real `CategoryRepo` via `seed_defaults` | Patch `email_triage.routers.auth.TriageConfigService` in the test |
| 403 on create with an owner token | Token minted for a different workspace, or `triage:configure` not in role | Confirm the caller's membership+role in `$TID` |
| Migration seeds 0 rows | No tenants existed yet | Expected; new workspaces seed in code, not the migration |
