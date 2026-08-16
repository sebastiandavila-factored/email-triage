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

# ---------------------------------------------------------------------------
# Agent telemetry (Plan 42) — the 6 KPIs from the OpenTelemetry-for-agents blog,
# emitted for the genuine agents (Plan 43 diagnosis, Plan 44 tuning). Labels stay
# low-cardinality: `agent` (diagnosis|tuning), `tool` (curated tool names), `outcome`
# (ok|error), `model`. Wiring + the `instrument_agent_run` helper: services/agent_telemetry.py.
# ---------------------------------------------------------------------------

# 1. Token Usage per Agent Run
AGENT_INPUT_TOKENS: Histogram = logfire.metric_histogram(
    "agent.input_tokens",
    unit="1",
    description="Input tokens consumed by one agent run, by agent.",
)
AGENT_OUTPUT_TOKENS: Histogram = logfire.metric_histogram(
    "agent.output_tokens",
    unit="1",
    description="Output tokens produced by one agent run, by agent.",
)

# 2. Tool Call Success Rate
TOOL_CALLS_TOTAL: Counter = logfire.metric_counter(
    "agent.tool_calls_total",
    unit="1",
    description="Agent tool invocations, labeled by tool and outcome (ok|error).",
)

# 3. LLM Latency Distribution (wall-clock of one agent run — model calls + tool time)
AGENT_LLM_LATENCY_MS: Histogram = logfire.metric_histogram(
    "agent.llm.latency_ms",
    unit="ms",
    description="Wall-clock of a single agent.run (model requests + tool calls), by agent.",
)

# 4. Agent Loop Iterations (ReAct cycles ≈ model requests per run)
AGENT_LOOP_ITERATIONS: Histogram = logfire.metric_histogram(
    "agent.loop_iterations",
    unit="1",
    description="Model requests (ReAct cycles) in one agent run, by agent.",
)

# 5. Context Window Utilization (input tokens / model context window)
CONTEXT_UTILIZATION: Histogram = logfire.metric_histogram(
    "agent.context_utilization",
    unit="ratio",
    description="Input tokens / model context window (0-1), by agent and model.",
)

# 6. End-to-End Agent Latency (whole entry-point operation)
AGENT_E2E_LATENCY_MS: Histogram = logfire.metric_histogram(
    "agent.e2e.latency_ms",
    unit="ms",
    description="Total time from request to final response for a top-level agent, by agent.",
)
