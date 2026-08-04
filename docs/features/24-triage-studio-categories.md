# Triage Studio F1 — Per-workspace categories

## What it does

Moves triage categories out of the frozen `schemas.Category` StrEnum and into a
per-tenant `categories` table. Each workspace now owns its taxonomy: `owner` and
`admin` roles can create, edit, activate/deactivate and delete categories through
`/workspaces/{tid}/categories*`, gated by the new `triage:configure` scope.
`member` can only read.

This is phase F1 of [proposal 001 — Triage Studio](../proposals/001-triage-studio.md).
It is deliberately zero-regression: `/triage`, `services/llm.py` and
`schemas.Category` are untouched, so classification still runs on the legacy enum.
The prompt compiler that consumes these categories (dynamic output type, XML
composition) lands in F2.

## How it works

```
POST /workspaces/{tid}/categories
  → require_scope("triage:configure")   # role in {owner, admin}, + membership (anti-IDOR)
  → TriageConfigService.create_category  # rules: reserved/format/uniqueness
  → CategoryRepo.create                  # SQL, appends sort_order
```

- **Seeding:** every workspace is born with the 5 legacy categories. New workspaces
  are seeded in code (`TriageConfigService.seed_defaults`, called from team creation
  and both personal-workspace paths in `routers/auth.py`); existing workspaces are
  seeded by migration `0004` (idempotent data step).
- **Reserved slug:** `unknown` cannot be created — it is the implicit escape category
  the F2 compiler will always add.
- **Immutable slug:** only `name`/`description`/`is_active`/`sort_order` are editable.
  The slug is the classification value written to `triage_logs`/evals, so renaming
  would corrupt history. Rename = create new + deactivate old.
- **Last-active guard:** deactivating or deleting the final active category returns
  409 — a tenant must always keep at least one active category (analogous to the
  last-owner rule in Plan 21).

## Files involved

| File | Role |
|---|---|
| `email_triage/db/models.py` | `Category` ORM model + `Tenant.categories` relationship |
| `alembic/versions/0004_categories.py` | Creates `categories`, seeds existing tenants (idempotent) |
| `email_triage/db/repos/categories.py` | `CategoryRepo` — tenant-scoped SQL |
| `email_triage/services/triage_config.py` | `TriageConfigService` — rules + `seed_defaults`; `DEFAULT_CATEGORIES`, `RESERVED_SLUGS` |
| `email_triage/auth/scopes.py` | `TRIAGE_CONFIGURE` added to `owner`/`admin` |
| `email_triage/deps.py` | `ConfigureTriageDep = require_scope("triage:configure")` |
| `email_triage/routers/categories.py` | `/workspaces/{tid}/categories*` CRUD |
| `email_triage/services/workspace.py`, `email_triage/routers/auth.py` | Wire `seed_defaults` into workspace creation |
| `email_triage/main.py` | Registers the router |
| `tests/test_triage_config.py` | Service rules + HTTP scope/IDOR tests |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Only `categories` table in F1 | Create all 4 Studio tables now | `prompt_templates`/`examples` are coupled to the F2 compiler; defining them now guarantees rework |
| `/triage` and `schemas.Category` untouched | Migrate the critical path now | F1 must be zero-regression; the legacy enum keeps serving until F2's compiler is proven |
| Seed 5 legacy per workspace | Start empty | Continuity — no tenant loses today's behavior |
| `unknown` reserved, not stored | Let owners create it | It is the compiler's escape category (F2); reserving avoids collision |
| Immutable slug | Editable slug with propagation | Slug is the value in logs/evals; renaming corrupts history |
| Category of another tenant → 404 | 403 | Don't leak existence of another tenant's resources (OWASP) |
| Slug lowercased/trimmed then validated | Reject any non-canonical input | Friendlier: `"  Returns "` → `returns`; only truly invalid shapes (spaces, dashes, emoji, >50) 422 |

## Gotchas / Edge cases

- **Seed in mocked unit tests:** `signup`/`callback` now call `seed_defaults`. Tests
  that fully mock the DB session must also patch `routers.auth.TriageConfigService`
  (see `tests/test_auth.py`), or the real `CategoryRepo` runs against the mock.
- **FK not enforced under SQLite:** service tests use arbitrary tenants created via
  `TenantRepo`; SQLite doesn't enforce the `tenant_id` FK by default, which is fine
  for these unit tests.
- **Migration seed is Postgres-only in practice:** it uses `now()` and is exercised
  against the real DB, not the SQLite metadata used by tests. Verify manually (see
  the testing guide).

## Testing

📋 [Testing guide](../testing/24-triage-studio-categories_testing.md)
