# Production configuration — Lifespan + Gunicorn + Docker

## What it does

Prepares the API to run in production: lifespan with eager initialization, Gunicorn as process manager with UvicornWorker, and multi-stage Dockerfile with uv.

## Components

### Lifespan (`main.py`)

FastAPI registers the `app` lifespan. On each worker startup:
1. Calls `get_llm_service()` to warm up the `@lru_cache` — validates `GROQ_API_KEY` before the first request
2. Logs `startup` with the active model
3. On shutdown: calls `aclose()` and logs `shutdown`

```
Gunicorn master fork → worker PID
    → UvicornWorker init
        → FastAPI lifespan startup
            → get_llm_service() [warm-up]
            → log: {"event": "startup", "groq_model": "llama-3.3-70b-versatile"}
        → serve requests
        → FastAPI lifespan shutdown
            → llm.aclose() [no-op in Pydantic AI]
            → log: {"event": "shutdown"}
```

### Gunicorn (`gunicorn.conf.py`)

```python
workers = (2 * multiprocessing.cpu_count()) + 1
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120   # generous for 1-3s LLM requests
keepalive = 5
```

`UvicornWorker` runs one asyncio event loop per worker → `async def` handlers work correctly. The 120s timeout gives room for slow calls to Groq.

### Dockerfile (multi-stage)

```
Stage 1: builder (python:3.14-slim + uv)
  ├── COPY pyproject.toml + uv.lock
  ├── uv sync --frozen --no-dev --no-install-project  ← cached deps layers
  ├── COPY src/
  └── uv sync --frozen --no-dev  ← installs the package

Stage 2: runtime (python:3.14-slim)
  ├── COPY .venv/ + src/ from builder
  ├── COPY gunicorn.conf.py
  ├── ENV PATH="/app/.venv/bin:$PATH"
  ├── HEALTHCHECK → python -c "urllib.request.urlopen('/health')"
  └── CMD: gunicorn -c gunicorn.conf.py email_triage.main:app
```

The two-stage split removes uv and build tools from the runtime.

## Files involved

| File | Role |
|---|---|
| `src/email_triage/main.py` | Lifespan `@asynccontextmanager` + `app = FastAPI(lifespan=lifespan)` |
| `gunicorn.conf.py` | Process manager config |
| `Dockerfile` | Multi-stage build with uv |
| `.dockerignore` | Excludes `.env`, `.venv`, `tests/`, `docs/` |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| `workers = (2×CPUs)+1` | Fixed 4 workers | Scales automatically with server hardware |
| `timeout = 120` | Default 30s | Groq calls can take up to 10-15s; 30s would cause false timeouts |
| Lifespan with eager `get_llm_service()` | Nothing in lifespan | Fail fast on startup if `GROQ_API_KEY` is missing → evident error before first request |
| Separate `.venv` in Dockerfile | Install globally | Predictable path; no risk of conflicts with system packages |
| `--no-install-project` in first `uv sync` | Single `uv sync` | Deps cached in separate layer; only re-executed if `uv.lock` changes |
| `PYTHONUNBUFFERED=1` | Default (buffered) | structlog JSON logs appear in real time, not buffered |

## Gotchas / Edge cases

- The lifespan runs **per worker**, not per master process. With 31 workers (15-CPU machine), 31 `startup` lines appear in the logs. This is correct behavior.
- On a 2-CPU VPS (DigitalOcean/Railway/Render): `workers = 5`. With Pydantic AI (I/O bound), the real limit is Groq request concurrency, not CPU cores.
- Python 3.14 may not be available as a base image in some registries. If the build fails, change to `python:3.13-slim` (fallback documented in the exec plan).
- `.env` is in `.dockerignore`. Environment variables are passed to the container at runtime via `--env-file .env` or via the deploy platform's environment variables.

## Testing

📋 [Testing guide](../testing/09-deploy-config_testing.md)
