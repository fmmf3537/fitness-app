"""GET /api/stats/trends API 测试。"""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import BodyMetric, GarminDaily, Workout


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


def _week_start(d: date) -> str:
    return (d - timedelta(days=d.weekday())).isoformat()


class TestStatsTrends:
    def test_requires_auth(self, client):
        assert client.get("/api/stats/trends").status_code == 401

    def test_invalid_weeks_returns_422(self, client, auth):
        assert client.get("/api/stats/trends?weeks=5", headers=auth).status_code == 422
        assert client.get("/api/stats/trends?weeks=abc", headers=auth).status_code == 422

    def test_empty_data(self, client, auth):
        resp = client.get("/api/stats/trends", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["weeks"] == 4
        assert len(data["weekly_volume"]) >= 4
        assert all(w["volume_tons"] == 0 and w["sessions"] == 0 for w in data["weekly_volume"])
        assert [w["week_start"] for w in data["body_part_frequency"]] == [
            w["week_start"] for w in data["weekly_volume"]
        ]
        assert all(b["parts"] == {} for b in data["body_part_frequency"])
        assert data["body_metrics"] == {"weight": [], "bodyfat": []}
        assert data["sleep_volume"] == []

    def test_weeks_12(self, client, auth):
        resp = client.get("/api/stats/trends?weeks=12", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["weeks"] == 12
        assert len(data["weekly_volume"]) >= 12

    def test_full_response(self, client, auth, session):
        today = date.today()
        last_week = today - timedelta(days=7)
        movements_today = [
            {"name": "杠铃卧推", "sets": [
                {"weight": 60, "unit": "kg", "reps": 10, "time": 0, "done": True},
                {"weight": 60, "unit": "kg", "reps": 8, "time": 0, "done": True},
            ]},
            {"name": "引体向上", "sets": [{"weight": 0, "unit": "kg", "reps": 8, "done": True}]},
        ]
        movements_last_week = [
            {"name": "杠铃深蹲", "sets": [{"weight": 100, "unit": "kg", "reps": 5, "done": True}]},
        ]
        session.add(Workout(date=today, title="胸", movements_json=json.dumps(movements_today, ensure_ascii=False)))
        session.add(Workout(date=last_week, title="腿", movements_json=json.dumps(movements_last_week, ensure_ascii=False)))
        session.add(BodyMetric(date=today, type="weight", value=72.4, unit="kg"))
        session.add(BodyMetric(date=today, type="bodyfat", value=18.2, unit="%"))
        session.add(GarminDaily(date=today, sleep_json=json.dumps({"sleepTimeSeconds": 25920})))
        session.commit()

        resp = client.get("/api/stats/trends?weeks=4", headers=auth)
        assert resp.status_code == 200
        data = resp.json()

        volume_by_week = {w["week_start"]: w for w in data["weekly_volume"]}
        this_week = volume_by_week[_week_start(today)]
        assert this_week["volume_tons"] == 1.08  # 600 + 480 kg
        assert this_week["sessions"] == 1
        prev_week = volume_by_week[_week_start(last_week)]
        assert prev_week["volume_tons"] == 0.5
        assert prev_week["sessions"] == 1

        parts_by_week = {b["week_start"]: b["parts"] for b in data["body_part_frequency"]}
        assert parts_by_week[_week_start(today)] == {"胸": 1, "背": 1}
        assert parts_by_week[_week_start(last_week)] == {"腿": 1}

        assert data["body_metrics"]["weight"] == [{"date": today.isoformat(), "value": 72.4}]
        assert data["body_metrics"]["bodyfat"] == [{"date": today.isoformat(), "value": 18.2}]

        assert data["sleep_volume"] == [
            {"date": today.isoformat(), "sleep_hours": 7.2, "volume_tons": 1.08}
        ]

    def test_out_of_range_data_excluded(self, client, auth, session):
        today = date.today()
        old_day = today - timedelta(days=29)  # 超出 4 周窗口
        session.add(Workout(
            date=old_day, title="旧训练",
            movements_json=json.dumps([{"name": "卧推", "sets": [{"weight": 100, "reps": 10, "done": True}]}]),
        ))
        session.add(BodyMetric(date=old_day, type="weight", value=99.9, unit="kg"))
        session.commit()

        resp = client.get("/api/stats/trends?weeks=4", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert all(w["sessions"] == 0 for w in data["weekly_volume"])
        assert data["body_metrics"]["weight"] == []
