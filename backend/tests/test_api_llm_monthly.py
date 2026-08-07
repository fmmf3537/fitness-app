"""V2-1 月度成本汇总 API 测试：GET /api/llm/monthly-usage（按 provider 分组）。"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import LLMCall


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


def _call(session, provider, model, created_at, cost=0.01, prompt=100, completion=50):
    row = LLMCall(
        provider=provider, model=model, purpose="test",
        prompt_tokens=prompt, completion_tokens=completion,
        cost_estimate=cost, status="ok",
    )
    session.add(row)
    session.flush()
    row.created_at = created_at  # server_default 后显式覆盖
    session.commit()
    return row


class TestMonthlyUsage:
    def test_requires_auth(self, client):
        assert client.get("/api/llm/monthly-usage").status_code == 401

    def test_invalid_month_422(self, client, auth):
        assert client.get("/api/llm/monthly-usage?month=2026-13", headers=auth).status_code == 422
        assert client.get("/api/llm/monthly-usage?month=bad", headers=auth).status_code == 422

    def test_empty_month(self, client, auth):
        resp = client.get("/api/llm/monthly-usage?month=2026-08", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["month"] == "2026-08"
        assert data["total_calls"] == 0
        assert data["total_cost"] == 0.0
        assert data["by_provider"] == []

    def test_grouped_by_provider_merges_models(self, client, auth, session):
        """同一 provider 下不同 model 合并为一行（与 settings/usage 的 provider+model 粒度区分）。"""
        _call(session, "kimi", "kimi-k2.6", datetime(2026, 8, 3), cost=0.10)
        _call(session, "kimi", "kimi-k3", datetime(2026, 8, 4), cost=0.20)
        _call(session, "deepseek", "deepseek-chat", datetime(2026, 8, 5), cost=0.05)
        resp = client.get("/api/llm/monthly-usage?month=2026-08", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 3
        assert data["total_cost"] == pytest.approx(0.35)
        rows = {r["provider"]: r for r in data["by_provider"]}
        assert set(rows) == {"kimi", "deepseek"}
        assert rows["kimi"]["calls"] == 2
        assert rows["kimi"]["prompt_tokens"] == 200
        assert rows["kimi"]["completion_tokens"] == 100
        assert rows["kimi"]["cost"] == pytest.approx(0.30)
        assert rows["deepseek"]["calls"] == 1

    def test_month_boundary_excluded(self, client, auth, session):
        _call(session, "kimi", "kimi-k2.6", datetime(2026, 7, 31, 23, 59))
        _call(session, "kimi", "kimi-k2.6", datetime(2026, 8, 1, 0, 0))
        resp = client.get("/api/llm/monthly-usage?month=2026-08", headers=auth)
        data = resp.json()
        assert data["total_calls"] == 1

    def test_default_current_month(self, client, auth, session):
        now = datetime.now()
        _call(session, "minimax", "MiniMax-M2", datetime(now.year, now.month, 1))
        resp = client.get("/api/llm/monthly-usage", headers=auth)
        data = resp.json()
        assert data["month"] == f"{now.year:04d}-{now.month:02d}"
        assert data["total_calls"] == 1
