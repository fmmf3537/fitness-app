"""M4-2 管理员用户管理 API 测试。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AuthToken, User
from app.services import users as user_service
from app.utils.password import verify_password


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.fixture
def admin_user(session):
    alice = user_service.get_user_by_username(session, "alice")
    alice.role = "admin"
    session.commit()
    return alice


@pytest.fixture
def admin_headers(client, admin_user):
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pass"}
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def regular_headers(client, session):
    try:
        user_service.create_user(
            session, username="bob", password="test-pass", role="user"
        )
    except ValueError:
        pass
    r = client.post(
        "/api/auth/login", json={"username": "bob", "password": "test-pass"}
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestAdminUsersAuth:
    def test_unauthenticated_401(self, client):
        assert client.get("/api/admin/users").status_code == 401

    def test_non_admin_403(self, client, regular_headers):
        assert client.get("/api/admin/users", headers=regular_headers).status_code == 403


class TestAdminUsersCRUD:
    def test_list_users(self, client, admin_headers, session):
        user_service.create_user(session, username="bob", password="test-pass")
        resp = client.get("/api/admin/users", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        names = {u["username"] for u in data}
        assert "alice" in names
        assert "bob" in names
        for u in data:
            assert "bindings" in u
            assert "last_sync_at" in u
            assert "monthly_llm_cost" in u

    def test_create_user_201_and_duplicate_409(self, client, admin_headers):
        resp = client.post(
            "/api/admin/users",
            json={"username": "carol", "password": "secret1", "role": "user"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["username"] == "carol"

        dup = client.post(
            "/api/admin/users",
            json={"username": "carol", "password": "secret2"},
            headers=admin_headers,
        )
        assert dup.status_code == 409

    def test_deactivate_clears_tokens_not_self(self, client, admin_headers, admin_user, session):
        bob = user_service.create_user(session, username="bob", password="test-pass")
        # 给 bob 发一个 token
        login = client.post(
            "/api/auth/login", json={"username": "bob", "password": "test-pass"}
        ).json()
        assert "token" in login
        tokens_before = session.scalars(
            select(AuthToken).where(AuthToken.user_id == bob.id)
        ).all()
        assert len(tokens_before) >= 1

        resp = client.put(
            f"/api/admin/users/{bob.id}/deactivate", headers=admin_headers
        )
        assert resp.status_code == 200
        session.refresh(bob)
        assert bob.is_active is False
        tokens_after = session.scalars(
            select(AuthToken).where(AuthToken.user_id == bob.id)
        ).all()
        assert tokens_after == []

        # admin 自己仍 active
        session.refresh(admin_user)
        assert admin_user.is_active is True

    def test_activate(self, client, admin_headers, session):
        bob = user_service.create_user(
            session, username="bob", password="test-pass", is_active=False
        )
        resp = client.put(
            f"/api/admin/users/{bob.id}/activate", headers=admin_headers
        )
        assert resp.status_code == 200
        session.refresh(bob)
        assert bob.is_active is True

    def test_reset_password_clears_tokens(self, client, admin_headers, session):
        bob = user_service.create_user(session, username="bob", password="old-pass")
        client.post("/api/auth/login", json={"username": "bob", "password": "old-pass"})
        assert session.scalars(select(AuthToken).where(AuthToken.user_id == bob.id)).first()

        old_hash = bob.password_hash
        resp = client.put(
            f"/api/admin/users/{bob.id}/reset-password",
            json={"new_password": "new-pass-99"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        session.refresh(bob)
        assert bob.password_hash != old_hash
        assert verify_password("new-pass-99", bob.password_hash)
        assert session.scalars(select(AuthToken).where(AuthToken.user_id == bob.id)).all() == []

    def test_not_found_404(self, client, admin_headers):
        resp = client.put("/api/admin/users/999999/activate", headers=admin_headers)
        assert resp.status_code == 404
