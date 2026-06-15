# 14. PostgreSQL + SQLAlchemy — Persistence Layer

**Status:** 📋 proposed
**Estimate:** 5 hrs

## Intent

The API currently holds no state: every request is ephemeral, eval results live only in Logfire, and there is no way to associate a request with a specific customer. This plan adds a PostgreSQL persistence layer using SQLAlchemy 2.x async — the modern, type-safe, officially recommended approach for FastAPI async services.

Four tables are introduced:

| Table | Purpose |
|---|---|
| `tenants` | One row per customer (mailbox / founder). Stores email, hashed API key, plan, and Google subject ID (pre-wired for Plan 15). |
| `triage_logs` | One row per `/triage` or `/triage/stream` request. Enables per-tenant analytics and billing signals. |
| `eval_runs` | One row per `make eval` invocation — accuracy, macro-F1, ECE, model used. |
| `eval_cases` | One row per case per run — individual correctness, confidence, judge score. |

The repository pattern isolates all SQL from handlers. FastAPI `Depends()` injects repositories just like the existing `LLMService`.

All code, comments, and documentation produced by this plan are written in **English**.

## Prior reading

- **SQLAlchemy 2.x async ORM** — https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- **FastAPI + SQLAlchemy (official tutorial)** — https://fastapi.tiangolo.com/tutorial/sql-databases/
- **Alembic migration tutorial** — https://alembic.sqlalchemy.org/en/latest/tutorial.html
- **asyncpg driver** — https://magicstack.github.io/asyncpg/current/
- **Render managed PostgreSQL** — https://render.com/docs/postgresql-creating-connecting
- **SQLAlchemy 2 migration guide** (if any existing ORM code uses 1.x patterns) — https://docs.sqlalchemy.org/en/20/changelog/migration_20.html
- **12-factor app: backing services** — https://12factor.net/backing-services

## Scope

**Included:**
- New dependencies: `sqlalchemy[asyncio]>=2.0`, `asyncpg>=0.30`, `alembic>=1.14`.
- `src/email_triage/db/` sub-package: engine factory, base model, all ORM models, repositories.
- Alembic setup with `env.py` configured for async.
- `config.py` gets `database_url: PostgresDsn` from env.
- FastAPI lifespan creates / disposes the async engine.
- `deps.py` gets `get_db_session` and per-repository dependencies.
- `routers/triage.py` logs each successful triage to `triage_logs` (fire-and-forget, does not block the response).
- `evals/run_evals.py` writes `eval_runs` + `eval_cases` rows after each run.
- Makefile targets: `db-migrate` (run pending Alembic migrations), `db-revision` (generate a new one).
- Local dev: PostgreSQL via Docker (`docker compose up -d db`); `docker-compose.yml` added.
- Tests: pytest fixture spins up a real SQLite URL (via `aiosqlite`) for unit tests — no mocking of the DB layer.
- `docs/features/14-database.md` and `docs/testing/14-database_testing.md`.

**Out of scope:**
- Multi-tenant row-level security in PostgreSQL (post-MVP).
- Read replicas or connection pooling via PgBouncer.
- Soft deletes / audit trail tables.
- GraphQL or any query API over the DB.

## Schema

```sql
-- tenants
CREATE TABLE tenants (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_sub   TEXT UNIQUE,                  -- pre-wired for Plan 15 OAuth
    email        TEXT UNIQUE NOT NULL,
    display_name TEXT,
    api_key_hash TEXT NOT NULL,                -- bcrypt hash; never store plaintext
    plan         TEXT NOT NULL DEFAULT 'free',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- triage_logs
CREATE TABLE triage_logs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id   TEXT NOT NULL,                -- from middleware X-Request-Id
    tenant_id    UUID REFERENCES tenants(id),  -- NULL for unauthenticated (unlikely)
    subject_chars INT NOT NULL,
    body_chars   INT NOT NULL,
    category     TEXT NOT NULL,
    confidence   REAL NOT NULL,
    draft_chars  INT NOT NULL,
    latency_ms   REAL,
    endpoint     TEXT NOT NULL,                -- 'sync' | 'stream'
    model_id     TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON triage_logs (tenant_id, created_at DESC);

-- eval_runs
CREATE TABLE eval_runs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_version  TEXT NOT NULL,            -- SHA256[:8] of dataset.jsonl
    model_id         TEXT NOT NULL,
    n_cases          INT NOT NULL,
    accuracy         REAL NOT NULL,
    macro_f1         REAL NOT NULL,
    ece              REAL NOT NULL,
    mean_judge_score REAL,                     -- NULL when --no-judge
    ran_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- eval_cases
CREATE TABLE eval_cases (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id               UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id              TEXT NOT NULL,         -- e.g. 'status-003'
    expected_category    TEXT NOT NULL,
    predicted_category   TEXT NOT NULL,
    is_correct           BOOLEAN NOT NULL,
    confidence           REAL NOT NULL,
    judge_overall        SMALLINT,              -- NULL when --no-judge
    judge_language_match BOOLEAN,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON eval_cases (run_id);
```

## Directory structure

```
src/email_triage/
└── db/
    ├── __init__.py
    ├── engine.py        # async engine + session factory (AsyncSessionLocal)
    ├── base.py          # DeclarativeBase subclass with shared metadata
    ├── models.py        # Tenant, TriageLog, EvalRun, EvalCase ORM models
    └── repos/
        ├── __init__.py
        ├── triage.py    # TriageLogRepo: insert_log()
        └── evals.py     # EvalRepo: insert_run(), insert_cases()

alembic/
├── env.py               # async-capable env using run_sync
├── script.py.mako
└── versions/
    └── 0001_initial.py  # auto-generated from models
```

## Concrete changes

| File | Change |
|---|---|
| `pyproject.toml` | Add `sqlalchemy[asyncio]>=2.0`, `asyncpg>=0.30`, `alembic>=1.14`, `aiosqlite>=0.20` (test dep). |
| `src/email_triage/config.py` | Add `database_url: PostgresDsn`. |
| `src/email_triage/db/engine.py` | `create_async_engine(settings.database_url)` + `AsyncSessionLocal` factory. |
| `src/email_triage/db/base.py` | `class Base(DeclarativeBase): pass` — shared metadata for Alembic autogenerate. |
| `src/email_triage/db/models.py` | `Tenant`, `TriageLog`, `EvalRun`, `EvalCase` SQLAlchemy 2.x mapped classes. |
| `src/email_triage/db/repos/triage.py` | `TriageLogRepo.insert_log(session, data)`. |
| `src/email_triage/db/repos/evals.py` | `EvalRepo.insert_run(session, run) → UUID`, `insert_cases(session, run_id, cases)`. |
| `src/email_triage/deps.py` | Add `get_db_session` async generator dependency + `TriageLogRepoDep`. |
| `src/email_triage/main.py` | Lifespan: `await engine.dispose()` on shutdown; optionally run pending Alembic migrations on startup (dev only, flag-gated). |
| `src/email_triage/routers/triage.py` | After successful triage: `asyncio.create_task(repo.insert_log(...))` — fire-and-forget, never blocks the response path. |
| `alembic/env.py` | Async env using `connectable.run_sync(do_run_migrations)`. Import `Base.metadata` for autogenerate. |
| `alembic/versions/0001_initial.py` | Initial migration (all four tables). |
| `alembic.ini` | Standard Alembic config; `sqlalchemy.url` reads `DATABASE_URL` from env. |
| `docker-compose.yml` | `postgres:17-alpine` service on port 5432. Dev-only. |
| `.env.example` | Add `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/email_triage`. |
| `Makefile` | Add `db-migrate`, `db-revision`, `db-shell` targets. |
| `tests/conftest.py` | Add `db_session` pytest fixture using `aiosqlite` + `Base.metadata.create_all`. |
| `tests/test_db.py` | Tests: insert + query TriageLog, insert EvalRun + EvalCases with cascade delete. |
| `docs/features/14-database.md` | Feature doc. |
| `docs/testing/14-database_testing.md` | Testing doc. |
| `docs/exec-plans/README.md` | Add entry #14. |

## Technical design

### 1. Engine and session (SQLAlchemy 2.x async)

```python
# src/email_triage/db/engine.py
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from email_triage.config import settings

engine = create_async_engine(
    str(settings.database_url),
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # detect stale connections before use
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # avoid lazy-load errors after commit
)
```

### 2. ORM models (SQLAlchemy 2.x mapped dataclasses style)

```python
# src/email_triage/db/models.py
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, func, String, Float, Integer, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from email_triage.db.base import Base

class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    google_sub: Mapped[str | None] = mapped_column(String, unique=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str | None]
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(String, default="free")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

class TriageLog(Base):
    __tablename__ = "triage_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    subject_chars: Mapped[int]
    body_chars: Mapped[int]
    category: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float]
    draft_chars: Mapped[int]
    latency_ms: Mapped[float | None]
    endpoint: Mapped[str] = mapped_column(String, nullable=False)  # 'sync' | 'stream'
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

### 3. Dependency injection

```python
# src/email_triage/deps.py (addition)
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from email_triage.db.engine import AsyncSessionLocal
from email_triage.db.repos.triage import TriageLogRepo

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
TriageLogRepoDep = Annotated[TriageLogRepo, Depends(lambda: TriageLogRepo())]
```

### 4. Fire-and-forget logging in the triage handler

The DB write must **never** add latency to the triage response. Pattern:

```python
# src/email_triage/routers/triage.py
import asyncio

@router.post("")
async def triage(req: TriageRequest, llm: LLMDep, session: DbSession, repo: TriageLogRepoDep) -> TriageResponse:
    t0 = time.perf_counter()
    response = await llm.triage(req)
    latency_ms = (time.perf_counter() - t0) * 1000

    # fire-and-forget: do not await, do not block the response
    asyncio.create_task(
        repo.insert_log(session, req, response, latency_ms, endpoint="sync")
    )
    return response
```

`asyncio.create_task` schedules the coroutine on the running event loop. If it fails, the exception is logged (attach a done-callback) but does **not** propagate to the caller.

### 5. Alembic async env

```python
# alembic/env.py (key parts)
import asyncio
from sqlalchemy.ext.asyncio import async_engine_from_config
from email_triage.db.base import Base

target_metadata = Base.metadata

def run_migrations_online() -> None:
    connectable = async_engine_from_config(config.get_section(config.config_ini_section))

    async def run_async_migrations() -> None:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()

    asyncio.run(run_async_migrations())
```

### 6. Makefile targets

```makefile
db-migrate: ## Apply pending Alembic migrations
	uv run alembic upgrade head

db-revision: ## Generate a new Alembic migration (MSG required). Usage: make db-revision MSG="add tenants"
	uv run alembic revision --autogenerate -m "$(MSG)"

db-shell: ## Open psql shell to the local dev database
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	psql $$DATABASE_URL
```

### 7. Test fixture

Unit tests use `aiosqlite` so they run without a running PostgreSQL:

```python
# tests/conftest.py (addition)
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from email_triage.db.base import Base

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()
```

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| SQLAlchemy 2.x async ORM | Tortoise ORM, SQLModel, raw asyncpg | SQLAlchemy is the industry standard; 2.x mapped dataclasses are fully type-safe; supported by Alembic natively |
| asyncpg driver | psycopg3 async | asyncpg is the fastest async PostgreSQL driver in Python; no C extension compile step on Render |
| Repository pattern | SQL in handlers | Keeps handlers thin and testable; repositories can be swapped for mocks without touching route logic |
| `asyncio.create_task` for triage logging | Middleware, background tasks, queue | Simplest fire-and-forget in async context; no additional service; acceptable for MVP volume |
| `aiosqlite` for tests | Docker PostgreSQL in tests, testcontainers | No Docker daemon required in CI; SQLAlchemy abstracts dialect differences for simple CRUD |
| `pool_pre_ping=True` | Default (no pre-ping) | Prevents `OperationalError` on idle connections after Render's PostgreSQL kills them at 5 min |
| UUID primary keys | Auto-increment integer | Render's PostgreSQL supports `gen_random_uuid()`; UUIDs are safe to expose in APIs; no sequential enumeration risk |
| `google_sub` column in `tenants` now (nullable) | Add it in Plan 15 | Schema migration is cheaper than a data migration later; column is NULL for all rows until Plan 15 |

## Risks

- **Schema drift between Alembic and models**: `--autogenerate` catches most changes but misses some (e.g. server-side defaults, check constraints). Mitigation: always review generated migration before applying.
- **Fire-and-forget task failures silently dropped**: if the DB is down, the triage log is lost with no retry. Mitigation: attach a `done_callback` that logs the exception to structlog. For MVP this is acceptable; a proper outbox pattern is post-MVP.
- **aiosqlite behavioral differences from PostgreSQL**: UUID type, `TIMESTAMPTZ`, and some index types differ. Mitigation: integration tests against a real PostgreSQL in the staging environment before each deploy.
- **Connection pool exhaustion under load**: `pool_size=5, max_overflow=10` gives 15 max connections. Render's free PostgreSQL tier allows 25. Safe at MVP scale; revisit at 100 req/min sustained.

## Execution order

1. **Deps + config** (20 min): add packages to `pyproject.toml`, `uv sync`, add `DATABASE_URL` to `config.py` and `.env.example`.
2. **Engine + base + models** (30 min): `db/engine.py`, `db/base.py`, `db/models.py` with all four models.
3. **Alembic setup** (30 min): `alembic init`, configure `env.py` for async, generate and apply `0001_initial.py`.
4. **Repositories** (30 min): `repos/triage.py` and `repos/evals.py`.
5. **FastAPI integration** (30 min): `deps.py` additions, lifespan engine disposal, fire-and-forget in `routers/triage.py`.
6. **Eval runner integration** (20 min): `evals/run_evals.py` writes `eval_runs` + `eval_cases` after each run.
7. **Docker Compose** (15 min): `docker-compose.yml` with `postgres:17-alpine`, `Makefile` targets.
8. **Tests** (30 min): `db_session` fixture, `tests/test_db.py` — insert/query TriageLog, cascade delete EvalCases.
9. **Docs + close** (20 min): feature doc, testing doc, README update, `make check`.

## Done when

- [ ] `uv sync` succeeds with new deps
- [ ] `make db-migrate` applies `0001_initial` against local PostgreSQL without errors
- [ ] `POST /triage` logs a row to `triage_logs` (verify with `make db-shell` + `SELECT * FROM triage_logs LIMIT 5`)
- [ ] `make eval` writes one `eval_runs` row and 40 `eval_cases` rows (verify with `SELECT count(*) FROM eval_cases`)
- [ ] `make test` passes — `tests/test_db.py` green with aiosqlite fixture
- [ ] `make check` passes (ruff + pyright + all tests)
- [ ] `DATABASE_URL` is never logged or included in spans (check scrubbing config)
- [ ] `docs/features/14-database.md` and `docs/testing/14-database_testing.md` created
- [ ] `docs/exec-plans/README.md` updated with entry #14
