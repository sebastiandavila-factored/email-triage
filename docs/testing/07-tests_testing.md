# Testing: Automated test suite

## Prerequisites

- Dependencies installed: `uv sync`
- No `GROQ_API_KEY` or `API_KEY` in `.env` required — tests use mocks

## Running the suite

```bash
# All tests
uv run pytest tests/ -v

# Health only
uv run pytest tests/test_health.py -v

# Triage only
uv run pytest tests/test_triage.py -v

# Show log output (structlog) during tests
uv run pytest tests/ -v -s
```

**Expected result:** `9 passed` in ~0.05s.

## Verified test cases

| Test | What it validates |
|---|---|
| `test_health_returns_ok` | GET /health → 200, `{"status": "ok"}` |
| `test_health_has_request_id_header` | Middleware adds `X-Request-Id` |
| `test_triage_happy_path_returns_valid_shape` | POST /triage → 200 with valid `category`, `draft_reply`, `confidence` |
| `test_triage_no_api_key_returns_403` | No header → 403 |
| `test_triage_wrong_api_key_returns_403` | Wrong header → 403 |
| `test_triage_invalid_body_returns_422` | Invalid body → 422 from FastAPI/Pydantic |
| `test_triage_llm_down_returns_503` | LLM unavailable → 503 |
| `test_triage_stream_no_api_key_returns_403` | POST /triage/stream without header → 403 |
| `test_triage_stream_happy_path_emits_sse` | Stream → `event: meta` + `event: done` in body |

## Edge Cases

| Scenario | Expected |
|---|---|
| Tests run without internet | All pass — none calls Groq |
| `GROQ_API_KEY` not defined | Irrelevant — `get_settings` is overridden |
| Tests run in parallel (`-n auto`) | May fail due to shared state in `dependency_overrides` — don't add `pytest-xdist` without isolating the overrides |

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `ImportError: cannot import name TEST_API_KEY` | `tests/` has no `__init__.py` | Verify that `tests/__init__.py` exists |
| Triage tests give unexpected 503 | Residual `dependency_overrides` from previous test | Verify the fixture calls `app.dependency_overrides.clear()` |
| `asyncio_mode` not recognized | `pytest-asyncio` not installed | `uv sync` |
| Tests give 422 on happy path | Test payload body changed | Verify `_PAYLOAD` in `test_triage.py` has valid fields |
