# Deploy + Polish — Logfire, Rate Limiting, Render

## What it does

Closes the MVP: public metadata at `/docs`, observability with Logfire, rate limiting with SlowAPI, and deploy on Render using the existing Dockerfile.

## Components

### Logfire (`main.py`)

Three setup lines at module level, before creating `app`:

```python
logfire.configure(send_to_logfire=bool(os.environ.get("LOGFIRE_TOKEN")))
logfire.instrument_pydantic_ai()
# ...after app = FastAPI(...):
logfire.instrument_fastapi(app)
```

- `send_to_logfire=bool(...)`: if `LOGFIRE_TOKEN` is not defined or empty, logfire runs in local mode (without sending to the cloud). Useful for dev without an account.
- `instrument_pydantic_ai()`: traces each `Agent.run()` call with duration, tokens and result.
- `instrument_fastapi(app)`: traces each HTTP request with path, status and latency. Complements (does not replace) the `RequestIdMiddleware`.

Dashboard: `logfire.pydantic.dev` — view spans in real time.

### Rate Limiting — SlowAPI (`deps.py` + `triage.py` + `main.py`)

```python
# deps.py
limiter = Limiter(key_func=get_remote_address)

# triage.py
@router.post("", response_model=TriageResponse)
@limiter.limit("20/minute")
async def triage(request: Request, req: TriageRequest, ...) -> TriageResponse:
```

- `get_remote_address`: uses `X-Forwarded-For` if available (correct behind Render/Railway).
- `20/minute` per IP: sufficient for Zapier/Make (max 1 req/3s in normal flows), blocks scrapers.
- Returns 429 with `{"error": "Rate limit exceeded: 20 per 1 minute"}`.
- `request: Request` is required by SlowAPI and FastAPI injects it automatically.

### Public metadata (`main.py`)

```python
app = FastAPI(
    title="Email Triage API",
    summary="Classify support emails and draft replies in <3 seconds.",
    version="0.1.0",
    description="...",
    contact={"name": "Seba Davila", "email": "..."},
    license_info={"name": "MIT"},
    lifespan=lifespan,
)
```

Appears in `/docs` (Swagger UI) and `/openapi.json`. Important for founders evaluating the API.

### Deploy on Render (`render.yaml`)

```yaml
services:
  - type: web
    name: email-triage
    env: docker
    healthCheckPath: /health
    envVars:
      - key: GROQ_API_KEY
        sync: false
      - key: API_KEY
        sync: false
      - key: LOGFIRE_TOKEN
        sync: false
```

- `env: docker`: uses the existing `Dockerfile` without additional configuration.
- `sync: false`: values are entered in the Render dashboard, never in the repo.
- Render detects `render.yaml` automatically when connecting the repo.

**Rollback runbook:**
1. Go to Render dashboard → Service → "Manual Deploy" → select previous commit
2. Or: `git revert HEAD && git push` — Render redeploys in ~2 min

## Files involved

| File | Change |
|---|---|
| `src/email_triage/main.py` | Logfire setup, slowapi registration, metadata |
| `src/email_triage/deps.py` | `limiter = Limiter(key_func=get_remote_address)` |
| `src/email_triage/routers/triage.py` | `@limiter.limit("20/minute")` + `request: Request` |
| `.env.example` | `LOGFIRE_TOKEN=` + `LOGFIRE_SEND_TO_LOGFIRE=false` |
| `render.yaml` | Deploy config for Render |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| `send_to_logfire=bool(os.environ.get("LOGFIRE_TOKEN"))` | `logfire.configure()` without args | No token → automatic local mode; dev doesn't need an account |
| `instrument_pydantic_ai()` at module level | In lifespan | pydantic-ai patches must be applied before agents are created |
| `20/minute` per IP | `100/minute` or no limit | Sufficient for legitimate integrations; blocks abuse without real friction |
| `render.yaml` with `env: docker` | `env: python` (buildpack) | Reuses the already-validated multi-stage Dockerfile |
| `limiter` in `deps.py` | New `limiter.py` file | Avoids an extra file; `deps.py` already centralizes shared dependencies |

## Testing

📋 [Testing guide](../testing/10-deploy_testing.md)
