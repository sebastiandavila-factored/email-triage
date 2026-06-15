from typing import Any
from unittest.mock import patch

from email_triage import observability
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


def test_auth_failure_increments_counter(client: TestClient, capfire: CaptureLogfire) -> None:
    with patch.object(observability.AUTH_FAILURES_TOTAL, "add") as mock_add:
        client.post("/triage", json=_PAYLOAD, headers={"X-Api-Key": "wrong-key"})
    mock_add.assert_called_once_with(1)


def test_llm_error_increments_errors_counter(
    failing_client: TestClient, capfire: CaptureLogfire
) -> None:
    with patch.object(observability.ERRORS_TOTAL, "add") as mock_add:
        failing_client.post("/triage", json=_PAYLOAD, headers=_AUTH)
    mock_add.assert_called_once()
    call_args = mock_add.call_args
    assert call_args.args[0] == 1
    assert call_args.args[1]["status_code"] == "503"


def test_successful_request_records_metrics(client: TestClient, capfire: CaptureLogfire) -> None:
    with (
        patch.object(observability.REQUESTS_TOTAL, "add") as mock_requests,
        patch.object(observability.CONFIDENCE, "record") as mock_conf,
        patch.object(observability.RESPONSE_DRAFT_CHARS, "record") as mock_draft,
        patch.object(observability.REQUEST_BODY_CHARS, "record") as mock_body,
    ):
        response = client.post("/triage", json=_PAYLOAD, headers=_AUTH)

    assert response.status_code == 200
    mock_requests.assert_called_once()
    assert mock_requests.call_args.args[0] == 1
    assert mock_requests.call_args.args[1]["endpoint"] == "sync"
    mock_conf.assert_called_once()
    mock_draft.assert_called_once()
    mock_body.assert_called_once_with(len(_PAYLOAD["body"]))


def test_sync_span_has_result_attributes(client: TestClient, capfire: CaptureLogfire) -> None:
    client.post("/triage", json=_PAYLOAD, headers=_AUTH)
    spans = _completed_spans(capfire)
    span_names = [s["name"] for s in spans]
    assert "triage.sync" in span_names, f"triage.sync not found in {span_names}"
    triage_span = next(s for s in spans if s["name"] == "triage.sync")
    attrs: dict[str, Any] = triage_span.get("attributes", {})
    assert attrs.get("endpoint") == "sync"
    assert "triage.result.category" in attrs
    assert "triage.result.confidence" in attrs


def test_stream_span_has_result_attributes(
    streaming_client: TestClient, capfire: CaptureLogfire
) -> None:
    streaming_client.post("/triage/stream", json=_PAYLOAD, headers=_AUTH)
    spans = _completed_spans(capfire)
    span_names = [s["name"] for s in spans]
    assert "triage.stream" in span_names, f"triage.stream not found in {span_names}"
    stream_span = next(s for s in spans if s["name"] == "triage.stream")
    attrs: dict[str, Any] = stream_span.get("attributes", {})
    assert attrs.get("endpoint") == "stream"
    assert "triage.result.category" in attrs
    assert "triage.result.confidence" in attrs
    assert "triage.stream.ttft_ms" in attrs
