"""V3-6 海报数据装配端点 GET /api/posters/data 测试。"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AIReport, GarminActivity, Workout


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
    from app.services import users as _us
    try:
        _us.create_user(session, username="alice", password="test-pass", role="user")
    except ValueError:
        pass  # alice 已由 conftest session 预建（id=1）
    _b = client.post("/api/auth/login", json={"username": "alice", "password": "test-pass"}).json()
    return {"Authorization": f"Bearer {_b['token']}"}


def _movements_json(movements):
    return json.dumps(movements, ensure_ascii=False)


def _strength_movements():
    return [
        {"name": "杠铃卧推", "sets": [
            {"weight": 60, "unit": "kg", "reps": 10, "done": True},
            {"weight": 65, "unit": "kg", "reps": 8, "done": True},
        ]},
        {"name": "哑铃划船", "sets": [
            {"weight": 30, "unit": "kg", "reps": 12, "done": True},
            {"weight": 30, "unit": "kg", "reps": 12, "done": True},
        ]},
        {"name": "坐姿推肩", "sets": [
            {"weight": 20, "unit": "kg", "reps": 10, "done": True},
        ]},
        {"name": "绳索下压", "sets": [
            {"weight": 15, "unit": "kg", "reps": 12, "done": True},
        ]},
    ]


def _make_report(session, workout=None, day=date(2026, 8, 3), score=88,
                 one_liner="今天状态火热，卧推破纪录！", subscores=None):
    if subscores is None and score is not None:
        subscores = {"completion": 90, "intensity": 85, "recovery_fit": 80}
    r = AIReport(
        user_id=1,
        type="session_review",
        workout_id=workout.id if workout else None,
        period_start=day,
        period_end=day,
        model="deepseek-chat",
        content_md="点评正文",
        score=score,
        one_liner=one_liner,
        subscores_json=json.dumps(subscores) if subscores else None,
    )
    session.add(r)
    session.commit()
    return r


class TestPosterDataAuth:
    def test_requires_auth(self, client):
        assert client.get("/api/posters/data?report_id=1").status_code == 401

    def test_report_not_found(self, client, auth):
        assert client.get("/api/posters/data?report_id=999", headers=auth).status_code == 404


class TestPosterDataStrength:
    """完整力量形态：评分 + 子分 + 亮点 top3 + PR 明细 + 本周计数。"""

    def test_full_strength_payload(self, client, auth, session):
        # 历史一次（上周），重量更低 → 本周卧推 65kg 构成 PR
        old = Workout(
            date=date(2026, 7, 27), title="胸", match_status="auto_matched",
            movements_json=_movements_json([
                {"name": "杠铃卧推", "sets": [{"weight": 55, "unit": "kg", "reps": 10, "done": True}]},
            ]),
        )
        session.add(old)
        # 本周较早两次训练（周一/周二），当前为周三 → 本周第 3 次
        session.add(Workout(date=date(2026, 8, 3), title="背", match_status="auto_matched"))
        session.add(Workout(date=date(2026, 8, 4), title="腿", match_status="auto_matched"))
        garmin = GarminActivity(
            activity_id="g-str", activity_type="strength_training", name="力量",
            duration_s=4020, calories=486, avg_hr=118, max_hr=152,
            raw_json=json.dumps({"summary": {"distance": 0.0}}),
        )
        session.add(garmin)
        session.commit()
        w = Workout(
            date=date(2026, 8, 5), title="胸部训练", match_status="auto_matched",
            garmin_activity_id=garmin.id,
            duration_s=4020, calories=486, avg_hr=118, max_hr=152,
            tags="strength_training",
            movements_json=_movements_json(_strength_movements()),
        )
        session.add(w)
        session.commit()
        report = _make_report(session, w, day=date(2026, 8, 5))

        resp = client.get(f"/api/posters/data?report_id={report.id}", headers=auth)
        assert resp.status_code == 200
        data = resp.json()

        # report 区
        rep = data["report"]
        assert rep["score"] == 88
        assert rep["subscores"] == {"completion": 90, "intensity": 85, "recovery_fit": 80}
        assert rep["one_liner"] == "今天状态火热，卧推破纪录！"
        assert rep["date"] == "2026-08-05"
        assert rep["workout_title"] == "胸部训练"

        # workout 区
        wo = data["workout"]
        assert wo["workout_kind"] == "strength"
        assert wo["duration_s"] == 4020
        assert wo["calories"] == 486
        assert wo["avg_hr"] == 118
        # 容量 = 60*10+65*8 + 30*12*2 + 20*10 + 15*12 = 1120+720+200+180 = 2220
        assert wo["volume_kg"] == 2220
        # 亮点 top3 按动作容量排序：哑铃划船720 > 杠铃卧推1120? 卧推1120 > 划船720 > 推肩200
        names = [h["name"] for h in wo["highlights"]]
        assert names == ["杠铃卧推", "哑铃划船", "坐姿推肩"]
        top = wo["highlights"][0]
        # 每动作最佳组：卧推最佳组为 65kg×8（容量 520 > 60*10=600? 600>520 → 60kg×10）
        assert top["weight"] == 60
        assert top["reps"] == 10
        assert top["unit"] == "kg"

        # PR 明细：卧推 65 > 历史 55；输出"动作名 重量 次数"
        assert data["prs"] == [{"movement": "杠铃卧推", "weight": 65, "unit": "kg", "reps": 8}]

        # 本周第 3 次训练
        assert data["week_count"] == 3


class TestPosterDataCardio:
    """有氧形态：movements 带 metrics，佳明带距离。"""

    def test_cardio_payload(self, client, auth, session):
        garmin = GarminActivity(
            activity_id="g-run", activity_type="running", name="晨跑",
            duration_s=2400, calories=320, avg_hr=145, max_hr=168,
            raw_json=json.dumps({"summary": {"distance": 5200.5}}),
        )
        session.add(garmin)
        session.commit()
        w = Workout(
            date=date(2026, 8, 5), title="跑步", match_status="auto_matched",
            garmin_activity_id=garmin.id,
            duration_s=2400, calories=320, avg_hr=145, max_hr=168,
            tags="running",
            movements_json=_movements_json([
                {"name": "跑步", "metrics": {"distance": 5200.5, "avgHeartRate": 145}},
            ]),
        )
        session.add(w)
        session.commit()
        report = _make_report(session, w, day=date(2026, 8, 5))

        resp = client.get(f"/api/posters/data?report_id={report.id}", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        wo = data["workout"]
        assert wo["workout_kind"] == "cardio"
        assert wo["highlights"] == []
        assert wo["distance_m"] == pytest.approx(5200.5)
        assert data["prs"] == []
        assert data["week_count"] == 1


class TestPosterDataMixed:
    def test_mixed_payload(self, client, auth, session):
        w = Workout(
            date=date(2026, 8, 5), title="综合训练", match_status="auto_matched",
            duration_s=3600, calories=400,
            movements_json=_movements_json([
                {"name": "杠铃深蹲", "sets": [{"weight": 80, "unit": "kg", "reps": 5, "done": True}]},
                {"name": "跑步机", "metrics": {"distance": 3000, "avgHeartRate": 138}},
            ]),
        )
        session.add(w)
        session.commit()
        report = _make_report(session, w, day=date(2026, 8, 5))

        resp = client.get(f"/api/posters/data?report_id={report.id}", headers=auth)
        assert resp.status_code == 200
        wo = resp.json()["workout"]
        assert wo["workout_kind"] == "mixed"
        # 混合形态亮点仅取力量动作
        assert [h["name"] for h in wo["highlights"]] == ["杠铃深蹲"]
        assert wo["distance_m"] == pytest.approx(3000)


class TestPosterDataDegraded:
    def test_no_score_report(self, client, auth, session):
        w = Workout(
            date=date(2026, 8, 5), title="背", match_status="auto_matched",
            movements_json=_movements_json(_strength_movements()),
        )
        session.add(w)
        session.commit()
        report = _make_report(session, w, day=date(2026, 8, 5),
                              score=None, one_liner=None, subscores=None)

        resp = client.get(f"/api/posters/data?report_id={report.id}", headers=auth)
        assert resp.status_code == 200
        rep = resp.json()["report"]
        assert rep["score"] is None
        assert rep["subscores"] is None
        assert rep["one_liner"] is None

    def test_report_without_workout(self, client, auth, session):
        report = _make_report(session, None)
        resp = client.get(f"/api/posters/data?report_id={report.id}", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["workout"] is None
        assert data["prs"] == []
        assert data["week_count"] is None
        # report 自身字段仍可用
        assert data["report"]["score"] == 88
        assert data["report"]["date"] == "2026-08-03"
        assert data["report"]["workout_title"] is None
