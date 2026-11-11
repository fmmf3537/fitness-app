"""顺延确认、原对象改期与故障恢复；全部使用临时 SQLite + FakeGarmin。"""
import copy
import json
from datetime import date, datetime, timedelta

import pytest

import app.main  # noqa: F401
from app.adapters.garmin_workout_adapter import GarminWorkoutAdapterError
from app.models import GarminPlanSync, JobRun, XunjiPlan
from app.services.garmin_plan_sync import (
    PlanSyncError,
    claim_plan_sync,
    source_key_for,
    sync_status_view,
)
from app.services.garmin_reschedule import (
    claim_reschedule,
    detect_reschedule_candidates,
    list_reschedule_candidates,
    preview_reschedule,
    run_reschedule,
)
from app.services.garmin_workout_mapper import map_plan_day, source_hash

PLAN_REF = "platform:155"
OLD_DATE = date(2026, 11, 10)
TARGET_DATE = OLD_DATE + timedelta(days=1)


def _movement(weight=20):
    return {
        "name": "杠铃卧推",
        "rest_seconds": 60,
        "target_sets": [
            {"weight": weight, "unit": "kg", "reps": 8},
            {"weight": weight, "unit": "kg", "reps": 8},
        ],
    }


def _plan_day(day=OLD_DATE, *, weight=20):
    return {
        "plan_ref": PLAN_REF,
        "plan_name": "增肌计划",
        "date": day.isoformat(),
        "title": "胸部训练",
        "movements": [_movement(weight)],
    }


def _set_cache(session, plan_day):
    session.query(XunjiPlan).delete()
    day = date.fromisoformat(plan_day["date"])
    session.add(XunjiPlan(
        plan_ref=PLAN_REF,
        plan_json=json.dumps({
            "plan": {"plan_ref": PLAN_REF, "name": "增肌计划"},
            "days": [{
                "datestr": plan_day["date"],
                "workout": {
                    "name": plan_day["title"],
                    "movements": plan_day["movements"],
                },
            }],
        }, ensure_ascii=False),
        date_from=day - timedelta(days=1),
        date_to=day + timedelta(days=30),
        fetched_at=datetime.now(),
    ))
    session.commit()


def _add_synced_record(session, plan_day):
    preview = map_plan_day(plan_day)
    record = GarminPlanSync(
        plan_ref=PLAN_REF,
        training_date=date.fromisoformat(plan_day["date"]),
        source_key=preview["source_key"],
        source_hash=preview["source_hash"],
        content_hash=preview["content_hash"],
        synced_hash=preview["source_hash"],
        payload_json=json.dumps(preview["workout"], ensure_ascii=False),
        workout_id="workout-old",
        workout_schedule_id="schedule-old",
        status="synced",
        phase="verify",
        attempt_count=2,
        synced_at=datetime(2026, 11, 10, 12),
    )
    session.add(record)
    session.commit()
    return record


def _adapter_error(operation):
    return GarminWorkoutAdapterError(
        "INJECTED_FAILURE", "注入失败", operation=operation
    )


class FakeAdapter:
    def __init__(self, old_plan):
        payload = map_plan_day(old_plan)["workout"]
        self.workouts = {
            "workout-old": {**copy.deepcopy(payload), "workoutId": "workout-old"}
        }
        self.schedules = {
            "schedule-old": {
                "workoutScheduleId": "schedule-old",
                "calendarDate": old_plan["date"],
                "workout": {"workoutId": "workout-old"},
                "serverField": "preserve-me",
            }
        }
        self.calls = []
        self.lose_update_response = False
        self.lose_reschedule_response = False

    def get_workout(self, workout_id):
        self.calls.append("get_workout")
        return copy.deepcopy(self.workouts[workout_id])

    def update_workout(self, workout_id, payload):
        self.calls.append("update")
        self.workouts[workout_id] = {
            **copy.deepcopy(payload), "workoutId": workout_id
        }
        if self.lose_update_response:
            self.lose_update_response = False
            raise _adapter_error("update")

    def get_schedule(self, schedule_id):
        self.calls.append("get_schedule")
        return copy.deepcopy(self.schedules[schedule_id])

    def reschedule_schedule(self, schedule_id, training_date):
        self.calls.append("reschedule")
        day = training_date.isoformat()
        self.schedules[schedule_id]["calendarDate"] = day
        if self.lose_reschedule_response:
            self.lose_reschedule_response = False
            raise _adapter_error("reschedule")

    def create_workout(self, payload):
        self.calls.append("create")
        raise AssertionError("顺延禁止创建 Workout")

    def schedule_workout(self, workout_id, training_date):
        self.calls.append("schedule")
        raise AssertionError("顺延禁止创建日程")


def _prepare(session, *, target_weight=20):
    old_day = _plan_day()
    target_day = _plan_day(TARGET_DATE, weight=target_weight)
    record = _add_synced_record(session, old_day)
    _set_cache(session, target_day)
    detect_reschedule_candidates(session)
    assert record.status == "reschedule_pending"
    return record, target_day, FakeAdapter(old_day)


def _claim(session, target_day, *, enabled=True):
    return claim_reschedule(
        session,
        from_date=OLD_DATE,
        target_date=TARGET_DATE,
        expected_source_hash=source_hash(target_day),
        enabled=enabled,
    )


def test_preview_is_local_and_same_content_preserves_both_remote_ids(session, monkeypatch):
    record, target_day, adapter = _prepare(session)
    monkeypatch.setattr(
        GarminWorkoutAdapter := __import__(
            "app.adapters.garmin_workout_adapter", fromlist=["GarminWorkoutAdapter"]
        ).GarminWorkoutAdapter,
        "from_settings",
        lambda _: (_ for _ in ()).throw(AssertionError("预览不得外呼")),
    )

    preview = preview_reschedule(
        session, from_date=OLD_DATE, target_date=TARGET_DATE
    )
    assert preview["from_date"] == OLD_DATE.isoformat()
    assert preview["to_date"] == TARGET_DATE.isoformat()
    assert preview["source_hash"] == source_hash(target_day)
    assert preview["reschedule"]["workout_id"] == "workout-old"
    assert record.status == "reschedule_pending"
    assert record.attempt_count == 2
    assert adapter.calls == []

    claimed, started = _claim(session, target_day)
    assert started is True
    assert claimed.reschedule_from_date == OLD_DATE
    assert claimed.reschedule_source_key == source_key_for(PLAN_REF, OLD_DATE)
    run_reschedule(session, record.id, adapter=adapter)

    assert record.status == "synced"
    assert record.training_date == TARGET_DATE
    assert record.source_key == source_key_for(PLAN_REF, TARGET_DATE)
    assert record.synced_hash == source_hash(target_day)
    assert record.reschedule_from_date == OLD_DATE
    assert record.reschedule_to_date == TARGET_DATE
    assert record.workout_id == "workout-old"
    assert record.workout_schedule_id == "schedule-old"
    assert adapter.calls.count("update") == 1  # 名称和来源键包含新日期
    assert adapter.calls.count("reschedule") == 1
    assert adapter.calls.count("create") == 0
    assert adapter.calls.count("schedule") == 0
    assert adapter.schedules["schedule-old"]["serverField"] == "preserve-me"
    job = session.query(JobRun).filter_by(job_name="garmin_plan_reschedule").one()
    assert job.status == "synced"
    assert json.loads(job.detail_json)["from_date"] == OLD_DATE.isoformat()


def test_linked_target_content_change_updates_original_before_reschedule(session):
    record, _, adapter = _prepare(session)
    changed = _plan_day(TARGET_DATE, weight=22.5)
    _set_cache(session, changed)
    detect_reschedule_candidates(session)

    claimed, started = _claim(session, changed)
    assert started is True
    run_reschedule(session, claimed.id, adapter=adapter)

    assert record.status == "synced"
    assert adapter.calls.count("update") == 1
    assert adapter.calls.count("reschedule") == 1
    steps = adapter.workouts["workout-old"]["workoutSegments"][0]["workoutSteps"]
    assert steps[0]["workoutSteps"][0]["weightValue"] == 22.5
    assert "create" not in adapter.calls


def test_lost_workout_update_response_recovers_without_second_update(session):
    record, target_day, adapter = _prepare(session)
    adapter.lose_update_response = True
    claimed, _ = _claim(session, target_day)

    run_reschedule(session, claimed.id, adapter=adapter)
    assert record.status == "failed"
    assert record.training_date == OLD_DATE
    assert record.reschedule_to_date == TARGET_DATE
    assert adapter.calls.count("update") == 1
    assert adapter.calls.count("reschedule") == 0

    claimed, started = _claim(session, target_day)
    assert started is True
    run_reschedule(session, claimed.id, adapter=adapter)
    assert record.status == "synced"
    assert adapter.calls.count("update") == 1
    assert adapter.calls.count("reschedule") == 1
    assert "create" not in adapter.calls


def test_lost_schedule_response_recovers_without_second_reschedule(session):
    record, target_day, adapter = _prepare(session)
    adapter.lose_reschedule_response = True
    claimed, _ = _claim(session, target_day)

    run_reschedule(session, claimed.id, adapter=adapter)
    assert record.status == "failed"
    assert adapter.schedules["schedule-old"]["calendarDate"] == TARGET_DATE.isoformat()
    assert adapter.calls.count("reschedule") == 1

    claimed, _ = _claim(session, target_day)
    run_reschedule(session, claimed.id, adapter=adapter)
    assert record.status == "synced"
    assert adapter.calls.count("update") == 1
    assert adapter.calls.count("reschedule") == 1
    assert adapter.calls.count("create") == 0


def test_remote_source_mismatch_is_conflict_without_writes(session):
    record, target_day, adapter = _prepare(session)
    adapter.workouts["workout-old"]["description"] = "source_key=other"
    claimed, _ = _claim(session, target_day)

    run_reschedule(session, claimed.id, adapter=adapter)

    assert record.status == "conflict"
    assert record.error_code == "GARMIN_WORKOUT_SOURCE_MISMATCH"
    assert adapter.calls.count("update") == 0
    assert adapter.calls.count("reschedule") == 0
    with pytest.raises(PlanSyncError) as caught:
        _claim(session, target_day)
    assert caught.value.error_code == "GARMIN_WORKOUT_SOURCE_MISMATCH"


def test_stale_hash_target_conflict_running_and_disabled_are_rejected(session):
    record, target_day, _ = _prepare(session)
    with pytest.raises(PlanSyncError) as stale:
        claim_reschedule(
            session,
            from_date=OLD_DATE,
            target_date=TARGET_DATE,
            expected_source_hash="0" * 64,
            enabled=True,
        )
    assert stale.value.error_code == "PLAN_CHANGED"
    with pytest.raises(PlanSyncError) as disabled:
        _claim(session, target_day, enabled=False)
    assert disabled.value.status_code == 503
    assert record.attempt_count == 2

    other = GarminPlanSync(
        plan_ref=PLAN_REF,
        training_date=TARGET_DATE,
        source_key=source_key_for(PLAN_REF, TARGET_DATE),
        source_hash=source_hash(target_day),
        status="pending",
        attempt_count=0,
    )
    session.add(other)
    session.commit()
    with pytest.raises(PlanSyncError) as conflict:
        _claim(session, target_day)
    assert conflict.value.error_code == "RESCHEDULE_TARGET_CONFLICT"
    session.delete(other)
    session.commit()

    claimed, _ = _claim(session, target_day)
    with pytest.raises(PlanSyncError) as running:
        _claim(session, target_day)
    assert running.value.error_code == "SYNC_ALREADY_RUNNING"
    assert claimed.attempt_count == 3


def test_successful_old_address_replay_is_noop_and_attempt_is_stable(session):
    record, target_day, adapter = _prepare(session)
    claimed, _ = _claim(session, target_day)
    run_reschedule(session, claimed.id, adapter=adapter)
    calls = list(adapter.calls)
    attempts = record.attempt_count

    completed, started = _claim(session, target_day)

    assert started is False
    assert completed.id == record.id
    assert completed.status == "synced"
    assert completed.attempt_count == attempts
    assert adapter.calls == calls


def test_failed_target_status_and_normal_sync_gate_cannot_be_bypassed(session):
    record, target_day, adapter = _prepare(session)
    adapter.lose_update_response = True
    claimed, _ = _claim(session, target_day)
    run_reschedule(session, claimed.id, adapter=adapter)

    view = sync_status_view(
        record,
        source_key=source_key_for(PLAN_REF, TARGET_DATE),
        source_hash=source_hash(target_day),
    )
    assert view["status"] == "failed"
    assert view["reschedule_from_date"] == OLD_DATE.isoformat()
    assert list_reschedule_candidates(session)[0]["status"] == "failed"
    with pytest.raises(PlanSyncError) as caught:
        claim_plan_sync(
            session,
            target_day,
            expected_source_hash=source_hash(target_day),
            enabled=True,
        )
    assert caught.value.error_code == "RESCHEDULE_CONFIRMATION_REQUIRED"
    assert record.training_date == OLD_DATE


def test_consecutive_reschedules_use_current_source_and_preserve_remote_ids(session):
    record, first_target, adapter = _prepare(session)
    claimed, _ = _claim(session, first_target)
    run_reschedule(session, claimed.id, adapter=adapter)
    assert record.training_date == TARGET_DATE

    second_target_date = TARGET_DATE + timedelta(days=1)
    second_target = _plan_day(second_target_date)
    _set_cache(session, second_target)
    detected = detect_reschedule_candidates(session)

    assert detected["pending"] == 1
    assert detected["conflicts"] == 0
    assert detected["items"][0]["from_date"] == TARGET_DATE.isoformat()
    assert detected["items"][0]["to_date"] == second_target_date.isoformat()
    assert detected["items"][0]["previous_source_hash"] == source_hash(first_target)
    assert record.training_date == TARGET_DATE
    assert record.source_hash == source_hash(first_target)
    assert record.synced_hash == source_hash(first_target)

    status = sync_status_view(
        record,
        source_key=source_key_for(PLAN_REF, second_target_date),
        source_hash=source_hash(second_target),
    )
    assert status["reschedule_from_date"] == TARGET_DATE.isoformat()
    assert status["reschedule_to_date"] == second_target_date.isoformat()

    preview = preview_reschedule(
        session, from_date=TARGET_DATE, target_date=second_target_date
    )
    assert preview["from_date"] == TARGET_DATE.isoformat()
    assert preview["to_date"] == second_target_date.isoformat()

    claimed, started = claim_reschedule(
        session,
        from_date=TARGET_DATE,
        target_date=second_target_date,
        expected_source_hash=source_hash(second_target),
        enabled=True,
    )
    assert started is True
    assert claimed.reschedule_from_date == TARGET_DATE
    assert claimed.reschedule_source_key == source_key_for(PLAN_REF, TARGET_DATE)
    run_reschedule(session, claimed.id, adapter=adapter)

    assert record.status == "synced"
    assert record.training_date == second_target_date
    assert record.source_key == source_key_for(PLAN_REF, second_target_date)
    assert record.synced_hash == source_hash(second_target)
    assert record.reschedule_from_date == TARGET_DATE
    assert record.reschedule_to_date == second_target_date
    assert record.workout_id == "workout-old"
    assert record.workout_schedule_id == "schedule-old"
    assert adapter.calls.count("update") == 2
    assert adapter.calls.count("reschedule") == 2
    assert adapter.calls.count("create") == 0
    assert adapter.calls.count("schedule") == 0
    assert session.query(GarminPlanSync).count() == 1
    assert session.query(JobRun).filter_by(job_name="garmin_plan_reschedule").count() == 2

    calls = list(adapter.calls)
    attempts = record.attempt_count
    completed, started = claim_reschedule(
        session,
        from_date=TARGET_DATE,
        target_date=second_target_date,
        expected_source_hash=source_hash(second_target),
        enabled=True,
    )
    assert started is False
    assert completed.id == record.id
    assert completed.attempt_count == attempts
    assert adapter.calls == calls


def _make_stale(session, record):
    session.query(GarminPlanSync).filter_by(id=record.id).update(
        {GarminPlanSync.updated_at: datetime.now() - timedelta(hours=1)},
        synchronize_session=False,
    )
    session.commit()
    session.refresh(record)


def test_stale_reschedule_recovers_and_old_runner_cannot_finish_new_attempt(session):
    from app.db import make_session_factory

    record, target_day, adapter = _prepare(session)
    claimed, _ = _claim(session, target_day)
    original_get_schedule = adapter.get_schedule
    reclaimed = []

    def reclaim_during_final_read(schedule_id):
        result = original_get_schedule(schedule_id)
        if result["calendarDate"] == TARGET_DATE.isoformat() and not reclaimed:
            other = make_session_factory(session.get_bind())()
            try:
                other_record = other.get(GarminPlanSync, record.id)
                _make_stale(other, other_record)
                other_record, started = claim_reschedule(
                    other,
                    from_date=OLD_DATE,
                    target_date=TARGET_DATE,
                    expected_source_hash=source_hash(target_day),
                    enabled=True,
                )
                reclaimed.append((other_record.id, other_record.attempt_count, started))
            finally:
                other.close()
        return result

    adapter.get_schedule = reclaim_during_final_read
    run_reschedule(session, claimed.id, adapter=adapter)
    session.refresh(record)

    assert reclaimed == [(record.id, 4, True)]
    assert record.status == "syncing"
    assert record.attempt_count == 4
    assert record.training_date == OLD_DATE
    assert session.query(JobRun).filter_by(status="synced").count() == 0

    adapter.get_schedule = original_get_schedule
    run_reschedule(session, record.id, adapter=adapter)

    assert record.status == "synced"
    assert record.training_date == TARGET_DATE
    assert record.workout_id == "workout-old"
    assert record.workout_schedule_id == "schedule-old"
    assert record.attempt_count == 4
    assert adapter.calls.count("update") == 1
    assert adapter.calls.count("reschedule") == 1
    assert adapter.calls.count("create") == 0
    assert adapter.calls.count("schedule") == 0
    jobs = (
        session.query(JobRun)
        .filter_by(job_name="garmin_plan_reschedule")
        .order_by(JobRun.id)
        .all()
    )
    assert [job.status for job in jobs] == ["failed", "synced"]
    assert json.loads(jobs[0].detail_json)["recovery"] == "stale_syncing"
