from fastapi.testclient import TestClient


def test_health_endpoint_returns_typed_status(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request"
    assert response.json() == {
        "status": "ok",
        "service": "a-stock-lab-backend",
        "version": "test",
        "generated_at": response.json()["generated_at"],
        "database": {"status": "available"},
    }
    assert response.json()["generated_at"].endswith("+08:00")
