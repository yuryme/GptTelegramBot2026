from fastapi.testclient import TestClient

from app.api import routes
from app.main import create_app


def test_healthcheck() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_behavior_depends_on_delivery_mode() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/webhook/telegram", json={})

    expected_status = 401 if routes.settings.telegram_delivery_mode == "webhook" else 409
    assert response.status_code == expected_status
