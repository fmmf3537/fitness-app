"""迟到数据补匹配：先到单边 workout 必须在另一侧补到后重新参与匹配。"""
from datetime import date, time

from app.models import MatchCandidate, Workout
from app.services.matcher import match_day
from tests.conftest import make_garmin_activity, make_xunji_train

DAY = date(2026, 8, 20)


def test_late_garmin_upgrades_existing_xunji_only_in_place(session):
    train = make_xunji_train(session, DAY, localid="late-x", title="胸部训练")
    match_day(session, DAY)
    initial = session.query(Workout).all()
    assert len(initial) == 1
    original = initial[0]
    assert original.match_status == "xunji_only"

    activity = make_garmin_activity(session, DAY, activity_id="late-g")
    result = match_day(session, DAY)

    workouts = session.query(Workout).all()
    assert len(workouts) == 1
    assert workouts[0].id == original.id
    assert workouts[0].match_status == "auto_matched"
    assert workouts[0].xunji_train_id == train.id
    assert workouts[0].garmin_activity_id == activity.id
    assert workouts[0].duration_s == 3600
    assert result["workouts"] == [workouts[0]]
    assert session.query(MatchCandidate).count() == 0


def test_late_xunji_upgrades_garmin_only_and_resolves_single_candidate(session):
    activity = make_garmin_activity(session, DAY, activity_id="late-g")
    match_day(session, DAY)
    original = session.query(Workout).one()
    candidate = session.query(MatchCandidate).one()
    assert original.match_status == "garmin_only"
    assert candidate.reason == "garmin_only_strength"

    train = make_xunji_train(session, DAY, localid="late-x", title="背部训练")
    match_day(session, DAY)

    workouts = session.query(Workout).all()
    assert len(workouts) == 1
    assert workouts[0].id == original.id
    assert workouts[0].match_status == "auto_matched"
    assert workouts[0].title == "背部训练"
    assert workouts[0].xunji_train_id == train.id
    assert workouts[0].garmin_activity_id == activity.id
    session.refresh(candidate)
    assert candidate.status == "merged"
    assert candidate.xunji_train_id == train.id
    assert candidate.garmin_activity_id == activity.id
    assert candidate.workout_id == original.id
    assert candidate.resolved_at is not None


def test_late_garmin_time_close_creates_two_sided_candidate_without_duplicate(session):
    train = make_xunji_train(session, DAY, localid="close-x")
    match_day(session, DAY)
    original = session.query(Workout).one()

    activity = make_garmin_activity(
        session, DAY, activity_id="close-g",
        start=time(10, 25), end=time(11, 30), duration_s=3900,
    )
    match_day(session, DAY)

    assert session.query(Workout).count() == 1
    assert original.match_status == "xunji_only"
    candidate = session.query(MatchCandidate).one()
    assert candidate.reason == "time_close"
    assert candidate.status == "pending"
    assert candidate.workout_id == original.id
    assert candidate.xunji_train_id == train.id
    assert candidate.garmin_activity_id == activity.id


def test_late_arrival_rematch_is_idempotent(session):
    make_xunji_train(session, DAY, localid="late-x")
    match_day(session, DAY)
    make_garmin_activity(session, DAY, activity_id="late-g")
    match_day(session, DAY)

    match_day(session, DAY)
    match_day(session, DAY)

    assert session.query(Workout).count() == 1
    assert session.query(MatchCandidate).count() == 0
