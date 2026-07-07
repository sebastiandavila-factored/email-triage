"""Custom ``pydantic_evals`` evaluators for the triage task.

The judge is held in a module-level slot (``set_judge``) rather than as an evaluator
dataclass field: evaluator instances are serialized into an ``EvaluatorSpec`` for the
report, and we do not want a ``JudgeAgent`` (or its API key) embedded there.
"""

from __future__ import annotations

from dataclasses import dataclass

from email_triage.schemas import TriageRequest, TriageResponse
from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from pydantic_evals.reporting import ReportCase

from evals.judge import JudgeAgent
from evals.schemas import CaseMeta, JudgeScore

_judge: JudgeAgent | None = None


def set_judge(judge: JudgeAgent | None) -> None:
    """Install (or clear) the judge used by ``JudgeQuality``. Call before ``evaluate``."""
    global _judge
    _judge = judge


@dataclass
class CategoryCorrect(Evaluator[TriageRequest, TriageResponse, CaseMeta]):
    """Boolean assertion: predicted category == ground-truth category (from metadata)."""

    def evaluate(self, ctx: EvaluatorContext[TriageRequest, TriageResponse, CaseMeta]) -> bool:
        if ctx.metadata is None:
            return False
        return ctx.output.category.value == ctx.metadata["expected_category"]


@dataclass
class JudgeQuality(Evaluator[TriageRequest, TriageResponse, CaseMeta]):
    """Reply-quality scores from the reused ``JudgeAgent``. Numeric fields become
    report scores; ``language_match`` becomes a report assertion. No-op if no judge
    is installed."""

    async def evaluate(
        self, ctx: EvaluatorContext[TriageRequest, TriageResponse, CaseMeta]
    ) -> dict[str, int | bool | str]:
        if _judge is None:
            return {}
        score = await _judge.evaluate(ctx.inputs.subject, ctx.inputs.body, ctx.output.draft_reply)
        # An abstaining judge emits only the verdict label (no numeric scores), so the
        # case is counted in the unknown rate but excluded from quality means.
        if (
            score.verdict == "unknown"
            or score.relevance is None
            or score.tone is None
            or score.correctness is None
            or score.overall is None
            or score.language_match is None
        ):
            return {"judge_verdict": "unknown"}
        return {
            "judge_verdict": "assessable",
            "judge_relevance": score.relevance,
            "judge_tone": score.tone,
            "judge_correctness": score.correctness,
            "judge_overall": score.overall,
            "judge_language_match": score.language_match,
        }


def judge_score_from_case(
    rc: ReportCase[TriageRequest, TriageResponse, CaseMeta],
) -> JudgeScore | None:
    """Rebuild a ``JudgeScore`` from a report case's labels/scores/assertions, so the
    aggregate metrics in ``metrics.py`` keep working. Returns None when the judge did not
    run for this case; a ``JudgeScore(verdict="unknown")`` when it abstained."""
    verdict = rc.labels.get("judge_verdict")
    if verdict is None:
        return None
    if verdict.value == "unknown":
        return JudgeScore(verdict="unknown")
    return JudgeScore(
        verdict="assessable",
        relevance=int(rc.scores["judge_relevance"].value),
        tone=int(rc.scores["judge_tone"].value),
        correctness=int(rc.scores["judge_correctness"].value),
        overall=int(rc.scores["judge_overall"].value),
        language_match=bool(rc.assertions["judge_language_match"].value),
    )
