"""V4-7 训练详情 API set_hr 键测试（参照 test_api_workouts.py 的 client/auth fixture 模式）。"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.services.fuse import fuse_workout
from tests.conftest import make_garmin_activity, make_xunji_train

DAY = date(2026, 8, 4)


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


# ---------- 完整 auto_matched：每组都有 set_hr 行 ----------

E2E_MOVEMENTS = [
    {
        "name": "深蹲",
        "sets": [
            {"weight": "60", "unit": "kg", "reps": "8", "done": True},
            {"weight": "60", "unit": "kg", "reps": "8", "done": True},
        ],
    },
    {
        "name": "卧推",
        "sets": [
            {"weight": "40", "unit": "kg", "reps": "10", "done": True},
            {"weight": "40", "unit": "kg", "reps": "10", "done": True},
        ],
    },
]


def _epoch_ms_to_iso(ms: int) -> str:
    from datetime import datetime
    sec = int(ms // 1000)
    msec = ms - sec * 1000
    base = datetime.utcfromtimestamp(sec).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{msec}"


def _build_full_raw() -> dict:
    """4 个 ACTIVE 组（SQUAT×2、BENCH_PRESS×2）+ 充足 HR 点 + 恢复点。"""
    starts_ms = [0, 40_000, 80_000, 120_000]
    durations_ms = [30_000, 30_000, 30_000, 30_000]
    categories = ["SQUAT", "SQUAT", "BENCH_PRESS", "BENCH_PRESS"]
    sets = []
    for st, dur, cat in zip(starts_ms, durations_ms, categories):
        sets.append({
            "setType": "ACTIVE",
            "startTime": _epoch_ms_to_iso(st),
            "duration": dur / 1000,
            "exercises": [{"category": cat, "probability": 80.0}],
            "repetitionCount": 5,
        })
    metrics = []
    for sec in range(0, 155):
        metrics.append({"metrics": [float(sec * 1000), float(100 + (sec % 5))]})
    metrics.append({"metrics": [60_000.0, 88.0]})
    metrics.append({"metrics": [61_000.0, 90.0]})
    return {
        "summary": {},
        "details": {
            "metricDescriptors": [
                {"metricsIndex": 0, "key": "directTimestamp"},
                {"metricsIndex": 1, "key": "directHeartRate"},
            ],
            "activityDetailMetrics": metrics,
        },
        "exercise_sets": {"activityId": 1, "exerciseSets": sets},
    }


def _make_auto_matched(session):
    train = make_xunji_train(session, DAY, movements=E2E_MOVEMENTS)
    activity = make_garmin_activity(session, DAY, activity_id="g_full")
    activity.raw_json = json.dumps(_build_full_raw(), ensure_ascii=False)
    session.commit()
    return fuse_workout(session, DAY, xunji=train, garmin=activity, match_status="auto_matched")


# ---------- 1. 详情返回 set_hr 键：完整数据 → 4 行 + 字段齐全 ----------

def test_workout_detail_returns_set_hr_for_auto_matched(client, auth, session):
    """auto_matched 带完整佳明数据 → set_hr 含每组 movement_name/set_index/hr_avg/hr_max/confidence。"""
    workout = _make_auto_matched(session)
    resp = client.get(f"/api/workouts/{workout.id}", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert "set_hr" in body
    rows = body["set_hr"]
    assert len(rows) == 4
    # 字段齐全（API 不返回 set_start/set_end）
    keys_seen = set()
    for r in rows:
        keys_seen.update(r.keys())
        assert {"movement_name", "set_index", "hr_avg", "hr_max",
                "hr_min", "hr_recovery_30s", "confidence"} <= set(r.keys())
    # 所有 confidence 应为 high（类别完全匹配）
    assert all(r["confidence"] == "high" for r in rows)
    # 数值非 None（窗口内有点）
    for r in rows:
        assert r["hr_avg"] is not None
        assert r["hr_max"] is not None
        assert r["hr_min"] is not None


def test_workout_detail_set_hr_low_confidence_on_category_mismatch(client, auth, session):
    """佳明首候选 BENCH_PRESS 对齐到训记"硬拉" → 该组 confidence=="low"。"""
    movements = [{"name": "硬拉", "sets": [{"weight": "60", "reps": "5", "done": True}]}]
    train = make_xunji_train(session, DAY, movements=movements)
    activity = make_garmin_activity(session, DAY, activity_id="g_mismatch")
    # 1 个 ACTIVE 组 (BENCH_PRESS)；1 个 REST 组
    sets = [
        {
            "setType": "ACTIVE",
            "startTime": _epoch_ms_to_iso(0),
            "duration": 30.0,
            "exercises": [{"category": "BENCH_PRESS", "probability": 80.0}],
            "repetitionCount": 5,
        },
    ]
    metrics = []
    for sec in range(0, 60):
        metrics.append({"metrics": [float(sec * 1000), float(110 + (sec % 3))]})
    raw = {
        "summary": {},
        "details": {
            "metricDescriptors": [
                {"metricsIndex": 0, "key": "directTimestamp"},
                {"metricsIndex": 1, "key": "directHeartRate"},
            ],
            "activityDetailMetrics": metrics,
        },
        "exercise_sets": {"activityId": 1, "exerciseSets": sets},
    }
    activity.raw_json = json.dumps(raw, ensure_ascii=False)
    session.commit()
    workout = fuse_workout(session, DAY, xunji=train, garmin=activity, match_status="auto_matched")

    resp = client.get(f"/api/workouts/{workout.id}", headers=auth)
    assert resp.status_code == 200
    rows = resp.json()["set_hr"]
    assert len(rows) == 1
    assert rows[0]["movement_name"] == "硬拉"
    assert rows[0]["confidence"] == "low"


# ---------- 2. 降级：garmin_only / 佳明无 exercise_sets → set_hr == []，响应仍 200 ----------

def test_workout_detail_set_hr_empty_for_garmin_only(client, auth, session):
    """garmin_only workout（无训记关联）→ set_hr == []。"""
    activity = make_garmin_activity(session, DAY, activity_id="g_only")
    activity.raw_json = json.dumps(_build_full_raw(), ensure_ascii=False)
    session.commit()
    workout = fuse_workout(session, DAY, garmin=activity, match_status="garmin_only")
    resp = client.get(f"/api/workouts/{workout.id}", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["set_hr"] == []


def test_workout_detail_set_hr_empty_when_no_exercise_sets(client, auth, session):
    """佳明 raw_json 无 exercise_sets → set_hr == []。"""
    train = make_xunji_train(session, DAY, movements=E2E_MOVEMENTS)
    activity = make_garmin_activity(session, DAY, activity_id="g_no_es")
    # 仅有 HR details，无 exercise_sets
    metrics = [{"metrics": [1000.0, 110.0]}, {"metrics": [2000.0, 115.0]}]
    activity.raw_json = json.dumps(
        {
            "summary": {},
            "details": {
                "metricDescriptors": [
                    {"metricsIndex": 0, "key": "directTimestamp"},
                    {"metricsIndex": 1, "key": "directHeartRate"},
                ],
                "activityDetailMetrics": metrics,
            },
            "exercise_sets": None,
        },
        ensure_ascii=False,
    )
    session.commit()
    workout = fuse_workout(session, DAY, xunji=train, garmin=activity, match_status="auto_matched")

    resp = client.get(f"/api/workouts/{workout.id}", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["set_hr"] == []


# ---------- 3. 懒计算幂等：同一 workout 连取两次，set_hr 内容一致 ----------

def test_workout_detail_set_hr_is_idempotent_across_requests(client, auth, session):
    """同一 workout 连取两次详情，set_hr 内容一致（第二次走 DB 缓存，行为等价）。"""
    workout = _make_auto_matched(session)
    resp1 = client.get(f"/api/workouts/{workout.id}", headers=auth)
    resp2 = client.get(f"/api/workouts/{workout.id}", headers=auth)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    body1 = resp1.json()["set_hr"]
    body2 = resp2.json()["set_hr"]
    assert body1 == body2
    assert len(body1) == 4