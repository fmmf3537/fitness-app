"""M5-2 排行榜 API 测试。"""
from datetime import date
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import Workout
from app.services import leaderboard as lb
from app.services import users as user_service

TODAY = date(2026, 8, 25)


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
def auth(client, session):
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pass"}
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestAuthAndValidation:
    def test_unauthenticated_401(self, client):
        resp = client.get("/api/leaderboard", params={"metric": "frequency", "window": "7d"})
        assert resp.status_code == 401

    def test_invalid_metric_422_or_400(self, client, auth):
        # FastAPI pattern → 422；若绕过 pattern 则为 400
        resp = client.get(
            "/api/leaderboard",
            params={"metric": "xxx", "window": "7d"},
            headers=auth,
        )
        assert resp.status_code in (400, 422)

    def test_invalid_window(self, client, auth):
        resp = client.get(
            "/api/leaderboard",
            params={"metric": "frequency", "window": "99d"},
            headers=auth,
        )
        assert resp.status_code in (400, 422)


class TestLeaderboardResponse:
    def test_live_compute(self, client, auth, session):
        alice = user_service.get_user_by_username(session, "alice")
        session.add(Workout(
            user_id=alice.id, date=TODAY, title="w",
            duration_s=3600, calories=300,
        ))
        session.commit()

        resp = client.get(
            "/api/leaderboard",
            params={"metric": "frequency", "window": "7d"},
            headers=auth,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["metric"] == "frequency"
        assert data["window"] == "7d"
        assert "entries" in data
        assert data["from_cache"] is False
        assert any(e["user_id"] == alice.id for e in data["entries"])

    def test_cache_hit_skips_recompute(self, client, auth, session, monkeypatch):
        lb.save_cached(
            session,
            "calories",
            "30d",
            [{"user_id": 1, "username": "alice", "value": 999, "rank": 1}],
        )
        spy = Mock(side_effect=AssertionError("should not recompute"))
        monkeypatch.setattr(lb, "compute_metric", spy)

        resp = client.get(
            "/api/leaderboard",
            params={"metric": "calories", "window": "30d"},
            headers=auth,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["from_cache"] is True
        assert data["entries"][0]["value"] == 999
        assert data["computed_at"] is not None
        spy.assert_not_called()
