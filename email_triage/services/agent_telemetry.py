"""Agent telemetry helper (Plan 42).

Wraps a single ``agent.run(...)`` to emit the OpenTelemetry-for-agents KPIs as metrics (so they
show in Logfire as distributions/rates, not just per-call spans). Used by the genuine agents:
Plan 43 (diagnosis) and Plan 44 (tuning). Tool-call outcomes are read from the run's message
history, so no per-tool code is needed.

Ref: https://www.mintmcp.com/blog/opentelemetry-ai-agents
"""

from __future__ import annotations

import time
from collections.abc import Awaitable
from typing import Any

from pydantic_ai.messages import ModelResponse, ToolReturnPart

from email_triage.observability import (
    AGENT_INPUT_TOKENS,
    AGENT_LLM_LATENCY_MS,
    AGENT_LOOP_ITERATIONS,
    AGENT_OUTPUT_TOKENS,
    CONTEXT_UTILIZATION,
    TOOL_CALLS_TOTAL,
)

# llama-3.3-70b-versatile context window (Groq). Per-model; the metric carries a `model` label.
MODEL_MAX_CONTEXT = 131_072
# pydantic-ai's default structured-output tool — not a "real" tool call, so we skip it in #2.
_OUTPUT_TOOL = "final_result"


def _usage_int(usage: Any, *names: str) -> int:
    """Read the first present usage field (names vary across pydantic-ai versions)."""
    for name in names:
        value = getattr(usage, name, None)
        if value is not None:
            try:
                return int(value)
            except TypeError, ValueError:
                return 0
    return 0


def _model_label(result: Any) -> str:
    model = "unknown"
    for msg in result.all_messages():
        if isinstance(msg, ModelResponse) and msg.model_name:
            model = msg.model_name
    return model


def record_tool_calls(result: Any) -> None:
    for msg in result.all_messages():
        for part in getattr(msg, "parts", []):
            if not isinstance(part, ToolReturnPart) or part.tool_name == _OUTPUT_TOOL:
                continue
            content = part.content
            is_error = (isinstance(content, str) and content.startswith("error")) or (
                isinstance(content, dict) and "error" in content
            )
            TOOL_CALLS_TOTAL.add(
                1, {"tool": part.tool_name, "outcome": "error" if is_error else "ok"}
            )


async def instrument_agent_run[T](agent_name: str, coro: Awaitable[T]) -> T:
    """Await ``coro`` (an ``agent.run(...)``) and emit per-agent telemetry: LLM latency (#3),
    token usage (#1), loop iterations (#4), context-window utilization (#5), and per-tool
    success/error counts (#2). End-to-end latency (#6) is recorded by the caller."""
    attrs = {"agent": agent_name}
    t0 = time.perf_counter()
    result = await coro
    AGENT_LLM_LATENCY_MS.record((time.perf_counter() - t0) * 1000, attrs)

    usage = result.usage  # type: ignore[attr-defined]  # property on pydantic-ai >=1.10
    input_tokens = _usage_int(usage, "input_tokens", "request_tokens")
    output_tokens = _usage_int(usage, "output_tokens", "response_tokens")
    AGENT_INPUT_TOKENS.record(input_tokens, attrs)
    AGENT_OUTPUT_TOKENS.record(output_tokens, attrs)
    AGENT_LOOP_ITERATIONS.record(_usage_int(usage, "requests"), attrs)
    CONTEXT_UTILIZATION.record(
        input_tokens / MODEL_MAX_CONTEXT, {"agent": agent_name, "model": _model_label(result)}
    )
    record_tool_calls(result)
    return result
