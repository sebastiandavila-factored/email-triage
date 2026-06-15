# Feature 14 — PostgreSQL + SQLAlchemy Persistence Layer

## Summary

Adds an optional, async PostgreSQL persistence layer using SQLAlchemy 2.x ORM and Alembic migrations. All triage requests are logged to a `triage_logs` table via fire-and-forget background tasks. Eval runs and per-case results are written to `eval_runs` / `eval_cases` tables after every `make eval` or `make eval-quick` invocation. The database is optional: the app starts and serves requests normally without `DATABASE_URL` configured.

## Architecture decisions

| Decision | Alternative | Reason |
|---|---|---|
| SQLAlchemy 2.x async ORM | raw asyncpg queries | ORM gives Alembic autogenerate and Python-level type safety at low overhead |
| `async_sessionmaker` module-level singleton | session-per-request | Fire-and-forget tasks run after the request lifecycle; they need their own sessions |
| `BackgroundTasks` for triage logging | inline await | Keeps critical path latency unaffected by DB writes |
| `aiosqlite` in tests | test Postgres container | No Docker dependency in CI; SQLAlchemy 2.x dialect abstracts the difference |
| Optional `DATABASE_URL` | required config | Simplifies local development and CI without a running database |

## Database schema

```
tenants          — future auth (Plan 15). tenant_id FK from triage_logs.
triage_logs      — one row per /triage or /triage/stream call.
eval_runs        — one row per make eval invocation.
eval_cases       — one row per dataset case within a run (CASCADE-deleted with run).
```

## New files

| Path | Role |
|---|---|
| `src/email_triage/db/__init__.py` | Package init |
| `src/email_triage/db/base.py` | `DeclarativeBase` shared by all models |
| `src/email_triage/db/engine.py` | Module-level singleton engine + `init_db` / `close_db` / `get_session_factory` |
| `src/email_triage/db/models.py` | `Tenant`, `TriageLog`, `EvalRun`, `EvalCase` ORM models |
| `src/email_triage/db/repos/triage.py` | `TriageLogRepo` + `persist_triage_log()` |
| `src/email_triage/db/repos/evals.py` | `EvalRepo` + `persist_eval_run()` |
| `alembic.ini` | Alembic config (DATABASE_URL from env) |
| `alembic/env.py` | Async-capable env using `asyncio.run` |
| `alembic/versions/0001_initial.py` | Initial migration: all four tables + indexes |
| `docker-compose.yml` | `postgres:17-alpine` for local dev (`make db-up`) |
| `tests/test_db.py` | 3 async tests covering insert + cascade delete |

## Modified files

| Path | Change |
|---|---|
| `src/email_triage/config.py` | Added `database_url: str \| None = None` |
| `src/email_triage/main.py` | Lifespan calls `init_db` + `close_db`; `database_url` added to scrub list |
| `src/email_triage/routers/triage.py` | Added `persist_triage_log` background task |
| `evals/run_evals.py` | Added `persist_eval_run` call after each run |
| `.env.example` | Added `DATABASE_URL` example |
| `Makefile` | Added `db-up`, `db-down`, `db-migrate`, `db-revision`, `db-shell` |
| `tests/conftest.py` | Added `db_session` fixture using `sqlite+aiosqlite:///:memory:` |
| `pyproject.toml` | Added `alembic`, `asyncpg`, `sqlalchemy[asyncio]`; dev: `aiosqlite` |

## Local development workflow

```bash
make db-up         # start postgres:17-alpine container
make db-migrate    # apply 0001_initial (reads DATABASE_URL from .env)
make dev           # app connects and logs to DB on startup
make db-shell      # open psql for inspection
make db-down       # stop and remove container
```

## Environment variables

| Variable | Example | Required |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/email_triage` | No (app no-ops without it) |
