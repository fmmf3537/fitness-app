import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.training_insights import (ActionUpdate, FeedbackInput, GoalInput, add_goal,
    delete_feedback, get_actions, get_feedback, list_goals, plan_comparison,
    put_action, put_feedback, sync_receipt)
from app.models import AIReport, BodyMetric, JobRun, PlanSnapshot, Workout, XunjiPlan
from app.services.sync import sync_plan_cache
from app.services.ai import _training_feedback_lines


def test_training_routes_require_login_and_serve_persisted_data(session):
    from app.main import app
    from app.db import get_session
    from app.api.auth import require_auth

    app.dependency_overrides[get_session] = lambda: session
    try:
        with TestClient(app) as client:
            assert client.get("/api/training/sync-receipt").status_code == 401
            app.dependency_overrides[require_auth] = lambda: "test"
            assert client.get("/api/training/sync-receipt").json() == {"run": None}
            assert client.get("/api/training/goals").json() == {"goals": []}
    finally:
        app.dependency_overrides.clear()


def test_sync_receipt_uses_persisted_run_after_manager_reset(session):
    day = date.today()
    session.add(JobRun(job_name="daily_sync", started_at=datetime.now(), finished_at=datetime.now(),
                       status="success", detail_json=json.dumps({"date": day.isoformat(),
                       "xunji_trains": 1, "workout_changes": {"new": 1, "updated": 0, "unchanged": 0}})))
    session.add(Workout(date=day, title="力量训练", match_status="xunji_only"))
    session.commit()
    receipt = sync_receipt(session)["run"]
    assert receipt["changes"]["new"] == 1
    assert receipt["workouts"][0]["title"] == "力量训练"
    assert receipt["report_counts"]["session_review"] == 0


def test_plan_comparison_requires_snapshot_and_never_calls_missing_data_missed(session):
    day = date.today()
    workout = Workout(date=day, title="训练", movements_json=json.dumps([
        {"name": "深蹲", "sets": [{"done": True}, {"done": False}]},
        {"name": "划船", "sets": [{"done": True}]}], ensure_ascii=False))
    session.add(workout)
    session.commit()
    assert plan_comparison(day, session)["status"] == "no_snapshot"
    session.add(PlanSnapshot(date=day, plan_json=json.dumps({"date": day.isoformat(),
        "is_rest": False, "movements": [{"name": "深蹲", "target_sets": [{}, {}]}]}, ensure_ascii=False)))
    session.commit()
    result = plan_comparison(day, session)
    assert result["status"] == "compared"
    assert result["movements"][0]["status"] == "less"
    assert result["movements"][1]["status"] == "extra"


def test_action_state_and_follow_up_are_bound_to_report(session):
    today = date.today()
    source = Workout(date=today - timedelta(days=3), title="训练")
    later = Workout(date=today, title="后续训练", movements_json=json.dumps([
        {"name": "深蹲", "sets": [{"weight": 80, "reps": 5}]}], ensure_ascii=False))
    session.add_all([source, later]); session.commit()
    report = AIReport(type="next_advice", workout_id=source.id,
        content_md='```json\n{"schema":"next_advice_v1","suggestions":[{"movement":"深蹲","category":"manual","suggested":{"weight":80}}]}\n```')
    session.add(report); session.commit()
    assert get_actions(report.id, session)["actions"][0]["follow_up"]["date"] == today.isoformat()
    put_action(report.id, 0, ActionUpdate(status="done"), session)
    assert get_actions(report.id, session)["actions"][0]["status"] == "done"
    with pytest.raises(HTTPException):
        put_action(report.id, 1, ActionUpdate(status="done"), session)


def test_feedback_crud_and_goal_summary(session):
    workout = Workout(date=date.today(), title="训练")
    session.add(workout); session.commit()
    put_feedback(workout.id, FeedbackInput(fatigue=4, soreness=2, note="今天较累"), session)
    assert get_feedback(workout.id, session)["feedback"]["fatigue"] == 4
    assert "非设备测量" in _training_feedback_lines(session, workout.id)[0]
    delete_feedback(workout.id, session)
    assert get_feedback(workout.id, session)["feedback"] is None
    goal = add_goal(GoalInput(kind="sessions_week", target=3), session)
    assert goal["current"] == 1
    assert list_goals(session)["goals"][0]["target"] == 3
    with pytest.raises(HTTPException):
        add_goal(GoalInput(kind="sessions_week", target=3.5), session)


def test_body_weight_goal_uses_multiple_readings(session):
    today = date.today()
    session.add_all([BodyMetric(date=today, type="weight", value=70, unit="kg"),
                     BodyMetric(date=today-timedelta(days=1), type="weight", value=72, unit="kg")])
    session.commit()
    goal = add_goal(GoalInput(kind="body_weight", target=68), session)
    assert goal["current"] == 71
    assert goal["sufficient_data"] is True


def test_plan_refresh_saves_snapshot_without_overwriting_past_day(session):
    today = date.today()
    yesterday = today - timedelta(days=1)
    old = PlanSnapshot(date=yesterday, plan_json='{"old":true}')
    plan = XunjiPlan(plan_ref="p1", date_from=today, date_to=today + timedelta(days=7),
        plan_json=json.dumps({"name": "力量计划", "days": [{"date": today.isoformat(),
            "movements": [{"name": "深蹲", "target_sets": [{"reps": 5}]}]}]}, ensure_ascii=False))
    session.add_all([old, plan]); session.commit()

    class FakeXunji:
        def fetch_plan_list(self):
            return [plan]

        def fetch_plan(self, *_args):
            return plan

    result = sync_plan_cache(session=session, xunji=FakeXunji(), days_ahead=7)
    assert result["status"] == "success"
    assert plan_comparison(today, session)["status"] == "no_workout_data"
    assert session.get(PlanSnapshot, yesterday).plan_json == '{"old":true}'
