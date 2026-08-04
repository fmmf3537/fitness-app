"""M6 待确认队列 API 测试：列表 + 合并/保持分开。"""
from datetime import date, time

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import MatchCandidate, Workout
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


def _make_time_close_candidate(session):
    """构造一对 time_close 待确认候选（训记 10:00-11:00 vs 佳明 10:20-11:20，重叠不足 60%）。"""
    train = make_xunji_train(session, DAY, localid="c1",
                             start=time(10, 0), end=time(11, 0))
    activity = make_garmin_activity(session, DAY, activity_id="gc1",
                                    start=time(10, 20), end=time(11, 20))
    candidate = MatchCandidate(
        xunji_train_id=train.id, garmin_activity_id=activity.id,
        reason="time_close", status="pending",
    )
    session.add(candidate)
    session.commit()
    return candidate


# ---------- GET /api/match-candidates ----------

def test_list_pending_candidates_with_both_sides(client, auth, session):
    candidate = _make_time_close_candidate(session)
    resp = client.get("/api/match-candidates", headers=auth)
    assert resp.status_code == 200
    items = resp.json()["candidates"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == candidate.id
    assert item["reason"] == "time_close"
    assert item["status"] == "pending"
    assert item["xunji_train"]["title"] == "训练"
    assert item["garmin_activity"]["name"] == "佳明活动"


def test_list_excludes_resolved_candidates(client, auth, session):
    candidate = _make_time_close_candidate(session)
    candidate.status = "merged"
    session.commit()
    resp = client.get("/api/match-candidates", headers=auth)
    assert resp.json()["candidates"] == []


def test_list_candidates_requires_auth(client):
    resp = client.get("/api/match-candidates")
    assert resp.status_code == 401


# ---------- POST /api/match-candidates/{id}/resolve ----------

def test_resolve_merge_creates_manual_matched_workout(client, auth, session):
    candidate = _make_time_close_candidate(session)
    resp = client.post(
        f"/api/match-candidates/{candidate.id}/resolve",
        json={"action": "merge"}, headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    session.expire_all()
    c = session.get(MatchCandidate, candidate.id)
    assert c.status == "merged"
    assert c.resolved_at is not None
    workout = session.get(Workout, body["workout_ids"][0])
    assert workout.match_status == "manual_matched"
    assert workout.xunji_train_id == c.xunji_train_id
    assert workout.garmin_activity_id == c.garmin_activity_id
    # 融合规则：时长取佳明
    assert workout.duration_s == 3600
    assert c.workout_id == workout.id


def test_resolve_split_creates_two_single_side_workouts(client, auth, session):
    candidate = _make_time_close_candidate(session)
    resp = client.post(
        f"/api/match-candidates/{candidate.id}/resolve",
        json={"action": "split"}, headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["workout_ids"]) == 2
    session.expire_all()
    statuses = sorted(
        session.get(Workout, wid).match_status for wid in body["workout_ids"]
    )
    assert statuses == ["garmin_only", "xunji_only"]
    assert session.get(MatchCandidate, candidate.id).status == "split"


def test_resolve_split_on_garmin_only_strength_keeps_existing_workout(client, auth, session):
    """佳明单边力量训练候选：保持分开 = 维持已有 garmin_only workout，仅关闭候选。"""
    activity = make_garmin_activity(session, DAY, activity_id="gs1")
    workout = fuse_workout(session, DAY, garmin=activity, match_status="garmin_only")
    candidate = MatchCandidate(
        workout_id=workout.id, garmin_activity_id=activity.id,
        reason="garmin_only_strength", status="pending",
    )
    session.add(candidate)
    session.commit()
    resp = client.post(
        f"/api/match-candidates/{candidate.id}/resolve",
        json={"action": "split"}, headers=auth,
    )
    assert resp.status_code == 200
    session.expire_all()
    assert session.get(MatchCandidate, candidate.id).status == "split"
    assert session.get(Workout, workout.id) is not None  # 原记录保留


def test_resolve_unknown_candidate_404(client, auth):
    resp = client.post(
        "/api/match-candidates/9999/resolve", json={"action": "merge"}, headers=auth
    )
    assert resp.status_code == 404


def test_resolve_already_resolved_409(client, auth, session):
    candidate = _make_time_close_candidate(session)
    candidate.status = "split"
    session.commit()
    resp = client.post(
        f"/api/match-candidates/{candidate.id}/resolve",
        json={"action": "merge"}, headers=auth,
    )
    assert resp.status_code == 409


def test_resolve_invalid_action_422(client, auth, session):
    candidate = _make_time_close_candidate(session)
    resp = client.post(
        f"/api/match-candidates/{candidate.id}/resolve",
        json={"action": "explode"}, headers=auth,
    )
    assert resp.status_code == 422


def test_resolve_requires_auth(client, session):
    candidate = _make_time_close_candidate(session)
    resp = client.post(
        f"/api/match-candidates/{candidate.id}/resolve", json={"action": "merge"}
    )
    assert resp.status_code == 401
