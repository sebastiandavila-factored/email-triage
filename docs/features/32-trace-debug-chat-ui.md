# Trace-Debug Chat — UI (Dashboard panel)

## What it does

Adds a **"Ver traces"** toggle to the triage result card on the Dashboard, visible only to
`owner`/`admin` and only once the result carries a `trace_id`. Expanding it opens a chat panel
anchored to that triage's trace: the user asks in natural language and the backend agent
(Plan 31) answers from the request's Logfire spans.

## How it works

- **Role gating.** The button renders only when `can(user?.role, 'traces:read')` (mirror of the
  backend `ROLE_SCOPES` in `rbac.ts`) — convenience only; the backend re-checks every request.
- **Anchoring.** `POST /triage` now returns `trace_id` (`TriageResponse.trace_id`); the panel
  passes it to `api.traceChat(token, tid, trace_id, message, history)` →
  `POST /workspaces/{tid}/traces/chat`. The tenant is derived server-side from the session, not
  sent by the client.
- **Conversation.** History is kept in the component's state and replayed on each request. An
  optimistic user turn is rolled back if the request fails, and the input is restored.
- **Reset.** Running a new triage collapses the panel and clears the anchor (`setShowTraces(false)`).

## Files involved

| File | Role |
|---|---|
| `frontend/src/rbac.ts` | `traces:read` added to `owner` + `admin` |
| `frontend/src/api.ts` | `trace_id` on `TriageResponse`; `TraceChat*` types; `traceChat()` |
| `frontend/src/components/TraceChat.tsx` | chat panel anchored to a `trace_id` |
| `frontend/src/pages/Dashboard.tsx` | "Ver traces" toggle in the result card |

## Out of scope

- Streaming replies (v1 is a single request/response; the endpoint is non-streaming).
- A rich span waterfall/timeline — v1 is a text chat; the agent summarizes the trace.
- Persisting chat history across reloads (kept in component memory).
