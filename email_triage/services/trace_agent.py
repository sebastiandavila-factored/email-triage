"""Trace-debug chat agent (Plan 31).

Lets a workspace owner/admin ask, in natural language, why a specific triage behaved
the way it did, answered by an agent that reads that request's traces from Logfire.

Security — the whole point of this module:
  The Logfire read token is **project-wide** (it can see every tenant's traces), so the
  model is NEVER given a free-form query tool. It only sees the curated tools below, whose
  SQL is built here with the caller's ``tenant_id`` (and the anchored ``trace_id``) baked in
  as literals we validate. The isolation is therefore *structural*: the model cannot express
  a query that omits the tenant predicate.

Logfire access is isolated behind the ``LogfireTraceClient`` protocol so tests inject a fake
(no network) and the query client stays in one place — see ``LogfireQueryApiClient``.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, cast

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.toolsets.function import FunctionToolset

from email_triage.observability import AGENT_E2E_LATENCY_MS
from email_triage.schemas import TraceDiagnosis
from email_triage.services.agent_telemetry import instrument_agent_run
from email_triage.services.groq import build_groq_model

# A 32-hex OTel trace id (what ``format(trace_id, "032x")`` produces). Anything else is
# rejected before it can reach a query string.
_TRACE_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")

# Core Logfire ``records`` columns (kept to a set we're confident exists so the query never
# fails on an unknown column). ``attributes`` carries our custom ``triage.*`` / ``error.*``.
_COLUMNS = (
    "trace_id, span_id, parent_span_id, span_name, message, "
    "level, start_timestamp, duration, attributes"
)
_MAX_ROWS = 200


class LogfireQueryError(RuntimeError):
    """Raised when a trace query is invalid or Logfire is unreachable/misconfigured."""


class LogfireTraceClient(Protocol):
    """Runs a read-only SQL query against Logfire and returns the rows.

    Implementations must be side-effect-free reads. The SQL is always built by this module
    (never by the model), with tenant/trace predicates already inlined.
    """

    async def query(self, sql: str) -> list[dict[str, Any]]: ...


# ── SQL builders (tenant/trace predicates are mandatory and validated) ────────────────


def _safe_tenant(tenant_id: str) -> str:
    """Return the canonical UUID string, raising on anything that isn't a UUID.

    ``tenant_id`` originates from the authenticated ``WorkspaceContext`` (already a
    ``uuid.UUID``), but we re-validate so a literal can be inlined without injection risk.
    """
    try:
        return str(uuid.UUID(str(tenant_id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise LogfireQueryError("invalid tenant id") from exc


def ensure_trace_id(trace_id: str) -> str:
    """Return ``trace_id`` iff it's 32 hex chars, else raise (injection guard)."""
    if not _TRACE_ID_RE.match(trace_id or ""):
        raise LogfireQueryError("invalid trace id (expected 32 hex chars)")
    return trace_id


def trace_spans_sql(tenant_id: str, trace_id: str, *, limit: int = _MAX_ROWS) -> str:
    t = _safe_tenant(tenant_id)
    tr = ensure_trace_id(trace_id)
    return (
        f"SELECT {_COLUMNS} FROM records "
        f"WHERE attributes->>'tenant_id' = '{t}' AND trace_id = '{tr}' "
        f"ORDER BY start_timestamp ASC LIMIT {int(limit)}"
    )


def recent_org_sql(tenant_id: str, *, limit: int) -> str:
    t = _safe_tenant(tenant_id)
    limit = max(1, min(int(limit), 50))
    return (
        f"SELECT {_COLUMNS} FROM records "
        f"WHERE attributes->>'tenant_id' = '{t}' "
        f"ORDER BY start_timestamp DESC LIMIT {limit}"
    )


# ── Agent wiring ──────────────────────────────────────────────────────────────────────


@dataclass
class TraceDeps:
    """Per-request context handed to the tools. Not model-controllable."""

    client: LogfireTraceClient
    tenant_id: str
    trace_id: str


TRACE_SYSTEM_PROMPT = (
    "You are a technical support engineer helping a workspace owner or admin debug ONE "
    "email-triage request using its observability traces from Logfire.\n"
    "- Use the tools to fetch spans; base every statement on returned data and never invent "
    "numbers, categories, or errors.\n"
    "- Explain latency (span durations), the resulting category and confidence, and any errors "
    "or slow LLM/HTTP steps, in plain language a non-engineer can act on.\n"
    "- You can only ever see this organization's traces; if the tools return nothing, say so "
    "instead of guessing.\n"
    "- Be concise and concrete."
)


async def get_trace_spans(
    ctx: RunContext[TraceDeps], limit: int = _MAX_ROWS
) -> list[dict[str, Any]]:
    """Return the spans of the triage request under investigation.

    Each span has its name, level, start time, duration and attributes (including the
    triage category/confidence and any error kind). This is the primary evidence.

    Args:
        limit: Max spans to return (defaults to all of them; the trace is small).
    """
    # NB: this tool intentionally carries a parameter. Groq sends `null` (not `{}`) as the
    # arguments for a zero-parameter tool, which fails pydantic-ai's object-schema validation
    # and exhausts retries — an argument gives the model a proper object to send.
    d = ctx.deps
    limit = max(1, min(int(limit), _MAX_ROWS))
    return await d.client.query(trace_spans_sql(d.tenant_id, d.trace_id, limit=limit))


async def search_recent_org_traces(
    ctx: RunContext[TraceDeps], limit: int = 20
) -> list[dict[str, Any]]:
    """Look at the workspace's most recent spans across requests (max 50).

    Use to judge whether a symptom (an error, high latency) is a one-off or recurring.
    Always scoped to this organization.
    """
    d = ctx.deps
    return await d.client.query(recent_org_sql(d.tenant_id, limit=limit))


def build_trace_agent(model: Model) -> Agent[TraceDeps, str]:
    """Build the trace-debug agent over the given model (a real Groq model in prod, a
    ``TestModel`` in tests)."""
    toolset = FunctionToolset[TraceDeps]([get_trace_spans, search_recent_org_traces])
    return Agent(
        model,
        deps_type=TraceDeps,
        toolsets=[toolset],
        system_prompt=TRACE_SYSTEM_PROMPT,
    )


DIAGNOSIS_SYSTEM_PROMPT = (
    "You are a support engineer producing a STRUCTURED diagnosis of ONE email-triage request "
    "from its Logfire traces.\n"
    "- First call the tools to fetch the trace's spans; if a symptom (error, high latency, low "
    "confidence) might be recurring, also look at recent org traces.\n"
    "- Ground EVERY field in returned data; never invent spans, numbers, categories or errors. "
    "Put the concrete spans you relied on in `evidence`.\n"
    "- Set `suggested_fix_kind`: `add_counter_example` when the model picked a category it "
    "shouldn't (a counter-example would help); `tweak_category` when a category's description is "
    "ambiguous; `adjust_examples` when existing few-shots mislead; `none` when config wouldn't "
    "help (correct result, or an infra/LLM outage).\n"
    "- When the fix targets a category, set `target_slug` to that category's slug.\n"
    "- If the tools return nothing, use `suggested_fix_kind=none` and a low `confidence`."
)


def build_diagnosis_agent(model: Model) -> Agent[TraceDeps, TraceDiagnosis]:
    """Structured-diagnosis agent: the SAME curated toolset as the chat agent, but returns a
    ``TraceDiagnosis`` instead of free text (so Plan 44 can act on it)."""
    toolset = FunctionToolset[TraceDeps]([get_trace_spans, search_recent_org_traces])
    return Agent(
        model,
        deps_type=TraceDeps,
        output_type=TraceDiagnosis,
        toolsets=[toolset],
        system_prompt=DIAGNOSIS_SYSTEM_PROMPT,
    )


def _compose_prompt(message: str, history: list[tuple[str, str]]) -> str:
    """Fold prior turns into the prompt (v1 keeps history client-side; proper
    ``message_history`` is a follow-up)."""
    if not history:
        return message
    lines = [f"{role}: {content}" for role, content in history]
    lines.append(f"user: {message}")
    return "Conversation so far:\n" + "\n".join(lines)


async def owns_trace(client: LogfireTraceClient, tenant_id: str, trace_id: str) -> bool:
    """True iff the trace has at least one span tagged with this tenant.

    Because the query ANDs both predicates, a trace belonging to another org (or a
    non-existent one) returns zero rows → the caller answers 404, never leaks.
    """
    rows = await client.query(trace_spans_sql(tenant_id, trace_id, limit=1))
    return len(rows) > 0


class TraceChatService:
    """Ties the agent to a Logfire client and enforces the ownership guard."""

    def __init__(self, agent: Agent[TraceDeps, str], client: LogfireTraceClient) -> None:
        self._agent = agent
        self._client = client

    async def owns_trace(self, tenant_id: str, trace_id: str) -> bool:
        return await owns_trace(self._client, tenant_id, trace_id)

    async def chat(
        self, tenant_id: str, trace_id: str, message: str, history: list[tuple[str, str]]
    ) -> str:
        deps = TraceDeps(
            client=self._client, tenant_id=tenant_id, trace_id=ensure_trace_id(trace_id)
        )
        try:
            result = await self._agent.run(_compose_prompt(message, history), deps=deps)
        except LogfireQueryError:
            raise  # already actionable (bad query / Logfire down) — let the router map it
        except Exception as exc:  # noqa: BLE001 — model/tool/transport failure → graceful 503
            raise LogfireQueryError(
                "The trace assistant could not complete the analysis; please retry."
            ) from exc
        return result.output


class TraceDiagnosisService:
    """Runs the structured-diagnosis agent for one trace, with the ownership guard (Plan 43)."""

    def __init__(self, agent: Agent[TraceDeps, TraceDiagnosis], client: LogfireTraceClient) -> None:
        self._agent = agent
        self._client = client

    async def owns_trace(self, tenant_id: str, trace_id: str) -> bool:
        return await owns_trace(self._client, tenant_id, trace_id)

    async def diagnose(self, tenant_id: str, trace_id: str) -> TraceDiagnosis:
        deps = TraceDeps(
            client=self._client, tenant_id=tenant_id, trace_id=ensure_trace_id(trace_id)
        )
        t0 = time.perf_counter()
        try:
            # Plan 42: instrument the agent.run (tokens/latency/iterations/context/tool-calls).
            result = await instrument_agent_run(
                "diagnosis", self._agent.run(f"Diagnose triage trace {trace_id}.", deps=deps)
            )
        except LogfireQueryError:
            raise  # already actionable (bad query / Logfire down) — let the router map it
        except Exception as exc:  # noqa: BLE001 — model/tool/transport failure → graceful 503
            raise LogfireQueryError(
                "The diagnosis assistant could not complete the analysis; please retry."
            ) from exc
        AGENT_E2E_LATENCY_MS.record((time.perf_counter() - t0) * 1000, {"agent": "diagnosis"})
        out = result.output
        out.confidence = max(0.0, min(1.0, out.confidence))  # defensive clamp
        return out


# ── Production Logfire adapter (isolates the version-sensitive MCP client) ─────────────


def _rows_from_result(result: object) -> list[dict[str, Any]]:
    """Normalize ``arbitrary_query`` output into a list of row dicts.

    The Logfire query tool may return a list of rows or a ``{"columns", "rows"}`` shape;
    be lenient so a schema tweak on their side doesn't crash us."""
    data: object = result
    if isinstance(data, dict):
        d = cast("dict[str, Any]", data)
        inner = d.get("rows")
        data = inner if inner is not None else d.get("data")
    if isinstance(data, list):
        items = cast("list[Any]", data)
        return [cast("dict[str, Any]", r) for r in items if isinstance(r, dict)]
    return []


class LogfireQueryApiClient:
    """``LogfireTraceClient`` backed by Logfire's read/query API (`AsyncLogfireQueryClient`).

    This is the same SQL-over-telemetry capability the Logfire MCP's ``arbitrary_query``
    tool wraps, but via Logfire's own version-aligned client. We use it instead of the MCP
    client because pydantic-ai 1.104's MCP hierarchy fails to import against the ``mcp>=2.0``
    this project pins (it imports the removed ``mcp.shared.session``) — see Plan 31/33 notes.
    Swapping back to the MCP is a one-class change once the versions line up.

    ``base_url=None`` lets the client derive the region (US/EU) from the read token.
    """

    def __init__(self, read_token: str, base_url: str | None = None) -> None:
        from logfire.experimental.query_client import AsyncLogfireQueryClient

        self._client = AsyncLogfireQueryClient(read_token=read_token, base_url=base_url)

    async def query(self, sql: str) -> list[dict[str, Any]]:
        try:
            result = await self._client.query_json_rows(sql)
        except Exception as exc:  # noqa: BLE001 — surface any query/transport failure as ours
            raise LogfireQueryError(f"Logfire query failed: {exc}") from exc
        return _rows_from_result(result)


def build_trace_chat_service(
    *, groq_model: str, groq_api_key: str, read_token: str, base_url: str | None = None
) -> TraceChatService:
    """Production factory: Groq-backed agent + Logfire query-API client."""
    agent = build_trace_agent(build_groq_model(groq_model, groq_api_key))
    client = LogfireQueryApiClient(read_token, base_url)
    return TraceChatService(agent, client)


def build_diagnosis_service(
    *, groq_model: str, groq_api_key: str, read_token: str, base_url: str | None = None
) -> TraceDiagnosisService:
    """Production factory: Groq-backed structured-diagnosis agent + Logfire query-API client."""
    agent = build_diagnosis_agent(build_groq_model(groq_model, groq_api_key))
    return TraceDiagnosisService(agent, LogfireQueryApiClient(read_token, base_url))
