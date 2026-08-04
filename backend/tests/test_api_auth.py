"""M6 登录口令 API 测试（含权限拒绝用例）。"""
import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings

    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_login_success_returns_token(client):
    resp = client.post("/api/auth/login", json={"password": "test-pass"})
    assert resp.status_code == 200
    assert resp.json()["token"]


def test_login_wrong_password_rejected(client):
    resp = client.post("/api/auth/login", json={"password": "wrong"})
    assert resp.status_code == 401


def test_login_rejected_when_password_not_configured(client, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "")
    from app.config import get_settings

    get_settings.cache_clear()
    resp = client.post("/api/auth/login", json={"password": "any"})
    assert resp.status_code == 503


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


def test_token_from_login_grants_access(client):
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    resp = client.get(
        "/api/workouts/calendar",
        params={"month": "2026-08"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
