"""ADR-P0-3b：同步层 partial 状态 + sync_result_json + 状态视图。

FakeAdapter 风格照抄 test_garmin_plan_sync_write；不改既有测试文件。
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta

import pytest

import app.main  # noqa: F401  先加载配置，再由共享夹具切换临时数据库
from app.adapters.garmin_workout_adapter import GarminWorkoutAdapterError
from app.models import ExerciseMapping, GarminPlanSync, XunjiPlan
from app.services.exercise_mapping import seed_mappings
from app.services.garmin_plan_sync import (
    claim_plan_sync,
    run_plan_sync,
    sync_status_view,
)
from app.services.garmin_workout_mapper import WorkoutMappingError, source_hash
from app.services.plans import query_plan_day

PLAN_DATE = date(2026, 11, 12)
PLAN_REF = "platform:155"
STRENGTH = "杠铃卧推"
STRETCH = "腿部拉伸"
UNKNOWN = "完全未知动作XYZ"


def _set(weight=20, reps=8, *, unit="kg"):
    item = {"weight": weight, "reps": reps}
    if unit is not None:
        item["unit"] = unit
    return item


def _movement(name, sets=None):
    return {
        "name": name,
        "rest_seconds": 60,
        "target_sets": sets if sets is not None else [_set(), _set()],
    }


def make_plan(session, movements):
    payload = {
        "plan": {"plan_ref": PLAN_REF, "name": "增肌计划"},
        "days": [
            {
                "datestr": PLAN_DATE.isoformat(),
                "workout": {
                    "name": "胸部训练",
                    "movements": movements,
                },
            }
        ],
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


def _add_mapping(
    session,
    *,
    name: str,
    status: str = "active",
    category: str = "BENCH_PRESS",
    exercise: str = "BARBELL_BENCH_PRESS",
    display: str = "Barbell Bench Press",
    not_applicable_reason: str | None = None,
) -> ExerciseMapping:
    row = ExerciseMapping(
        xunji_name=name,
        garmin_category=None if status == "not_applicable" else category,
        garmin_exercise_name=None if status == "not_applicable" else exercise,
        garmin_display_name=None if status == "not_applicable" else display,
        weight_strategy=None if status == "not_applicable" else "total",
        status=status,
        not_applicable_reason=not_applicable_reason,
        confidence="high",
        source="test",
        verified_level="catalog",
        mapping_version=1,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
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


class FakeAdapter:
    def __init__(self):
        self.workouts = {}
        self.schedules = {}
        self.calls = []
        self.fail_once = set()

    def _fail(self, operation):
        if operation in self.fail_once:
            self.fail_once.remove(operation)
            raise GarminWorkoutAdapterError(
                "INJECTED_FAILURE", "注入失败", operation=operation
            )

    def find_workouts_by_source_key(self, source_key):
        self.calls.append("find_workouts")
        self._fail("find_workouts")
        return [
            copy.deepcopy(row)
            for row in self.workouts.values()
            if f"source_key={source_key};" in (row.get("description") or "")
        ]

    def create_workout(self, payload):
        self.calls.append("create")
        self._fail("create")
        workout_id = f"w{len(self.workouts) + 1}"
        self.workouts[workout_id] = {**copy.deepcopy(payload), "workoutId": workout_id}
        return workout_id

    def get_workout(self, workout_id):
        self.calls.append("get_workout")
        self._fail("get_workout")
        return copy.deepcopy(self.workouts[workout_id])

    def update_workout(self, workout_id, payload):
        self.calls.append("update")
        self._fail("update")
        self.workouts[workout_id] = {**copy.deepcopy(payload), "workoutId": workout_id}

    def find_schedules(self, workout_id, training_date):
        self.calls.append("find_schedules")
        self._fail("find_schedules")
        day = training_date.isoformat()
        return [
            copy.deepcopy(row)
            for row in self.schedules.values()
            if row["calendarDate"] == day
            and row["workout"]["workoutId"] == workout_id
        ]

    def schedule_workout(self, workout_id, training_date):
        self.calls.append("schedule")
        self._fail("schedule")
        schedule_id = f"s{len(self.schedules) + 1}"
        self.schedules[schedule_id] = {
            "workoutScheduleId": schedule_id,
            "calendarDate": training_date.isoformat(),
            "workout": {"workoutId": workout_id},
        }
        return schedule_id

    def get_schedule(self, schedule_id):
        self.calls.append("get_schedule")
        self._fail("get_schedule")
        return copy.deepcopy(self.schedules[schedule_id])


def _result(record):
    return json.loads(record.sync_result_json or "{}")


# ---- claim 阶段（4） ----


def test_claim_uses_include_excluded(session):
    seed_mappings(session)
    _add_mapping(
        session, name=STRETCH, status="not_applicable", not_applicable_reason="stretch"
    )
    make_plan(
        session,
        [
            _movement(STRENGTH),
            _movement(STRETCH, sets=[_set(weight=0, reps=1)]),
        ],
    )
    record, started = claim(session)
    assert started is True
    assert record.status == "syncing"
    result = _result(record)
    assert any(m.get("name") == STRETCH for m in result["excluded_movements"])


def test_claim_stores_skipped_in_sync_result(session):
    make_plan(session, [_movement(STRENGTH), _movement(UNKNOWN)])
    record, started = claim(session)
    assert started is True
    result = _result(record)
    names = [m.get("name") for m in result["skipped_movements"]]
    assert UNKNOWN in names


def test_claim_stores_written_and_excluded(session):
    seed_mappings(session)
    _add_mapping(
        session, name=STRETCH, status="not_applicable", not_applicable_reason="stretch"
    )
    make_plan(
        session,
        [
            _movement(STRENGTH),
            _movement(UNKNOWN),
            _movement(STRETCH, sets=[_set(weight=0, reps=1)]),
        ],
    )
    record, _ = claim(session)
    result = _result(record)
    assert STRENGTH in result["written_movements"]
    assert any(m.get("name") == UNKNOWN for m in result["skipped_movements"])
    assert any(m.get("name") == STRETCH for m in result["excluded_movements"])
    # 三类分开，不得混成一个列表
    assert STRENGTH not in [m.get("name") for m in result["skipped_movements"]]
    assert STRENGTH not in [m.get("name") for m in result["excluded_movements"]]


def test_claim_payload_name_has_marker(session):
    make_plan(session, [_movement(STRENGTH), _movement(UNKNOWN)])
    record, _ = claim(session)
    payload = json.loads(record.payload_json)
    assert "（缺 1 个动作）" in payload["workoutName"]


# ---- 完成阶段（4） ----


def test_run_sets_partial_when_skipped(session):
    make_plan(session, [_movement(STRENGTH), _movement(UNKNOWN)])
    adapter = FakeAdapter()
    record, _ = claim(session)
    run_plan_sync(session, record.id, adapter=adapter)
    session.refresh(record)
    assert record.status == "partial"


def test_run_sets_synced_when_no_skipped(session):
    make_plan(session, [_movement(STRENGTH)])
    adapter = FakeAdapter()
    record, _ = claim(session)
    run_plan_sync(session, record.id, adapter=adapter)
    session.refresh(record)
    assert record.status == "synced"


def test_partial_still_sets_synced_hash_and_at(session):
    make_plan(session, [_movement(STRENGTH), _movement(UNKNOWN)])
    adapter = FakeAdapter()
    record, _ = claim(session)
    run_plan_sync(session, record.id, adapter=adapter)
    session.refresh(record)
    assert record.status == "partial"
    assert record.synced_hash == record.source_hash
    assert record.synced_at is not None
    assert record.phase == "verify"


def test_all_unwritable_does_not_call_adapter(session):
    make_plan(session, [_movement(UNKNOWN)])
    adapter = FakeAdapter()
    with pytest.raises(WorkoutMappingError) as caught:
        claim(session)
    codes = {issue["code"] for issue in caught.value.issues}
    assert "NO_WRITABLE_MOVEMENTS" in codes
    assert adapter.calls.count("create") == 0
    assert "create" not in adapter.calls
    assert session.query(GarminPlanSync).count() == 0


# ---- 状态视图（3） ----


def test_status_view_reports_partial(session):
    make_plan(session, [_movement(STRENGTH), _movement(UNKNOWN)])
    adapter = FakeAdapter()
    record, _ = claim(session)
    run_plan_sync(session, record.id, adapter=adapter)
    session.refresh(record)
    plan_day = query_plan_day(session, PLAN_DATE)
    view = sync_status_view(
        record,
        source_key=record.source_key,
        source_hash=record.source_hash,
    )
    assert record.synced_hash == source_hash(plan_day)
    assert view["status"] == "partial"


def test_status_view_sync_result_counts(session):
    seed_mappings(session)
    _add_mapping(
        session, name=STRETCH, status="not_applicable", not_applicable_reason="stretch"
    )
    make_plan(
        session,
        [
            _movement(STRENGTH),
            _movement(UNKNOWN),
            _movement(STRETCH, sets=[_set(weight=0, reps=1)]),
        ],
    )
    record, _ = claim(session)
    view = sync_status_view(
        record,
        source_key=record.source_key,
        source_hash=record.source_hash,
    )
    sr = view["sync_result"]
    assert sr["written"] == 1
    assert sr["skipped"] == 1
    assert sr["excluded"] == 1
    assert any(m.get("name") == UNKNOWN for m in sr["skipped_movements"])
    assert "written_movements" not in sr


def test_status_view_sync_result_broken_json_is_safe(session):
    make_plan(session, [_movement(STRENGTH)])
    plan_day = query_plan_day(session, PLAN_DATE)
    record = GarminPlanSync(
        plan_ref=PLAN_REF,
        training_date=PLAN_DATE,
        source_key=f"xunji-plan:v1:{PLAN_REF}:{PLAN_DATE.isoformat()}",
        source_hash=source_hash(plan_day),
        status="partial",
        phase="verify",
        sync_result_json="{not-json",
        workout_id="w1",
        workout_schedule_id="s1",
        synced_hash=source_hash(plan_day),
        attempt_count=1,
    )
    session.add(record)
    session.commit()
    view = sync_status_view(
        record,
        source_key=record.source_key,
        source_hash=record.source_hash,
    )
    assert view["status"] == "partial"
    assert view["sync_result"] == {
        "written": 0,
        "skipped": 0,
        "excluded": 0,
        "skipped_movements": [],
    }


# ---- 不可降级（2） ----


def test_unit_error_still_fails_whole_day(session):
    # 有 weight 但缺 unit → UNIT_UNSUPPORTED；不得记成 partial
    make_plan(
        session,
        [_movement(STRENGTH, sets=[_set(weight=20, reps=8, unit=None)])],
    )
    with pytest.raises(WorkoutMappingError) as caught:
        claim(session)
    codes = {issue["code"] for issue in caught.value.issues}
    assert "UNIT_UNSUPPORTED" in codes
    rows = session.query(GarminPlanSync).all()
    assert all(r.status != "partial" for r in rows)
    # 整体失败：无成功写入记录
    assert not any(r.status in ("synced", "partial") for r in rows)


def test_adapter_failure_still_failed(session):
    make_plan(session, [_movement(STRENGTH), _movement(UNKNOWN)])
    adapter = FakeAdapter()
    adapter.fail_once.add("create")
    record, _ = claim(session)
    sync_result_before = record.sync_result_json
    run_plan_sync(session, record.id, adapter=adapter)
    session.refresh(record)
    assert record.status == "failed"
    assert record.status != "partial"
    # sync_result 受理不受影响（claim 阶段已落库）
    assert record.sync_result_json == sync_result_before
    result = _result(record)
    assert any(m.get("name") == UNKNOWN for m in result["skipped_movements"])


# ---- 补全路径（1） ----


def test_resync_after_fix_clears_partial(session):
    seed_mappings(session)
    make_plan(session, [_movement(STRENGTH), _movement(UNKNOWN)])
    adapter = FakeAdapter()
    record, _ = claim(session)
    run_plan_sync(session, record.id, adapter=adapter)
    session.refresh(record)
    assert record.status == "partial"
    first_workout_id = record.workout_id
    assert first_workout_id is not None
    assert "（缺" in json.loads(record.payload_json)["workoutName"]

    # 补齐未知动作映射后再次 claim+run
    _add_mapping(
        session,
        name=UNKNOWN,
        category="BENCH_PRESS",
        exercise="BARBELL_BENCH_PRESS",
        display="Unknown Fixed",
    )
    record2, started = claim(session)
    assert started is True
    assert record2.id == record.id
    run_plan_sync(session, record2.id, adapter=adapter)
    session.refresh(record2)
    assert record2.status == "synced"
    payload = json.loads(record2.payload_json)
    assert "（缺" not in payload["workoutName"]
    assert record2.workout_id == first_workout_id
    result = _result(record2)
    assert result["skipped_movements"] == []
