"""Voice report — a deterministic summarize → script workflow (Plan 41).

The professional shape for a known pipeline is a workflow (prompt chaining), not an agent. Two
LLM steps: summarize the (already-triaged) inbox items, then write a spoken-briefing script. The
caller passes the ``items`` it already has on screen, so this is fully decoupled from Gmail.

Counts (``by_category``/``total``) are computed by the harness — exact, not model-reported. v1 is
script-only; ``VoiceReport.audio_url`` stays None for a future TTS step.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.models import Model

from email_triage.schemas import (
    CategoryCount,
    InboxItem,
    ReportSummary,
    VoiceReport,
    VoiceScript,
)
from email_triage.services.agent_telemetry import instrument_agent_run
from email_triage.services.groq import build_groq_model

SUMMARY_SYSTEM_PROMPT = (
    "You summarize a support inbox for a spoken daily briefing. From the triaged items, produce a "
    "crisp one-line headline, the key themes, and which senders/subjects need attention. Ground "
    "every claim in the items; never invent counts or categories."
)

SCRIPT_SYSTEM_PROMPT = (
    "You are a scriptwriter for a professional voice briefing. Turn the summary into a short, "
    "well-structured script: a warm opening, one section per theme with concrete copy, and a "
    "closing with the single most important next action. Natural, spoken tone — this will be read "
    "aloud."
)


def build_summary_agent(model: Model) -> Agent[None, ReportSummary]:
    return Agent(model, output_type=ReportSummary, system_prompt=SUMMARY_SYSTEM_PROMPT)


def build_script_agent(model: Model) -> Agent[None, VoiceScript]:
    return Agent(model, output_type=VoiceScript, system_prompt=SCRIPT_SYSTEM_PROMPT)


def _render_items(items: list[InboxItem]) -> str:
    lines = [f"- [{i.category} {i.confidence:.2f}] {i.sender}: {i.subject}" for i in items]
    return "Today's triaged inbox:\n" + "\n".join(lines)


def _render_summary(summary: ReportSummary) -> str:
    parts = [f"Headline: {summary.headline}"]
    if summary.themes:
        parts.append("Themes: " + "; ".join(summary.themes))
    if summary.urgent:
        parts.append("Needs attention: " + "; ".join(summary.urgent))
    return "\n".join(parts)


async def run_voice_report(
    *,
    summary_agent: Agent[None, ReportSummary],
    script_agent: Agent[None, VoiceScript],
    items: list[InboxItem],
) -> VoiceReport:
    counts = Counter(item.category for item in items)
    by_category = [CategoryCount(category=cat, count=n) for cat, n in counts.items()]

    if not items:
        script = VoiceScript(
            opening="No relevant emails today.",
            sections=[],
            closing="Nothing to report. Have a good day.",
        )
        return VoiceReport(script=script, headline="No emails today", by_category=[], total=0)

    summary = (
        await instrument_agent_run("voice_summary", summary_agent.run(_render_items(items)))
    ).output
    script = (
        await instrument_agent_run("voice_script", script_agent.run(_render_summary(summary)))
    ).output
    return VoiceReport(
        script=script, headline=summary.headline, by_category=by_category, total=len(items)
    )


@dataclass
class VoiceReportRunner:
    """Bundles the two workflow agents. Overridden in tests with ``TestModel``-backed agents."""

    summary_agent: Agent[None, ReportSummary]
    script_agent: Agent[None, VoiceScript]

    async def run(self, items: list[InboxItem]) -> VoiceReport:
        return await run_voice_report(
            summary_agent=self.summary_agent, script_agent=self.script_agent, items=items
        )


def build_voice_report_runner(*, groq_model: str, groq_api_key: str) -> VoiceReportRunner:
    model = build_groq_model(groq_model, groq_api_key)
    return VoiceReportRunner(build_summary_agent(model), build_script_agent(model))
