# Testing: POST /triage/stream — SSE Endpoint

## Prerequisites

- Server running: `uv run uvicorn email_triage.main:app --reload`
- `.env` with valid `GROQ_API_KEY` and `API_KEY`
- `curl` with streaming support (standard version on macOS/Linux)

## Test Cases

### TC-01: Happy path — see SSE events
**Action**:
```bash
curl -N -X POST http://localhost:8000/triage/stream \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $API_KEY" \
  -d '{
    "subject": "Do you have the product in stock?",
    "sender": "customer@example.com",
    "body": "I am interested in buying model X. Is it available for immediate shipping?"
  }'
```
**Expected**: Text stream with this format:
```
event: meta
data: {"category": "availability", "confidence": 0.93}

data: "Dear "
data: "customer, "
...
event: done
data: [DONE]
```
- The first event is `event: meta`.
- Unnamed `data:` events are JSON-encoded **deltas** of `draft_reply` (concatenate to reconstruct).
- The last event is `event: done`.

### TC-02: Response Content-Type
**Action**:
```bash
curl -I -X POST http://localhost:8000/triage/stream \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $API_KEY" \
  -d '{"subject":"x","sender":"a@b.com","body":"test"}'
```
**Expected**: Header `content-type: text/event-stream; charset=utf-8`.

### TC-03: Error 503 — Groq down before stream
**Action**: Export `GROQ_API_KEY=invalid` and restart the server. Send the TC-01 request.
**Expected**: HTTP 503 with JSON `{"detail": "LLM service unavailable"}` **before** the stream starts (not an error mid-stream).

### TC-04: Reconstruct draft_reply from deltas
**Action**: Python script to consume the stream and verify reconstruction:
```python
import httpx, json, os

with httpx.Client() as client:
    with client.stream(
        "POST",
        "http://localhost:8000/triage/stream",
        headers={"X-Api-Key": os.environ["API_KEY"]},
        json={"subject": "Shipping", "sender": "a@b.com", "body": "How long does shipping take?"},
    ) as resp:
        full_reply = ""
        for line in resp.iter_lines():
            if line.startswith("data: ") and not line.endswith("[DONE]"):
                decoded = json.loads(line[6:])
                if isinstance(decoded, str):
                    full_reply += decoded
        print(repr(full_reply))
```
**Expected**: `full_reply` is the complete `draft_reply`, coherent with the email context.

### TC-05: Measure TTFT (time-to-first-token)
**Objective**: confirm that the TTFT of `/triage/stream` is significantly lower than the latency of `/triage`.

**Script**:
```python
import httpx, json, os, time

PAYLOAD = {
    "subject": "What is the status of my order?",
    "sender": "customer@example.com",
    "body": "I placed an order 5 days ago and haven't received any updates. Order number: 12345.",
}
HEADERS = {"X-Api-Key": os.environ["API_KEY"]}

# Measure synchronous latency
t0 = time.perf_counter()
r = httpx.post("http://localhost:8000/triage", json=PAYLOAD, headers=HEADERS)
sync_latency = time.perf_counter() - t0
print(f"POST /triage latency: {sync_latency*1000:.0f} ms")

# Measure stream TTFT
with httpx.Client() as client:
    with client.stream("POST", "http://localhost:8000/triage/stream",
                       json=PAYLOAD, headers=HEADERS) as resp:
        t_start = time.perf_counter()
        for chunk in resp.iter_text():
            if "event: meta" in chunk:
                ttft = time.perf_counter() - t_start
                print(f"TTFT (first meta event): {ttft*1000:.0f} ms")
                break
```
**Expected**: TTFT < 500 ms vs synchronous latency of 1.5–3 s. Record measured values here:

| Run | TTFT (ms) | /triage latency (ms) |
|---|---|---|
| 1 | ___ | ___ |
| 2 | ___ | ___ |
| 3 | ___ | ___ |

### TC-06: Client cancellation mid-stream
**Action**: Open the stream with curl and press `Ctrl-C` before the `done` event:
```bash
curl -N -X POST http://localhost:8000/triage/stream \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $API_KEY" \
  -d '{"subject": "test", "sender": "a@b.com", "body": "test cancellation"}'
# Press Ctrl-C as soon as the first data appears
```
**Expected**: The server finishes the generator cleanly. In Logfire, verify the request span closes (not left hanging). In local logs, no unhandled `CancelledError` should appear.

## Edge Cases

| Scenario | Expected |
|---|---|
| Groq down during the request | 503 before the stream (not an error mid-stream) |
| `draft_reply` with internal newlines | JSON-encoded deltas; client must `json.loads()` each `data:` |
| Client connection closed mid-stream | Server finishes the generator without error (FastAPI handles the cancel) |
| `category` or `confidence` arrive late | `event: meta` is delayed; `draft_reply` `data:` chunks may precede it (see risk in exec-plan 11) |

## Log verification

structlog logs show:
- `event: request.start` at the beginning
- `event: triage.stream.result` with `category`, `confidence` and `sender` at generator close
- `event: request.end` with `elapsed_ms`

```bash
# Filter only stream logs:
uv run uvicorn email_triage.main:app | grep triage.stream
```

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Stream closes immediately without events | `GROQ_API_KEY` missing/invalid → 503 | Check env var |
| `event: meta` missing `category` or `confidence` | Groq emitted `draft_reply` before those fields | See field order risk in exec-plan 11 |
| `draft_reply` deltas don't concatenate correctly | Client not doing `json.loads()` on data | Deltas are JSON-encoded; parse before concatenating |
| `curl` doesn't show the stream in real time | curl without `-N` flag (not unbuffered) | Add `-N` to the curl command |
| 403 instead of stream | `X-Api-Key` header missing or incorrect | Verify the API key in the header |
