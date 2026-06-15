import json

from email_triage.schemas import Category
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_KEY

_PAYLOAD = {
    "subject": "I want a refund",
    "sender": "customer@test.com",
    "body": "I bought a product 3 days ago and want to return it.",
}

_AUTH = {"X-Api-Key": TEST_API_KEY}


def test_triage_happy_path_returns_valid_shape(client: TestClient) -> None:
    response = client.post("/triage", json=_PAYLOAD, headers=_AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["category"] in [c.value for c in Category]
    assert isinstance(data["draft_reply"], str) and len(data["draft_reply"]) > 0
    assert 0.0 <= data["confidence"] <= 1.0


def test_triage_no_api_key_returns_403(client: TestClient) -> None:
    response = client.post("/triage", json=_PAYLOAD)
    assert response.status_code == 403


def test_triage_wrong_api_key_returns_403(client: TestClient) -> None:
    response = client.post("/triage", json=_PAYLOAD, headers={"X-Api-Key": "wrong"})
    assert response.status_code == 403


def test_triage_invalid_body_returns_422(client: TestClient) -> None:
    response = client.post(
        "/triage", json={"subject": "", "sender": "bad", "body": ""}, headers=_AUTH
    )
    assert response.status_code == 422


def test_triage_llm_down_returns_503(failing_client: TestClient) -> None:
    response = failing_client.post("/triage", json=_PAYLOAD, headers=_AUTH)
    assert response.status_code == 503


def test_triage_stream_no_api_key_returns_403(client: TestClient) -> None:
    response = client.post("/triage/stream", json=_PAYLOAD)
    assert response.status_code == 403


def test_triage_stream_happy_path_emits_sse(streaming_client: TestClient) -> None:
    response = streaming_client.post("/triage/stream", json=_PAYLOAD, headers=_AUTH)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert "event: meta" in body
    assert "event: done" in body


def test_triage_stream_meta_before_data(streaming_client: TestClient) -> None:
    response = streaming_client.post("/triage/stream", json=_PAYLOAD, headers=_AUTH)
    assert response.status_code == 200
    body = response.text
    meta_pos = body.find("event: meta")
    first_data_pos = body.find("\ndata: ")
    assert meta_pos != -1, "event: meta not found"
    assert first_data_pos != -1, "data: chunk not found"
    assert meta_pos < first_data_pos, "event: meta must arrive before first data chunk"


def test_triage_stream_delta_reconstructs_full_reply(streaming_client: TestClient) -> None:
    response = streaming_client.post("/triage/stream", json=_PAYLOAD, headers=_AUTH)
    assert response.status_code == 200
    reconstructed = ""
    for line in response.text.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            decoded = json.loads(line[len("data: ") :])
            if isinstance(decoded, str):
                reconstructed += decoded
    assert reconstructed == "We will process your refund shortly."


def test_triage_stream_open_failure_returns_503(failing_stream_client: TestClient) -> None:
    response = failing_stream_client.post("/triage/stream", json=_PAYLOAD, headers=_AUTH)
    assert response.status_code == 503
