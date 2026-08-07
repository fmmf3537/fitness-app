"""V1-1/V2-1 LLM 设置 API 测试：GET/PUT /api/settings/llm。

PUT 时先调厂商轻量接口验证 Key 有效再保存；无效 Key 拒绝入库。
V2-1：Kimi 已接入；GET 返回各 provider 连续失败计数与建议备用模型；
PUT 支持不带 api_key 仅切换默认模型。
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
        assert by_name["kimi"]["implemented"] is True  # V2-1 已接入
        assert by_name["kimi"]["default_model"] == "kimi-k2.6"


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

    @respx.mock
    def test_kimi_key_accepted_after_v2_1(self, client, auth, session):
        respx.post("https://api.moonshot.cn/v1/chat/completions").mock(return_value=_ok_resp())
        resp = client.put(
            "/api/settings/llm",
            json={"provider": "kimi", "api_key": "sk-kimi-x"},
            headers=auth,
        )
        assert resp.status_code == 200

    def test_unknown_provider_rejected(self, client, auth):
        resp = client.put(
            "/api/settings/llm",
            json={"provider": "no-such", "api_key": "sk-x"},
            headers=auth,
        )
        assert resp.status_code == 400


# ---------- V2-1：仅切换默认模型（不重传 Key） ----------

class TestSwitchDefaultOnly:
    @respx.mock
    def test_switch_default_without_key(self, client, auth, session, monkeypatch):
        """已配置 Key 的 provider 可不带 api_key 直接设为默认。"""
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-env-minimax")
        get_settings.cache_clear()
        try:
            resp = client.put(
                "/api/settings/llm",
                json={"provider": "minimax", "api_key": "", "set_default": True},
                headers=auth,
            )
            assert resp.status_code == 200
            assert resp.json()["default_llm"] == "minimax"
        finally:
            get_settings.cache_clear()

    def test_switch_default_without_configured_key_rejected(self, client, auth, session, monkeypatch):
        """未配置 Key 的 provider 不允许设为默认。"""
        monkeypatch.delenv("KIMI_API_KEY", raising=False)  # 排除根目录 .env 真实 Key 干扰
        get_settings.cache_clear()
        try:
            resp = client.put(
                "/api/settings/llm",
                json={"provider": "kimi", "api_key": "", "set_default": True},
                headers=auth,
            )
            assert resp.status_code == 400
        finally:
            get_settings.cache_clear()

    def test_empty_key_without_set_default_rejected(self, client, auth):
        resp = client.put(
            "/api/settings/llm",
            json={"provider": "deepseek", "api_key": ""},
            headers=auth,
        )
        assert resp.status_code == 400


# ---------- V2-1：连续失败计数与备用模型建议 ----------

class TestFailureHealth:
    def test_get_includes_consecutive_failures_and_fallback(self, client, auth, session, monkeypatch):
        from app.models import LLMCall

        monkeypatch.setenv("MINIMAX_API_KEY", "sk-env-minimax")
        get_settings.cache_clear()
        try:
            session.add_all([
                LLMCall(provider="deepseek", model="deepseek-chat", status="ok"),
                LLMCall(provider="deepseek", model="deepseek-chat", status="error"),
                LLMCall(provider="deepseek", model="deepseek-chat", status="error"),
            ])
            session.commit()
            resp = client.get("/api/settings/llm", headers=auth)
            assert resp.status_code == 200
            data = resp.json()
            by_name = {p["name"]: p for p in data["providers"]}
            assert by_name["deepseek"]["consecutive_failures"] == 2
            assert by_name["minimax"]["consecutive_failures"] == 0
            # 默认 deepseek 连续失败 ≥2 时给出备用建议（其他已配置 Key 的 provider）
            assert data["suggested_fallback"] == "minimax"
        finally:
            get_settings.cache_clear()

    def test_no_fallback_when_nothing_else_configured(self, client, auth, session, monkeypatch):
        from app.models import LLMCall

        for k in ("MINIMAX_API_KEY", "KIMI_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        get_settings.cache_clear()
        try:
            session.add_all([
                LLMCall(provider="deepseek", model="m", status="error"),
                LLMCall(provider="deepseek", model="m", status="error"),
            ])
            session.commit()
            data = client.get("/api/settings/llm", headers=auth).json()
            assert data["suggested_fallback"] is None
        finally:
            get_settings.cache_clear()
