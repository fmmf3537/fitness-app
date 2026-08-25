"""M5 同步触发 API 测试 + V2-7 认证修复与异步化改造。

V2-7 契约：
- 未登录 POST /api/sync/{day} → 401 且不触发同步；GET /api/sync/status 同样要登录；
- POST 立即返回 {"status": "started"}，同步在后台线程执行；
- 同步运行中重复 POST → 409；
- GET /api/sync/status → running/status(success|failed)/result 摘要/error。
"""
import threading
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.sync import get_sync_manager
from app.main import app
from app.services.sync_manager import SyncManager


@pytest.fixture
def client(env_vars, monkeypatch, session):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings
    from app.db import get_session

    get_settings.cache_clear()

    def override_session():
        yield session

    calls = []
    gate = threading.Event()
    gate.set()  # 默认不阻塞
    flags = {"fail": False}

    def fake_sync(day, session=None, user_id=None):
        calls.append(day)
        gate.wait(timeout=5)
        if flags["fail"]:
            raise RuntimeError("garmin 429 too many requests")
        return {"date": day.isoformat(), "status": "success", "error": None,
                "detail": {"workouts": 2, "candidates": 1}}

    manager = SyncManager(sync_fn=fake_sync)
    app.dependency_overrides[get_sync_manager] = lambda: manager
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        c.sync_calls = calls
        c.gate = gate
        c.flags = flags
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def auth(client, session):
    from app.services import users as _us
    try:
        _us.create_user(session, username="alice", password="test-pass", role="user")
    except ValueError:
        pass  # alice 已由 conftest session 预建（id=1）
    _b = client.post("/api/auth/login", json={"username": "alice", "password": "test-pass"}).json()
    return {"Authorization": f"Bearer {_b['token']}"}


def wait_done(client, auth, timeout=5):
    """轮询 status 直到同步结束，返回最终状态体。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/api/sync/status", headers=auth).json()
        if not body["running"]:
            return body
        time.sleep(0.02)
    raise AssertionError("后台同步未在超时内结束")


# ---- 认证（先红后绿：修复前 401 用例必须失败） ----

def test_sync_requires_auth(client):
    """未登录调用 /api/sync/{day} 必须 401，且不触发同步（防公网烧 LLM 费用）。"""
    resp = client.post("/api/sync/2026-08-03")
    assert resp.status_code == 401
    assert client.sync_calls == []


def test_sync_status_requires_auth(client):
    resp = client.get("/api/sync/status")
    assert resp.status_code == 401


# ---- 异步化 ----

def test_trigger_sync_starts_background(client, auth):
    """POST 立即返回 started；后台线程真正执行同步；status 可查最终结果摘要。"""
    resp = client.post("/api/sync/2026-08-03", headers=auth)
    assert resp.status_code == 200
    assert resp.json() == {"status": "started", "date": "2026-08-03"}

    body = wait_done(client, auth)
    assert client.sync_calls == [date(2026, 8, 3)]
    assert body["status"] == "success"
    assert body["date"] == "2026-08-03"
    assert body["error"] is None
    assert body["result"]["detail"]["workouts"] == 2
    assert body["started_at"] is not None
    assert body["finished_at"] is not None


def test_duplicate_sync_returns_409(client, auth):
    """同步运行中重复触发 → 409，且不重复执行。"""
    client.gate.clear()  # 让第一次同步卡在后台
    resp = client.post("/api/sync/2026-08-03", headers=auth)
    assert resp.json()["status"] == "started"

    resp2 = client.post("/api/sync/2026-08-03", headers=auth)
    assert resp2.status_code == 409

    client.gate.set()
    wait_done(client, auth)
    assert client.sync_calls == [date(2026, 8, 3)]


def test_failed_sync_status(client, auth):
    """后台同步抛异常 → status 变 failed 并带错误信息（如佳明 429）。"""
    client.flags["fail"] = True
    client.post("/api/sync/2026-08-03", headers=auth)

    body = wait_done(client, auth)
    assert body["status"] == "failed"
    assert "429" in body["error"]


def test_status_never_run(client, auth):
    body = client.get("/api/sync/status", headers=auth).json()
    assert body == {"running": False, "status": None, "date": None,
                    "started_at": None, "finished_at": None,
                    "error": None, "result": None}


def test_trigger_sync_invalid_date(client, auth):
    resp = client.post("/api/sync/not-a-date", headers=auth)
    assert resp.status_code == 422
