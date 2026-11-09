"""模型真实可用性诊断、最新模型参数与价格测试。"""
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.llm import compute_cost, test_model_availability as check_model_availability
from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import LLMCall

KIMI_URL = "https://api.moonshot.cn/v1/chat/completions"
MINIMAX_URL = "https://api.minimaxi.com/v1/chat/completions"


def _ok(content="OK", finish_reason="stop"):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 5},
        },
    })


@pytest.fixture
def provider_keys(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "sk-test-kimi")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test-minimax")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestAvailabilityAdapter:
    @respx.mock
    def test_kimi_success_checks_content_usage_and_records_cost(self, session, provider_keys):
        route = respx.post(KIMI_URL).mock(return_value=_ok())
        result = check_model_availability(session, "kimi")
        assert result["ok"] is True
        assert result["code"] == "ok"
        assert result["content_preview"] == "OK"
        assert result["prompt_tokens"] == 20
        assert result["completion_tokens"] == 10
        assert result["cost_estimate"] > 0
        body = json.loads(route.calls.last.request.content)
        assert body["model"] == "kimi-k3.1-pro"
        assert body["max_completion_tokens"] == 256
        row = session.scalars(select(LLMCall)).one()
        assert row.purpose == "availability_test"
        assert row.status == "ok"

    @respx.mock
    def test_http_200_with_empty_truncated_content_is_not_available(self, session, provider_keys):
        respx.post(KIMI_URL).mock(return_value=_ok(content="", finish_reason="length"))
        result = check_model_availability(session, "kimi")
        assert result["ok"] is False
        assert result["code"] == "output_truncated"
        assert "输出额度" in result["message"]
        assert session.scalars(select(LLMCall)).all() == []

    @respx.mock
    def test_permission_error_is_actionable_and_does_not_leak_key(self, session, provider_keys):
        respx.post(KIMI_URL).mock(return_value=httpx.Response(
            403, json={"error": {"message": "model permission denied for sk-test-kimi"}},
        ))
        result = check_model_availability(session, "kimi")
        assert result["ok"] is False
        assert result["code"] == "permission_denied"
        assert result["http_status"] == 403
        assert "sk-test-kimi" not in result["detail"]
        assert "[已隐藏]" in result["detail"]

    @respx.mock
    def test_rate_limit_distinguishes_insufficient_balance(self, session, provider_keys):
        respx.post(KIMI_URL).mock(return_value=httpx.Response(
            429, json={"error": {"message": "insufficient balance"}},
        ))
        result = check_model_availability(session, "kimi")
        assert result["code"] == "insufficient_balance"

    def test_missing_key_has_specific_result(self, session, monkeypatch):
        for name in ("KIMI_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        get_settings.cache_clear()
        try:
            result = check_model_availability(session, "kimi")
            assert result["ok"] is False
            assert result["code"] == "missing_key"
        finally:
            get_settings.cache_clear()

    @respx.mock
    def test_minimax_m31_uses_completion_token_parameter(self, session, provider_keys):
        route = respx.post(MINIMAX_URL).mock(return_value=_ok())
        result = check_model_availability(session, "minimax", "MiniMax-M3.1-Flash")
        assert result["ok"] is True
        body = json.loads(route.calls.last.request.content)
        assert body["model"] == "MiniMax-M3.1-Flash"
        assert body["max_completion_tokens"] == 256
        assert "max_tokens" not in body


class TestLatestModelPrices:
    def test_deepseek_v4_peak_prices_and_cache(self):
        expected = (800 * 9 + 200 * 0.3 + 500 * 27) / 1_000_000
        assert compute_cost(
            "deepseek", 1000, 500, model="deepseek-v4-pro", cached_tokens=200,
        ) == pytest.approx(expected)

    def test_minimax_m3_long_input_uses_higher_tier(self):
        expected = (600_000 * 4.2 + 1000 * 16.8) / 1_000_000
        assert compute_cost(
            "minimax", 600_000, 1000, model="MiniMax-M3",
        ) == pytest.approx(expected)

    def test_minimax_flash_prices(self):
        assert compute_cost(
            "minimax", 1_000_000, 1_000_000, model="MiniMax-M3.1-Flash",
        ) == pytest.approx(5.0)


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    monkeypatch.setenv("KIMI_API_KEY", "sk-test-kimi")
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


class TestAvailabilityAPI:
    def test_requires_auth(self, client):
        resp = client.post("/api/settings/llm/test", json={"provider": "kimi"})
        assert resp.status_code == 401

    @respx.mock
    def test_returns_diagnostic_without_changing_selected_model(self, client, auth):
        respx.post(KIMI_URL).mock(return_value=_ok())
        resp = client.post(
            "/api/settings/llm/test",
            json={"provider": "kimi", "model": "kimi-k3"},
            headers=auth,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        settings = client.get("/api/settings/llm", headers=auth).json()
        kimi = next(p for p in settings["providers"] if p["name"] == "kimi")
        assert kimi["selected_model"] == "kimi-k3.1-pro"
        assert settings["default_llm"] == "deepseek"

    def test_unknown_model_returns_400(self, client, auth):
        resp = client.post(
            "/api/settings/llm/test",
            json={"provider": "kimi", "model": "retired-model"},
            headers=auth,
        )
        assert resp.status_code == 400
