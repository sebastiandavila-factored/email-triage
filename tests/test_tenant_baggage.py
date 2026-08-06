"""Plan 33: tenant_id reaches every span of a /triage request.

- Both root spans (`triage.sync`, `triage.stream`) carry `tenant_id`.
- Child spans opened during the LLM call inherit it via OTel baggage → a per-org trace
  query (Plan 31) sees the whole tree, not just the root.

No DB here, so `tenant_id` resolves to the string ``"None"`` — we assert the attribute is
present (the wiring), not a specific tenant value."""

from typing import Any

import logfire
from email_triage.config import Settings
from email_triage.deps import get_settings, get_triage_service
from email_triage.main import app
from email_triage.schemas import Category, TriageRequest, TriageResponse
from email_triage.services.llm import LLMService
from fastapi.testclient import TestClient
from logfire.testing import CaptureLogfire

from tests.conftest import TEST_API_KEY

_PAYLOAD = {
    "subject": "I want a refund",
    "sender": "customer@test.com",
    "body": "I bought a product 3 days ago and want to return it.",
}
_AUTH = {"X-Api-Key": TEST_API_KEY}


def _completed_spans(cap: CaptureLogfire) -> list[dict[str, Any]]:
    return cap.exporter.exported_spans_as_dict()  # type: ignore[return-value]


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        groq_api_key="x", api_key=TEST_API_KEY, database_url=None, bcrypt_rounds=4
    )


class ChildSpanLLMService(LLMService):
    """LLM double that opens a child span inside triage(), to prove baggage propagation."""

    def __init__(self) -> None:
        pass

    async def triage(self, req: TriageRequest) -> TriageResponse:
        with logfire.span("llm.fake_call"):
            pass
        return TriageResponse(category=Category.REFUNDS, draft_reply="ok", confidence=0.9)


def test_sync_span_has_tenant_id(client: TestClient, capfire: CaptureLogfire) -> None:
    client.post("/triage", json=_PAYLOAD, headers=_AUTH)
    span = next(s for s in _completed_spans(capfire) if s["name"] == "triage.sync")
    assert "tenant_id" in span.get("attributes", {})


def test_stream_span_has_tenant_id(streaming_client: TestClient, capfire: CaptureLogfire) -> None:
    streaming_client.post("/triage/stream", json=_PAYLOAD, headers=_AUTH)
    span = next(s for s in _completed_spans(capfire) if s["name"] == "triage.stream")
    # Regression guard: this endpoint's span previously carried no tenant_id.
    assert "tenant_id" in span.get("attributes", {})


def test_baggage_propagates_tenant_to_child_span(capfire: CaptureLogfire) -> None:
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[get_triage_service] = ChildSpanLLMService
    try:
        with TestClient(app) as c:
            c.post("/triage", json=_PAYLOAD, headers=_AUTH)
    finally:
        app.dependency_overrides.clear()

    spans = _completed_spans(capfire)
    child = next(s for s in spans if s["name"] == "llm.fake_call")
    root = next(s for s in spans if s["name"] == "triage.sync")
    # The child span, opened inside the handler's set_baggage() scope, inherits tenant_id.
    assert "tenant_id" in child.get("attributes", {})
    assert child["attributes"]["tenant_id"] == root["attributes"]["tenant_id"]
