"""M4-3 管理员健康面板 API 测试。"""
import pytest
from fastapi.testclient import TestClient

from app.config import encrypt_value, get_settings
from app.db import get_session
from app.main import app
from app.models import Setting
from app.services import users as user_service


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
def admin_headers(client, session):
    alice = user_service.get_user_by_username(session, "alice")
    alice.role = "admin"
    session.commit()
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pass"}
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def regular_headers(client, session):
    try:
        user_service.create_user(session, username="bob", password="test-pass")
    except ValueError:
        pass
    r = client.post(
        "/api/auth/login", json={"username": "bob", "password": "test-pass"}
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _setting(session, user_id: int, **fields) -> Setting:
    row = session.query(Setting).filter_by(user_id=user_id).first()
    if row is None:
        row = Setting(user_id=user_id)
        session.add(row)
        session.flush()
    for k, v in fields.items():
        setattr(row, k, v)
    session.commit()
    return row


class TestAdminHealthAuth:
    def test_unauthenticated_401(self, client):
        assert client.get("/api/admin/health").status_code == 401

    def test_non_admin_403(self, client, regular_headers):
        assert client.get("/api/admin/health", headers=regular_headers).status_code == 403


class TestAdminHealthPayload:
    def test_shape_and_db_size(self, client, admin_headers):
        resp = client.get("/api/admin/health", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data
        assert "system" in data
        assert "db_size_bytes" in data["system"]
        # SQLite 临时库应有 size 或显式 null
        assert data["system"]["db_size_bytes"] is None or isinstance(
            data["system"]["db_size_bytes"], int
        )
        assert data["system"]["scheduler_running"] is True
        assert "last_backup_at" in data["system"]

    def test_garmin_token_states(self, client, admin_headers, session):
        alice = user_service.get_user_by_username(session, "alice")
        bob = user_service.create_user(session, username="bob", password="test-pass")
        carol = user_service.create_user(session, username="carol", password="test-pass")
        dave = user_service.create_user(session, username="dave", password="test-pass")

        # alice: ok（有 token）
        _setting(
            session,
            alice.id,
            garmin_email_enc=encrypt_value("a@x.com"),
            garmin_password_enc=encrypt_value("pw"),
            garmin_token_store_enc=encrypt_value("{}"),
        )
        # bob: expired（有凭据无 token）
        _setting(
            session,
            bob.id,
            garmin_email_enc=encrypt_value("b@x.com"),
            garmin_password_enc=encrypt_value("pw"),
            garmin_token_store_enc=None,
        )
        # carol: missing（有 settings 行但无佳明字段）
        _setting(session, carol.id)
        # dave: n/a（无 settings 行）

        data = client.get("/api/admin/health", headers=admin_headers).json()
        by_name = {u["username"]: u for u in data["users"]}
        assert by_name["alice"]["garmin_token_state"] == "ok"
        assert by_name["bob"]["garmin_token_state"] == "expired"
        assert by_name["carol"]["garmin_token_state"] == "missing"
        assert by_name["dave"]["garmin_token_state"] == "n/a"
        for u in data["users"]:
            assert "monthly_llm_cost" in u
            assert "pending_match_count" in u
            assert "last_sync_at" in u
