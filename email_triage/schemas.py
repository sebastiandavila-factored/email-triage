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
