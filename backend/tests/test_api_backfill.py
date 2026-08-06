"""V1-2 backfill API 测试：POST /api/backfill/start 与 GET /api/backfill/status。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


class FakeManager:
    """BackfillManager 桩：记录 start 调用次数，返回固定状态。"""

    def __init__(self):
        self.start_calls = 0
        self._running = False

    def start(self):
        self.start_calls += 1
        if self._running:
            return {"started": False, "message": "backfill 已在运行中"}
        self._running = True
        return {"started": True, "message": "backfill 已启动"}

    def status(self):
        return {
            "running": self._running,
            "phase": "xunji" if self._running else "idle",
            "percent": 1.5,
            "eta_seconds": 3600,
            "details": {"xunji": {"done": 3, "total": 1283}},
        }


@pytest.fixture
def client(env_vars):
    from app.api.backfill import get_backfill_manager

    manager = FakeManager()
    app.dependency_overrides[get_backfill_manager] = lambda: manager
    with TestClient(app) as c:
        c.manager = manager
        yield c
    app.dependency_overrides.clear()


def test_start_returns_started(client):
    resp = client.post("/api/backfill/start")
    assert resp.status_code == 200
    assert resp.json()["started"] is True
    assert client.manager.start_calls == 1


def test_start_twice_does_not_duplicate(client):
    client.post("/api/backfill/start")
    resp = client.post("/api/backfill/start")
    assert resp.json()["started"] is False
    assert client.manager.start_calls == 2


def test_status_returns_progress_json(client):
    client.post("/api/backfill/start")
    resp = client.get("/api/backfill/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is True
    assert data["phase"] == "xunji"
    assert data["percent"] == 1.5
    assert data["eta_seconds"] == 3600
    assert data["details"]["xunji"]["total"] == 1283
