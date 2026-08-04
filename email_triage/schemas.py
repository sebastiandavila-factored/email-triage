from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


class Category(StrEnum):
    STATUS = "status"
    REFUNDS = "refunds"
    AVAILABILITY = "availability"
    SHIPMENTS = "shipments"
    PRICES = "prices"


class TriageRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    sender: EmailStr
    body: str = Field(min_length=1, max_length=20_000)


class TriageResponse(BaseModel):
    category: Category
    draft_reply: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class StreamingTriageResponse(BaseModel):
    category: Category | None = None
    confidence: float | None = None
    draft_reply: str = ""


# ── Dynamic taxonomy (Triage Studio F2) ───────────────────────────────────────
# The legacy models above pin ``category`` to the frozen ``Category`` enum and stay
# in use on the no-DB path and in the offline evals. When a workspace defines its
# own categories the classification value is an arbitrary tenant slug, so the
# dynamic models widen ``category`` to ``str``. The allowed set is enforced by the
# compiled prompt plus a post-hoc coercion in ``LLMService`` (out-of-set → unknown).


class DynamicTriageResponse(BaseModel):
    category: str = Field(min_length=1)
    draft_reply: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class DynamicStreamingTriageResponse(BaseModel):
    category: str | None = None
    confidence: float | None = None
    draft_reply: str = ""


# What the router / persistence layer accept from either path.
AnyTriageResponse = TriageResponse | DynamicTriageResponse
AnyStreamingResponse = StreamingTriageResponse | DynamicStreamingTriageResponse
