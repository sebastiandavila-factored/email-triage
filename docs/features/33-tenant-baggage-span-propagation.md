# tenant_id on every span (OTel baggage)

## What it does

Makes **every span** of a `/triage` request carry `tenant_id`, not just the root of the sync
path. Two gaps are closed:

1. `/triage/stream`'s root span now sets `tenant_id` (it previously had none).
2. Child spans (pydantic-ai model requests, httpx) on **both** sync and stream inherit
   `tenant_id` via OpenTelemetry **baggage**.

This is what lets the per-org trace query behind the trace-debug chat (Plan 31) see the whole
trace tree — including the LLM/HTTP steps — instead of only the root span.

## How it works

- `logfire.set_baggage(tenant_id=...)` attaches the value to OTel baggage for the enclosing
  scope. Logfire's `DirectBaggageAttributesSpanProcessor` (on by default via
  `add_baggage_to_attributes=True`) copies each baggage key onto every span started in that
  scope as a **direct attribute** — so it's queryable as `attributes->>'tenant_id'`, matching
  the root span's explicit attribute (identical value → no `baggage_conflict.*`).
- **Sync** (`routers/triage.py`): the `llm.triage(req)` call is wrapped in `set_baggage(...)`,
  so the agent/httpx child spans get `tenant_id`.
- **Stream**: the root span sets `tenant_id` explicitly, and `stream_cm.__aenter__()` — where
  the model-request/httpx child spans are created — is wrapped in `set_baggage(...)`. We wrap
  `__aenter__` (no `yield` inside) rather than the streaming loop, because entering/exiting a
  baggage context across an async-generator `yield` can detach an OTel context token in the
  wrong context.

## Files involved

| File | Change |
|---|---|
| `email_triage/routers/triage.py` | `set_baggage` around the sync LLM call; stream root `tenant_id` + `set_baggage` around `__aenter__`; `tenant: TenantDep` on the stream handler |
| `tests/test_tenant_baggage.py` | root spans carry `tenant_id`; a child span inherits it via baggage |

## Notes

- `tenant_id` stays on **spans/attributes**, never on metric labels (high cardinality would
  break the metrics in `observability.py`).
- No schema/metrics changes; no historical backfill.
