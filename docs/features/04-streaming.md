# POST /triage/stream — SSE Endpoint

## What it does

Same logic as `POST /triage` but returns the response as an SSE stream (`text/event-stream`). The client can display the category and draft progressively without waiting for the complete JSON. The quantitative goal is **TTFT < 500 ms** (time to first visible token), versus the 1.5–3 s of the synchronous endpoint.

## How it works

```
Client → POST /triage/stream (TriageRequest)
             ↓
        routers/triage.py::triage_stream()
             ↓  (opens the context manager before responding 200)
        LLMService.triage_stream()  →  agent.run_stream()  →  Groq API
             ↓
        stream.stream_output(debounce_by=None)  ← StreamingTriageResponse partials
             ↓
Client ← event: meta   → {"category": "...", "confidence": 0.95}  (first partial with both fields)
Client ← data: "chunk" → draft_reply delta (JSON-encoded)
Client ← data: "chunk" → next delta
Client ← event: done   → [DONE]
```

### Delta encoding

Pydantic AI emits each `partial` with the **accumulated** text up to that moment in `draft_reply`. The handler calculates the delta by slicing:

```python
delta = partial.draft_reply[len(emitted_text):]
emitted_text = partial.draft_reply
```

The client receives only the new text in each `data:` — it must concatenate them to reconstruct the full `draft_reply`.

### Pre-fetch to guarantee 503

The handler opens the context manager (`__aenter__`) **before** returning the `StreamingResponse`. If Groq fails to connect, `HTTPException(503)` is raised with the correct code. Once the server starts sending the response (status 200 + headers), the HTTP code can no longer be changed.

```python
stream_cm = llm.triage_stream(req)
try:
    stream = await stream_cm.__aenter__()   # fails here → 503
except LLMError as exc:
    raise HTTPException(status_code=503, ...) from exc

return StreamingResponse(gen(), ...)        # 200, stream starts
```

### Guaranteed cleanup

The `try/finally` inside the generator calls `stream_cm.__aexit__` always, including the case of client disconnection (FastAPI cancels the coroutine and triggers the `finally`).

## SSE format

```
event: meta
data: {"category": "refunds", "confidence": 0.94}

data: "Dear "
data: "customer, "
data: "your refund..."
...
event: done
data: [DONE]
```

- `meta` event: category and confidence score (arrives as soon as the LLM emits both fields)
- Unnamed `data` events: **deltas** of `draft_reply` (JSON-encoded to handle newlines)
- `done` event: end-of-stream signal

## Files involved

| File | Role |
|---|---|
| `src/email_triage/schemas.py` | `StreamingTriageResponse` (optional fields for incremental validation) |
| `src/email_triage/services/llm.py` | `LLMService.triage_stream()` — `@asynccontextmanager` over `agent.run_stream()` |
| `src/email_triage/routers/triage.py` | `triage_stream` handler with pre-fetch, delta encoding, log at close |
| `tests/conftest.py` | `StreamingMockLLMService`, `FailingStreamLLMService` |
| `tests/test_triage.py` | 3 real streaming tests |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Separate `StreamingTriageResponse` | Make `TriageResponse` fields Optional | Breaking the OpenAPI contract of the synchronous endpoint is worse than having two close models |
| Manual `__aenter__` + `try/finally` in the generator | `async with` inside the generator | We need to capture the open failure as 503 *before* returning the `StreamingResponse` |
| Delta by slicing the accumulated | Raw LLM tokens | Pydantic AI with structured `output_type` emits the partially validated object, not raw tokens |
| `debounce_by=None` | `debounce_by=100ms` (default) | Minimizes TTFT; validating each delta is cheap for short JSONs |
| Log at end of generator | `BackgroundTasks` | `BackgroundTasks` doesn't fit the generator's lifecycle for a stream |
| JSON-encode each `draft_reply` delta | Plain text | `draft_reply` can have newlines that would break the client's SSE parser |

## Gotchas / Edge cases

- The first event is always `meta`. The client must process `event: meta` before any `data:`.
- The `data:` events are **deltas**, not the accumulated text. The client concatenates to reconstruct `draft_reply`.
- If Groq emits `draft_reply` before `category`/`confidence`, `data:` events will be emitted before `meta`. See the field order risk in exec-plan 11.

## Testing

📋 [Testing guide](../testing/04-streaming_testing.md)
