"""T01 scenario 1 (now via the app factory): GET /api/health -> 200 ok."""

from fastapi.testclient import TestClient

from app.api.factory import create_app


def test_health_returns_ok():
    app = create_app(repo=None, manager=None, serve_static=False)
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
