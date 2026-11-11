"""Garmin 计划写入状态机故障注入测试；FakeAdapter 不访问网络。"""
import copy
import json
from datetime import date, datetime, timedelta

import pytest

import app.main  # noqa: F401  先加载配置，再由共享夹具切换临时数据库
from app.adapters.garmin_workout_adapter import GarminWorkoutAdapterError
from app.models import GarminPlanSync, JobRun, XunjiPlan
from app.services.garmin_plan_sync import (
    PlanSyncError,
    claim_plan_sync,
    run_plan_sync,
)
from app.services.garmin_workout_mapper import source_hash
from app.services.plans import query_plan_day

PLAN_DATE = date(2026, 11, 12)
PLAN_REF = "platform:155"


def make_plan(session):
    payload = {
        "plan": {"plan_ref": PLAN_REF, "name": "增肌计划"},
        "days": [{
            "datestr": PLAN_DATE.isoformat(),
            "workout": {
                "name": "胸部训练",
                "movements": [{
                    "name": "杠铃卧推",
                    "rest_seconds": 60,
                    "target_sets": [
                        {"weight": 20, "unit": "kg", "reps": 8},
                        {"weight": 20, "unit": "kg", "reps": 8},
                    ],
                }],
            },
        }],
    }
    row = XunjiPlan(
        plan_ref=PLAN_REF,
        plan_json=json.dumps(payload, ensure_ascii=False),
        date_from=PLAN_DATE - timedelta(days=1),
        date_to=PLAN_DATE + timedelta(days=60),
    )
    session.add(row)
    session.commit()
    return row


def claim(session):
    plan_day = query_plan_day(session, PLAN_DATE)
    record, started = claim_plan_sync(
        session,
        plan_day,
        expected_source_hash=source_hash(plan_day),
        enabled=True,
    )
    return record, started


def adapter_error(operation="test"):
    return GarminWorkoutAdapterError(
        "INJECTED_FAILURE", "注入失败", operation=operation
    )


class FakeAdapter:
    def __init__(self):
        self.workouts = {}
        self.schedules = {}
        self.calls = []
        self.fail_once = set()
        self.lose_create_response = False
        self.lose_schedule_response = False
        self.corrupt_readback = False

    def _fail(self, operation):
        if operation in self.fail_once:
            self.fail_once.remove(operation)
            raise adapter_error(operation)

    def find_workouts_by_source_key(self, source_key):
        self.calls.append("find_workouts")
        self._fail("find_workouts")
        return [
            copy.deepcopy(row) for row in self.workouts.values()
            if f"source_key={source_key};" in (row.get("description") or "")
        ]

    def create_workout(self, payload):
        self.calls.append("create")
        workout_id = f"w{len(self.workouts) + 1}"
        self.workouts[workout_id] = {**copy.deepcopy(payload), "workoutId": workout_id}
        if self.lose_create_response:
            self.lose_create_response = False
            raise adapter_error("create")
        return workout_id

    def get_workout(self, workout_id):
        self.calls.append("get_workout")
        self._fail("get_workout")
        result = copy.deepcopy(self.workouts[workout_id])
        if self.corrupt_readback:
            for segment in result.get("workoutSegments", []):
                for step in segment.get("workoutSteps", []):
                    for child in step.get("workoutSteps", [step]):
                        if child.get("weightValue") is not None:
                            child["weightValue"] += 1
        return result

    def update_workout(self, workout_id, payload):
        self.calls.append("update")
        self._fail("update")
        self.workouts[workout_id] = {**copy.deepcopy(payload), "workoutId": workout_id}

    def find_schedules(self, workout_id, training_date):
        self.calls.append("find_schedules")
        self._fail("find_schedules")
        day = training_date.isoformat()
        return [
            copy.deepcopy(row) for row in self.schedules.values()
            if row["calendarDate"] == day
            and row["workout"]["workoutId"] == workout_id
        ]

    def schedule_workout(self, workout_id, training_date):
        self.calls.append("schedule")
        schedule_id = f"s{len(self.schedules) + 1}"
        self.schedules[schedule_id] = {
            "workoutScheduleId": schedule_id,
            "calendarDate": training_date.isoformat(),
            "workout": {"workoutId": workout_id},
        }
        if self.lose_schedule_response:
            self.lose_schedule_response = False
            raise adapter_error("schedule")
        return schedule_id

    def get_schedule(self, schedule_id):
        self.calls.append("get_schedule")
        self._fail("get_schedule")
        return copy.deepcopy(self.schedules[schedule_id])


def test_first_sync_creates_and_verifies_then_repeat_is_noop(session):
    make_plan(session)
    adapter = FakeAdapter()
    record, started = claim(session)
    assert started is True

    run_plan_sync(session, record.id, adapter=adapter)

    assert record.status == "synced"
    assert record.phase == "verify"
    assert record.workout_id == "w1"
    assert record.workout_schedule_id == "s1"
    assert record.synced_hash == record.source_hash
    assert adapter.calls.count("create") == 1
    assert adapter.calls.count("update") == 0
    assert adapter.calls.count("schedule") == 1
    job = session.query(JobRun).filter_by(job_name="garmin_plan_sync").one()
    assert job.status == "synced"
    assert "secret" not in (job.detail_json or "")

    same_record, started_again = claim(session)
    assert same_record.id == record.id
    assert started_again is False
    assert adapter.calls.count("create") == 1
    assert adapter.calls.count("schedule") == 1


def test_source_change_updates_same_workout_and_preserves_schedule(session):
    row = make_plan(session)
    adapter = FakeAdapter()
    record, _ = claim(session)
    run_plan_sync(session, record.id, adapter=adapter)

    payload = json.loads(row.plan_json)
    payload["days"][0]["workout"]["movements"][0]["target_sets"][0]["weight"] = 22.5
    payload["days"][0]["workout"]["movements"][0]["target_sets"][1]["weight"] = 22.5
    row.plan_json = json.dumps(payload, ensure_ascii=False)
    session.commit()
    updated_record, started = claim(session)
    assert started is True
    assert updated_record.id == record.id

    run_plan_sync(session, record.id, adapter=adapter)

    assert record.status == "synced"
    assert record.workout_id == "w1"
    assert record.workout_schedule_id == "s1"
    assert adapter.calls.count("create") == 1
    assert adapter.calls.count("update") == 1
    assert adapter.calls.count("schedule") == 1
    work = adapter.workouts["w1"]["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"][0]
    assert work["weightValue"] == 22.5


def test_lost_create_response_reconciles_without_duplicate_create(session):
    make_plan(session)
    adapter = FakeAdapter()
    adapter.lose_create_response = True
    record, _ = claim(session)

    run_plan_sync(session, record.id, adapter=adapter)
    assert record.status == "failed"
    assert record.workout_id is None
    assert adapter.calls.count("create") == 1

    record, started = claim(session)
    assert started is True
    run_plan_sync(session, record.id, adapter=adapter)

    assert record.status == "synced"
    assert record.workout_id == "w1"
    assert adapter.calls.count("create") == 1


def test_failure_after_workout_id_is_saved_resumes_without_create(session):
    make_plan(session)
    adapter = FakeAdapter()
    adapter.fail_once.add("find_schedules")
    record, _ = claim(session)

    run_plan_sync(session, record.id, adapter=adapter)
    assert record.status == "failed"
    assert record.workout_id == "w1"
    assert record.workout_schedule_id is None

    record, _ = claim(session)
    run_plan_sync(session, record.id, adapter=adapter)
    assert record.status == "synced"
    assert adapter.calls.count("create") == 1
    assert adapter.calls.count("schedule") == 1


def test_lost_schedule_response_reconciles_without_duplicate_schedule(session):
    make_plan(session)
    adapter = FakeAdapter()
    adapter.lose_schedule_response = True
    record, _ = claim(session)

    run_plan_sync(session, record.id, adapter=adapter)
    assert record.status == "failed"
    assert record.workout_id == "w1"
    assert record.workout_schedule_id is None

    record, _ = claim(session)
    run_plan_sync(session, record.id, adapter=adapter)
    assert record.status == "synced"
    assert record.workout_schedule_id == "s1"
    assert adapter.calls.count("schedule") == 1


def test_duplicate_claim_and_stale_hash_are_rejected(session):
    make_plan(session)
    record, _ = claim(session)
    with pytest.raises(PlanSyncError) as running:
        claim(session)
    assert running.value.error_code == "SYNC_ALREADY_RUNNING"

    plan_day = query_plan_day(session, PLAN_DATE)
    with pytest.raises(PlanSyncError) as changed:
        claim_plan_sync(
            session, plan_day, expected_source_hash="0" * 64, enabled=True
        )
    assert changed.value.error_code == "PLAN_CHANGED"
    assert session.query(GarminPlanSync).count() == 1


def test_multiple_remote_candidates_conflict_without_create(session):
    make_plan(session)
    plan_day = query_plan_day(session, PLAN_DATE)
    from app.services.garmin_workout_mapper import map_plan_day

    desired = map_plan_day(plan_day)["workout"]
    adapter = FakeAdapter()
    adapter.workouts = {
        "w1": {**copy.deepcopy(desired), "workoutId": "w1"},
        "w2": {**copy.deepcopy(desired), "workoutId": "w2"},
    }
    record, _ = claim(session)

    run_plan_sync(session, record.id, adapter=adapter)

    assert record.status == "conflict"
    assert record.error_code == "GARMIN_DUPLICATE_WORKOUTS"
    assert "create" not in adapter.calls


def test_remote_owned_by_other_source_is_never_overwritten(session):
    make_plan(session)
    plan_day = query_plan_day(session, PLAN_DATE)
    from app.services.garmin_workout_mapper import map_plan_day

    desired = map_plan_day(plan_day)["workout"]
    adapter = FakeAdapter()
    adapter.workouts["w9"] = {
        **copy.deepcopy(desired), "workoutId": "w9", "description": "source_key=other"
    }
    record, _ = claim(session)
    record.workout_id = "w9"
    session.commit()

    run_plan_sync(session, record.id, adapter=adapter)

    assert record.status == "conflict"
    assert record.error_code == "GARMIN_WORKOUT_SOURCE_MISMATCH"
    assert "update" not in adapter.calls


def test_readback_semantic_mismatch_is_conflict_not_success(session):
    make_plan(session)
    adapter = FakeAdapter()
    adapter.corrupt_readback = True
    record, _ = claim(session)

    run_plan_sync(session, record.id, adapter=adapter)

    assert record.status == "conflict"
    assert record.error_code == "GARMIN_WORKOUT_READBACK_MISMATCH"
    assert record.workout_schedule_id is None
    assert adapter.calls.count("update") == 1


def test_schedule_date_mismatch_does_not_create_or_reschedule(session):
    make_plan(session)
    adapter = FakeAdapter()
    record, _ = claim(session)
    record.workout_id = "w1"
    record.workout_schedule_id = "s1"
    from app.services.garmin_workout_mapper import map_plan_day

    adapter.workouts["w1"] = {
        **map_plan_day(query_plan_day(session, PLAN_DATE))["workout"], "workoutId": "w1"
    }
    adapter.schedules["s1"] = {
        "workoutScheduleId": "s1", "calendarDate": "2026-11-13",
        "workout": {"workoutId": "w1"},
    }
    session.commit()

    run_plan_sync(session, record.id, adapter=adapter)

    assert record.status == "conflict"
    assert record.error_code == "GARMIN_SCHEDULE_DATE_MISMATCH"
    assert "schedule" not in adapter.calls


def test_unexpected_exception_is_sanitized_and_job_is_failed(session):
    make_plan(session)
    adapter = FakeAdapter()
    adapter.find_workouts_by_source_key = lambda _: (_ for _ in ()).throw(
        ValueError("password=super-secret")
    )
    record, _ = claim(session)

    run_plan_sync(session, record.id, adapter=adapter)

    assert record.status == "failed"
    assert record.error_code == "GARMIN_SYNC_UNEXPECTED"
    assert "super-secret" not in record.last_error
    assert "ValueError" in record.last_error
    job = session.query(JobRun).filter_by(job_name="garmin_plan_sync").one()
    assert job.status == "failed"
    assert "super-secret" not in (job.error or "")


def _make_stale(session, record):
    session.query(GarminPlanSync).filter_by(id=record.id).update(
        {GarminPlanSync.updated_at: datetime.now() - timedelta(hours=1)},
        synchronize_session=False,
    )
    session.commit()
    session.refresh(record)


def test_stale_claim_recovers_and_resumes_without_duplicate_create(session):
    make_plan(session)
    adapter = FakeAdapter()
    record, _ = claim(session)
    _make_stale(session, record)

    record, started = claim(session)

    assert started is True
    assert record.status == "syncing"
    assert record.attempt_count == 2
    assert record.error_code is None
    run_plan_sync(session, record.id, adapter=adapter)

    assert record.status == "synced"
    assert record.attempt_count == 2
    assert adapter.calls.count("create") == 1
    assert adapter.calls.count("schedule") == 1
    jobs = (
        session.query(JobRun)
        .filter_by(job_name="garmin_plan_sync")
        .order_by(JobRun.id)
        .all()
    )
    assert [job.status for job in jobs] == ["failed", "synced"]
    assert json.loads(jobs[0].detail_json)["recovery"] == "stale_syncing"
    assert json.loads(jobs[0].detail_json)["error_code"] == "GARMIN_SYNC_INTERRUPTED"


def test_stale_runner_cannot_finish_reclaimed_attempt(session):
    from app.db import make_session_factory

    make_plan(session)
    adapter = FakeAdapter()
    record, _ = claim(session)
    original_get_schedule = adapter.get_schedule
    reclaimed = []

    def reclaim_during_final_read(schedule_id):
        result = original_get_schedule(schedule_id)
        other = make_session_factory(session.get_bind())()
        try:
            other_record = other.get(GarminPlanSync, record.id)
            _make_stale(other, other_record)
            other_record, started = claim(other)
            reclaimed.append((other_record.id, other_record.attempt_count, started))
        finally:
            other.close()
        return result

    adapter.get_schedule = reclaim_during_final_read
    run_plan_sync(session, record.id, adapter=adapter)
    session.refresh(record)

    assert reclaimed == [(record.id, 2, True)]
    assert record.status == "syncing"
    assert record.attempt_count == 2
    assert record.synced_hash is None
    assert session.query(JobRun).filter_by(status="synced").count() == 0

    adapter.get_schedule = original_get_schedule
    run_plan_sync(session, record.id, adapter=adapter)

    assert record.status == "synced"
    assert record.attempt_count == 2
    assert adapter.calls.count("create") == 1
    assert adapter.calls.count("schedule") == 1
