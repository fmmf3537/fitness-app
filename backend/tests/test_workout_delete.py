"""V3-11 训练删除（软删除 + 源墓碑防复活）与恢复测试。

覆盖：delete_workout/restore_workout 服务、同步 upsert 不复活、匹配器排除墓碑源、
API（DELETE /api/workouts/{id}、GET /api/workouts/deleted、POST /{id}/restore）、
日历/详情/趋势/AI 点评全链路排除已删除训练。
"""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import (
    AIReport,
    GarminActivity,
    MatchCandidate,
    ReportChatMessage,
    Workout,
    XunjiTrain,
)
from app.services.fuse import fuse_workout
from app.services.matcher import match_day
from app.services.workouts import delete_workout, list_deleted_workouts, restore_workout
from tests.conftest import make_garmin_activity, make_xunji_train

DAY = date(2026, 8, 16)


# ---------- 共享构造 ----------


def _matched_workout(session):
    """构造一对自动匹配的训记+佳明并跑 match_day，返回 (workout, train, activity)。"""
    train = make_xunji_train(session, DAY, localid="1", title="胸部训练")
    act = make_garmin_activity(session, DAY, activity_id="g1", name="力量训练")
    match_day(session, DAY, user_id=1)
    w = session.query(Workout).filter(Workout.date == DAY).one()
    return w, train, act


def _make_report(session, workout_id, rtype="session_review"):
    r = AIReport(
        user_id=1,
        type=rtype,
        workout_id=workout_id,
        period_start=DAY,
        period_end=DAY,
        model="fake",
        prompt_tokens=1,
        completion_tokens=1,
        cost_estimate=0.0,
        content_md="点评",
    )
    session.add(r)
    session.commit()
    return r


# ---------- 服务层：删除 ----------


def test_delete_marks_soft_delete_and_tombstones(session):
    """删除：workout 打 deleted_at，两侧源记录打 excluded 墓碑。"""
    w, train, act = _matched_workout(session)

    result = delete_workout(session, w.id, user_id=1)

    assert result is not None
    assert w.deleted_at is not None
    assert session.get(XunjiTrain, train.id).excluded is True
    assert session.get(GarminActivity, act.id).excluded is True


def test_delete_removes_session_reports_and_chat_keeps_weekly(session):
    """删除：关联 session_review/next_advice（及追问消息）清除，weekly 报告保留。"""
    w, _, _ = _matched_workout(session)
    review = _make_report(session, w.id, "session_review")
    advice = _make_report(session, w.id, "next_advice")
    weekly = _make_report(session, None, "weekly")
    chat = ReportChatMessage(report_id=review.id, role="user", content="追问")
    session.add(chat)
    session.commit()

    delete_workout(session, w.id, user_id=1)

    remaining = {r.type for r in session.query(AIReport).all()}
    assert remaining == {"weekly"}
    assert session.query(ReportChatMessage).count() == 0


def test_delete_cleans_match_candidates(session):
    """删除：关联 match_candidate 行清理。"""
    w, _, act = _matched_workout(session)
    session.add(MatchCandidate(
        user_id=1,
        workout_id=w.id, garmin_activity_id=act.id,
        reason="garmin_only_strength", status="pending",
    ))
    session.commit()

    delete_workout(session, w.id, user_id=1)

    assert session.query(MatchCandidate).count() == 0


def test_delete_idempotent(session):
    """幂等：重复删除不报错、不产生新状态。"""
    w, _, _ = _matched_workout(session)
    delete_workout(session, w.id, user_id=1)
    deleted_at = w.deleted_at

    again = delete_workout(session, w.id, user_id=1)

    assert again is not None
    assert again.deleted_at == deleted_at
    assert session.query(Workout).count() == 1


def test_delete_nonexistent_returns_none(session):
    assert delete_workout(session, 999, user_id=1) is None


# ---------- 服务层：恢复 ----------


def test_restore_clears_flags(session):
    """恢复：清 deleted_at 与两侧墓碑；不重建 AI 报告。"""
    w, train, act = _matched_workout(session)
    _make_report(session, w.id, "session_review")
    delete_workout(session, w.id, user_id=1)

    result = restore_workout(session, w.id, user_id=1)

    assert result is not None
    assert w.deleted_at is None
    assert session.get(XunjiTrain, train.id).excluded is False
    assert session.get(GarminActivity, act.id).excluded is False
    # AI 报告不自动重建
    assert session.query(AIReport).count() == 0


def test_restore_not_deleted_returns_none(session):
    w, _, _ = _matched_workout(session)
    assert restore_workout(session, w.id, user_id=1) is None
    assert restore_workout(session, 999, user_id=1) is None


# ---------- 防复活：同步 upsert / 匹配器 ----------


def test_garmin_upsert_skips_tombstoned(session):
    """佳明同步 upsert 同一 activity_id：excluded=True 时跳过更新、匹配不重建。"""
    from app.adapters.garmin_adapter import GarminClient

    w, _, act = _matched_workout(session)
    delete_workout(session, w.id, user_id=1)

    client = GarminClient(session)
    row = client._upsert_activity(
        {"activityId": act.activity_id, "activityName": "改名了",
         "activityType": {"typeKey": "running"},
         "startTimeLocal": "2026-08-16 10:00:00", "duration": 3600},
        None,
        None,
    )
    session.commit()

    assert row.name == "力量训练"  # 未被更新
    assert row.excluded is True
    # 即便硬删 workout 行，匹配器也不再用墓碑源重建
    session.delete(w)
    session.commit()
    match_day(session, DAY, user_id=1)
    assert session.query(Workout).count() == 0
    assert session.query(MatchCandidate).count() == 0


def test_xunji_upsert_skips_tombstoned(session):
    """训记缓存重拉 upsert 同一 datestr+localid：excluded=True 时跳过更新。"""
    from app.adapters.xunji import XunjiClient

    w, train, _ = _matched_workout(session)
    delete_workout(session, w.id, user_id=1)

    client = XunjiClient(session, api_key="k")
    row = client._upsert_train(DAY.isoformat(), {
        "localid": train.localid, "title": "改过的标题",
        "start": train.start_ms, "end": train.end_ms,
    })
    session.commit()

    assert row.title == "胸部训练"  # 未被更新
    assert row.excluded is True


def test_import_fit_file_skips_tombstoned(session, tmp_path):
    """同一文件重复导入：墓碑活动不更新、不触发重匹配重建 workout。"""
    from app.adapters.garmin_adapter import import_fit_file

    p = tmp_path / "run.gpx"
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        "<trk><name>晨跑</name><trkseg>"
        '<trkpt lat="39.9042" lon="116.4074"><time>2026-08-16T02:00:00Z</time></trkpt>'
        '<trkpt lat="39.9052" lon="116.4084"><time>2026-08-16T02:15:00Z</time></trkpt>'
        "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    first = import_fit_file(session, p, user_id=1)
    w = session.query(Workout).one()
    delete_workout(session, w.id, user_id=1)
    # 硬删 workout，模拟用户想彻底重来但又不让文件导入复活
    session.delete(w)
    session.commit()

    second = import_fit_file(session, p)

    assert second["activity"].excluded is True
    assert second["match"] is None
    assert session.query(Workout).count() == 0


def test_matcher_excludes_tombstoned_sources(session):
    """匹配器候选扫描直接排除 excluded 源（不等 _processed_ids 兜底）。"""
    train = make_xunji_train(session, DAY, localid="1")
    act = make_garmin_activity(session, DAY, activity_id="g1")
    train.excluded = True
    act.excluded = True
    session.commit()

    result = match_day(session, DAY, user_id=1)

    assert result["workouts"] == []
    assert result["candidates"] == []
    assert session.query(Workout).count() == 0


# ---------- 全链路排除：AI / 趋势 ----------


def test_run_daily_reviews_skips_deleted(session):
    """AI 单次点评：已删除训练不生成报告，未删除的正常生成。"""
    from app.services.ai import run_daily_reviews

    w1 = fuse_workout(session, DAY, xunji=make_xunji_train(session, DAY, localid="1"),
                       match_status="xunji_only")
    w2 = fuse_workout(session, DAY, xunji=make_xunji_train(session, DAY, localid="2"),
                      match_status="xunji_only")
    delete_workout(session, w1.id, user_id=1)

    chat_fn = lambda msgs: {"content": "点评", "prompt_tokens": 1,  # noqa: E731
                            "completion_tokens": 1, "model": "fake"}
    summary = run_daily_reviews(session, DAY, chat_fn=chat_fn)

    assert summary["generated"] == 1
    report = session.query(AIReport).one()
    assert report.workout_id == w2.id


# ---------- API 层 ----------


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
def auth(client, session):
    from app.services import users as _us
    try:
        _us.create_user(session, username="alice", password="test-pass", role="user")
    except ValueError:
        pass  # alice 已由 conftest session 预建（id=1）
    _b = client.post("/api/auth/login", json={"username": "alice", "password": "test-pass"}).json()
    return {"Authorization": f"Bearer {_b['token']}"}


def test_api_delete_hides_from_calendar_and_detail(client, auth, session):
    w, _, _ = _matched_workout(session)

    resp = client.delete(f"/api/workouts/{w.id}", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    cal = client.get("/api/workouts/calendar?month=2026-08", headers=auth).json()
    assert cal["days"] == []
    assert client.get(f"/api/workouts/{w.id}", headers=auth).status_code == 404


def test_api_deleted_list_and_restore(client, auth, session):
    w, _, _ = _matched_workout(session)
    client.delete(f"/api/workouts/{w.id}", headers=auth)

    listed = client.get("/api/workouts/deleted", headers=auth).json()["workouts"]
    assert len(listed) == 1
    assert listed[0]["id"] == w.id
    assert listed[0]["title"] == "胸部训练"
    assert listed[0]["deleted_at"]

    resp = client.post(f"/api/workouts/{w.id}/restore", headers=auth)
    assert resp.status_code == 200

    assert client.get("/api/workouts/deleted", headers=auth).json()["workouts"] == []
    cal = client.get("/api/workouts/calendar?month=2026-08", headers=auth).json()
    assert len(cal["days"]) == 1
    assert client.get(f"/api/workouts/{w.id}", headers=auth).status_code == 200


def test_api_delete_twice_still_200(client, auth, session):
    """幂等：重复 DELETE 返回 200，不报错也不产生新状态。"""
    w, _, _ = _matched_workout(session)
    assert client.delete(f"/api/workouts/{w.id}", headers=auth).status_code == 200
    assert client.delete(f"/api/workouts/{w.id}", headers=auth).status_code == 200
    assert len(client.get("/api/workouts/deleted", headers=auth).json()["workouts"]) == 1


def test_api_delete_404(client, auth):
    assert client.delete("/api/workouts/999", headers=auth).status_code == 404


def test_api_restore_404_when_not_deleted(client, auth, session):
    w, _, _ = _matched_workout(session)
    assert client.post(f"/api/workouts/{w.id}/restore", headers=auth).status_code == 404
    assert client.post("/api/workouts/999/restore", headers=auth).status_code == 404


def test_api_delete_unauthorized(client, session):
    w, _, _ = _matched_workout(session)
    assert client.delete(f"/api/workouts/{w.id}").status_code == 401
    assert client.get("/api/workouts/deleted").status_code == 401
    assert client.post(f"/api/workouts/{w.id}/restore").status_code == 401


def test_api_trends_excludes_deleted(client, auth, session):
    """趋势统计：已删除训练不计入周容量。"""
    from datetime import date as _date, timedelta

    today = _date.today()
    movements = [{"name": "卧推", "sets": [
        {"weight": 100, "unit": "kg", "reps": 10, "time": 0, "done": True},
    ]}]
    train1 = make_xunji_train(session, today, localid="1", movements=movements)
    train2 = make_xunji_train(session, today - timedelta(days=1), localid="2",
                              movements=movements)
    w1 = fuse_workout(session, today, xunji=train1, match_status="xunji_only")
    fuse_workout(session, today - timedelta(days=1), xunji=train2, match_status="xunji_only")
    delete_workout(session, w1.id, user_id=1)

    data = client.get("/api/stats/trends?weeks=4", headers=auth).json()
    total_sessions = sum(row["sessions"] for row in data["weekly_volume"])
    total_volume = sum(row["volume_tons"] for row in data["weekly_volume"])
    assert total_sessions == 1
    assert total_volume == pytest.approx(1.0, abs=0.01)
