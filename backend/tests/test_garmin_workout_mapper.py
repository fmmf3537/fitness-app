"""Garmin 本地 Workout 映射器测试；全部纯内存，零网络请求。"""
import json
from pathlib import Path

import pytest

from app.services.garmin_workout_mapper import (
    EXERCISE_WHITELIST,
    WorkoutMappingError,
    content_hash,
    expand_workout,
    map_plan_day,
    source_hash,
    source_set_projection,
)
from app.services.plans import extract_plan_days

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def make_set(weight=20, reps=10, *, set_type="working", rest=None, duration=60, unit="kg"):
    return {
        "set_type": set_type,
        "weight": weight,
        "left_weight": weight,
        "unit": unit,
        "reps": reps,
        "duration_seconds": duration,
        "rest_seconds": rest,
        "rounds": None,
    }


def make_movement(name="哑铃卧推", sets=None, *, rest=60, warmup_rest=30):
    return {
        "name": name,
        "sets": sets if sets is not None else [make_set()],
        "rest_seconds": rest,
        "warmup_rest_seconds": warmup_rest,
        "single_side": False,
        "amrap": False,
    }


def make_day(movements=None):
    return {
        "plan_ref": "universal:1",
        "date": "2026-11-10",
        "title": "胸·三头·腹肌·2",
        "movements": movements if movements is not None else [make_movement()],
    }


def steps_of(result):
    return result["workout"]["workoutSegments"][0]["workoutSteps"]


def assert_roundtrip(day, result):
    expanded = expand_workout(result["workout"])
    assert source_set_projection(expanded) == source_set_projection(day["movements"])


def test_current_whitelist_tracks_p0_p2_and_p3_verified():
    p2_verified = {name for name, item in EXERCISE_WHITELIST.items() if item["support_level"] == "p2_verified"}
    p3_verified = {name for name, item in EXERCISE_WHITELIST.items() if item["support_level"] == "p3_verified"}
    assert p3_verified == {
        "腿举", "杠铃深蹲", "杠铃罗马尼亚硬拉", "史密斯机推举",
        "哑铃推肩", "侧平举", "哑铃上斜俯身侧平举",
    }
    assert p2_verified == {
        "哑铃卧推", "器械推胸", "上斜哑铃飞鸟", "哑铃臂屈伸",
        "绳索过头臂屈伸", "俄罗斯转体", "卷腹", "绳索Pallof推",
    }
    assert EXERCISE_WHITELIST["杠铃卧推"]["support_level"] == "p0_verified"
    assert EXERCISE_WHITELIST["哑铃臂屈伸"]["exerciseName"] == "OVERHEAD_DUMBBELL_TRICEPS_EXTENSION"
    assert EXERCISE_WHITELIST["器械推胸"]["exerciseName"] == "BENCH_PRESS"
    assert EXERCISE_WHITELIST["绳索Pallof推"]["exerciseName"] == "CABLE_CORE_PRESS"
    assert EXERCISE_WHITELIST["哑铃上斜俯身侧平举"]["exerciseName"] == "INCLINE_REVERSE_FLYE"


def test_contiguous_identical_sets_merge_but_weight_drop_does_not():
    day = make_day([make_movement(sets=[
        make_set(82.5), make_set(82.5), make_set(77.5),
    ], rest=90)])

    result = map_plan_day(day)

    assert result["stats"]["sets"] == 3
    assert result["stats"]["repeat_groups"] == 1
    repeat, single, rest = steps_of(result)
    assert repeat["numberOfIterations"] == 2
    assert repeat["workoutSteps"][0]["weightValue"] == 82.5
    assert single["weightValue"] == 77.5
    assert rest["endConditionValue"] == 90
    assert result["stats"]["rest_seconds"] == 270
    assert_roundtrip(day, result)


def test_nonconsecutive_same_weight_is_not_merged():
    day = make_day([make_movement(sets=[
        make_set(20), make_set(22.5), make_set(20),
    ])])

    result = map_plan_day(day)

    assert result["stats"]["repeat_groups"] == 0
    assert [step["weightValue"] for step in steps_of(result) if step.get("category")] == [20.0, 22.5, 20.0]
    assert_roundtrip(day, result)


def test_kg_raw_value_and_warmup_steps_roundtrip():
    day = make_day([make_movement(sets=[
        make_set(15, set_type="warmup", duration=30),
        make_set(17.5, set_type="warmup", duration=30),
        make_set(20),
        make_set(20),
    ], rest=120, warmup_rest=30)])

    result = map_plan_day(day)
    steps = steps_of(result)
    work_steps = [step for step in steps if step.get("category")]
    repeat = next(step for step in steps if step["type"] == "RepeatGroupDTO")

    assert [step["weightValue"] for step in work_steps] == [15.0, 17.5]
    assert repeat["workoutSteps"][0]["weightValue"] == 20.0
    repeat_work = repeat["workoutSteps"][0]
    assert all(step["weightValue"] != 20000.0 for step in work_steps + [repeat_work])
    assert [step["stepType"]["stepTypeKey"] for step in work_steps] == ["warmup", "warmup"]
    assert repeat["workoutSteps"][0]["stepType"]["stepTypeKey"] == "interval"
    assert repeat["workoutSteps"][1]["endConditionValue"] == 120
    assert result["stats"]["warmup_sets"] == 2
    assert result["stats"]["working_sets"] == 2
    assert_roundtrip(day, result)


def test_duration_seconds_is_not_rest_and_does_not_split_reps_sets():
    day = make_day([make_movement(sets=[
        make_set(20, duration=60), make_set(20, duration=0),
    ], rest=60)])

    result = map_plan_day(day)

    assert result["stats"]["repeat_groups"] == 1
    repeat = steps_of(result)[0]
    assert repeat["numberOfIterations"] == 2
    assert repeat["workoutSteps"][0]["endCondition"]["conditionTypeKey"] == "reps"
    assert repeat["workoutSteps"][1]["endConditionValue"] == 60
    assert_roundtrip(day, result)


def test_set_rest_overrides_movement_rest():
    day = make_day([make_movement(sets=[
        make_set(rest=30), make_set(rest=None),
    ], rest=90)])

    result = map_plan_day(day)

    assert result["stats"]["repeat_groups"] == 0
    expanded = expand_workout(result["workout"])
    assert [item["rest_seconds"] for item in expanded[0]["sets"]] == [30.0, 90.0]
    assert_roundtrip(day, result)


def test_no_rest_and_unweighted_set_stays_null_not_fake_zero():
    source_set = make_set(weight=None, unit=None, duration=None)
    day = make_day([make_movement(sets=[source_set], rest=None)])

    result = map_plan_day(day)
    work = steps_of(result)[0]

    assert len(steps_of(result)) == 1
    assert work["weightValue"] is None
    assert work["weightValue"] != 0
    assert work["weightUnit"]["unitKey"] == "kilogram"
    assert_roundtrip(day, result)


def test_source_hash_is_stable_and_sensitive_to_real_changes():
    day = make_day()
    reordered = json.loads(json.dumps(day, sort_keys=True))
    left_weight_changed = make_day()
    left_weight_changed["movements"][0]["sets"][0]["left_weight"] = 999
    duration_changed = make_day()
    duration_changed["movements"][0]["sets"][0]["duration_seconds"] = 0
    weight_changed = make_day()
    weight_changed["movements"][0]["sets"][0]["weight"] = 22.5

    assert source_hash(day) == source_hash(reordered)
    assert source_hash(day) == source_hash(left_weight_changed)
    assert source_hash(day) != source_hash(duration_changed)
    assert source_hash(day) != source_hash(weight_changed)


def test_content_hash_ignores_only_date_and_tracks_full_prescription():
    day = make_day([make_movement(), make_movement("卷腹")])
    moved = json.loads(json.dumps(day))
    moved["date"] = "2026-11-11"
    title_changed = json.loads(json.dumps(day))
    title_changed["title"] = "新的标题"
    weight_changed = json.loads(json.dumps(day))
    weight_changed["movements"][0]["sets"][0]["weight"] = 22.5
    reps_changed = json.loads(json.dumps(day))
    reps_changed["movements"][0]["sets"][0]["reps"] = 12
    rest_changed = json.loads(json.dumps(day))
    rest_changed["movements"][0]["rest_seconds"] = 90
    order_changed = json.loads(json.dumps(day))
    order_changed["movements"].reverse()
    other_plan = json.loads(json.dumps(day))
    other_plan["plan_ref"] = "universal:2"

    assert content_hash(day) == content_hash(moved)
    assert source_hash(day) != source_hash(moved)
    assert map_plan_day(moved)["content_hash"] == content_hash(day)
    assert {
        content_hash(title_changed),
        content_hash(weight_changed),
        content_hash(reps_changed),
        content_hash(rest_changed),
        content_hash(order_changed),
        content_hash(other_plan),
    }.isdisjoint({content_hash(day)})


def test_source_identity_is_embedded_and_write_gate_is_closed():
    result = map_plan_day(make_day())

    assert result["source_key"] == "xunji-plan:v1:universal:1:2026-11-10"
    assert result["preview_only"] is True
    assert result["remote_write_eligible"] is False
    assert result["workout"]["workoutName"] == "训记｜胸·三头·腹肌·2｜2026-11-10"
    assert result["source_key"] in result["workout"]["description"]
    assert result["source_hash"] in result["workout"]["description"]


def test_unknown_exercise_rejects_whole_day_instead_of_skipping():
    day = make_day([
        make_movement("不存在的动作"),
        make_movement("哑铃卧推", sets=[make_set(), make_set()]),
    ])

    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(day)

    assert [issue["code"] for issue in caught.value.issues] == ["UNKNOWN_EXERCISE"]
    assert "不存在的动作" in caught.value.issues[0]["message"]


@pytest.mark.parametrize(
    ("movement", "expected_code"),
    [
        ({**make_movement(), "single_side": True}, "SINGLE_SIDE_UNSUPPORTED"),
        ({**make_movement(), "amrap": True}, "AMRAP_UNSUPPORTED"),
        (make_movement(sets=[{**make_set(), "rounds": 2}]), "ROUNDS_UNSUPPORTED"),
        (make_movement(sets=[make_set(unit="lb")]), "UNIT_UNSUPPORTED"),
        (make_movement(sets=[make_set(reps=None)]), "REPS_REQUIRED"),
        (make_movement(sets=[make_set(set_type="superset")]), "SET_TYPE_UNSUPPORTED"),
        (make_movement(sets=[make_set(rest=-1)]), "INVALID_REST"),
        (make_movement(sets=[]), "EMPTY_MOVEMENT"),
    ],
)
def test_unsupported_semantics_are_rejected(movement, expected_code):
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(make_day([movement]))
    assert expected_code in {issue["code"] for issue in caught.value.issues}


def test_real_fixture_parses_and_unknown_actions_are_explicit():
    raw = json.loads((FIXTURES / "plan_get_real.json").read_text(encoding="utf-8"))
    source_day = extract_plan_days(raw)[0]
    day = {"plan_ref": "universal:1", **source_day, "date": source_day["date"].isoformat()}

    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(day)

    unknown = {issue["movement"] for issue in caught.value.issues if issue["code"] == "UNKNOWN_EXERCISE"}
    assert "双杠臂屈伸" in unknown
    assert "杠铃卧推" not in unknown  # P0 已验证项不能被误报为未知。


def test_expand_rejects_complex_repeat_with_multiple_work_steps():
    result = map_plan_day(make_day([make_movement(sets=[make_set(), make_set()])]))
    payload = result["workout"]
    repeat = payload["workoutSegments"][0]["workoutSteps"][0]
    repeat["workoutSteps"].insert(1, dict(repeat["workoutSteps"][0]))

    with pytest.raises(ValueError, match="一个工作步骤"):
        expand_workout(payload)


def test_expand_accepts_garmin_normalized_generic_bench_press():
    day = make_day([make_movement("器械推胸", sets=[make_set(47.5, reps=8)])])
    payload = map_plan_day(day)["workout"]
    work = payload["workoutSegments"][0]["workoutSteps"][0]
    assert work["category"] == "BENCH_PRESS"
    assert work["exerciseName"] == "BENCH_PRESS"

    # Garmin P2 创建后的真实回读会将通用 Bench Press 规范化为空串。
    work["exerciseName"] = ""

    assert source_set_projection(expand_workout(payload)) == source_set_projection(
        day["movements"]
    )


def test_expand_accepts_garmin_normalized_lateral_raise():
    day = make_day([
        make_movement("侧平举", sets=[make_set(7.5, reps=15), make_set(7.5, reps=15)])
    ])
    payload = map_plan_day(day)["workout"]
    repeat = payload["workoutSegments"][0]["workoutSteps"][0]
    work = repeat["workoutSteps"][0]
    assert work["category"] == "LATERAL_RAISE"
    assert work["exerciseName"] == "LATERAL_RAISE"

    # Garmin P3 创建后的真实回读会将 Lateral Raise 规范化为空串。
    work["exerciseName"] = ""

    assert source_set_projection(expand_workout(payload)) == source_set_projection(
        day["movements"]
    )
