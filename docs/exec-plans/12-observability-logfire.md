# 12. Observability with Logfire (OTel) + streaming metrics

**Status:** ✅ delivered
**Estimate:** 4.5 hrs (1 session + measurement)

## Intent

Convert the current minimal Logfire setup (`instrument_fastapi` + `instrument_pydantic_ai`) into an actionable observability layer that answers three operational questions: *is the API healthy?*, *how fast does the client perceive the response (TTFT in streaming)?*, *what categories and confidence is the LLM producing?* The headline metric of the plan is `triage.stream.ttft_ms`: we want to empirically validate the improvement from exec plan #11 (real streaming).

Logfire is the single source of telemetry: traces, logs, and metrics. We do not introduce Prometheus, Grafana, or additional APMs — the unit economics of the MVP don't justify it and Logfire is already in the stack.

## Scope

**Included:**
- Metrics catalog (counters / histograms / gauges) defined as constants in an `observability.py` module.
- TTFT instrumentation in `/triage/stream` with `logfire.span(...)` and a dedicated histogram, measuring the time between request arrival and the first useful byte to the client (first `event: meta` or first `data:`).
- Custom span attributes on the request span: `request_id`, `result.category`, `result.confidence`, `llm.model`, `endpoint`, `email.body_chars`, `email.subject_chars`.
- structlog ↔ trace correlation: each JSON log includes `trace_id` and `span_id` of the active span.
- Additional instrumentation: `logfire.instrument_pydantic()` (422 validation errors), `logfire.instrument_system_metrics()` (CPU, memory), `logfire.instrument_httpx()` (egress, applies to Pydantic AI's internal client if it uses httpx).
- `scripts/measure_ttft.py`: standalone script that exercises `/triage/stream` and reports client-side measured TTFT — independent input for cross-checking the server histogram.
- Configuration of scrubbing for sensitive fields (`email.sender`, `groq_api_key`) in `logfire.configure(scrubbing=...)`.
- Sampling: 100% for 4xx/5xx errors and requests > 5 s; probabilistic sampling (e.g. 10%) for the rest. Configurable via env var.
- Documentation: new `docs/features/12-observability.md` and `docs/testing/12-observability_testing.md`. Update `CLAUDE.md §Stack` and `06-logging.md`.

**Out of scope (post-MVP):**
- Persisted dashboards in Logfire UI (built ad-hoc; nobody depends on a dashboard today).
- Alerts / SLOs configured in Logfire (catalog suggested at the end of the plan, but not implemented).
- Trace export to another backend (Honeycomb, Datadog). Logfire is the only sink.
- Business metrics (revenue, retention). Only technical telemetry.
- Replay/sampled-trace-export to S3.

## Dependency on other plans

This plan **does not block** nor **is blocked by** exec plan #11 (real streaming), but the recommended order is **11 → 12**:

- If #11 is merged first, the `triage.stream.ttft_ms` metric will capture the real value (~300–500 ms expected).
- If #12 is merged first, the metric will capture the TTFT of the current cosmetic streaming (~full Groq latency) — serves as a baseline prior to #11.

Both orders are valid. Plan #12 is written assuming #11 already exists; if reversed, only TC-02 of the testing doc needs adjustment (expected ranges).

## Prior reading

- Logfire docs: [Manual Tracing](https://logfire.pydantic.dev/docs/guides/onboarding-checklist/add-manual-tracing/), [Metrics](https://logfire.pydantic.dev/docs/guides/onboarding-checklist/add-metrics/), [Scrubbing](https://logfire.pydantic.dev/docs/guides/advanced/scrubbing/), [Sampling](https://logfire.pydantic.dev/docs/guides/advanced/sampling/), [Standard library logging integration](https://logfire.pydantic.dev/docs/integrations/logging/).
- OpenTelemetry semantic conventions: [HTTP](https://opentelemetry.io/docs/specs/semconv/http/http-spans/), [GenAI](https://opentelemetry.io/docs/specs/semconv/gen-ai/) — align attribute names where applicable (`gen_ai.request.model`, `gen_ai.response.tokens`, etc.).
- Existing code: `src/email_triage/main.py` (current setup), `src/email_triage/middleware.py` (structlog) and `src/email_triage/routers/triage.py` (instrumentation points).

## Metrics catalog

Defined in `src/email_triage/observability.py` as global constants (instantiated once, reused per request).

### Counters

| Name | Labels | When incremented | Why |
|---|---|---|---|
| `triage.requests_total` | `endpoint` (`sync`\|`stream`), `category` (result) | Each successful request to `/triage` or `/triage/stream` | Throughput and category distribution — base for per-mailbox discount/upsell |
| `triage.errors_total` | `endpoint`, `status_code` | Each 4xx/5xx on `/triage*` | Errors by type. Detects: misconfigured clients (high 403), bad inputs (high 422), unstable Groq (high 503) |
| `triage.llm_errors_total` | `error_class` (exact class of exc wrapped in `LLMError`) | Each time `LLMService` raises `LLMError` | Provider debugging: timeout vs rate limit vs auth |
| `triage.auth_failures_total` | (no labels) | Each 403 in `verify_api_key` | Security signal: key rotations, brute-force attacks |
| `triage.rate_limit_hits_total` | `endpoint` | Each 429 emitted by slowapi | Capacity planning: if it grows, validate whether to bump the limit or charge a higher plan |

### Histograms

| Name | Unit | Suggested buckets | When measured | Why |
|---|---|---|---|---|
| `triage.latency_ms` | ms | `[50, 100, 250, 500, 1000, 2500, 5000, 10000]` | End-to-end per handler (already captured by `instrument_fastapi`, but explicit is better for alerts) | Basic SLO: p95 < 3 s |
| **`triage.stream.ttft_ms`** | ms | `[50, 100, 200, 400, 800, 1500, 3000]` | Between `request.start` and first useful byte sent to client in `/triage/stream` | Headline metric of the plan; validates #11 |
| `triage.llm.latency_ms` | ms | `[100, 250, 500, 1000, 2500, 5000]` | Only the time spent inside `LLMService.triage()` / `triage_stream()` | Isolates provider latency from framework latency |
| `triage.llm.confidence` | ratio (0–1) | `[0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0]` | Each successful response | Quality drift: if the mean drops, the prompt/model degraded |
| `triage.request.body_chars` | chars | `[100, 500, 1000, 5000, 10000, 20000]` | Received input | Email size distribution — informs pricing decisions and limit settings |
| `triage.response.draft_chars` | chars | `[50, 100, 200, 500, 1000, 2000]` | LLM output | Detects anomalously short/long replies |

### Gauges

| Name | When updated | Why |
|---|---|---|
| `triage.llm.in_flight` | Increment on entering `LLMService.triage*`, decrement on exit (try/finally) | Real concurrency to the provider. If it approaches the worker limit, backpressure is imminent |

### System metrics (automatic)

Activated with `logfire.instrument_system_metrics()`:
- CPU usage (%), memory (RSS), open file descriptors, network I/O.

No custom code required. Useful for correlating latency with container saturation on Render.

## Concrete changes

| File | Change |
|---|---|
| `src/email_triage/observability.py` | + new module. Defines `LATENCY_MS`, `STREAM_TTFT_MS`, `LLM_LATENCY_MS`, `CONFIDENCE`, `REQUEST_BODY_CHARS`, `RESPONSE_DRAFT_CHARS` as histograms; `REQUESTS_TOTAL`, `ERRORS_TOTAL`, `LLM_ERRORS_TOTAL`, `AUTH_FAILURES_TOTAL`, `RATE_LIMIT_HITS_TOTAL` as counters; `LLM_IN_FLIGHT` as gauge. All via `logfire.metric_histogram(...)`, `logfire.metric_counter(...)`, `logfire.metric_up_down_counter(...)`. |
| `src/email_triage/main.py` | Replace `logfire.configure(send_to_logfire=...)` with a call that includes `scrubbing=ScrubbingOptions(...)`, `sampling=SamplingOptions(...)` and `service_name="email-triage"`. Add `logfire.instrument_pydantic()`, `logfire.instrument_system_metrics()`, `logfire.instrument_httpx()`. |
| `src/email_triage/middleware.py` | Add structlog processor that injects `trace_id` and `span_id` from the active span (via `logfire.current_span()` or `opentelemetry.trace.get_current_span()`) into each log record. |
| `src/email_triage/routers/triage.py` | Wrap handlers in `with logfire.span("triage.sync"/"triage.stream", endpoint=..., ...) as span:`. Increment appropriate counters. Measure `LLM_LATENCY_MS` around the `LLMService` call. In the stream handler, capture `t_start` on entry and record `STREAM_TTFT_MS` at the exact moment the first chunk is emitted (boolean flag `first_emitted`). Set span attributes with `span.set_attribute(...)`. |
| `src/email_triage/services/llm.py` | Add `LLM_IN_FLIGHT` gauge with `try/finally` around the call. Catch `Exception` to increment `LLM_ERRORS_TOTAL` with the `error_class`. |
| `src/email_triage/deps.py` | In `verify_api_key`, increment `AUTH_FAILURES_TOTAL` before the `raise`. |
| `src/email_triage/config.py` | + fields: `logfire_send_to_logfire: bool = False`, `logfire_sample_rate: float = 0.1`, `logfire_environment: str = "dev"`. Covers the bug from plan #11 step (1) if not done before. |
| `scripts/measure_ttft.py` | + new script. Runs N requests against `/triage/stream`, measures client-side TTFT with `time.perf_counter()`, prints p50/p95/max. Uses `httpx.AsyncClient().stream()`. |
| `tests/test_observability.py` | + tests: (a) a 403 increments `AUTH_FAILURES_TOTAL` (use `logfire.testing.CaptureLogfire`), (b) a successful request emits a span with expected attributes, (c) a 503 increments `LLM_ERRORS_TOTAL`. |
| `docs/features/12-observability.md` | + new: explain the catalog, how to read traces in Logfire UI, useful queries. |
| `docs/testing/12-observability_testing.md` | + new: TC-01 run `scripts/measure_ttft.py` and record TTFT; TC-02 verify attributes on an individual trace; TC-03 verify scrubbing of `sender`. |
| `docs/features/06-logging.md` | Update: each log now has `trace_id` and `span_id`. |
| `CLAUDE.md` §Stack | Update the `logfire[fastapi]` cell with the complete list of active instrumentations. |
| `docs/exec-plans/README.md` | Add entry #12. |
| `.env.example` | + `LOGFIRE_SAMPLE_RATE=0.1`, `LOGFIRE_ENVIRONMENT=dev`. |

## Technical design

### 1. `observability.py` module — single source of truth

```python
# src/email_triage/observability.py
import logfire

# Counters
REQUESTS_TOTAL = logfire.metric_counter(
    "triage.requests_total",
    unit="1",
    description="Successful triage requests by endpoint and resulting category.",
)
ERRORS_TOTAL = logfire.metric_counter(
    "triage.errors_total",
    unit="1",
    description="Triage requests that returned 4xx/5xx, labeled by status code.",
)
# ... remaining counters

# Histograms
STREAM_TTFT_MS = logfire.metric_histogram(
    "triage.stream.ttft_ms",
    unit="ms",
    description="Time from request arrival to first SSE byte sent to client.",
)
LLM_LATENCY_MS = logfire.metric_histogram(
    "triage.llm.latency_ms",
    unit="ms",
    description="Time spent inside LLMService.triage*.",
)
# ... remaining histograms

# Gauges (UpDownCounter in OTel — incrementable and decrementable)
LLM_IN_FLIGHT = logfire.metric_up_down_counter(
    "triage.llm.in_flight",
    unit="1",
    description="In-flight LLM calls at this instant.",
)
```

Centralizing handles avoids duplication (OTel emits warnings for duplicates); facilitates inventory for future dashboards.

### 2. TTFT measurement in `/triage/stream`

TTFT is measured between handler entry and the first `yield` of the generator consumed by the ASGI server. It's important that the timer starts *before* the Pydantic AI context manager `__aenter__` (because the time to connect to Groq counts toward the user's TTFT):

```python
@router.post("/stream")
@limiter.limit("20/minute")
async def triage_stream(request: Request, req: TriageRequest, llm: LLMDep) -> StreamingResponse:
    t_start = time.perf_counter()
    with logfire.span(
        "triage.stream",
        endpoint="stream",
        email_subject_chars=len(req.subject),
        email_body_chars=len(req.body),
    ) as span:
        stream_cm = llm.triage_stream(req)
        try:
            stream = await stream_cm.__aenter__()
        except LLMError as exc:
            ERRORS_TOTAL.add(1, {"endpoint": "stream", "status_code": "503"})
            span.set_attribute("error.kind", "llm_unavailable")
            raise HTTPException(status_code=503, detail="LLM service unavailable") from exc

        async def gen() -> AsyncGenerator[str]:
            first_emitted = False
            emitted_text = ""
            final: StreamingTriageResponse | None = None
            try:
                async for partial in stream.stream_output(debounce_by=None):
                    final = partial
                    chunk = _next_chunk(partial, emitted_text)  # returns None or the SSE event
                    if chunk is None:
                        continue
                    if not first_emitted:
                        ttft_ms = (time.perf_counter() - t_start) * 1000
                        STREAM_TTFT_MS.record(ttft_ms)
                        span.set_attribute("triage.stream.ttft_ms", ttft_ms)
                        first_emitted = True
                    yield chunk
                yield "event: done\ndata: [DONE]\n\n"
            finally:
                await stream_cm.__aexit__(None, None, None)
                if final and final.category and final.confidence is not None:
                    REQUESTS_TOTAL.add(1, {"endpoint": "stream", "category": str(final.category)})
                    CONFIDENCE.record(final.confidence)
                    span.set_attribute("triage.result.category", str(final.category))
                    span.set_attribute("triage.result.confidence", final.confidence)

        return StreamingResponse(gen(), media_type="text/event-stream")
```

**Critical notes:**
- `t_start` is captured *before* any I/O. It's the TTFT perceived by the client, not the server's internal one.
- The histogram is recorded at the exact moment the generator makes its first `yield` consumed by ASGI — that's as close as possible to "first byte on the wire". The delta vs the real flush moment is negligible (<1 ms in the ASGI stack).
- The span stays open until the generator finishes. Logfire closes it automatically when exiting the `with`, which occurs **after** returning `StreamingResponse` (the generator is lazily consumed). Validate that Logfire correctly handles spans whose lifetime exceeds the handler return — if not, use manual `span.__enter__()` and close it in the generator's `finally`. See Risks.

### 3. structlog ↔ trace correlation

Add a processor to `structlog.configure(...)`:

```python
# src/email_triage/middleware.py
from opentelemetry import trace

def _add_trace_context(logger, method_name, event_dict):
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict

structlog.configure(
    processors=[
        merge_contextvars,
        structlog.stdlib.add_log_level,
        _add_trace_context,            # ← new
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    ...
)
```

Now each JSON log has `trace_id` and `span_id` in addition to the existing `request_id`. In Logfire UI you can jump from log to trace.

### 4. Scrubbing of sensitive fields

```python
# src/email_triage/main.py
from logfire import ScrubbingOptions, ScrubMatch

def _scrub(match: ScrubMatch) -> str | None:
    if match.path[-1] in {"sender", "groq_api_key", "api_key", "x-api-key", "authorization"}:
        return "[REDACTED]"
    return None

logfire.configure(
    service_name="email-triage",
    send_to_logfire=settings.logfire_send_to_logfire,
    environment=settings.logfire_environment,
    scrubbing=ScrubbingOptions(callback=_scrub),
    sampling=SamplingOptions(head=settings.logfire_sample_rate, tail=...),  # see §5
)
```

`sender` is PII (email of the founder's customer). The email body (`body`) is **not** included in spans — only `email.body_chars` (length). If someone needs the body for debugging, they access it via structlog logs and the operator assumes the privacy cost.

### 5. Sampling

```python
sampling=SamplingOptions(
    head=settings.logfire_sample_rate,       # 0.1 default → 10% of requests enter the pipeline
    tail=TailSamplingOptions(
        level="error",       # 100% if the span has error level
        duration=5.0,        # 100% if the span lasts >5s
    ),
)
```

This keeps the Logfire count reasonable (limited free tier) without losing the important cases: all errors and all latency outliers are always recorded. The sample rate comes from env var → adjustable without code redeploy.

### 6. External TTFT measurement script

```python
# scripts/measure_ttft.py
import asyncio, httpx, time, statistics, sys

PAYLOAD = {
    "subject": "I want a refund",
    "sender": "customer@test.com",
    "body": "I bought a product 3 days ago and want to return it.",
}

async def one_request(client: httpx.AsyncClient, api_key: str) -> float:
    t0 = time.perf_counter()
    async with client.stream(
        "POST",
        "http://localhost:8000/triage/stream",
        json=PAYLOAD,
        headers={"X-API-Key": api_key},
    ) as r:
        async for chunk in r.aiter_bytes():
            if chunk:
                return (time.perf_counter() - t0) * 1000
    return float("nan")

async def main(n: int, api_key: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        samples = [await one_request(client, api_key) for _ in range(n)]
    samples.sort()
    print(f"n={n}  p50={samples[n//2]:.0f}ms  p95={samples[int(n*0.95)]:.0f}ms  max={samples[-1]:.0f}ms")

if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20, sys.argv[2]))
```

Serves as a cross-check for the server histogram. If they differ >50 ms, there's buffering overhead somewhere.

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Logfire as single sink | Prometheus + Grafana + OTel Collector | Additional stack to maintain; Logfire already integrated and free tier is enough to validate. Migrate later if unit economics support it |
| Centralized metrics catalog in `observability.py` | Create metrics inline where used | Avoids creating duplicates (OTel emits warnings); facilitates inventory for future dashboards |
| TTFT measured in the handler (not middleware) | Custom middleware timing the first chunk of the response body | Simpler to capture the moment of the first yield from inside the generator; middleware has no granular visibility of SSE |
| `logfire.metric_up_down_counter` for `in_flight` | Observable gauge with callback | UpDownCounter is synchronous and trivial with `try/finally`. Observable gauge would require a global registry |
| Head + tail sampling | Head sampling only | Tail sampling preserves errors and outliers without inflating the count — for SaaS B2B that tail is what matters |
| Scrubbing of `sender` with custom callback | Relying on default patterns | The `sender` field is a business field; no default regex detects it. Explicit is better |
| Span attributes follow OTel GenAI convention (`gen_ai.*`) where applicable | Ad-hoc names (`llm.model`) | Future compatibility with tooling that consumes OTel semconv; Pydantic AI already emits several `gen_ai.*` on its own |
| `email.body_chars` instead of `email.body` | Log the full body | PII + storage cost. Length is sufficient for size and outlier detection |
| Tests use `logfire.testing.CaptureLogfire` | Don't test instrumentation | The catalog is a contract; without tests, a refactor breaks it silently |

## Risks / Open questions

- **Span lifetime > handler return in streaming**: the `with logfire.span(...)` covers the creation of `StreamingResponse`, but the generator is consumed **after** the return. There's a risk the span closes before the stream ends, losing the final attributes (`triage.result.category`, etc.). **Mitigation**: if the span closes prematurely, refactor to `span = logfire.span(...).__enter__()` at the start and `span.__exit__(None, None, None)` inside the generator's `finally`. Validate empirically with TC-04 (verify the span in Logfire UI contains the final attributes).

- **Tail sampling fee on free tier**: tail sampling decides retroactively, which requires a buffer on Logfire's side — some platforms charge extra for that feature. **Mitigation**: check pricing in docs before enabling; if not applicable to the plan, disable tail and raise head to 0.3.

- **Scrubbing of `sender` via custom callback**: the callback receives the attribute path. If Pydantic AI emits the email body as a span attribute (e.g. `gen_ai.prompt`), the scrub must cover it. **Mitigation**: pre-read what `instrument_pydantic_ai()` emits with `logfire.testing.CaptureLogfire`; broaden the scrub if needed.

- **Double counting of `triage.latency_ms`**: `instrument_fastapi` already generates duration spans. Creating our own histogram may duplicate the signal. **Mitigation**: use **only** the defined histogram, and disable the default duration attribute from `instrument_fastapi` if it competes. Or remove `triage.latency_ms` from the catalog and derive p95 from spans in Logfire UI.

- **Label cardinality cost**: `category` has 5 values → OK. `status_code` has ~10 values → OK. **Do not** add `request_id`, `sender` or anything with high cardinality to metric labels (they go only to spans). Document the rule in the header of the `observability.py` module.

- **TTFT inflated by Render cold start**: the first request post-deploy pays the LLMService warm-up cost (Pydantic AI warm-up). It will appear as a TTFT outlier. **Mitigation**: the lifespan already does warm-up; verify in TC-01 that the first "real" request is not the absolute first. Document it.

- **Compatibility between `logfire.span()` and Pydantic AI internal spans**: Pydantic AI emits child spans when the agent is invoked. Ensure our parent span is active (context manager open) when the agent is called, so the trace is correctly nested in Logfire UI. Verify visually with TC-02.

- **Sampling and auth errors (403)**: if credential stuffing attacks occur, we want 100% of 403s (counter already captures them, but the span may be sampled out). Ensure the 403 branch marks the span with `level="warn"` and relies on tail sampling to retain it.

## Future metrics and improvements (not included in this plan)

What **does not** enter this session but remains in the backlog for a later iteration:

- **LLM tokens**: `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` as histogram. Pydantic AI exposes them via `result.usage()`. Prerequisite for alerting on per-request cost when moving off the free tier.
- **Cost per request** (in USD): derivable from tokens × model rate. Useful when Groq moves to paid or if Anthropic is added.
- **Heatmaps by hour of day / day of week**: reveals founder usage patterns, informs scaling decisions.
- **Category distribution by tenant** (when multi-tenancy exists): which founder has which mix → product can recommend personalized templates.
- **Alerts in Logfire**: suggested catalog to implement when there's real traffic:
  - p95 `triage.latency_ms` > 5000 ms for 5 min → page
  - rate of `triage.errors_total{status_code="503"}` > 1% for 10 min → page
  - p95 `triage.stream.ttft_ms` > 1500 ms for 10 min → warn
  - mean `triage.llm.confidence` < 0.6 for 1 h → warn (quality drift)
  - `triage.auth_failures_total` rate spike (3× baseline) in 5 min → warn (possible attack)

## Execution plan (suggested commit order)

1. **Catalog and base configuration** (45 min): create `observability.py`, update `main.py` with scrubbing + sampling + new instrumentations, add fields to `config.py` and `.env.example`. Verify local startup without errors.
2. **structlog ↔ trace correlation** (30 min): processor in `middleware.py`. Verify manually with `curl /health` that the JSON log has `trace_id`.
3. **Handler instrumentation** (60 min): refactor `routers/triage.py` with spans, counters, histograms. Refactor `services/llm.py` with `LLM_IN_FLIGHT` and `LLM_ERRORS_TOTAL`. Refactor `deps.py` with `AUTH_FAILURES_TOTAL`.
4. **TTFT in stream** (45 min): `first_emitted` flag logic. Manual verification with `curl -N` that the metric appears in Logfire.
5. **`measure_ttft.py` script** (30 min): implementation + run against local. Adjust histograms if the ranges don't fit.
6. **Tests** (45 min): `tests/test_observability.py` with `CaptureLogfire`. Suite green locally.
7. **Docs** (30 min): `12-observability.md`, `12-observability_testing.md`, update `06-logging.md`, `CLAUDE.md`, `AGENTS.md` §5, exec-plans/README.
8. **Wrap-up** (15 min): pre-commit, pyright, plan status → ✅.

## Done when

- [ ] `observability.py` module with complete catalog of counters/histograms/gauges
- [ ] `logfire.configure` includes scrubbing + sampling configurable via env
- [ ] `instrument_pydantic()`, `instrument_system_metrics()`, `instrument_httpx()` active
- [ ] structlog logs include `trace_id` and `span_id` (verifiable with `curl /health`)
- [ ] Spans of `/triage` and `/triage/stream` with attributes: `endpoint`, `email.body_chars`, `email.subject_chars`, `triage.result.category`, `triage.result.confidence`, and (for stream) `triage.stream.ttft_ms`
- [ ] `triage.stream.ttft_ms` histogram reported in Logfire UI with real data
- [ ] `scripts/measure_ttft.py` runs locally and reports p50/p95 coherent with the server histogram (difference <50 ms)
- [ ] PII (`sender`, API keys) scrubbed in all spans
- [ ] New tests pass; 9 existing tests remain green
- [ ] `docs/features/12-observability.md` and `docs/testing/12-observability_testing.md` created
- [ ] AGENTS.md §5 and exec-plans/README updated; plan in status ✅
- [ ] Pre-commit + pyright pass
- [ ] Human ran the testing guide and validated that metrics are visible in Logfire UI
