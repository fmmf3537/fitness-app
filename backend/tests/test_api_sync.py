"""M5 同步触发 API 测试。"""
from datetime import date

from fastapi.testclient import TestClient

from app.api.sync import get_sync_fn
from app.db import get_session
from app.main import app


def test_trigger_sync_endpoint():
    received = {}

    def fake_sync(day, session=None):
        received["day"] = day
        received["session"] = session
        return {"date": day.isoformat(), "status": "success", "error": None,
                "detail": {"workouts": 0}}

    def fake_get_session():
        yield None

    app.dependency_overrides[get_sync_fn] = lambda: fake_sync
    app.dependency_overrides[get_session] = fake_get_session
    try:
        client = TestClient(app)
        resp = client.post("/api/sync/2026-08-03")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["date"] == "2026-08-03"
        assert received["day"] == date(2026, 8, 3)
    finally:
        app.dependency_overrides.clear()


def test_trigger_sync_invalid_date():
    client = TestClient(app)
    resp = client.post("/api/sync/not-a-date")
    assert resp.status_code == 422
