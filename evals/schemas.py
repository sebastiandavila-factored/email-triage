from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field, model_validator

CategoryStr = Literal["status", "refunds", "availability", "shipments", "prices"]
LanguageStr = Literal["es", "en"]
DifficultyStr = Literal["easy", "medium", "hard"]
SourceStr = Literal["real", "synthetic"]


class CaseMeta(TypedDict):
    """Metadata attached to each ``pydantic_evals.Case``. Carries the ground-truth
    category (kept out of ``expected_output``, which is typed as the task output
    ``TriageResponse``) plus provenance fields used by the report breakdowns."""

    expected_category: CategoryStr
    language: LanguageStr
    difficulty: DifficultyStr
    notes: str
    source: SourceStr


class EvalCase(BaseModel):
    id: str
    subject: str
    sender: str
    body: str
    expected_category: CategoryStr
    language: LanguageStr
    difficulty: DifficultyStr
    # Provenance: required so a dataset row missing it is rejected at load time. All
    # current cases are hand-authored ("synthetic"); "real" awaits production data.
    source: SourceStr
    notes: str = ""
    provenance_note: str = ""


class JudgeScore(BaseModel):
    """Reply-quality scores. ``verdict="unknown"`` lets the judge abstain instead of
    inventing numbers when it cannot fairly assess; the numeric fields are then None and
    excluded from aggregate means (but counted in the unknown rate)."""

    verdict: Literal["assessable", "unknown"] = "assessable"
    relevance: int | None = Field(default=None, ge=1, le=5)
    language_match: bool | None = None
    tone: int | None = Field(default=None, ge=1, le=5)
    correctness: int | None = Field(default=None, ge=1, le=5)
    overall: int | None = Field(default=None, ge=1, le=5)
    reason: str = ""

    @model_validator(mode="after")
    def _assessable_requires_scores(self) -> JudgeScore:
        if self.verdict == "assessable" and None in (
            self.relevance,
            self.language_match,
            self.tone,
            self.correctness,
            self.overall,
        ):
            raise ValueError("an 'assessable' verdict requires all five scores")
        return self


class EvalResult(BaseModel):
    case: EvalCase
    predicted_category: str
    confidence: float
    draft_reply: str
    is_correct: bool
    judge_score: JudgeScore | None = None
    error: str | None = None
