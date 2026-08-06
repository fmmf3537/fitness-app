"""V1-1 LLM 设置 API 测试：GET/PUT /api/settings/llm。

PUT 时先调厂商轻量接口验证 Key 有效再保存；无效 Key 拒绝入库。
"""
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import decrypt_value, get_settings
from app.db import get_session
from app.main import app
from app.models import Setting

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


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
def auth(client):
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _ok_resp():
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "pong"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


class TestGetSettings:
    def test_requires_auth(self, client):
        assert client.get("/api/settings/llm").status_code == 401

    def test_get_returns_providers_without_keys(self, client, auth, session):
        resp = client.get("/api/settings/llm", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_llm"] == "deepseek"
        names = {p["name"] for p in data["providers"]}
        assert names == {"deepseek", "minimax", "kimi"}
        for p in data["providers"]:
            assert "api_key" not in p  # 永不回传明文 Key
            assert "has_key" in p
        by_name = {p["name"]: p for p in data["providers"]}
        assert by_name["deepseek"]["default_model"] == "deepseek-chat"
        assert by_name["minimax"]["default_model"] == "MiniMax-M2"
        assert by_name["kimi"]["implemented"] is False


class TestPutSettings:
    def test_requires_auth(self, client):
        resp = client.put("/api/settings/llm", json={"provider": "deepseek", "api_key": "sk-x"})
        assert resp.status_code == 401

    @respx.mock
    def test_valid_key_saved_encrypted(self, client, auth, session):
        respx.post(DEEPSEEK_URL).mock(return_value=_ok_resp())
        resp = client.put(
            "/api/settings/llm",
            json={"provider": "deepseek", "api_key": "sk-real-key"},
            headers=auth,
        )
        assert resp.status_code == 200
        row = session.scalars(__import__("sqlalchemy").select(Setting)).one()
        assert row.llm_keys_json_enc  # 已加密存储
        assert "sk-real-key" not in row.llm_keys_json_enc  # 非明文
        import json

        keys = json.loads(decrypt_value(row.llm_keys_json_enc))
        assert keys["deepseek"] == "sk-real-key"

    @respx.mock
    def test_invalid_key_rejected_not_saved(self, client, auth, session):
        respx.post(DEEPSEEK_URL).mock(
            return_value=httpx.Response(401, json={"error": "invalid key"})
        )
        resp = client.put(
            "/api/settings/llm",
            json={"provider": "deepseek", "api_key": "sk-bad"},
            headers=auth,
        )
        assert resp.status_code == 400
        assert session.scalars(__import__("sqlalchemy").select(Setting)).first() is None

    @respx.mock
    def test_set_default_provider(self, client, auth, session):
        respx.post(DEEPSEEK_URL).mock(return_value=_ok_resp())
        resp = client.put(
            "/api/settings/llm",
            json={"provider": "deepseek", "api_key": "sk-x", "set_default": True},
            headers=auth,
        )
        assert resp.status_code == 200
        assert client.get("/api/settings/llm", headers=auth).json()["default_llm"] == "deepseek"

    def test_kimi_stub_rejected(self, client, auth):
        resp = client.put(
            "/api/settings/llm",
            json={"provider": "kimi", "api_key": "sk-x"},
            headers=auth,
        )
        assert resp.status_code == 400

    def test_unknown_provider_rejected(self, client, auth):
        resp = client.put(
            "/api/settings/llm",
            json={"provider": "no-such", "api_key": "sk-x"},
            headers=auth,
        )
        assert resp.status_code == 400
