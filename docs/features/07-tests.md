# Automated tests

## What it does

Test suite of 9 tests that validates the three endpoints (`/health`, `/triage`, `/triage/stream`) without calling Groq. Runs in ~0.05s. Tests use `dependency_overrides` to replace `get_llm_service` and `get_settings` with test doubles.

## How it works

```
pytest
  └── conftest.py
        ├── MockLLMService   → triage() returns fixed TriageResponse
        ├── FailingLLMService → triage() raises httpx.ConnectError
        ├── fixture client       → overrides: mock settings + mock LLM
        └── fixture failing_client → overrides: mock settings + failing LLM

tests/test_health.py   → GET /health: 200, X-Request-Id header present
tests/test_triage.py   → POST /triage: happy path, 403, 422, 503
                       → POST /triage/stream: 403, SSE meta+done present
```

**Why `dependency_overrides` instead of monkeypatching:**
FastAPI resolves dependencies at runtime. By replacing the function in `app.dependency_overrides`, the entire DI chain (middleware → router → handler → dep) uses the double. No risk of the mock getting "trapped" in a closure.

## Files involved

| File | Role |
|---|---|
| `tests/conftest.py` | Fixtures `client` and `failing_client`, LLM and Settings mocks |
| `tests/test_health.py` | Tests for `/health` |
| `tests/test_triage.py` | Tests for `/triage` and `/triage/stream` |
| `pyproject.toml` | `asyncio_mode = "auto"`, dev deps pytest + pytest-asyncio |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| `MockLLMService(LLMService)` subclass | `MagicMock(spec=LLMService)` | More explicit, type-safe, no dependency on `unittest.mock` |
| `FailingLLMService` raises `httpx.ConnectError` | Raises `LLMError` | The router catches both; the mock simulates a real network failure |
| `app.dependency_overrides.clear()` in teardown | Partial per-test reset | Guarantees isolation between tests; no residual state |
| Synchronous `TestClient` | httpx `AsyncClient` | `TestClient` is sufficient for integration tests without real concurrency |
| `failing_client` as a separate fixture | Override inside the test | Avoids shared state and complicated teardown |

## Gotchas / Edge cases

- `app.dependency_overrides` is global state. If a test fails before `clear()`, subsequent fixtures may see residual overrides. The `with TestClient(app) as c: yield c` guarantees that `clear()` runs even if the test fails (it's code after the `yield`).
- `@lru_cache` on `get_llm_service` and `get_settings` is bypassed when `dependency_overrides` is active — FastAPI calls the override directly, not the original function.

## Testing

📋 [Testing guide](../testing/07-tests_testing.md)
