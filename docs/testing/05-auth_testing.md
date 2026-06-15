# Testing: Auth — X-API-Key

## Prerequisites

- `API_KEY` defined in `.env` (see `.env.example`)
- Server running: `uv run uvicorn email_triage.main:app --reload`
- The value of `API_KEY` in `.env` (e.g. `dev-local-key`)

## Test Cases

### TC-01: No header → 403
**Action**:
```bash
curl -s -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"subject":"test","sender":"a@b.com","body":"hello"}'
```
**Expected**: HTTP 403, `{"detail": "Invalid or missing API key"}`.

### TC-02: Wrong header → 403
**Action**:
```bash
curl -s -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: wrong-key" \
  -d '{"subject":"test","sender":"a@b.com","body":"hello"}'
```
**Expected**: HTTP 403.

### TC-03: Correct header → 200 (or 503 if Groq is down)
**Action**:
```bash
curl -s -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: dev-local-key" \
  -d '{"subject":"Refund","sender":"customer@example.com","body":"I want my money back"}'
```
**Expected**: HTTP 200 with `TriageResponse` (if `GROQ_API_KEY` valid), or HTTP 503 if Groq unavailable.

### TC-04: /health without header → 200
**Action**:
```bash
curl -s http://localhost:8000/health
```
**Expected**: HTTP 200 `{"status": "ok"}`. Does not require `X-Api-Key`.

### TC-05: /triage/stream without header → 403
**Action**:
```bash
curl -s -X POST http://localhost:8000/triage/stream \
  -H "Content-Type: application/json" \
  -d '{"subject":"test","sender":"a@b.com","body":"hello"}'
```
**Expected**: HTTP 403 (auth also applies to the streaming endpoint).

## Edge Cases

| Scenario | Expected |
|---|---|
| Empty `API_KEY` in `.env` | Server fails to start with pydantic `ValidationError` |
| Header `x-api-key` in lowercase | 200/403 depending on value — HTTP headers are case-insensitive, FastAPI normalizes |
| Correct header + missing `GROQ_API_KEY` | 503 `LLM service not configured` (auth passes, LLM dep fails) |

## Log verification

Each request should produce two JSON lines with the same `request_id`:

```bash
# Look for the latest request_id in server logs:
# {"event": "request.start", "request_id": "abc...", "path": "/triage", ...}
# {"event": "request.end",   "request_id": "abc...", "status": 403, ...}
```

The `X-Request-Id` header in the response must match the `request_id` in the logs.

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Server doesn't start (`ValidationError`) | `API_KEY` or `GROQ_API_KEY` not in `.env` | Copy `.env.example` → `.env` and fill in values |
| TC-03 gives 403 with correct header | Value of `API_KEY` in `.env` differs from the sent header | Verify the exact value (case-sensitive) |
| TC-04 gives 403 | `/health` accidentally has auth | Verify that `health.router` has no `dependencies` |
