"""手动重新匹配：预览无副作用，确认后合并且不制造重复训练。"""
from datetime import date, datetime, time

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import MatchCandidate, Workout, WorkoutFeedback
from app.services.matcher import match_day
from app.services.rematch import RematchValidationError, confirm_rematch, preview_rematch
from tests.conftest import make_garmin_activity, make_xunji_train

DAY = date(2026, 8, 21)


def _two_singles(session, *, final_start=time(10, 0), final_end=time(11, 0)):
    train = make_xunji_train(session, DAY, localid="manual-x", title="胸部训练")
    match_day(session, DAY)
    x_workout = session.query(Workout).one()
    activity = make_garmin_activity(
        session, DAY, activity_id="manual-g",
        start=time(14, 0), end=time(15, 0),
    )
    match_day(session, DAY)
    g_workout = session.query(Workout).filter_by(match_status="garmin_only").one()
    candidate = session.query(MatchCandidate).one()
    activity.start_ts = datetime.combine(DAY, final_start)
    activity.end_ts = datetime.combine(DAY, final_end)
    session.commit()
    return x_workout, g_workout, train, activity, candidate


def test_preview_finds_best_xunji_single_without_writing(session):
    _, g_workout, _, _, _ = _two_singles(session)
    before_workouts = session.query(Workout).count()

    preview = preview_rematch(session, [g_workout.id])

    assert preview["action"] == "merge"
    assert preview["reason"] == "auto"
    assert preview["overlap_ratio"] == 1.0
    assert preview["xunji_train"]["title"] == "胸部训练"
    assert session.query(Workout).count() == before_workouts
    assert session.get(MatchCandidate, 1).status == "pending"


def test_confirm_merge_reuses_xunji_workout_and_resolves_candidate(session):
    x_workout, g_workout, train, activity, candidate = _two_singles(session)

    result = confirm_rematch(session, [g_workout.id, x_workout.id])

    assert result["action"] == "merge"
    assert result["workout_id"] == x_workout.id
    workouts = session.query(Workout).all()
    assert len(workouts) == 1
    assert workouts[0].id == x_workout.id
    assert workouts[0].match_status == "auto_matched"
    assert workouts[0].xunji_train_id == train.id
    assert workouts[0].garmin_activity_id == activity.id
    session.refresh(candidate)
    assert candidate.status == "merged"
    assert candidate.workout_id == x_workout.id


def test_confirm_time_close_replaces_single_candidate_with_two_sided_candidate(session):
    x_workout, g_workout, train, activity, candidate = _two_singles(
        session, final_start=time(10, 25), final_end=time(11, 30),
    )

    result = confirm_rematch(session, [x_workout.id, g_workout.id])

    assert result["action"] == "candidate"
    assert result["candidate_id"] == candidate.id
    assert session.query(Workout).count() == 1
    assert session.get(Workout, x_workout.id).match_status == "xunji_only"
    session.refresh(candidate)
    assert candidate.reason == "time_close"
    assert candidate.status == "pending"
    assert candidate.workout_id == x_workout.id
    assert candidate.xunji_train_id == train.id
    assert candidate.garmin_activity_id == activity.id


def test_unmatched_preview_has_no_confirm_action(session):
    _, g_workout, _, _, _ = _two_singles(
        session, final_start=time(14, 0), final_end=time(15, 0),
    )
    preview = preview_rematch(session, [g_workout.id])
    assert preview["action"] == "unmatched"
    with pytest.raises(RematchValidationError):
        confirm_rematch(session, [g_workout.id, g_workout.id])


def test_confirm_migrates_feedback_from_duplicate_workout(session):
    x_workout, g_workout, _, _, _ = _two_singles(session)
    session.add(WorkoutFeedback(workout_id=g_workout.id, note="训练后反馈"))
    session.commit()

    confirm_rematch(session, [x_workout.id, g_workout.id])

    feedback = session.get(WorkoutFeedback, x_workout.id)
    assert feedback is not None
    assert feedback.note == "训练后反馈"
    assert session.get(WorkoutFeedback, g_workout.id) is None


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


def test_rematch_api_preview_and_confirm(client, auth, session):
    x_workout, g_workout, _, _, _ = _two_singles(session)

    preview_resp = client.post(
        "/api/workouts/rematch/preview", json={"workout_ids": [g_workout.id]}, headers=auth,
    )
    assert preview_resp.status_code == 200
    preview = preview_resp.json()
    assert preview["action"] == "merge"

    confirm_resp = client.post(
        "/api/workouts/rematch",
        json={"workout_ids": [preview["xunji_workout_id"], preview["garmin_workout_id"]]},
        headers=auth,
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["workout_id"] == x_workout.id
    assert session.query(Workout).count() == 1


def test_late_time_close_candidate_merge_reuses_existing_workout(client, auth, session):
    train = make_xunji_train(session, DAY, localid="late-close-x")
    match_day(session, DAY)
    original = session.query(Workout).one()
    make_garmin_activity(
        session, DAY, activity_id="late-close-g",
        start=time(10, 25), end=time(11, 30), duration_s=3900,
    )
    match_day(session, DAY)
    candidate = session.query(MatchCandidate).one()

    resp = client.post(
        f"/api/match-candidates/{candidate.id}/resolve",
        json={"action": "merge"}, headers=auth,
    )

    assert resp.status_code == 200
    assert resp.json()["workout_ids"] == [original.id]
    assert session.query(Workout).count() == 1
    assert session.get(Workout, original.id).match_status == "manual_matched"
    assert session.get(Workout, original.id).xunji_train_id == train.id


def test_late_time_close_candidate_split_reuses_existing_workout(client, auth, session):
    make_xunji_train(session, DAY, localid="late-close-x")
    match_day(session, DAY)
    original = session.query(Workout).one()
    make_garmin_activity(
        session, DAY, activity_id="late-close-g",
        start=time(10, 25), end=time(11, 30), duration_s=3900,
    )
    match_day(session, DAY)
    candidate = session.query(MatchCandidate).one()

    resp = client.post(
        f"/api/match-candidates/{candidate.id}/resolve",
        json={"action": "split"}, headers=auth,
    )

    assert resp.status_code == 200
    assert len(resp.json()["workout_ids"]) == 2
    assert original.id in resp.json()["workout_ids"]
    assert session.query(Workout).count() == 2
    assert session.query(Workout).filter_by(match_status="xunji_only").one().id == original.id
