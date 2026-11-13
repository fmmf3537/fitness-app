"""ADR-P0-2：mapper excluded 通道（not_applicable 正常排除）。

纯函数测 map_plan_day；mappings 手写，不落库。
"""
from __future__ import annotations

import pytest

from app.services.garmin_workout_mapper import WorkoutMappingError, map_plan_day


def _strength_mapping() -> dict:
    return {
        "category": "BENCH_PRESS",
        "exerciseName": "DUMBBELL_BENCH_PRESS",
        "display_name": "Dumbbell Bench Press",
        "support_level": "p2_verified",
        "weight_strategy": "per_hand",
        "status": "active",
    }


def _not_applicable_mapping() -> dict:
    return {
        "category": None,
        "exerciseName": None,
        "display_name": None,
        "support_level": "user_confirmed_catalog_pending_end_to_end",
        "weight_strategy": None,
        "status": "not_applicable",
    }


def _set(weight=20, reps=10, *, rest=60):
    return {
        "set_type": "working",
        "weight": weight,
        "unit": "kg",
        "reps": reps,
        "rest_seconds": rest,
    }


def _movement(name: str, sets=None):
    return {
        "name": name,
        "sets": sets if sets is not None else [_set(), _set(), _set()],
        "rest_seconds": 60,
        "single_side": False,
        "amrap": False,
    }


def _day(movements):
    return {
        "plan_ref": "platform:155",
        "date": "2026-11-12",
        "title": "excluded 通道测试",
        "movements": movements,
    }


def _strength_plus_stretch_day():
    return _day(
        [
            _movement("哑铃卧推"),
            _movement("腿部拉伸", sets=[_set(weight=0, reps=1)]),
        ]
    )


def _mixed_mappings():
    return {
        "哑铃卧推": _strength_mapping(),
        "腿部拉伸": _not_applicable_mapping(),
    }


def test_not_applicable_goes_to_excluded():
    preview = map_plan_day(_strength_plus_stretch_day(), mappings=_mixed_mappings())
    assert preview["excluded"] == [
        {"name": "腿部拉伸", "reason": "not_applicable"}
    ]


def test_not_applicable_produces_no_issue():
    # 返回成功即表示未抛 WorkoutMappingError
    preview = map_plan_day(_strength_plus_stretch_day(), mappings=_mixed_mappings())
    assert isinstance(preview, dict)
    assert "workout" in preview


def test_not_applicable_not_in_steps():
    preview = map_plan_day(_strength_plus_stretch_day(), mappings=_mixed_mappings())
    names = [m["name"] for m in preview["movements"]]
    assert "腿部拉伸" not in names
    assert "哑铃卧推" in names
    steps = preview["workout"]["workoutSegments"][0]["workoutSteps"]
    blob = str(steps)
    assert "腿部拉伸" not in blob


def test_not_applicable_not_counted_in_totals():
    preview = map_plan_day(_strength_plus_stretch_day(), mappings=_mixed_mappings())
    # 力量动作 3 组；拉伸不计入
    assert preview["stats"]["sets"] == 3
    assert preview["stats"]["movements"] == 1


def test_only_not_applicable_still_raises_empty_workout():
    """只有拉伸时：movements 非空故不抛 EMPTY_WORKOUT，成功返回空 payload。

    现状（实读 map_plan_day）：EMPTY_WORKOUT 仅在 source_movements 为空时追加；
    全部 not_applicable 被跳过后 mapped_movements 为空，但 issues 也为空，
    因此返回成功且 steps/组数为 0（空力量 Workout）。
    """
    day = _day([_movement("腿部拉伸", sets=[_set(weight=0, reps=1)])])
    mappings = {"腿部拉伸": _not_applicable_mapping()}
    preview = map_plan_day(day, mappings=mappings)
    assert preview["excluded"] == [
        {"name": "腿部拉伸", "reason": "not_applicable"}
    ]
    assert preview["stats"]["sets"] == 0
    assert preview["stats"]["movements"] == 0
    assert preview["movements"] == []
    assert preview["workout"]["workoutSegments"][0]["workoutSteps"] == []


def test_excluded_carried_on_error():
    day = _day(
        [
            _movement("哑铃卧推"),
            _movement("腿部拉伸", sets=[_set(weight=0, reps=1)]),
            _movement("完全未知动作"),
        ]
    )
    mappings = {
        "哑铃卧推": _strength_mapping(),
        "腿部拉伸": _not_applicable_mapping(),
    }
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(day, mappings=mappings)
    assert caught.value.excluded == [
        {"name": "腿部拉伸", "reason": "not_applicable"}
    ]
    codes = {issue["code"] for issue in caught.value.issues}
    assert "UNKNOWN_EXERCISE" in codes


def test_draft_still_mapping_not_approved():
    mappings = {
        "哑铃卧推": {**_strength_mapping(), "status": "draft"},
    }
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(_day([_movement("哑铃卧推")]), mappings=mappings)
    codes = {issue["code"] for issue in caught.value.issues}
    assert codes == {"MAPPING_NOT_APPROVED"}
    assert caught.value.excluded == []


def test_disabled_still_mapping_not_approved():
    mappings = {
        "哑铃卧推": {**_strength_mapping(), "status": "disabled"},
    }
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(_day([_movement("哑铃卧推")]), mappings=mappings)
    codes = {issue["code"] for issue in caught.value.issues}
    assert codes == {"MAPPING_NOT_APPROVED"}
    assert caught.value.excluded == []


def test_workout_mapping_error_backward_compatible():
    exc = WorkoutMappingError(
        [{"code": "UNKNOWN_EXERCISE", "message": "未映射动作：x"}]
    )
    assert exc.excluded == []
    assert len(exc.issues) == 1


def test_multiple_not_applicable_all_listed():
    day = _day(
        [
            _movement("哑铃卧推"),
            _movement("腿部拉伸", sets=[_set(weight=0, reps=1)]),
            _movement("肩部拉伸", sets=[_set(weight=0, reps=1)]),
        ]
    )
    mappings = {
        "哑铃卧推": _strength_mapping(),
        "腿部拉伸": _not_applicable_mapping(),
        "肩部拉伸": _not_applicable_mapping(),
    }
    preview = map_plan_day(day, mappings=mappings)
    assert preview["excluded"] == [
        {"name": "腿部拉伸", "reason": "not_applicable"},
        {"name": "肩部拉伸", "reason": "not_applicable"},
    ]
