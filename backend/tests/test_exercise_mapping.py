"""V6-1：动作映射 seed / 加载 / mapper 注入行为。"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import ExerciseMapping
from app.services.exercise_mapping import (
    SEED_MAPPINGS,
    build_seed_rows,
    load_active_mappings,
    load_mapping_snapshot_hash,
    seed_mappings,
)
from app.services.garmin_workout_mapper import (
    EXERCISE_WHITELIST,
    WorkoutMappingError,
    expand_workout,
    map_plan_day,
)


def _make_set(weight=20, reps=10):
    return {
        "set_type": "working",
        "weight": weight,
        "left_weight": weight,
        "unit": "kg",
        "reps": reps,
        "duration_seconds": 60,
        "rest_seconds": 60,
        "rounds": None,
    }


def _make_day(name: str, sets=None):
    return {
        "plan_ref": "universal:1",
        "date": "2026-11-10",
        "title": "映射注入测试",
        "movements": [
            {
                "name": name,
                "sets": sets if sets is not None else [_make_set()],
                "rest_seconds": 60,
                "warmup_rest_seconds": 30,
                "single_side": False,
                "amrap": False,
            }
        ],
    }


def test_build_seed_rows_count():
    rows = build_seed_rows()
    assert len(rows) == 16
    assert len(SEED_MAPPINGS) == 16
    assert all(row["status"] == "active" for row in rows)
    # 16 条均已完成端到端验收（侧平举 2026-11-12 改哑铃专用项后已真机目视确认）。
    assert all(row["verified_level"] == "displayed" for row in rows)


def test_build_seed_rows_preserves_whitelist_values():
    by_name = {row["xunji_name"]: row for row in build_seed_rows()}
    assert set(by_name) == set(EXERCISE_WHITELIST)
    for name, item in EXERCISE_WHITELIST.items():
        row = by_name[name]
        assert row["garmin_category"] == item["category"]
        assert row["garmin_exercise_name"] == item["exerciseName"]
        assert row["garmin_display_name"] == item["display_name"]


def test_build_seed_rows_note_keeps_support_level():
    for row in build_seed_rows():
        support = EXERCISE_WHITELIST[row["xunji_name"]]["support_level"]
        assert f"support_level={support}" in row["note"]
        assert "seed from EXERCISE_WHITELIST" in row["note"]


def test_weight_strategy_inference():
    by_name = {row["xunji_name"]: row for row in build_seed_rows()}
    assert by_name["哑铃卧推"]["weight_strategy"] == "per_hand"
    assert by_name["哑铃推肩"]["weight_strategy"] == "per_hand"
    assert by_name["上斜哑铃飞鸟"]["weight_strategy"] == "per_hand"
    assert by_name["杠铃卧推"]["weight_strategy"] == "total"
    assert by_name["腿举"]["weight_strategy"] == "total"
    assert by_name["卷腹"]["weight_strategy"] == "bodyweight"
    assert by_name["俄罗斯转体"]["weight_strategy"] == "bodyweight"


def test_seed_is_idempotent(session):
    first = seed_mappings(session)
    assert first["inserted"] == 16
    assert first["skipped"] == 0
    count_after_first = session.scalar(select(func.count()).select_from(ExerciseMapping))
    assert count_after_first == 16

    second = seed_mappings(session)
    assert second["inserted"] == 0
    assert second["skipped"] == 16
    count_after_second = session.scalar(select(func.count()).select_from(ExerciseMapping))
    assert count_after_second == 16


def test_seed_does_not_overwrite_user_edited_row(session):
    seed_mappings(session)
    row = session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.xunji_name == "哑铃卧推")
    ).one()
    row.garmin_exercise_name = "USER_EDITED_NAME"
    session.commit()

    seed_mappings(session)
    session.refresh(row)
    assert row.garmin_exercise_name == "USER_EDITED_NAME"


def test_load_active_mappings_shape(session):
    seed_mappings(session)
    mappings = load_active_mappings(session)
    assert "哑铃卧推" in mappings
    item = mappings["哑铃卧推"]
    assert "category" in item
    assert "exerciseName" in item
    assert "display_name" in item
    result = map_plan_day(_make_day("哑铃卧推"), mappings=mappings)
    assert result["stats"]["sets"] == 1


def test_load_active_mappings_excludes_non_active(session):
    seed_mappings(session)
    row = session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.xunji_name == "哑铃卧推")
    ).one()
    row.status = "draft"
    session.commit()

    mappings = load_active_mappings(session)
    assert "哑铃卧推" not in mappings
    assert "杠铃卧推" in mappings

    row.status = "disabled"
    session.commit()
    mappings = load_active_mappings(session)
    assert "哑铃卧推" not in mappings


def test_load_active_mappings_fallback_when_empty(session):
    count = session.scalar(select(func.count()).select_from(ExerciseMapping))
    assert count == 0
    mappings = load_active_mappings(session)
    assert len(mappings) == 16
    assert set(mappings) == set(EXERCISE_WHITELIST)
    assert mappings["哑铃卧推"]["category"] == EXERCISE_WHITELIST["哑铃卧推"]["category"]
    assert mappings["哑铃卧推"]["exerciseName"] == EXERCISE_WHITELIST["哑铃卧推"]["exerciseName"]


def test_snapshot_hash_changes_when_mapping_changes(session):
    seed_mappings(session)
    names = ["哑铃卧推", "杠铃卧推"]
    before = load_mapping_snapshot_hash(session, names)

    row = session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.xunji_name == "哑铃卧推")
    ).one()
    row.garmin_exercise_name = "CHANGED_ENUM"
    row.mapping_version = row.mapping_version + 1
    session.commit()

    after = load_mapping_snapshot_hash(session, names)
    assert before != after


def test_snapshot_hash_stable_for_same_input(session):
    seed_mappings(session)
    names = ["哑铃卧推", "卷腹", "腿举"]
    first = load_mapping_snapshot_hash(session, names)
    second = load_mapping_snapshot_hash(session, names)
    assert first == second
    assert len(first) == 64


def test_snapshot_hash_handles_missing_mapping(session):
    seed_mappings(session)
    digest = load_mapping_snapshot_hash(session, ["完全不存在的动作", "哑铃卧推"])
    assert isinstance(digest, str)
    assert len(digest) == 64


def test_map_plan_day_accepts_injected_mappings():
    mappings = {
        "测试动作": {
            "category": "BENCH_PRESS",
            "exerciseName": "CUSTOM_TEST_PRESS",
            "display_name": "Custom Test Press",
        }
    }
    result = map_plan_day(_make_day("测试动作"), mappings=mappings)
    step = result["workout"]["workoutSegments"][0]["workoutSteps"][0]
    assert step["category"] == "BENCH_PRESS"
    assert step["exerciseName"] == "CUSTOM_TEST_PRESS"


def test_map_plan_day_without_injection_uses_whitelist():
    result = map_plan_day(_make_day("哑铃卧推"))
    step = result["workout"]["workoutSegments"][0]["workoutSteps"][0]
    assert step["category"] == EXERCISE_WHITELIST["哑铃卧推"]["category"]
    assert step["exerciseName"] == EXERCISE_WHITELIST["哑铃卧推"]["exerciseName"]

    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(_make_day("测试动作"))
    assert caught.value.issues[0]["code"] == "UNKNOWN_EXERCISE"


def test_map_plan_day_raises_mapping_not_approved():
    mappings = {
        "待复核动作": {
            "category": "SQUAT",
            "exerciseName": "LEG_PRESS",
            "display_name": "Leg Press",
            "status": "draft",
        }
    }
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(_make_day("待复核动作"), mappings=mappings)
    codes = {issue["code"] for issue in caught.value.issues}
    assert "MAPPING_NOT_APPROVED" in codes
    assert "UNKNOWN_EXERCISE" not in codes
    assert "待复核动作" in caught.value.issues[0]["message"]
    assert "draft" in caught.value.issues[0]["message"]


def test_expand_workout_accepts_injected_mappings():
    mappings = {
        "测试动作": {
            "category": "BENCH_PRESS",
            "exerciseName": "CUSTOM_TEST_PRESS",
            "display_name": "Custom Test Press",
        }
    }
    payload = map_plan_day(_make_day("测试动作"), mappings=mappings)["workout"]
    expanded = expand_workout(payload, mappings=mappings)
    assert expanded[0]["name"] == "测试动作"
    assert expanded[0]["sets"][0]["reps"] == 10


def test_expand_workout_keeps_normalized_aliases():
    payload = {
        "workoutSegments": [
            {
                "workoutSteps": [
                    {
                        "type": "ExecutableStepDTO",
                        "category": "BENCH_PRESS",
                        "exerciseName": "",
                        "stepType": {"stepTypeKey": "interval"},
                        "endCondition": {"conditionTypeKey": "reps"},
                        "endConditionValue": 8,
                        "weightValue": 40,
                    },
                    {
                        "type": "ExecutableStepDTO",
                        "category": "LATERAL_RAISE",
                        "exerciseName": "",
                        "stepType": {"stepTypeKey": "interval"},
                        "endCondition": {"conditionTypeKey": "reps"},
                        "endConditionValue": 12,
                        "weightValue": 8,
                    },
                ]
            }
        ]
    }
    expanded = expand_workout(payload)
    assert [item["name"] for item in expanded] == ["器械推胸", "侧平举"]
