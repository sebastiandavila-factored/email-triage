# Trace-Debug Chat — Backend (Logfire MCP agent)

## What it does

Lets a workspace `owner`/`admin` debug **one triage request** by chatting in natural
language. `POST /workspaces/{tid}/traces/chat` runs a backend agent (pydantic-ai) that
reads that request's traces from Logfire and explains latency, category/confidence, and
errors — like a technical support engineer. Gated by the new `traces:read` scope (owner +
admin; `member` is excluded).

Every `POST /triage` now returns a `trace_id` (32-hex) so the UI (Plan 32) can anchor the
chat to the exact request.

## How it works

```
POST /workspaces/{tid}/traces/chat
  → require_scope("traces:read")          # role in {owner, admin} + membership (anti-IDOR)
  → get_trace_chat_service(settings)       # None if no read token → 503
  → service.owns_trace(tenant_id, trace_id)  # ownership guard → 404 if not this org's
  → agent.run(...) with curated tools      # answers from Logfire spans
```

- **Tenant isolation is structural.** The Logfire read token is *project-wide* (it can see
  every tenant's traces), so it lives only in the backend and the model never gets a
  free-form query tool. The agent sees only two curated tools — `get_trace_spans` and
  `search_recent_org_traces` — whose SQL is built in `services/trace_agent.py` with
  `WHERE attributes->>'tenant_id' = '<tenant>'` (and, for the anchored trace,
  `AND trace_id = '<trace>'`) inlined from validated literals. The model supplies only a
  clamped `limit`. It *cannot* express a query that omits the tenant predicate.
- **Ownership guard.** `tenant_id` comes from the authenticated membership, never the body.
  Before the agent runs, `owns_trace` checks the trace has ≥1 span tagged with this tenant;
  a foreign or unknown trace returns zero rows → `404` (identical response either way, no
  leak).
- **Injection defense.** `tenant_id` is re-parsed as a UUID and `trace_id` must match
  `^[0-9a-f]{32}$` before either is inlined; a bad shape → `422`.
- **Logfire access is isolated** behind the `LogfireTraceClient` protocol. Production uses
  `LogfireQueryApiClient` (Logfire's own `AsyncLogfireQueryClient` read/query API — the same
  SQL-over-telemetry capability the Logfire MCP's `arbitrary_query` wraps); tests inject a
  fake. We use the query API instead of pydantic-ai's MCP client because that client
  (`pydantic_ai.mcp`, 1.104) fails to import against the `mcp>=2.0` this project pins for its
  own F4 server (it imports the removed `mcp.shared.session`). The protocol keeps this a
  one-class swap back to the MCP once versions align. `base_url=None` → region (US/EU) is
  derived from the read token.
- **No Groq/Logfire in tests.** The agent runs on pydantic-ai's `TestModel` (which calls
  every tool once); the Logfire client is a fake that records SQL.

## Files involved

| File | Role |
|---|---|
| `email_triage/auth/scopes.py` | new `traces:read` scope (owner + admin) |
| `email_triage/deps.py` | `TracesReadDep` (`require_scope("traces:read")`) |
| `email_triage/config.py` | `logfire_read_token`, `logfire_mcp_url` |
| `email_triage/schemas.py` | `trace_id` on triage responses; `TraceChat*` models |
| `email_triage/routers/triage.py` | set `trace_id` from the span context |
| `email_triage/services/trace_agent.py` | agent, curated tenant-bound tools, SQL builders, ownership guard, Logfire adapter |
| `email_triage/routers/traces.py` | `POST /workspaces/{tid}/traces/chat` + service provider |
| `email_triage/main.py` | register the router |
| `tests/test_traces_chat.py` | SQL isolation, agent guardrail, endpoint RBAC |

## Configuration

- `LOGFIRE_READ_TOKEN` — read token with scope `project:read` (backend-only). Absent → the
  endpoint returns `503`.
- `LOGFIRE_MCP_URL` — defaults to `https://logfire-us.pydantic.dev/mcp` (EU:
  `https://logfire-eu.pydantic.dev/mcp`).

## Out of scope (other plans)

- UI panel → Plan 32. Streaming responses (v1 is non-streaming JSON).
- `tenant_id` on `/triage/stream` + child spans via baggage → Plan 33 (so the agent also
  sees streaming traces and LLM/HTTP child spans).
- Dep bump to a MCP 2026-07-28-speaking client → follow-up (backward-compat holds meanwhile).
