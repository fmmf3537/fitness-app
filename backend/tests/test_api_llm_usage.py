"""GET /api/settings/llm/usage API 测试。"""
from datetime import date, datetime

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


def _make_call(session, provider, model, created_at, prompt=100, completion=20, cost=0.001):
    row = LLMCall(
        provider=provider, model=model, purpose="test",
        prompt_tokens=prompt, completion_tokens=completion,
        cost_estimate=cost, status="ok", created_at=created_at,
    )
    session.add(row)
    session.commit()
    return row


class TestLLMUsage:
    def test_requires_auth(self, client):
        assert client.get("/api/settings/llm/usage").status_code == 401

    def test_invalid_month_returns_422(self, client, auth):
        for bad in ("2026-8", "2026-13", "abc", "2026/08"):
            resp = client.get(f"/api/settings/llm/usage?month={bad}", headers=auth)
            assert resp.status_code == 422, bad

    def test_empty_month(self, client, auth):
        resp = client.get("/api/settings/llm/usage?month=2026-08", headers=auth)
        assert resp.status_code == 200
        assert resp.json() == {
            "month": "2026-08",
            "total_calls": 0,
            "total_cost": 0.0,
            "by_provider": [],
        }

    def test_aggregates_by_provider_and_model(self, client, auth, session):
        _make_call(session, "deepseek", "deepseek-chat", datetime(2026, 8, 3, 10),
                   prompt=100, completion=20, cost=0.0012)
        _make_call(session, "deepseek", "deepseek-chat", datetime(2026, 8, 20, 9),
                   prompt=200, completion=40, cost=0.0022)
        _make_call(session, "qwen", "qwen-plus", datetime(2026, 8, 5, 8),
                   prompt=50, completion=10, cost=0.0005)
        _make_call(session, "deepseek", "deepseek-chat", datetime(2026, 7, 31, 23),
                   prompt=999, completion=999, cost=9.9)  # 上月，不计入

        resp = client.get("/api/settings/llm/usage?month=2026-08", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["month"] == "2026-08"
        assert data["total_calls"] == 3
        assert data["total_cost"] == round(0.0012 + 0.0022 + 0.0005, 4)
        by = {(p["provider"], p["model"]): p for p in data["by_provider"]}
        ds = by[("deepseek", "deepseek-chat")]
        assert ds["calls"] == 2
        assert ds["prompt_tokens"] == 300
        assert ds["completion_tokens"] == 60
        assert ds["cost"] == round(0.0012 + 0.0022, 4)
        qw = by[("qwen", "qwen-plus")]
        assert qw["calls"] == 1
        assert qw["cost"] == 0.0005

    def test_december_crosses_year_boundary(self, client, auth, session):
        _make_call(session, "deepseek", "deepseek-chat", datetime(2026, 12, 31, 23), cost=0.001)
        _make_call(session, "deepseek", "deepseek-chat", datetime(2027, 1, 1, 0), cost=9.9)
        resp = client.get("/api/settings/llm/usage?month=2026-12", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["month"] == "2026-12"
        assert data["total_calls"] == 1
        assert data["total_cost"] == 0.001

    def test_default_month_is_current(self, client, auth, session):
        now = datetime.now()
        _make_call(session, "deepseek", "deepseek-chat", now, cost=0.01)
        _make_call(session, "deepseek", "deepseek-chat", datetime(2020, 1, 15), cost=5.0)

        resp = client.get("/api/settings/llm/usage", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["month"] == date.today().strftime("%Y-%m")
        assert data["total_calls"] == 1
        assert data["total_cost"] == 0.01
