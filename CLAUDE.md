# CLAUDE.md — Technical Conventions

Technical reference for AI agents working on this repo. Read before editing code.

## Stack

| Component | Version | Role |
|---|---|---|
| Python | 3.14 | Runtime (pinned in `.python-version`) |
| FastAPI | ≥0.136 | Framework, validation, auto-docs |
| Uvicorn | ≥0.48 | ASGI server (dev `--reload`) |
| Gunicorn | ≥26.0 | Process manager in production |
| httpx | ≥0.28 | Async HTTP client (requests in tests) |
| pydantic-ai-slim[groq] | ≥1.104 | Provider-agnostic LLM client (Groq via Pydantic AI) |
| pydantic-settings | ≥2.14 | Typed config from `.env` |
| structlog | ≥25.5 | JSON logs with `request_id`, `trace_id`, `span_id` |
| logfire[fastapi,httpx,system-metrics] | ≥4.34 | OTEL observability: HTTP spans, pydantic-ai, httpx, system metrics; scrubbing + sampling |
| slowapi | ≥0.1.9 | Rate limiting by IP (20 req/min on `/triage`) |
| uv | external | Package and environment manager |
| ruff | --dev | Lint + format |
| pyright | --dev | Type checker (strict) |
| pre-commit | --dev | Local hooks |

## Target structure

```
email-triage/
├── email_triage/        # Main package
│   ├── main.py              # FastAPI app + lifespan
│   ├── config.py            # Settings (pydantic-settings)
│   ├── schemas.py           # TriageRequest, TriageResponse, Category
│   ├── deps.py              # Injectable dependencies (api key, llm)
│   ├── middleware.py        # request_id + timing + structlog
│   ├── services/            # Business logic
│   │   └── llm.py           # LLMService (Groq via httpx → Pydantic AI)
│   └── routers/             # Endpoints grouped by domain
│       ├── health.py
│       └── triage.py
├── tests/                   # pytest async, no real network
├── docs/                    # see AGENTS.md
├── Dockerfile               # multi-stage uv (Day 6)
├── gunicorn.conf.py         # (Day 6)
└── pyproject.toml           # deps + ruff + pyright config
```

**Build:** `hatchling` declared in `[build-system]`. Package is installed editable with `uv sync`.

## Tests

Formally established on Day 5. Conventions:

- `pytest` + `pytest-asyncio` with `asyncio_mode = "auto"` (in `pyproject.toml`).
- Tests **never** call Groq. The `get_llm_service` dependency is overridden with a mock via `app.dependency_overrides`.
- Commands:
  - `uv run pytest` — full suite
  - `uv run pytest tests/test_triage.py -v`

## Code quality

- Format: `uv run ruff format`
- Lint: `uv run ruff check --fix`
- Types: `uv run pyright`
- Hooks: `uv run pre-commit run --all-files`

Pre-commit runs ruff + pyright. If it fails, fix the code — **do not** use `--no-verify`.

## Agreed patterns

Some are not yet implemented but are already contractual. Respect them when adding code.

### 1. Pydantic as single source of truth
- **What:** every input/output payload is a Pydantic model.
- **Where:** `email_triage/schemas.py` (from Day 2).
- **Why:** FastAPI uses them for validation + serialization + docs simultaneously.

### 2. Dependency injection for external services
- **What:** `LLMService`, `Settings`, etc. are injected via `Depends()`, not instantiated inside the handler.
- **Where:** `email_triage/deps.py` (Day 4).
- **Why:** in tests they are replaced with `app.dependency_overrides` without monkeypatching.

### 3. Async by default on the critical path
- **What:** handlers that touch the network are `async def`. Sync only if the op is trivially CPU-bound.
- **Where:** every handler that calls `LLMService`.
- **Why:** each request waits 1-3s for Groq. Sync blocks the worker — the difference between 5 and 500 concurrent.

### 4. Errors with correct HTTP codes
- **What:** `try/except` around LLM calls. Raise `HTTPException` with semantic status (503 if Groq is down, 422 if LLM output doesn't validate, 403 if API key is missing).
- **Where:** handlers in `routers/triage.py`.
- **Why:** the caller (Zapier/Make) needs correct codes to retry.

### 5. Structured logging with request_id
- **What:** middleware generates `request_id` per request. All logs include it. `structlog` in JSON format.
- **Where:** `email_triage/middleware.py` (Day 4).
- **Why:** debug in production without grepping stdout.

## Performance — critical path

`POST /triage` → Groq → response. Decisions that depend on this:

- **Shared `httpx.AsyncClient`** via lifespan (Day 6), not one per request.
- **Workers:** `(2 × cores) + 1` with `UvicornWorker` under Gunicorn.
- **Streaming** (`POST /triage/stream`) so the caller doesn't wait for the complete generation.

## Agent limits

- **DO NOT commit**: the human makes commits. Never run `git commit`, `git push`, `git amend`.
- **DO NOT call Groq from tests**: use dependency override.
- **DO NOT invent categories**: the five are `status`, `refunds`, `availability`, `shipments`, `prices` (defined in `email_triage/schemas.py:Category`). Changing them requires updating this file + `schemas.py` + the `SYSTEM_PROMPT` in `services/llm.py` + `docs/features/`.
- **DO NOT use `--no-verify`**: if pre-commit fails, fix the code.
- **DO NOT add features outside the scope** of the active exec plan without discussing with the human first.
- **DO NOT hallucinate values**: if a secret or environment variable is not available, warn and stop.
