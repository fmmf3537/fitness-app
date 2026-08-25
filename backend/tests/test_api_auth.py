"""M2-3/M2-4 登录与认证依赖测试（多用户 username+password 令牌）。"""
import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user_id
from app.db import get_session
from app.main import app
from app.services import users as user_service


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings

    get_settings.cache_clear()

    def override_session():
        yield session

    # 本文件自管理认证 override：默认清掉 conftest 的 m2_user_override，
    # 以便真实校验 401/403 行为；需要「已登录」上下文的用例自行注入 token。
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides.pop(get_current_user_id, None)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def _create_and_login(client, session, username="alice", password="test-pass"):
    # alice 已由 conftest session 夹具预建（password=test-pass）；若已存在则忽略
    try:
        user_service.create_user(session, username=username, password=password)
    except ValueError:
        pass
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def test_login_success_returns_token(client, session):
    token = _create_and_login(client, session)
    assert token


def test_login_wrong_password_rejected(client, session):
    # alice 已由 conftest 预建；登录错误密码应被拒
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user_rejected(client):
    resp = client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    assert resp.status_code == 401


def test_protected_endpoint_without_token_rejected(client):
    resp = client.get("/api/workouts/calendar", params={"month": "2026-08"})
    assert resp.status_code == 401


def test_protected_endpoint_with_bad_token_rejected(client):
    resp = client.get(
        "/api/workouts/calendar",
        params={"month": "2026-08"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


def test_token_from_login_grants_access(client, session):
    token = _create_and_login(client, session)
    resp = client.get(
        "/api/workouts/calendar",
        params={"month": "2026-08"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
