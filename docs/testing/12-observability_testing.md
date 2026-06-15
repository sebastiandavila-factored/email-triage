# Testing: Observability with Logfire

## Prerequisites

- Server running: `uv run uvicorn email_triage.main:app --reload`
- `.env` with valid `GROQ_API_KEY`, `API_KEY`, and `LOGFIRE_TOKEN` (for TC-02/TC-03)
- `LOGFIRE_SEND_TO_LOGFIRE=true` in `.env` for data to reach Logfire UI

## TC-01: Measure TTFT and compare against POST /triage

**Objective:** confirm that `/triage/stream` is significantly faster (in time to first byte) than `/triage`.

**Action:**
```bash
uv run python scripts/measure_ttft.py 10 $API_KEY
```

**Expected** (example with exec-plan 11 active):
```
=== POST /triage/stream — TTFT (ms) ===
  p50=340  p95=520  max=800

=== POST /triage — full latency (ms) ===
  p50=1800  p95=2400  max=3100

  TTFT p50 is 5.3× faster than full /triage p50.
```

**Record measured values here:**

| Run | Date | TTFT p50 (ms) | TTFT p95 (ms) | /triage p50 (ms) | Improvement |
|---|---|---|---|---|---|
| 1 | ___ | ___ | ___ | ___ | ___× |
| 2 | ___ | ___ | ___ | ___ | ___× |

**Cross-check with Logfire UI:** the `triage.stream.ttft_ms` histogram should show values within ±50 ms of the script. A larger difference indicates buffering in ASGI.

## TC-02: Verify span attributes in Logfire UI

**Objective:** confirm that spans have the expected attributes.

**Action:**
1. Send a request:
```bash
curl -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $API_KEY" \
  -d '{"subject":"Order status","sender":"a@b.com","body":"When does my order 12345 arrive?"}'
```
2. Go to Logfire UI → Traces → search for the `triage.sync` span.

**Expected:** the span must have:
- `endpoint = "sync"`
- `email.body_chars = <body length>`
- `triage.result.category = "status"` (or the category Groq determines)
- `triage.result.confidence` between 0 and 1

For the stream, repeat with `/triage/stream` and additionally verify `triage.stream.ttft_ms`.

## TC-03: Verify scrubbing of the sender field

**Objective:** confirm that the sender's email does not appear in any span.

**Action:**
1. Send a request with `sender = "secret-customer@company.com"`.
2. Go to Logfire UI → search for that email in the spans.

**Expected:** `"secret-customer@company.com"` must not appear in any span attribute. The field must be redacted as `[Redacted due to sensitive data]` or `[REDACTED]`.

## TC-04: Verify `trace_id` in logs

**Objective:** confirm structlog ↔ traces correlation.

**Action:**
```bash
curl -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $API_KEY" \
  -d '{"subject":"test","sender":"a@b.com","body":"test"}'
```

**Expected:** in the server stdout, JSON logs must include:
```json
{"event": "request.start", ..., "trace_id": "abc123...", "span_id": "def456..."}
```
The `trace_id` must match the trace that appears in Logfire UI for that request.

## TC-05: Verify `triage.llm.in_flight` gauge

**Objective:** confirm the gauge reflects real concurrency.

**Action:** send multiple concurrent requests:
```bash
for i in {1..5}; do
  curl -X POST http://localhost:8000/triage \
    -H "Content-Type: application/json" \
    -H "X-Api-Key: $API_KEY" \
    -d '{"subject":"test","sender":"a@b.com","body":"concurrency test"}' &
done
wait
```

**Expected:** in Logfire UI, the `triage.llm.in_flight` gauge should show peaks > 1 during concurrent execution.

## TC-06: Verify system metrics

**Objective:** confirm CPU and memory are reported.

**Action:** go to Logfire UI → Metrics → search for `process.cpu.utilization` and `process.memory.rss`.

**Expected:** system metrics visible and updated.

## Edge Cases

| Scenario | Expected |
|---|---|
| Groq down → 503 | `triage.errors_total{status_code="503"}` increments |
| Wrong API key → 403 | `triage.auth_failures_total` increments; sender scrubbed in span |
| Very long body (>10 KB) | `triage.request.body_chars` histogram reflects the outlier |
| `LOGFIRE_SAMPLE_RATE=0.1` | Only ~10% of requests in Logfire; errors and spans >5s always included |

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| No traces in Logfire | `LOGFIRE_SEND_TO_LOGFIRE` is not `true` | Check `.env` |
| `trace_id` missing from logs | OTel context not active when logging | Verify the middleware runs BEFORE the handler |
| `triage.sync` span without `triage.result.category` | Exception before `span.set_attribute(...)` | Check if the handler reached the attributes block |
| Script TTFT differs >50 ms from histogram | ASGI or httpx buffering | Verify the server is not in debug mode with extra logging |
