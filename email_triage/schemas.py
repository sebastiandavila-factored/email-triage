from datetime import datetime
from enum import StrEnum
from typing import Literal

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
    # OTel trace id (32 hex) of the span that produced this result, so the UI can
    # anchor the trace-debug chat (Plan 31) to this exact request. None on paths
    # that ran outside a recording span.
    trace_id: str | None = None


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
    trace_id: str | None = None  # see TriageResponse.trace_id (Plan 31)


class DynamicStreamingTriageResponse(BaseModel):
    category: str | None = None
    confidence: float | None = None
    draft_reply: str = ""


# What the router / persistence layer accept from either path.
AnyTriageResponse = TriageResponse | DynamicTriageResponse
AnyStreamingResponse = StreamingTriageResponse | DynamicStreamingTriageResponse


# ── Trace-debug chat (Plan 31) ────────────────────────────────────────────────


class TraceChatMessage(BaseModel):
    """One prior turn of the trace-debug conversation, replayed by the client."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


def _empty_history() -> list[TraceChatMessage]:
    return []


class TraceChatRequest(BaseModel):
    # 32-hex OTel trace id from a TriageResponse.trace_id; validated again server-side
    # before it ever reaches a query.
    trace_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2_000)
    history: list[TraceChatMessage] = Field(default_factory=_empty_history, max_length=20)


class TraceChatResponse(BaseModel):
    reply: str


# ── Gmail ingestion (Plan 37) ─────────────────────────────────────────────────


class GmailStatusResponse(BaseModel):
    connected: bool
    google_email: str | None = None
    last_synced_at: datetime | None = None


class InboxItem(BaseModel):
    """One of today's emails, already triaged. ``sender`` is the raw From header for
    display; the strict-email value used for classification is derived internally."""

    message_id: str
    sender: str
    subject: str
    received_at: datetime | None = None
    category: str
    confidence: float
    draft_reply: str
    trace_id: str | None = None


class SyncResponse(BaseModel):
    items: list[InboxItem]
    synced_at: datetime
