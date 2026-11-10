from fastapi.testclient import TestClient

from apps.api.main import app


def test_health_reports_db_down_without_crashing(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    body = TestClient(app).get("/health").json()
    assert body == {"status": "ok", "db": False}
