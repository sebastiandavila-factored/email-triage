from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CategoryStr = Literal["status", "refunds", "availability", "shipments", "prices"]
LanguageStr = Literal["es", "en"]
DifficultyStr = Literal["easy", "medium", "hard"]


class EvalCase(BaseModel):
    id: str
    subject: str
    sender: str
    body: str
    expected_category: CategoryStr
    language: LanguageStr
    difficulty: DifficultyStr
    notes: str = ""


class JudgeScore(BaseModel):
    relevance: int = Field(ge=1, le=5)
    language_match: bool
    tone: int = Field(ge=1, le=5)
    correctness: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)


class EvalResult(BaseModel):
    case: EvalCase
    predicted_category: str
    confidence: float
    draft_reply: str
    is_correct: bool
    judge_score: JudgeScore | None = None
    error: str | None = None
