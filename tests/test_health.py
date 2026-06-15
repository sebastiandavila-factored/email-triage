from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_has_request_id_header(client: TestClient) -> None:
    response = client.get("/health")
    assert "x-request-id" in response.headers
