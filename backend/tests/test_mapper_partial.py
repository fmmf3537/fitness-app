"""ADR-P0-3a：mapper allow_partial（skipped 收集 + 缺口标记）。

纯函数测 map_plan_day；mappings 手写，不落库。
默认路径（allow_partial=False）必须与改动前行为一致。
"""
from __future__ import annotations

import pytest

from app.services.garmin_workout_mapper import (
    PARTIAL_ELIGIBLE_CODES,
    WorkoutMappingError,
    map_plan_day,
)


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


def _set(weight=20, reps=10, *, unit="kg", rest=60, **extra):
    item = {
        "set_type": "working",
        "weight": weight,
        "reps": reps,
        "rest_seconds": rest,
        "done": True,
    }
    if unit is not None:
        item["unit"] = unit
    item.update(extra)
    return item


def _movement(name: str, sets=None, **flags):
    return {
        "name": name,
        "sets": sets if sets is not None else [_set(), _set(), _set()],
        "rest_seconds": 60,
        "single_side": flags.get("single_side", False),
        "amrap": flags.get("amrap", False),
    }


def _day(movements, title="partial 通道测试"):
    return {
        "plan_ref": "platform:155",
        "date": "2026-11-12",
        "title": title,
        "movements": movements,
    }


# ---- 默认路径零变化（4） ----


def test_default_still_raises_on_unknown():
    day = _day([_movement("哑铃卧推"), _movement("完全未知动作")])
    mappings = {"哑铃卧推": _strength_mapping()}
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(day, mappings=mappings)
    codes = {issue["code"] for issue in caught.value.issues}
    assert "UNKNOWN_EXERCISE" in codes
    assert caught.value.skipped == []


def test_default_still_raises_on_draft():
    mappings = {"哑铃卧推": {**_strength_mapping(), "status": "draft"}}
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(_day([_movement("哑铃卧推")]), mappings=mappings)
    codes = {issue["code"] for issue in caught.value.issues}
    assert codes == {"MAPPING_NOT_APPROVED"}
    assert caught.value.skipped == []


def test_default_preview_has_empty_skipped():
    day = _day([_movement("哑铃卧推")])
    mappings = {"哑铃卧推": _strength_mapping()}
    preview = map_plan_day(day, mappings=mappings)
    assert preview["skipped"] == []


def test_default_excluded_unchanged():
    day = _day(
        [
            _movement("哑铃卧推"),
            _movement("腿部拉伸", sets=[_set(weight=0, reps=1)]),
        ]
    )
    mappings = {
        "哑铃卧推": _strength_mapping(),
        "腿部拉伸": _not_applicable_mapping(),
    }
    preview = map_plan_day(day, mappings=mappings)
    assert preview["excluded"] == [
        {"name": "腿部拉伸", "reason": "not_applicable"}
    ]
    assert preview["skipped"] == []


# ---- partial 主路径（5） ----


def test_partial_skips_unknown():
    day = _day([_movement("哑铃卧推"), _movement("完全未知动作")])
    mappings = {"哑铃卧推": _strength_mapping()}
    preview = map_plan_day(day, mappings=mappings, allow_partial=True)
    assert len(preview["skipped"]) == 1
    assert preview["skipped"][0]["reason"] == "UNKNOWN_EXERCISE"
    assert preview["skipped"][0]["name"] == "完全未知动作"
    names = [m["name"] for m in preview["movements"]]
    assert names == ["哑铃卧推"]


def test_partial_skips_draft():
    mappings = {"哑铃卧推": {**_strength_mapping(), "status": "draft"}}
    day = _day([_movement("哑铃卧推"), _movement("器械推胸")])
    mappings["器械推胸"] = {
        "category": "BENCH_PRESS",
        "exerciseName": "BENCH_PRESS",
        "display_name": "Bench Press",
        "support_level": "p2_verified",
        "status": "active",
    }
    preview = map_plan_day(day, mappings=mappings, allow_partial=True)
    assert len(preview["skipped"]) == 1
    assert preview["skipped"][0]["reason"] == "MAPPING_NOT_APPROVED"
    assert "draft" in preview["skipped"][0]["detail"]
    assert [m["name"] for m in preview["movements"]] == ["器械推胸"]


def test_partial_skips_disabled():
    mappings = {
        "哑铃卧推": {**_strength_mapping(), "status": "disabled"},
        "器械推胸": {
            "category": "BENCH_PRESS",
            "exerciseName": "BENCH_PRESS",
            "display_name": "Bench Press",
            "support_level": "p2_verified",
            "status": "active",
        },
    }
    day = _day([_movement("哑铃卧推"), _movement("器械推胸")])
    preview = map_plan_day(day, mappings=mappings, allow_partial=True)
    assert preview["skipped"][0]["reason"] == "MAPPING_NOT_APPROVED"
    assert "disabled" in preview["skipped"][0]["detail"]


def test_partial_keeps_excluded_separate():
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
    preview = map_plan_day(day, mappings=mappings, allow_partial=True)
    assert preview["excluded"] == [
        {"name": "腿部拉伸", "reason": "not_applicable"}
    ]
    assert preview["skipped"] == [
        {
            "name": "完全未知动作",
            "reason": "UNKNOWN_EXERCISE",
            "detail": "未找到映射行",
        }
    ]
    assert [m["name"] for m in preview["movements"]] == ["哑铃卧推"]


def test_partial_written_movements_correct():
    day = _day(
        [
            _movement("哑铃卧推", sets=[_set(), _set(), _set()]),
            _movement("完全未知动作"),
        ]
    )
    mappings = {"哑铃卧推": _strength_mapping()}
    preview = map_plan_day(day, mappings=mappings, allow_partial=True)
    assert preview["stats"]["movements"] == 1
    assert preview["stats"]["sets"] == 3
    assert len(preview["movements"]) == 1
    assert preview["movements"][0]["name"] == "哑铃卧推"


# ---- 不可降级的错误（4） ----


def test_partial_still_raises_on_unit_unsupported():
    # 有 weight 但缺 unit → UNIT_UNSUPPORTED；不得进 skipped
    day = _day(
        [
            _movement(
                "哑铃卧推",
                sets=[_set(unit=None)],
            )
        ]
    )
    mappings = {"哑铃卧推": _strength_mapping()}
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(day, mappings=mappings, allow_partial=True)
    codes = {issue["code"] for issue in caught.value.issues}
    assert "UNIT_UNSUPPORTED" in codes
    assert caught.value.skipped == []


def test_partial_still_raises_on_single_side():
    day = _day([_movement("哑铃卧推", single_side=True)])
    mappings = {"哑铃卧推": _strength_mapping()}
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(day, mappings=mappings, allow_partial=True)
    codes = {issue["code"] for issue in caught.value.issues}
    assert "SINGLE_SIDE_UNSUPPORTED" in codes


def test_partial_still_raises_on_amrap():
    day = _day([_movement("哑铃卧推", amrap=True)])
    mappings = {"哑铃卧推": _strength_mapping()}
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(day, mappings=mappings, allow_partial=True)
    codes = {issue["code"] for issue in caught.value.issues}
    assert "AMRAP_UNSUPPORTED" in codes


def test_partial_still_raises_on_empty_movement():
    day = _day([_movement("哑铃卧推", sets=[])])
    mappings = {"哑铃卧推": _strength_mapping()}
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(day, mappings=mappings, allow_partial=True)
    codes = {issue["code"] for issue in caught.value.issues}
    assert "EMPTY_MOVEMENT" in codes


# ---- 全不可写与名称标记（3+1） ----


def test_all_unwritable_raises_no_writable():
    day = _day([_movement("未知甲"), _movement("未知乙")])
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(day, mappings={}, allow_partial=True)
    codes = {issue["code"] for issue in caught.value.issues}
    assert codes == {"NO_WRITABLE_MOVEMENTS"}
    assert [s["name"] for s in caught.value.skipped] == ["未知甲", "未知乙"]
    assert all(s["reason"] == "UNKNOWN_EXERCISE" for s in caught.value.skipped)


def test_all_unwritable_is_not_partial_eligible():
    assert "NO_WRITABLE_MOVEMENTS" not in PARTIAL_ELIGIBLE_CODES


def test_workout_name_has_gap_marker():
    day = _day([_movement("哑铃卧推"), _movement("完全未知动作")], title="胸日")
    mappings = {"哑铃卧推": _strength_mapping()}
    preview = map_plan_day(day, mappings=mappings, allow_partial=True)
    assert preview["workout"]["workoutName"].endswith("（缺 1 个动作）")

    full = map_plan_day(
        _day([_movement("哑铃卧推")], title="胸日"),
        mappings=mappings,
        allow_partial=True,
    )
    assert "（缺" not in full["workout"]["workoutName"]


def test_marker_absent_when_only_excluded():
    day = _day(
        [
            _movement("哑铃卧推"),
            _movement("腿部拉伸", sets=[_set(weight=0, reps=1)]),
        ],
        title="胸日",
    )
    mappings = {
        "哑铃卧推": _strength_mapping(),
        "腿部拉伸": _not_applicable_mapping(),
    }
    preview = map_plan_day(day, mappings=mappings, allow_partial=True)
    assert preview["excluded"]
    assert preview["skipped"] == []
    assert "（缺" not in preview["workout"]["workoutName"]


# ---- 错误对象兼容（1） ----


def test_error_skipped_defaults_empty():
    exc = WorkoutMappingError(
        [{"code": "UNKNOWN_EXERCISE", "message": "未映射动作：x"}]
    )
    assert exc.skipped == []
    assert exc.excluded == []
