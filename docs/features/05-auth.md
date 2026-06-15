# Auth — X-API-Key

## What it does

Protects the endpoints `POST /triage` and `POST /triage/stream` with an `X-API-Key` header. Requests without the header or with an incorrect value receive HTTP 403. `GET /health` is public (no auth).

## How it works

```
Incoming request
      ↓
RequestIdMiddleware (log + request_id)
      ↓
FastAPI router /triage with dependencies=[Depends(verify_api_key)]
      ↓
verify_api_key(x_api_key: Header, settings: Settings)
      ├── x_api_key is None  →  HTTPException(403)
      ├── x_api_key != settings.api_key  →  HTTPException(403)
      └── match  →  request continues to handler
```

`verify_api_key` is declared as a dependency at router level (`APIRouter(dependencies=[...])`), so it applies to all endpoints in the router without repeating `Depends` on each handler.

## Files involved

| File | Role |
|---|---|
| `src/email_triage/config.py` | `Settings.api_key` read from `API_KEY` env var |
| `src/email_triage/deps.py` | `get_settings()` (cached), `verify_api_key()`, `get_llm_service()` (cached) |
| `src/email_triage/routers/triage.py` | Router with `dependencies=[Depends(verify_api_key)]` |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Optional `Header()` + manual check in `verify_api_key` | `APIKeyHeader` from `fastapi.security` | Full control over error message; `APIKeyHeader` returns hardcoded "Not authenticated" |
| Dependency at router level | `dependencies=[...]` on each handler | DRY: one place to add auth to all domain endpoints |
| `@lru_cache(maxsize=1)` on `get_settings()` and `get_llm_service()` | New instance per request | `Settings` reads `.env` from disk; `LLMService` opens `httpx.AsyncClient`; neither should be rebuilt per request |
| `# type: ignore[call-arg]` on `Settings()` | Fields with defaults in `Settings` | pydantic-settings populates fields from env vars at runtime; pyright doesn't know this without the explicit suppression |

## Gotchas / Edge cases

- `API_KEY` is the env var. If it's not in `.env`, `Settings()` raises `ValidationError` on server startup.
- The incoming header can be `x-api-key` or `X-API-Key` (HTTP headers are case-insensitive). FastAPI normalizes to lowercase in `Header()`.
- On Day 5, tests override `get_settings` with `app.dependency_overrides` so they don't need a real `API_KEY` in CI.

## Testing

📋 [Testing guide](../testing/05-auth_testing.md)
