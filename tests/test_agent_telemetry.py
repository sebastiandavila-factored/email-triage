"""Agent telemetry (Plan 42): the 6 KPIs fire, with the right low-cardinality labels.

No network: the diagnosis agent runs on ``TestModel`` over a fake Logfire client. The metric
instruments are replaced with recording doubles so we can assert what was emitted."""

from __future__ import annotations

from typing import Any

import email_triage.services.agent_telemetry as at
import email_triage.services.trace_agent as ta
from email_triage.services.agent_telemetry import record_tool_calls
from email_triage.services.trace_agent import TraceDiagnosisService, build_diagnosis_agent
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from pydantic_ai.models.test import TestModel

_TENANT = "11111111-1111-1111-1111-111111111111"
_TRACE = "a" * 32


class FakeLogfireClient:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else [{"span_name": "triage.sync", "level": 9}]

    async def query(self, sql: str) -> list[dict[str, Any]]:
        return self.rows


class _Rec:
    def __init__(self) -> None:
        self.calls: list[tuple[float, dict[str, Any] | None]] = []

    def record(self, value: float, attributes: dict[str, Any] | None = None) -> None:
        self.calls.append((value, attributes))

    def add(self, amount: float, attributes: dict[str, Any] | None = None) -> None:
        self.calls.append((amount, attributes))


def _patch_instruments(monkeypatch: Any) -> dict[str, _Rec]:
    recs = {
        name: _Rec()
        for name in (
            "AGENT_INPUT_TOKENS",
            "AGENT_OUTPUT_TOKENS",
            "AGENT_LLM_LATENCY_MS",
            "AGENT_LOOP_ITERATIONS",
            "CONTEXT_UTILIZATION",
            "TOOL_CALLS_TOTAL",
        )
    }
    for name, rec in recs.items():
        monkeypatch.setattr(at, name, rec)
    recs["E2E"] = _Rec()
    monkeypatch.setattr(ta, "AGENT_E2E_LATENCY_MS", recs["E2E"])
    return recs


async def test_diagnosis_run_emits_all_six_kpi_families(monkeypatch: Any) -> None:
    recs = _patch_instruments(monkeypatch)
    svc = TraceDiagnosisService(build_diagnosis_agent(TestModel()), FakeLogfireClient())

    await svc.diagnose(_TENANT, _TRACE)

    # #1 token usage, #3 llm latency, #4 iterations — each emitted once, labeled agent=diagnosis.
    for name in (
        "AGENT_INPUT_TOKENS",
        "AGENT_OUTPUT_TOKENS",
        "AGENT_LLM_LATENCY_MS",
        "AGENT_LOOP_ITERATIONS",
    ):
        assert recs[name].calls, f"{name} not recorded"
        assert recs[name].calls[0][1] == {"agent": "diagnosis"}
    # #5 context utilization: ratio in [0,1], labeled agent+model.
    val, attrs = recs["CONTEXT_UTILIZATION"].calls[0]
    assert 0.0 <= val <= 1.0
    assert attrs is not None and attrs["agent"] == "diagnosis" and "model" in attrs
    # #6 end-to-end latency, labeled agent=diagnosis.
    assert recs["E2E"].calls and recs["E2E"].calls[0][1] == {"agent": "diagnosis"}
    # #2 tool-call success rate: the curated tools were counted as ok.
    outcomes = {a["tool"]: a["outcome"] for _, a in recs["TOOL_CALLS_TOTAL"].calls if a}
    assert outcomes.get("get_trace_spans") == "ok"


def test_record_tool_calls_classifies_ok_and_error(monkeypatch: Any) -> None:
    rec = _Rec()
    monkeypatch.setattr(at, "TOOL_CALLS_TOTAL", rec)

    class FakeResult:
        def all_messages(self) -> list[Any]:
            return [
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="add_counter_example",
                            content="error: no category with slug 'x'",
                            tool_call_id="c1",
                        ),
                        ToolReturnPart(
                            tool_name="run_check",
                            content={"target_fixed": True, "checked": 1},
                            tool_call_id="c2",
                        ),
                        ToolReturnPart(
                            tool_name="final_result",  # output tool — must be skipped
                            content="ok",
                            tool_call_id="c3",
                        ),
                    ]
                )
            ]

    record_tool_calls(FakeResult())
    outcomes = {a["tool"]: a["outcome"] for _, a in rec.calls if a}
    assert outcomes["add_counter_example"] == "error"
    assert outcomes["run_check"] == "ok"
    assert "final_result" not in outcomes  # skipped
