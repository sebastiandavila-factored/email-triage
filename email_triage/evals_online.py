"""Cheap, non-LLM online evaluators run on a sampled fraction of live /triage traffic.

Each evaluator is pure and total (never raises) so it cannot affect the request. The
capability dispatches them asynchronously after the agent run, so they do not add latency
to the response; ``sample_rate`` and ``max_concurrency`` bound their footprint further.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from pydantic_evals.online import OnlineEvalConfig, OnlineEvaluator
from pydantic_evals.online_capability import OnlineEvaluation

from email_triage.config import Settings
from email_triage.schemas import TriageResponse

# Cheap language heuristic (no language-detection dependency): Spanish-only characters and
# a few high-frequency stopwords. Best-effort — used only to flag obvious mismatches.
_ES_CHARS = set("áéíóúñ¿¡")
_ES_WORDS = {"el", "la", "los", "las", "de", "que", "su", "para", "gracias", "pedido", "envío"}


def looks_spanish(text: str) -> bool:
    lowered = text.lower()
    if any(ch in _ES_CHARS for ch in lowered):
        return True
    tokens = set(lowered.split())
    return len(tokens & _ES_WORDS) >= 2


@dataclass
class OutputNotEmpty(Evaluator[object, TriageResponse, object]):
    def evaluate(self, ctx: EvaluatorContext[object, TriageResponse, object]) -> bool:
        return bool(ctx.output.draft_reply.strip())


@dataclass
class ConfidenceInRange(Evaluator[object, TriageResponse, object]):
    def evaluate(self, ctx: EvaluatorContext[object, TriageResponse, object]) -> bool:
        return 0.0 <= ctx.output.confidence <= 1.0


@dataclass
class LanguageMatches(Evaluator[object, TriageResponse, object]):
    """Heuristic: the reply's language should match the incoming email's. Passes when the
    Spanish/non-Spanish guess agrees for input and reply."""

    def evaluate(self, ctx: EvaluatorContext[object, TriageResponse, object]) -> bool:
        return looks_spanish(str(ctx.inputs)) == looks_spanish(ctx.output.draft_reply)


def build_online_capability(settings: Settings) -> OnlineEvaluation | None:
    """Build the online-eval capability from settings, or None when disabled (the
    default), in which case /triage runs exactly as before."""
    if not settings.online_eval_enabled:
        return None
    rate = settings.online_eval_sample_rate
    max_concurrency = settings.online_eval_max_concurrency
    evaluators: list[Evaluator[object, TriageResponse, object]] = [
        OutputNotEmpty(),
        ConfidenceInRange(),
        LanguageMatches(),
    ]
    wrapped = [
        OnlineEvaluator(evaluator=ev, sample_rate=rate, max_concurrency=max_concurrency)
        for ev in evaluators
    ]
    return OnlineEvaluation(
        evaluators=wrapped,
        config=OnlineEvalConfig(default_sample_rate=rate, enabled=True),
    )
