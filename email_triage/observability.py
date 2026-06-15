"""
OTel metric instruments for email-triage.

Rules:
- All labels (attributes) must have low cardinality: no request_id, sender, or free-form text.
- Allowed labels: endpoint (sync|stream), category (5 values), status_code (~10 values),
  error_class.
- body/reply content is intentionally omitted from spans; only char lengths are tracked.
"""

import logfire
from opentelemetry.metrics import Counter, Histogram, UpDownCounter

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

REQUESTS_TOTAL: Counter = logfire.metric_counter(
    "triage.requests_total",
    unit="1",
    description="Successful triage requests by endpoint and resulting category.",
)

ERRORS_TOTAL: Counter = logfire.metric_counter(
    "triage.errors_total",
    unit="1",
    description="Triage requests that returned 4xx/5xx, labeled by status code.",
)

LLM_ERRORS_TOTAL: Counter = logfire.metric_counter(
    "triage.llm_errors_total",
    unit="1",
    description="LLM backend errors, labeled by exception class.",
)

AUTH_FAILURES_TOTAL: Counter = logfire.metric_counter(
    "triage.auth_failures_total",
    unit="1",
    description="API key auth failures (403).",
)

RATE_LIMIT_HITS_TOTAL: Counter = logfire.metric_counter(
    "triage.rate_limit_hits_total",
    unit="1",
    description="Rate limit hits (429) by endpoint.",
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

STREAM_TTFT_MS: Histogram = logfire.metric_histogram(
    "triage.stream.ttft_ms",
    unit="ms",
    description="Time from request arrival to first SSE byte sent to client.",
)

LLM_LATENCY_MS: Histogram = logfire.metric_histogram(
    "triage.llm.latency_ms",
    unit="ms",
    description="Time spent inside LLMService.triage*.",
)

CONFIDENCE: Histogram = logfire.metric_histogram(
    "triage.llm.confidence",
    unit="ratio",
    description="LLM output confidence score distribution.",
)

REQUEST_BODY_CHARS: Histogram = logfire.metric_histogram(
    "triage.request.body_chars",
    unit="chars",
    description="Input email body length in characters.",
)

RESPONSE_DRAFT_CHARS: Histogram = logfire.metric_histogram(
    "triage.response.draft_chars",
    unit="chars",
    description="LLM draft reply length in characters.",
)

# ---------------------------------------------------------------------------
# Gauges (UpDownCounter — increment on enter, decrement on exit)
# ---------------------------------------------------------------------------

LLM_IN_FLIGHT: UpDownCounter = logfire.metric_up_down_counter(
    "triage.llm.in_flight",
    unit="1",
    description="In-flight LLM calls at this instant.",
)
