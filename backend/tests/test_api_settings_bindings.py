"""M3-4 绑定状态管理 API 测试：GET/POST/DELETE /api/settings/bindings*。

不触网：佳明 / 训记 / LLM 校验一律 monkeypatch；原有 test_api_settings_llm 不动。
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters import garmin_adapter, llm
from app.adapters.xunji import XunjiAPIError, XunjiClient
from app.config import decrypt_value, encrypt_value, get_settings
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
def alice_auth(client, session):
    try:
        user_service.create_user(session, username="alice", password="test-pass", role="user")
    except ValueError:
        pass
    body = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pass"}
    ).json()
    return {"Authorization": f"Bearer {body['token']}"}


@pytest.fixture
def bob_auth(client, session):
    try:
        user_service.create_user(session, username="bob", password="test-pass", role="user")
    except ValueError:
        pass
    body = client.post(
        "/api/auth/login", json={"username": "bob", "password": "test-pass"}
    ).json()
    return {"Authorization": f"Bearer {body['token']}"}


def _alice_id(session) -> int:
    return user_service.get_user_by_username(session, "alice").id


def _bob_id(session) -> int:
    return user_service.get_user_by_username(session, "bob").id


def _setting_for(session, user_id: int) -> Setting | None:
    return session.scalars(select(Setting).where(Setting.user_id == user_id)).first()


def _seed_full_bindings(session, user_id: int) -> Setting:
    """给用户写入 garmin / xunji / llm 全绑定（密文）。"""
    row = _setting_for(session, user_id)
    if row is None:
        row = Setting(user_id=user_id)
        session.add(row)
        session.flush()
    row.garmin_email_enc = encrypt_value("alice@example.com")
    row.garmin_password_enc = encrypt_value("secret-pass")
    row.garmin_token_store_enc = encrypt_value('{"oauth1":{},"oauth2":{},"domain":"garmin.cn"}')
    row.xunji_api_key_enc = encrypt_value("xj-key")
    row.xunji_body_api_key_enc = None
    row.llm_keys_json_enc = encrypt_value(
        json.dumps({"deepseek": "sk-ds", "kimi": "sk-kimi"}, ensure_ascii=False)
    )
    row.default_llm = "deepseek"
    session.commit()
    return row


# ---------- 未登录 ----------

class TestAuthRequired:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/settings/bindings"),
            ("post", "/api/settings/bindings/garmin"),
            ("post", "/api/settings/bindings/xunji"),
            ("post", "/api/settings/bindings/llm"),
            ("delete", "/api/settings/bindings/garmin"),
        ],
    )
    def test_unauthenticated_401(self, client, method, path):
        call = getattr(client, method)
        if method == "post":
            resp = call(path, json={})
        else:
            resp = call(path)
        assert resp.status_code == 401


# ---------- GET /bindings ----------

class TestGetBindings:
    def test_alice_fully_bound(self, client, alice_auth, session):
        _seed_full_bindings(session, _alice_id(session))
        resp = client.get("/api/settings/bindings", headers=alice_auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["garmin"]["bound"] is True
        assert data["garmin"]["has_token"] is True
        assert data["garmin"]["domain"] == "garmin.cn"
        assert data["xunji"]["bound"] is True
        assert data["xunji"]["body_bound"] is False
        assert data["llm"]["bound"] is True
        assert data["llm"]["default_provider"] == "deepseek"
        assert set(data["llm"]["providers"]) == {"deepseek", "kimi"}
        # 永不回传明文
        raw = resp.text
        assert "secret-pass" not in raw
        assert "sk-ds" not in raw
        assert "xj-key" not in raw

    def test_bob_unbound(self, client, bob_auth, session):
        resp = client.get("/api/settings/bindings", headers=bob_auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["garmin"]["bound"] is False
        assert data["garmin"]["has_token"] is False
        assert data["xunji"]["bound"] is False
        assert data["xunji"]["body_bound"] is False
        assert data["llm"]["bound"] is False
        assert data["llm"]["providers"] == []

    def test_alice_cannot_see_bob_bindings(self, client, alice_auth, bob_auth, session):
        _seed_full_bindings(session, _alice_id(session))
        # bob 自己看 → 未绑定
        bob_view = client.get("/api/settings/bindings", headers=bob_auth).json()
        assert bob_view["garmin"]["bound"] is False
        assert bob_view["llm"]["bound"] is False
        # alice 自己看 → 已绑定（只看自己）
        alice_view = client.get("/api/settings/bindings", headers=alice_auth).json()
        assert alice_view["garmin"]["bound"] is True


# ---------- POST /bindings/garmin ----------

class TestBindGarmin:
    def test_bad_credentials_401(self, client, alice_auth, monkeypatch):
        class BoomClient:
            def __init__(self, *a, **k):
                pass

            def _relogin(self):
                raise garmin_adapter.GarminAdapterError("bad creds")

        monkeypatch.setattr(garmin_adapter, "GarminClient", BoomClient)
        resp = client.post(
            "/api/settings/bindings/garmin",
            json={"email": "a@b.com", "password": "wrong"},
            headers=alice_auth,
        )
        assert resp.status_code == 401
        assert "wrong" not in resp.text

    def test_good_credentials_encrypted(self, client, alice_auth, session, monkeypatch):
        class OkClient:
            def __init__(self, *a, **k):
                pass

            def _relogin(self):
                return None

        monkeypatch.setattr(garmin_adapter, "GarminClient", OkClient)
        resp = client.post(
            "/api/settings/bindings/garmin",
            json={"email": "foo@example.com", "password": "plain-secret"},
            headers=alice_auth,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["email_masked"] == "f***@example.com"
        assert "plain-secret" not in resp.text
        assert "foo@example.com" not in resp.text

        row = _setting_for(session, _alice_id(session))
        assert row is not None
        assert row.garmin_email_enc
        assert "foo@example.com" not in row.garmin_email_enc
        assert decrypt_value(row.garmin_email_enc) == "foo@example.com"
        assert decrypt_value(row.garmin_password_enc) == "plain-secret"

    def test_missing_fields_422(self, client, alice_auth):
        resp = client.post(
            "/api/settings/bindings/garmin",
            json={"email": "a@b.com"},
            headers=alice_auth,
        )
        assert resp.status_code == 422


# ---------- POST /bindings/xunji ----------

class TestBindXunji:
    def test_bad_key_401(self, client, alice_auth, monkeypatch):
        def boom(self):
            raise XunjiAPIError("invalid key")

        monkeypatch.setattr(XunjiClient, "fetch_plan_list", boom)
        resp = client.post(
            "/api/settings/bindings/xunji",
            json={"api_key": "bad-key"},
            headers=alice_auth,
        )
        assert resp.status_code == 401
        assert "bad-key" not in resp.text

    def test_good_key_encrypted(self, client, alice_auth, session, monkeypatch):
        monkeypatch.setattr(XunjiClient, "fetch_plan_list", lambda self: [])
        resp = client.post(
            "/api/settings/bindings/xunji",
            json={"api_key": "xj-real-key", "body_api_key": "body-key"},
            headers=alice_auth,
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert "xj-real-key" not in resp.text

        row = _setting_for(session, _alice_id(session))
        assert decrypt_value(row.xunji_api_key_enc) == "xj-real-key"
        assert decrypt_value(row.xunji_body_api_key_enc) == "body-key"


# ---------- POST /bindings/llm ----------

class TestBindLlm:
    def test_unknown_provider_400(self, client, alice_auth):
        resp = client.post(
            "/api/settings/bindings/llm",
            json={"provider": "nope", "api_key": "sk-x"},
            headers=alice_auth,
        )
        assert resp.status_code == 400

    def test_bad_key_401(self, client, alice_auth, monkeypatch):
        monkeypatch.setattr(llm, "verify_api_key", lambda *a, **k: False)
        resp = client.post(
            "/api/settings/bindings/llm",
            json={"provider": "deepseek", "api_key": "sk-bad"},
            headers=alice_auth,
        )
        assert resp.status_code == 401
        assert "sk-bad" not in resp.text

    def test_good_key_preserves_others(self, client, alice_auth, session, monkeypatch):
        monkeypatch.setattr(llm, "verify_api_key", lambda *a, **k: True)
        r1 = client.post(
            "/api/settings/bindings/llm",
            json={"provider": "deepseek", "api_key": "sk-ds"},
            headers=alice_auth,
        )
        assert r1.status_code == 200
        assert r1.json() == {"ok": True, "provider": "deepseek"}

        r2 = client.post(
            "/api/settings/bindings/llm",
            json={"provider": "kimi", "api_key": "sk-kimi"},
            headers=alice_auth,
        )
        assert r2.status_code == 200

        bindings = client.get("/api/settings/bindings", headers=alice_auth).json()
        assert set(bindings["llm"]["providers"]) == {"deepseek", "kimi"}
        assert bindings["llm"]["bound"] is True

        keys = json.loads(
            decrypt_value(_setting_for(session, _alice_id(session)).llm_keys_json_enc)
        )
        assert keys["deepseek"] == "sk-ds"
        assert keys["kimi"] == "sk-kimi"


# ---------- DELETE /bindings/{type} ----------

class TestUnbind:
    def test_unbind_garmin_clears_all_enc(self, client, alice_auth, session):
        _seed_full_bindings(session, _alice_id(session))
        resp = client.delete("/api/settings/bindings/garmin", headers=alice_auth)
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "unbound": "garmin"}
        row = _setting_for(session, _alice_id(session))
        assert row.garmin_email_enc is None
        assert row.garmin_password_enc is None
        assert row.garmin_token_store_enc is None
        # 其它绑定不受影响
        assert row.xunji_api_key_enc is not None
        assert row.llm_keys_json_enc is not None

    def test_unbind_llm_provider_keeps_others(self, client, alice_auth, session):
        _seed_full_bindings(session, _alice_id(session))
        resp = client.delete(
            "/api/settings/bindings/llm",
            params={"provider": "kimi"},
            headers=alice_auth,
        )
        assert resp.status_code == 200
        assert resp.json()["unbound"] == "llm"
        keys = json.loads(
            decrypt_value(_setting_for(session, _alice_id(session)).llm_keys_json_enc)
        )
        assert "kimi" not in keys
        assert keys["deepseek"] == "sk-ds"


# ---------- 跨用户隔离 ----------

class TestCrossUserIsolation:
    def test_bob_get_does_not_see_alice_garmin(self, client, alice_auth, bob_auth, session):
        _seed_full_bindings(session, _alice_id(session))
        bob_view = client.get("/api/settings/bindings", headers=bob_auth).json()
        assert bob_view["garmin"]["bound"] is False
        assert bob_view["xunji"]["bound"] is False
        assert bob_view["llm"]["bound"] is False

    def test_bob_delete_does_not_affect_alice(self, client, alice_auth, bob_auth, session):
        _seed_full_bindings(session, _alice_id(session))
        resp = client.delete("/api/settings/bindings/garmin", headers=bob_auth)
        assert resp.status_code == 200
        # alice 的佳明仍在
        row = _setting_for(session, _alice_id(session))
        assert row.garmin_email_enc is not None
        assert row.garmin_password_enc is not None
        alice_view = client.get("/api/settings/bindings", headers=alice_auth).json()
        assert alice_view["garmin"]["bound"] is True
