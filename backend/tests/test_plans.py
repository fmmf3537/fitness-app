"""V2-8 训练计划查询 API（/api/plans）测试。

覆盖：
- 计划缓存解析：get 结构（datestr + workout.movements + target_sets）与
  list 结构（date + movements）两种缓存、status=ended 计划剔除、休息日区分；
- GET /api/plans/upcoming：鉴权 401、逐日返回、休息日可区分；
- POST /api/plans/refresh：鉴权 401、202 后台执行、运行中 409、状态查询；
  全部 mock（fake xunji client / 注入 refresh_fn），零真实外呼。
"""
import json
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

import app.main  # noqa: F401  提前触发 app.config 加载（.env override=True），保证测试用 tmp 库
from app.models import XunjiPlan

FIXTURES = Path(__file__).resolve().parent / "fixtures"

START = date(2026, 8, 10)


def _make_plan(session, days, *, plan_ref="platform:155", plan_name="增肌计划",
               status=None, structure="get", date_from=None, date_to=None, user_id=1):
    """构造一行计划缓存。structure='get' 用 datestr+workout.movements+target_sets；
    structure='list' 用 date+movements（旧缓存结构）。"""
    if structure == "get":
        plan = {"plan_ref": plan_ref, "name": plan_name}
        if status:
            plan["status"] = status
        payload = {"plan": plan, "days": days}
    else:
        payload = {"plan_ref": plan_ref, "name": plan_name, "days": days}
        if status:
            payload["status"] = status
    row = XunjiPlan(
        plan_ref=plan_ref,
        plan_json=json.dumps(payload, ensure_ascii=False),
        date_from=date_from or (START - timedelta(days=7)),
        date_to=date_to or (START + timedelta(days=60)),
        user_id=user_id,
    )
    session.add(row)
    session.commit()
    return row


# ---------- 计划缓存解析（services/plans.py） ----------


class TestQueryPlanDays:
    def test_get_structure_normalizes_target_sets(self, session):
        from app.services.plans import query_plan_days

        _make_plan(session, days=[
            {"datestr": START.isoformat(), "workout": {"name": "胸·三头", "movements": [
                {"name": "杠铃卧推", "target_sets": [{"weight": 32.5, "unit": "kg", "reps": 6}]},
            ]}},
            {"datestr": (START + timedelta(days=1)).isoformat(), "workout": {"name": "休息", "movements": []}},
        ])

        days = query_plan_days(session, START, days=3)

        assert len(days) == 3
        first = days[0]
        assert first["date"] == START.isoformat()
        assert first["is_rest"] is False
        assert first["plan_ref"] == "platform:155"
        assert first["plan_name"] == "增肌计划"
        assert first["title"] == "胸·三头"
        assert first["movements"] == [
            {"name": "杠铃卧推", "target_sets": [{"weight": 32.5, "unit": "kg", "reps": 6}]}
        ]
        # 次日 movements 为空 → 休息日
        assert days[1]["is_rest"] is True
        assert days[1]["movements"] == []
        # 缓存中完全缺失的日期 → 休息日
        assert days[2]["is_rest"] is True

    def test_list_structure_supported(self, session):
        from app.services.plans import query_plan_days

        _make_plan(session, structure="list", days=[
            {"date": START.isoformat(),
             "movements": [{"name": "杠铃划船", "sets": [{"weight": 60, "reps": 10}]}]},
        ])

        days = query_plan_days(session, START, days=1)

        assert days[0]["is_rest"] is False
        assert days[0]["movements"][0]["name"] == "杠铃划船"
        assert days[0]["movements"][0]["target_sets"] == [{"weight": 60, "reps": 10}]

    def test_ended_plan_excluded(self, session):
        """status=ended 的计划（get/list 两种位置）不再呈现训练日。"""
        from app.services.plans import query_plan_days

        _make_plan(session, status="ended", days=[
            {"datestr": START.isoformat(), "workout": {"name": "胸", "movements": [
                {"name": "杠铃卧推", "target_sets": [{"weight": 32.5, "reps": 6}]},
            ]}},
        ])
        _make_plan(session, structure="list", status="ended", plan_ref="platform:156",
                   days=[
                       {"date": (START + timedelta(days=1)).isoformat(),
                        "movements": [{"name": "杠铃划船"}]},
                   ])

        days = query_plan_days(session, START, days=2)

        assert all(d["is_rest"] for d in days)

    def test_real_get_fixture(self, session):
        """真实 get 响应结构回归：datestr + workout.movements + target_sets。"""
        from app.services.plans import query_plan_days

        real = json.loads((FIXTURES / "plan_get_real.json").read_text(encoding="utf-8"))
        session.add(XunjiPlan(
            plan_ref="universal:1",
            plan_json=json.dumps(real, ensure_ascii=False),
            date_from=date(2026, 8, 7),
            date_to=date(2026, 9, 6),
        ))
        session.commit()

        days = query_plan_days(session, date(2026, 8, 7), days=1)

        assert days[0]["is_rest"] is False
        assert days[0]["movements"][0]["name"] == "杠铃卧推"
        assert days[0]["movements"][0]["target_sets"][0]["weight"] == 32.5

    def test_cache_range_filter(self, session):
        """缓存覆盖范围（date_from/date_to）外的日期不产出训练日。"""
        from app.services.plans import query_plan_days

        _make_plan(session, days=[
            {"datestr": START.isoformat(), "workout": {"name": "胸", "movements": [
                {"name": "杠铃卧推", "target_sets": []},
            ]}},
        ], date_to=START - timedelta(days=1))  # 缓存已过期

        days = query_plan_days(session, START, days=1)
        assert days[0]["is_rest"] is True


class TestQueryPlanDay:
    def test_returns_single_plan_day(self, session):
        from app.services.plans import query_plan_day

        _make_plan(session, days=[
            {"datestr": START.isoformat(), "workout": {"name": "背·二头", "movements": [
                {"name": "杠铃划船", "target_sets": [{"weight": 60, "reps": 10}]},
            ]}},
        ])

        plan_day = query_plan_day(session, START)

        assert plan_day is not None
        assert plan_day["date"] == START.isoformat()
        assert plan_day["plan_name"] == "增肌计划"
        assert plan_day["title"] == "背·二头"
        # 内部形态：target_sets 归一化为 sets（供 prompt 组装读取）
        assert plan_day["movements"][0]["sets"] == [{"weight": 60, "reps": 10}]

    def test_rest_day_returns_none(self, session):
        from app.services.plans import query_plan_day

        _make_plan(session, days=[
            {"datestr": START.isoformat(), "workout": {"name": "休息", "movements": []}},
        ])
        assert query_plan_day(session, START) is None

    def test_ended_plan_returns_none(self, session):
        from app.services.plans import query_plan_day

        _make_plan(session, status="ended", days=[
            {"datestr": START.isoformat(), "workout": {"name": "胸", "movements": [
                {"name": "杠铃卧推"},
            ]}},
        ])
        assert query_plan_day(session, START) is None


class TestPlanDaySkipReason:
    def test_empty_cache(self, session):
        from app.services.plans import plan_day_skip_reason

        reason = plan_day_skip_reason(session, START)
        assert "缓存为空" in reason

    def test_all_ended(self, session):
        from app.services.plans import plan_day_skip_reason

        _make_plan(session, status="ended", days=[])
        reason = plan_day_skip_reason(session, START)
        assert "ended" in reason

    def test_rest_day(self, session):
        from app.services.plans import plan_day_skip_reason

        _make_plan(session, days=[
            {"datestr": (START + timedelta(days=1)).isoformat(),
             "workout": {"name": "胸", "movements": [{"name": "杠铃卧推"}]}},
        ])
        reason = plan_day_skip_reason(session, START)
        assert START.isoformat() in reason
        assert "休息" in reason or "无计划" in reason


# ---------- API ----------


@pytest.fixture
def client(env_vars, session, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api.plans import get_plan_refresh_manager
    from app.config import get_settings
    from app.db import get_session
    from app.main import app

    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    get_settings.cache_clear()

    from app.api.plans import PlanRefreshManager

    calls = []
    gate = threading.Event()
    gate.set()
    flags = {"fail": False}

    def fake_refresh():
        calls.append("refresh")
        gate.wait(timeout=5)
        if flags["fail"]:
            raise RuntimeError("xunji too frequent")
        return {"status": "success", "error": None, "detail": {"plans": 1}}

    def override_session():
        yield session

    manager = PlanRefreshManager(refresh_fn=fake_refresh)
    app.dependency_overrides[get_plan_refresh_manager] = lambda: manager
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        c.refresh_calls = calls
        c.gate = gate
        c.flags = flags
        yield c
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


def _wait_refresh_done(client, auth, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/api/plans/refresh/status", headers=auth).json()
        if not body["running"]:
            return body
        time.sleep(0.02)
    raise AssertionError("后台计划刷新未在超时内结束")


class TestUpcomingAPI:
    def test_requires_auth(self, client):
        assert client.get("/api/plans/upcoming").status_code == 401

    def test_returns_upcoming_days(self, client, auth, session):
        today = date.today()
        _make_plan(session, date_from=today - timedelta(days=1),
                   date_to=today + timedelta(days=60), days=[
                       {"datestr": today.isoformat(), "workout": {"name": "胸·三头", "movements": [
                           {"name": "杠铃卧推",
                            "target_sets": [{"weight": 32.5, "unit": "kg", "reps": 6}]},
                       ]}},
                   ])

        resp = client.get("/api/plans/upcoming?days=7", headers=auth)

        assert resp.status_code == 200
        body = resp.json()
        assert body["from"] == today.isoformat()
        assert len(body["days"]) == 7
        assert body["days"][0]["is_rest"] is False
        assert body["days"][0]["movements"][0]["name"] == "杠铃卧推"
        assert body["days"][1]["is_rest"] is True


class TestRefreshAPI:
    def test_requires_auth(self, client):
        assert client.post("/api/plans/refresh").status_code == 401
        assert client.get("/api/plans/refresh/status").status_code == 401
        assert client.refresh_calls == []

    def test_refresh_starts_background(self, client, auth):
        resp = client.post("/api/plans/refresh", headers=auth)
        assert resp.status_code == 202
        assert resp.json()["status"] == "started"
        assert resp.json()["job"] == "plan_refresh"

        body = _wait_refresh_done(client, auth)
        assert client.refresh_calls == ["refresh"]
        assert body["status"] == "success"

    def test_duplicate_refresh_returns_409(self, client, auth):
        client.gate.clear()
        resp = client.post("/api/plans/refresh", headers=auth)
        assert resp.status_code == 202

        resp2 = client.post("/api/plans/refresh", headers=auth)
        assert resp2.status_code == 409

        client.gate.set()
        _wait_refresh_done(client, auth)
        assert client.refresh_calls == ["refresh"]

    def test_failed_refresh_status(self, client, auth):
        client.flags["fail"] = True
        client.post("/api/plans/refresh", headers=auth)

        body = _wait_refresh_done(client, auth)
        assert body["status"] == "failed"
        assert "too frequent" in body["error"]
