# Testing: Structured logging — request_id + structlog

## Prerequisites

- Server running with terminal output visible: `uv run uvicorn email_triage.main:app --reload`
- Terminal where the uvicorn process logs are visible

## Test Cases

### TC-01: JSON log on each request
**Action**:
```bash
curl -s http://localhost:8000/health
```
**Expected**: In the server logs, two consecutive JSON lines with the same `request_id`:
```json
{"method": "GET", "path": "/health", "event": "request.start", "request_id": "...", "level": "info", "timestamp": "..."}
{"status": 200, "elapsed_ms": ..., "event": "request.end", "request_id": "...", "level": "info", "timestamp": "..."}
```

### TC-02: Unique request_id per request
**Action**: Make two consecutive requests and compare the `request_id` in the logs.
```bash
curl -s http://localhost:8000/health && curl -s http://localhost:8000/health
```
**Expected**: Four JSON lines, with two different `request_id` (one per request).

### TC-03: X-Request-Id in the response header
**Action**:
```bash
curl -si http://localhost:8000/health | grep -i x-request-id
```
**Expected**: `x-request-id: <uuid>` — the same UUID that appears in the server logs for that request.

### TC-04: elapsed_ms reflects real time
**Action**: Compare the `elapsed_ms` of `/triage` with a real Groq call vs `/health` (which doesn't call Groq).
**Expected**: `/health` < 5ms, `/triage` > 500ms (Groq latency). The middleware measures end-to-end.

### TC-05: Concurrent requests don't mix request_id
**Action**:
```bash
# Launch two simultaneous requests and verify in logs that request_ids don't mix
curl -s http://localhost:8000/health & curl -s http://localhost:8000/health & wait
```
**Expected**: In the logs, the `request.start` and `request.end` events for each request share the same `request_id` with each other, and differ from the other request.

## Edge Cases

| Scenario | Expected |
|---|---|
| Request that returns 404 | Two JSON lines with `status: 404` |
| Request that returns 403 (no API key) | Two JSON lines with `status: 403` |
| Request that returns 422 (invalid body) | Two JSON lines with `status: 422` |

## Log verification

```bash
# Filter all logs for a specific request_id:
# (replace the UUID with the one from the test)
uv run uvicorn email_triage.main:app 2>&1 | grep "abc12345-..."
```

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Logs are not JSON (they're plain text) | structlog not configured before the first request | Verify that `middleware.py` is imported in `main.py` before any log |
| `request_id` missing from some logs | `clear_contextvars()` not called at the start | Check `RequestIdMiddleware.dispatch` |
| `elapsed_ms` always 0 | `time.perf_counter()` not initialized before `call_next` | Check the order in `dispatch` |
| Two lines with different `request_id` for the same request | `clear_contextvars()` is not per-coroutine | Confirm Python 3.14 uses `contextvars` by default (asyncio) |
