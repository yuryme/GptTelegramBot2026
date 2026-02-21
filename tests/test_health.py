from fastapi.testclient import TestClient

from app.main import create_app


def test_healthcheck() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_rejects_invalid_secret() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/webhook/telegram", json={})

    assert response.status_code == 401

