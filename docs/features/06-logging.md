# Structured logging — request_id + structlog

## What it does

Each request generates a unique UUID `request_id`. All logs in that request's lifecycle include that ID. Logs are emitted in JSON format (structlog), which allows filtering by `request_id` in production without grepping plain text.

## How it works

```
RequestIdMiddleware.dispatch()
      ├── uuid4() → request_id
      ├── structlog.contextvars.clear_contextvars()
      ├── structlog.contextvars.bind_contextvars(request_id=request_id)
      ├── log.info("request.start", method=..., path=...)
      ├── await call_next(request)   ← all handler logic runs here
      │         (any log.info() inside the handler inherits request_id)
      ├── log.info("request.end", status=..., elapsed_ms=...)
      └── response.headers["X-Request-Id"] = request_id  ← propagates to caller
```

The structlog context (`bind_contextvars`) uses `contextvars.ContextVar`, which is per-coroutine in asyncio. This guarantees that concurrent requests don't mix their `request_id`.

## Log format

Since exec-plan 12, each log also includes `trace_id` and `span_id` from the active OTel span (if any), which allows jumping from a JSON log directly to the trace in Logfire UI.

```json
{"method": "POST", "path": "/triage", "event": "request.start", "request_id": "5fa4...", "trace_id": "00000000000000000000000000000001", "span_id": "0000000000000001", "level": "info", "timestamp": "2026-06-01T14:11:24.960845Z"}
{"status": 200, "elapsed_ms": 1243.5, "event": "request.end", "request_id": "5fa4...", "trace_id": "00000000000000000000000000000001", "span_id": "0000000000000001", "level": "info", "timestamp": "2026-06-01T14:11:26.204Z"}
```

If there's no active span (e.g. health check without instrumentation), the `trace_id` and `span_id` fields are absent.

## Files involved

| File | Role |
|---|---|
| `src/email_triage/middleware.py` | `RequestIdMiddleware`, structlog configuration |
| `src/email_triage/main.py` | `app.add_middleware(RequestIdMiddleware)` |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| `structlog.contextvars` | Pass bound `log` as argument to each function | contextvars propagates automatically without modifying signatures |
| JSON in all environments | Pretty-print in dev, JSON in prod | MVP simplicity; can detect environment with `Settings.env` on Day 7 |
| `cache_logger_on_first_use=True` | No cache | Avoids re-lookup of the logger on each call — structlog recommendation |
| `structlog.configure()` at module level | `configure_logging()` function called from lifespan | Simple for MVP; can be moved in Day 6 (lifespan) if needed |
| `elapsed_ms` rounded to 2 decimals | Exact microseconds | Readability in logs; sufficient precision to detect outliers |

## Gotchas / Edge cases

- `clear_contextvars()` at the start of each request is mandatory. Without it, variables from the previous request leak into the next one in the same worker.
- The `X-Request-Id` header returned to the caller allows correlating an HTTP response with its logs without server access.
- If the handler raises an unhandled exception, `request.end` may not log the correct status. FastAPI returns 500 but the middleware only sees the processed `Response`.

## Testing

📋 [Testing guide](../testing/06-logging_testing.md)
