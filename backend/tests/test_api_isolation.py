"""M2-4 多用户隔离端到端测试：登录用户只能访问自己的数据。

覆盖：
- 未带 token 访问业务接口 → 401；
- 用户 A 创建的数据，用户 B 的列表/详情/删除访问不到（404 或空列表）；
- 带 token 访问自己的数据 → 200 且正确；
- settings / llm usage 按用户隔离。
"""
from datetime import date, timedelta
import json

import pytest
from fastapi.testclient import TestClient

from app.adapters import llm
from app.db import get_session
from app.main import app
from app.models import AIReport, LLMCall, MatchCandidate, Workout, XunjiPlan
from app.services import users as user_service
from app.services.fuse import fuse_workout
from tests.conftest import make_garmin_activity, make_xunji_train

DAY = date(2026, 8, 3)


@pytest.fixture
def client(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _login(client, session, username: str) -> tuple[int, dict]:
    """创建用户并登录，返回 (user_id, headers)。"""
    try:
        user = user_service.create_user(
            session, username=username, password="test-pass", role="user"
        )
    except ValueError:
        user = user_service.get_user_by_username(session, username)
        assert user is not None
    body = client.post(
        "/api/auth/login", json={"username": username, "password": "test-pass"}
    ).json()
    return user.id, {"Authorization": f"Bearer {body['token']}"}


@pytest.fixture
def user_a(client, session):
    return _login(client, session, "alice")


@pytest.fixture
def user_b(client, session):
    return _login(client, session, "bob")


# ---------- 未认证 → 401 ----------

@pytest.mark.parametrize("method,path", [
    ("GET", "/api/workouts/calendar?month=2026-08"),
    ("GET", "/api/workouts/deleted"),
    ("GET", "/api/match-candidates"),
    ("GET", "/api/settings/llm"),
    ("GET", "/api/settings/llm/usage"),
    ("GET", "/api/llm/monthly-usage"),
    ("GET", "/api/stats/trends"),
    ("GET", "/api/ai-reports"),
    ("GET", "/api/backfill/status"),
    ("GET", "/api/body-metrics"),
    ("GET", "/api/plans/upcoming"),
    ("GET", "/api/plans/refresh/status"),
    ("GET", "/api/posters/data?report_id=1"),
    ("GET", "/api/sync/status"),
])
def test_business_get_endpoints_require_auth(client, method, path):
    resp = client.request(method, path)
    assert resp.status_code == 401, f"{method} {path} 未带 token 应 401"


@pytest.mark.parametrize("method,path,json_body", [
    ("POST", "/api/body-metrics", {"date": "2026-08-03", "type": "weight", "value": 70.0}),
    ("POST", "/api/sync/2026-08-03", None),
    ("POST", "/api/backfill/start", None),
    ("POST", "/api/writeback/preview", {"datestr": "2026-08-03", "localid": 1, "changes": {}}),
    ("POST", "/api/screenshot/confirm", {"datestr": "2026-08-03", "title": "t", "movements": []}),
    ("PUT", "/api/settings/llm", {"provider": "kimi", "api_key": "x"}),
])
def test_business_write_endpoints_require_auth(client, method, path, json_body):
    resp = client.request(method, path, json=json_body)
    assert resp.status_code == 401, f"{method} {path} 未带 token 应 401"


# ---------- body_metrics 隔离 ----------

def test_body_metrics_isolation(client, session, user_a, user_b):
    uid_a, headers_a = user_a
    _, headers_b = user_b
    resp = client.post(
        "/api/body-metrics",
        json={"date": DAY.isoformat(), "type": "weight", "value": 70.5},
        headers=headers_a,
    )
    assert resp.status_code == 200
    metric_id = resp.json()["id"]

    # A 自己看得到
    rows = client.get("/api/body-metrics", headers=headers_a).json()["metrics"]
    assert [r["id"] for r in rows] == [metric_id]

    # B 看不到 A 的记录，也不能操作 A 的记录（sync-xunji → 404）
    assert client.get("/api/body-metrics", headers=headers_b).json()["metrics"] == []
    resp = client.post(
        f"/api/body-metrics/{metric_id}/sync-xunji",
        json={"confirmed": False},
        headers=headers_b,
    )
    assert resp.status_code == 404


# ---------- workouts 隔离 ----------

def _make_workout(session, user_id):
    train = make_xunji_train(session, DAY, user_id=user_id)
    activity = make_garmin_activity(session, DAY, user_id=user_id)
    return fuse_workout(session, DAY, xunji=train, garmin=activity,
                        match_status="auto_matched", user_id=user_id)


def test_workout_detail_and_calendar_isolation(client, session, user_a, user_b):
    uid_a, headers_a = user_a
    _, headers_b = user_b
    workout = _make_workout(session, uid_a)

    resp = client.get(f"/api/workouts/{workout.id}", headers=headers_a)
    assert resp.status_code == 200
    assert resp.json()["id"] == workout.id

    # B：详情 404，日历为空，删除/恢复 404
    assert client.get(f"/api/workouts/{workout.id}", headers=headers_b).status_code == 404
    cal = client.get(
        "/api/workouts/calendar", params={"month": "2026-08"}, headers=headers_b
    ).json()
    assert cal["days"] == []
    assert client.delete(f"/api/workouts/{workout.id}", headers=headers_b).status_code == 404
    assert client.post(
        f"/api/workouts/{workout.id}/restore", headers=headers_b
    ).status_code == 404

    # A 的日历包含该训练
    cal = client.get(
        "/api/workouts/calendar", params={"month": "2026-08"}, headers=headers_a
    ).json()
    assert [d["date"] for d in cal["days"]] == [DAY.isoformat()]


# ---------- ai_reports 隔离 ----------

def _make_report(session, user_id) -> AIReport:
    report = AIReport(
        user_id=user_id,
        type="weekly",
        period_start=DAY,
        period_end=DAY,
        model="m",
        content_md="# 报告",
    )
    session.add(report)
    session.commit()
    return report


def test_ai_reports_isolation(client, session, user_a, user_b):
    uid_a, headers_a = user_a
    _, headers_b = user_b
    report = _make_report(session, uid_a)

    assert client.get(f"/api/ai-reports/{report.id}", headers=headers_a).status_code == 200
    # B：详情 404、导出 404、消息列表 404、列表为空
    assert client.get(f"/api/ai-reports/{report.id}", headers=headers_b).status_code == 404
    assert client.get(
        f"/api/ai-reports/{report.id}/export", params={"format": "md"}, headers=headers_b
    ).status_code == 404
    assert client.get(
        f"/api/ai-reports/{report.id}/messages", headers=headers_b
    ).status_code == 404
    assert client.get("/api/ai-reports", headers=headers_b).json()["reports"] == []


# ---------- llm 用量隔离 ----------

def test_llm_usage_isolation(client, session, user_a, user_b):
    uid_a, headers_a = user_a
    _, headers_b = user_b
    session.add(LLMCall(
        user_id=uid_a, provider="kimi", model="k1", purpose="test",
        prompt_tokens=10, completion_tokens=5, cost_estimate=0.01,
    ))
    session.commit()

    usage_a = client.get("/api/llm/monthly-usage", headers=headers_a).json()
    assert usage_a["total_calls"] == 1
    usage_b = client.get("/api/llm/monthly-usage", headers=headers_b).json()
    assert usage_b["total_calls"] == 0
    assert usage_b["by_provider"] == []


# ---------- settings 隔离（每用户一行） ----------

def test_llm_settings_isolation(client, session, user_a, user_b, monkeypatch):
    _, headers_a = user_a
    _, headers_b = user_b
    monkeypatch.setattr(llm, "verify_api_key", lambda provider, key: True)

    resp = client.put(
        "/api/settings/llm",
        json={"provider": "kimi", "api_key": "sk-a-key", "set_default": True},
        headers=headers_a,
    )
    assert resp.status_code == 200

    providers_a = client.get("/api/settings/llm", headers=headers_a).json()["providers"]
    kimi_a = next(p for p in providers_a if p["name"] == "kimi")
    assert kimi_a["has_key"] is True

    # B 的设置行独立：未配置 kimi key
    providers_b = client.get("/api/settings/llm", headers=headers_b).json()["providers"]
    kimi_b = next(p for p in providers_b if p["name"] == "kimi")
    assert kimi_b["has_key"] is False


# ---------- 管理员 ?user_id= 代查看（M2-5） ----------

@pytest.fixture
def admin(client, session):
    """创建并登录一个管理员账号。"""
    try:
        user = user_service.create_user(
            session, username="admin", password="test-pass", role="admin"
        )
    except ValueError:
        user = user_service.get_user_by_username(session, "admin")
        assert user is not None
    body = client.post(
        "/api/auth/login", json={"username": "admin", "password": "test-pass"}
    ).json()
    return user.id, {"Authorization": f"Bearer {body['token']}"}


def _seed_user_a_data(client, session, uid_a, headers_a):
    """为 alice 造各表数据（以 alice 自身 token 写入，贴近真实路径）。"""
    today = date.today()
    workout = _make_workout(session, uid_a)
    workout.date = today  # 挪到今天，确保落在 stats 趋势窗口内
    session.commit()
    client.post(
        "/api/body-metrics",
        json={"date": today.isoformat(), "type": "weight", "value": 70.5},
        headers=headers_a,
    )
    session.add(AIReport(
        user_id=uid_a, type="weekly", period_start=today, period_end=today,
        model="m", content_md="# 报告",
    ))
    session.add(MatchCandidate(user_id=uid_a, status="pending", reason="待确认"))
    plan_json = json.dumps({
        "status": "active", "plan": {"name": "P"},
        "days": [{"date": today.isoformat(), "title": "推",
                  "movements": [{"name": "卧推", "target_sets": [{"reps": 8}]}]}],
    })
    session.add(XunjiPlan(
        user_id=uid_a, plan_ref="ref-admin", plan_json=plan_json,
        date_from=today, date_to=today,
    ))
    session.commit()
    return today


def test_admin_user_id_override_sees_target_data(client, session, user_a, admin):
    """管理员带 ?user_id=A 能看到 A 在每张个人数据表的数据。"""
    uid_a, headers_a = user_a
    _, headers_admin = admin
    today = _seed_user_a_data(client, session, uid_a, headers_a)
    month = today.strftime("%Y-%m")

    # 管理员不带 override 时只看自己（admin 无数据）→ 空（控制用例）
    own = client.get("/api/body-metrics", headers=headers_admin).json()
    assert own["metrics"] == []

    # 各表代查看
    cal = client.get(
        "/api/workouts/calendar", params={"month": month, "user_id": uid_a},
        headers=headers_admin,
    ).json()
    assert [d["date"] for d in cal["days"]] == [today.isoformat()]

    metrics = client.get(
        "/api/body-metrics", params={"user_id": uid_a}, headers=headers_admin
    ).json()
    assert [m["value"] for m in metrics["metrics"]] == [70.5]

    reports = client.get(
        "/api/ai-reports", params={"user_id": uid_a}, headers=headers_admin
    ).json()
    assert [r["type"] for r in reports["reports"]] == ["weekly"]

    candidates = client.get(
        "/api/match-candidates", params={"user_id": uid_a}, headers=headers_admin
    ).json()
    assert [c["status"] for c in candidates["candidates"]] == ["pending"]

    plans = client.get(
        "/api/plans/upcoming", params={"user_id": uid_a}, headers=headers_admin
    ).json()
    assert any(not d["is_rest"] for d in plans["days"])

    # stats：管理员代看 alice 应看到 alice 的训练容量（非空）；看自己则为空
    stats_self = client.get(
        "/api/stats/trends", params={"weeks": 4}, headers=headers_admin
    ).json()
    stats_alice = client.get(
        "/api/stats/trends", params={"weeks": 4, "user_id": uid_a},
        headers=headers_admin,
    ).json()
    assert any(b["sessions"] >= 1 for b in stats_alice["weekly_volume"])
    assert all(b["sessions"] == 0 for b in stats_self["weekly_volume"])


def test_non_admin_user_id_override_ignored(client, session, user_a, user_b):
    """普通用户传 ?user_id=A 越权被忽略，仅能看到自己的数据。"""
    uid_a, headers_a = user_a
    _, headers_b = user_b
    today = date.today()
    workout = _make_workout(session, uid_a)
    workout.date = today
    session.commit()
    client.post(
        "/api/body-metrics",
        json={"date": today.isoformat(), "type": "weight", "value": 70.5},
        headers=headers_a,
    )

    # bob 试图代看 alice → 被忽略，看到的是自己（空）
    cal = client.get(
        "/api/workouts/calendar", params={"month": today.strftime("%Y-%m"), "user_id": uid_a},
        headers=headers_b,
    ).json()
    assert cal["days"] == []

    metrics = client.get(
        "/api/body-metrics", params={"user_id": uid_a}, headers=headers_b
    ).json()
    assert metrics["metrics"] == []
