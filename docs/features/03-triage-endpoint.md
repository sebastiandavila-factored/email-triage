# POST /triage — Synchronous triage endpoint

## What it does

Receives an email (subject, sender, body) and returns a JSON with the category, a draft reply and a confidence score. This is the main API endpoint: one request → one complete response.

## How it works

```
Client → POST /triage (TriageRequest)
             ↓
        routers/triage.py::triage()
             ↓
        LLMService.triage()  →  Groq API  →  JSON
             ↓
        TriageResponse.model_validate_json()
             ↓
Client ← 200 TriageResponse
```

If Groq returns an HTTP error or cannot connect, the handler raises `HTTPException(503)`.

## Files involved

| File | Role |
|---|---|
| `src/email_triage/routers/triage.py` | Handler, LLMService dependency, error logic |
| `src/email_triage/routers/health.py` | `/health` moved here from `main.py` |
| `src/email_triage/main.py` | Registers routers with `include_router` |
| `src/email_triage/schemas.py` | `TriageRequest`, `TriageResponse`, `Category` |
| `src/email_triage/services/llm.py` | `LLMService.triage()` |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| `get_llm_service()` inline in `triage.py` | `deps.py` from Day 3 | `deps.py` is Day 4; avoid anticipating pydantic-settings |
| Catch `httpx.HTTPStatusError` and `httpx.RequestError` | Only `Exception` | Precise types → add others if they appear |
| `@router.post("")` with `/triage` prefix on `APIRouter` | `@router.post("/triage")` without prefix | Groups all domain endpoints in one place |
| Explicit `response_model=TriageResponse` | Only return type annotation | FastAPI uses `response_model` to filter future hidden fields |

## Gotchas / Edge cases

- `get_llm_service()` creates a new `httpx.AsyncClient` per request. On Day 6 it is replaced by a shared client via lifespan. Acceptable for now in MVP.
- `GROQ_API_KEY` is read from `os.environ` directly. On Day 4 it moves to `pydantic-settings`.
- The endpoint has no auth yet. Auth (X-API-Key) is added on Day 4 with `Depends(verify_api_key)`.

## Testing

📋 [Testing guide](../testing/03-triage-endpoint_testing.md)
