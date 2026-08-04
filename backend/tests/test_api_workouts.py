"""M6 训练档案看板 API 测试：日历 + 详情（融合/训记原始/佳明原始 三标签数据）。"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.services.fuse import fuse_workout
from tests.conftest import make_garmin_activity, make_xunji_train

DAY = date(2026, 8, 3)


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings

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


MOVEMENTS = [{"name": "卧推", "sets": [
    {"weight": 60, "unit": "kg", "reps": 10, "time": 0, "done": True, "rpe": 8},
    {"weight": 60, "unit": "kg", "reps": 8, "time": 0, "done": True},
]}]

HR_DETAILS = {
    "metricDescriptors": [
        {"key": "directTimestamp", "index": 0},
        {"key": "directHeartRate", "index": 1},
    ],
    "activityDetailMetrics": [
        {"metrics": [1000, 110]},
        {"metrics": [2000, 125]},
        {"metrics": [3000, 140]},
    ],
}


def _make_fused(session, day=DAY, status="auto_matched"):
    train = make_xunji_train(session, day, movements=MOVEMENTS)
    activity = make_garmin_activity(session, day)
    activity.raw_json = json.dumps(
        {"summary": {"activityId": "g1"}, "details": HR_DETAILS, "exercise_sets": None},
        ensure_ascii=False,
    )
    session.commit()
    return fuse_workout(session, day, xunji=train, garmin=activity, match_status=status)


# ---------- GET /api/workouts/calendar ----------

def test_calendar_returns_workouts_of_month(client, auth, session):
    _make_fused(session)
    other_day = date(2026, 8, 15)
    train = make_xunji_train(session, other_day, localid="2")
    fuse_workout(session, other_day, xunji=train, match_status="xunji_only")
    # 不在本月的记录不应出现
    prev_month = date(2026, 7, 20)
    train2 = make_xunji_train(session, prev_month, localid="3")
    fuse_workout(session, prev_month, xunji=train2, match_status="xunji_only")

    resp = client.get("/api/workouts/calendar", params={"month": "2026-08"}, headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["month"] == "2026-08"
    days = {d["date"]: d for d in body["days"]}
    assert set(days) == {"2026-08-03", "2026-08-15"}
    assert days["2026-08-03"]["workouts"][0]["match_status"] == "auto_matched"
    assert days["2026-08-15"]["workouts"][0]["match_status"] == "xunji_only"
    assert days["2026-08-03"]["workouts"][0]["tags"] == "strength_training"


def test_calendar_empty_month(client, auth):
    resp = client.get("/api/workouts/calendar", params={"month": "2026-01"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["days"] == []


def test_calendar_invalid_month_format(client, auth):
    resp = client.get("/api/workouts/calendar", params={"month": "2026-8-3"}, headers=auth)
    assert resp.status_code == 422


def test_calendar_requires_auth(client):
    resp = client.get("/api/workouts/calendar", params={"month": "2026-08"})
    assert resp.status_code == 401


# ---------- GET /api/workouts/{id} ----------

def test_workout_detail_three_views(client, auth, session):
    workout = _make_fused(session)
    resp = client.get(f"/api/workouts/{workout.id}", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    # 融合视图：动作取训记，时长/热量/心率取佳明
    assert body["match_status"] == "auto_matched"
    assert body["duration_s"] == 3600 and body["calories"] == 300
    assert body["avg_hr"] == 120 and body["max_hr"] == 150
    assert body["movements"][0]["name"] == "卧推"
    assert body["movements"][0]["sets"][0]["rpe"] == 8
    # 心率曲线来自佳明 raw_json
    assert body["heart_rate"] == [
        {"t": 0, "hr": 110}, {"t": 1, "hr": 125}, {"t": 2, "hr": 140}
    ]
    # 原始视图
    assert body["xunji_raw"]["movements"][0]["name"] == "卧推"
    assert body["garmin_raw"]["details"]["metricDescriptors"][1]["key"] == "directHeartRate"


def test_workout_detail_xunji_only_has_no_garmin_view(client, auth, session):
    train = make_xunji_train(session, DAY, movements=MOVEMENTS)
    workout = fuse_workout(session, DAY, xunji=train, match_status="xunji_only")
    resp = client.get(f"/api/workouts/{workout.id}", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["garmin_raw"] is None
    assert body["heart_rate"] == []
    assert body["movements"][0]["name"] == "卧推"


def test_workout_detail_404(client, auth):
    resp = client.get("/api/workouts/9999", headers=auth)
    assert resp.status_code == 404


def test_workout_detail_requires_auth(client):
    resp = client.get("/api/workouts/1")
    assert resp.status_code == 401


# ---------- 心率序列提取兜底路径 ----------

def test_hr_fallback_plain_heart_key_list():
    from app.api.workouts import extract_heart_rate_series

    raw = json.dumps({"summary": {"heartRateSamples": [100, 105, 99]}})
    assert extract_heart_rate_series(raw) == [
        {"t": 0, "hr": 100}, {"t": 1, "hr": 105}, {"t": 2, "hr": 99}
    ]


def test_hr_extraction_tolerates_bad_json_and_missing_data():
    from app.api.workouts import extract_heart_rate_series

    assert extract_heart_rate_series(None) == []
    assert extract_heart_rate_series("not json") == []
    assert extract_heart_rate_series(json.dumps([1, 2])) == []
    assert extract_heart_rate_series(json.dumps({"details": {"foo": "bar"}})) == []
