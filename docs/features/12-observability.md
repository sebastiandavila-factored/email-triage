# Observability with Logfire (OTel) + streaming metrics

## What it does

Converts the minimal Logfire setup into an actionable observability layer that answers three questions:
- *Is the API healthy?* — `triage.errors_total`, `triage.latency_ms`
- *How fast does the client perceive the response?* — `triage.stream.ttft_ms` (real TTFT measured in the handler)
- *What categories and confidence is the LLM producing?* — `triage.requests_total`, `triage.llm.confidence`

## Metrics catalog

All defined in `src/email_triage/observability.py`.

### Counters

| Name | Labels | When |
|---|---|---|
| `triage.requests_total` | `endpoint`, `category` | Each successful request |
| `triage.errors_total` | `endpoint`, `status_code` | Each 4xx/5xx |
| `triage.llm_errors_total` | `error_class` | Each `LLMError` in the service |
| `triage.auth_failures_total` | (none) | Each 403 in `verify_api_key` |
| `triage.rate_limit_hits_total` | `endpoint` | Each 429 from slowapi |

### Histograms

| Name | Unit | What it measures |
|---|---|---|
| `triage.stream.ttft_ms` | ms | Time to first SSE chunk |
| `triage.llm.latency_ms` | ms | Time inside `LLMService.triage*` |
| `triage.llm.confidence` | ratio | Confidence score distribution |
| `triage.request.body_chars` | chars | Email body length |
| `triage.response.draft_chars` | chars | Draft reply length |

### Gauges

| Name | What it measures |
|---|---|
| `triage.llm.in_flight` | LLM calls in flight at this instant |

### System metrics (automatic)

`logfire.instrument_system_metrics()` adds CPU, RSS memory, file descriptors, network I/O.

## Spans and attributes

Handlers inject custom attributes into their spans:

| Span | Attributes |
|---|---|
| `triage.sync` | `endpoint`, `email.subject_chars`, `email.body_chars`, `triage.result.category`, `triage.result.confidence` |
| `triage.stream` | Same + `triage.stream.ttft_ms` |

## structlog ↔ traces correlation

The `_add_trace_context` processor in `middleware.py` injects `trace_id` and `span_id` into every JSON log. If the log appears in stdout, you can search for the trace in Logfire UI with that `trace_id`.

## PII and scrubbing

`logfire.configure(scrubbing=ScrubbingOptions(...))`:
- `sender` — scrubbed via `extra_patterns=["sender"]` (email of the founder's customer)
- `api_key`, `groq_api_key`, `x-api-key`, `authorization` — covered by custom callback
- Email `body` — **not** included in spans; only `email.body_chars` (length)

## Sampling

Configurable via env var `LOGFIRE_SAMPLE_RATE` (default `1.0` = 100%):
- Head sampling: `head=logfire_sample_rate`
- Tail sampling: 100% if the span has error level or duration > 5 s

## Active instrumentations

| Instrument | What it captures |
|---|---|
| `instrument_fastapi(app)` | HTTP request/response spans |
| `instrument_pydantic_ai()` | LLM agent spans (inputs, outputs) |
| `instrument_pydantic()` | 422 validation errors |
| `instrument_httpx()` | Egress HTTP calls (Pydantic AI's internal client) |
| `instrument_system_metrics()` | CPU, memory, file descriptors |

## Files involved

| File | Role |
|---|---|
| `src/email_triage/observability.py` | Metrics catalog (source of truth) |
| `src/email_triage/main.py` | `logfire.configure` with scrubbing + sampling + instrumentations |
| `src/email_triage/middleware.py` | structlog processor for `trace_id`/`span_id` |
| `src/email_triage/routers/triage.py` | Spans, counters, histograms, TTFT |
| `src/email_triage/services/llm.py` | `LLM_IN_FLIGHT` gauge, `LLM_ERRORS_TOTAL` counter |
| `src/email_triage/deps.py` | `AUTH_FAILURES_TOTAL` counter in verify_api_key |
| `scripts/measure_ttft.py` | Standalone client-side TTFT measurement script |

## Testing

📋 [Testing guide](../testing/12-observability_testing.md)
