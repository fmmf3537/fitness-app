"""训记力量计划到 Garmin 原始 Workout JSON 的纯本地映射。

边界：
- 不导入 Garmin/HTTP 客户端，不访问网络、数据库或文件；
- 未映射、单位/组次语义不支持时收集全部错误并拒绝生成 payload；
- kg 按训记 weight 原值写入 weightValue，left_weight 不参与；
- 有 reps 时忽略源 duration_seconds，不把它当成组间休息；
- 反向展开用于验证组次、重量、次数和休息没有在 RepeatGroupDTO 中丢失。

本模块只负责预览 payload。是否允许上传由上层同步编排单独门禁控制。
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from typing import Any, Iterator

# support_level 只说明证据来源，不代表上层已经开放远端写入。
EXERCISE_WHITELIST: dict[str, dict[str, str]] = {
    "哑铃卧推": {
        "display_name": "Dumbbell Bench Press",
        "category": "BENCH_PRESS",
        "exerciseName": "DUMBBELL_BENCH_PRESS",
        "support_level": "p2_verified",
    },
    "器械推胸": {
        "display_name": "Bench Press",
        "category": "BENCH_PRESS",
        "exerciseName": "BENCH_PRESS",
        "support_level": "p2_verified",
    },
    "上斜哑铃飞鸟": {
        "display_name": "Incline Dumbbell Fly",
        "category": "FLYE",
        "exerciseName": "INCLINE_DUMBBELL_FLYE",
        "support_level": "p2_verified",
    },
    "哑铃臂屈伸": {
        "display_name": "Overhead Dumbbell Triceps Extension",
        "category": "TRICEPS_EXTENSION",
        "exerciseName": "OVERHEAD_DUMBBELL_TRICEPS_EXTENSION",
        "support_level": "p2_verified",
    },
    "绳索过头臂屈伸": {
        "display_name": "Cable Overhead Triceps Extension",
        "category": "TRICEPS_EXTENSION",
        "exerciseName": "CABLE_OVERHEAD_TRICEPS_EXTENSION",
        "support_level": "p2_verified",
    },
    "俄罗斯转体": {
        "display_name": "Russian Twist",
        "category": "CORE",
        "exerciseName": "RUSSIAN_TWIST",
        "support_level": "p2_verified",
    },
    "卷腹": {
        "display_name": "Crunch",
        "category": "CRUNCH",
        "exerciseName": "CRUNCH",
        "support_level": "p2_verified",
    },
    "绳索Pallof推": {
        "display_name": "Cable Core Press",
        "category": "CORE",
        "exerciseName": "CABLE_CORE_PRESS",
        "support_level": "p2_verified",
    },
    "腿举": {
        "display_name": "Leg Press",
        "category": "SQUAT",
        "exerciseName": "LEG_PRESS",
        "support_level": "p3_verified",
    },
    "杠铃深蹲": {
        "display_name": "Barbell Back Squat",
        "category": "SQUAT",
        "exerciseName": "BARBELL_BACK_SQUAT",
        "support_level": "p3_verified",
    },
    "杠铃罗马尼亚硬拉": {
        "display_name": "Romanian Deadlift",
        "category": "DEADLIFT",
        "exerciseName": "ROMANIAN_DEADLIFT",
        "support_level": "p3_verified",
    },
    "史密斯机推举": {
        "display_name": "Smith Machine Overhead Press",
        "category": "SHOULDER_PRESS",
        "exerciseName": "SMITH_MACHINE_OVERHEAD_PRESS",
        "support_level": "p3_verified",
    },
    "哑铃推肩": {
        "display_name": "Dumbbell Shoulder Press",
        "category": "SHOULDER_PRESS",
        "exerciseName": "DUMBBELL_SHOULDER_PRESS",
        "support_level": "p3_verified",
    },
    "侧平举": {
        "display_name": "Lateral Raise",
        "category": "LATERAL_RAISE",
        "exerciseName": "LATERAL_RAISE",
        "support_level": "p3_verified",
    },
    "哑铃上斜俯身侧平举": {
        "display_name": "Incline Reverse Fly",
        "category": "FLYE",
        "exerciseName": "INCLINE_REVERSE_FLYE",
        "support_level": "p3_verified",
    },
    # P0 已在中国区完成创建、更新、日程回读和 FR955 重量显示验证。
    "杠铃卧推": {
        "display_name": "Barbell Bench Press",
        "category": "BENCH_PRESS",
        "exerciseName": "BARBELL_BENCH_PRESS",
        "support_level": "p0_verified",
    },
}

SPORT = {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5}
STEP_WARMUP = {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1}
STEP_INTERVAL = {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3}
STEP_REST = {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5}
STEP_REPEAT = {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
CONDITION_REPS = {
    "conditionTypeId": 10,
    "conditionTypeKey": "reps",
    "displayOrder": 10,
    "displayable": True,
}
CONDITION_TIME = {
    "conditionTypeId": 2,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}
CONDITION_ITERATIONS = {
    "conditionTypeId": 7,
    "conditionTypeKey": "iterations",
    "displayOrder": 7,
    "displayable": False,
}
WEIGHT_KG = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}
MAX_WORKOUT_NAME_LENGTH = 100


class WorkoutMappingError(ValueError):
    """计划不能完整映射；issues 包含所有已发现问题，不静默跳过。"""

    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        message = "；".join(issue["message"] for issue in issues) or "计划无法映射"
        super().__init__(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value: Any) -> float | int | None:
    return float(value) if _is_number(value) else None


def _sets(movement: dict[str, Any]) -> list[dict[str, Any]]:
    sets = movement.get("sets") if movement.get("sets") is not None else movement.get("target_sets")
    return sets or []


def _rest_rule(movement: dict[str, Any], item: dict[str, Any]) -> Any:
    if item.get("rest_seconds") is not None:
        return item.get("rest_seconds")
    set_type = item.get("set_type") or "working"
    key = "warmup_rest_seconds" if set_type == "warmup" else "rest_seconds"
    return movement.get(key)


def canonical_source(plan_day: dict[str, Any], *, plan_ref: str | None = None) -> dict[str, Any]:
    """只保留影响同步判断的来源字段，消除 JSON 键序和无意义元数据影响。"""
    movements = []
    for movement in plan_day.get("movements") or []:
        sets = []
        for item in _sets(movement):
            sets.append(
                {
                    "set_type": item.get("set_type") or "working",
                    "weight": _number(item.get("weight")),
                    "unit": item.get("unit"),
                    "reps": _number(item.get("reps")),
                    "duration_seconds": _number(item.get("duration_seconds")),
                    "rest_seconds": _number(item.get("rest_seconds")),
                    "rounds": item.get("rounds"),
                }
            )
        movements.append(
            {
                "name": (movement.get("name") or "").strip(),
                "rest_seconds": _number(movement.get("rest_seconds")),
                "warmup_rest_seconds": _number(movement.get("warmup_rest_seconds")),
                "single_side": movement.get("single_side") is True,
                "amrap": movement.get("amrap") is True,
                "sets": sets,
            }
        )
    return {
        "plan_ref": plan_ref or plan_day.get("plan_ref"),
        "date": plan_day.get("date"),
        "title": plan_day.get("title"),
        "movements": movements,
    }


def _canonical_hash(canonical: dict[str, Any]) -> str:
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def source_hash(plan_day: dict[str, Any], *, plan_ref: str | None = None) -> str:
    """完整来源哈希：日期变化也必须产生新哈希。"""
    return _canonical_hash(canonical_source(plan_day, plan_ref=plan_ref))


def content_hash(plan_day: dict[str, Any], *, plan_ref: str | None = None) -> str:
    """训练内容哈希：仅排除日期，用于识别同一处方的跨日顺延。"""
    canonical = canonical_source(plan_day, plan_ref=plan_ref)
    canonical.pop("date", None)
    return _canonical_hash(canonical)


def _workout_name(title: str, day: str) -> str:
    return f"训记｜{title}｜{day}"[:MAX_WORKOUT_NAME_LENGTH]


def _work_step(
    order: int,
    *,
    name: str,
    mapping: dict[str, str],
    set_type: str,
    weight: float | None,
    reps: float,
    source_sets: str,
) -> dict[str, Any]:
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(STEP_WARMUP if set_type == "warmup" else STEP_INTERVAL),
        "endCondition": dict(CONDITION_REPS),
        "endConditionValue": reps,
        "targetType": dict(NO_TARGET),
        "category": mapping["category"],
        "exerciseName": mapping["exerciseName"],
        "weightValue": weight,
        "weightUnit": dict(WEIGHT_KG),
        "description": f"{name}｜源组 {source_sets}",
    }


def _rest_step(order: int, seconds: float) -> dict[str, Any]:
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(STEP_REST),
        "endCondition": dict(CONDITION_TIME),
        "endConditionValue": seconds,
        "targetType": dict(NO_TARGET),
    }


def _repeat_step(order: int, count: int, children: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": dict(STEP_REPEAT),
        "numberOfIterations": count,
        "smartRepeat": False,
        "endCondition": dict(CONDITION_ITERATIONS),
        "endConditionValue": float(count),
        "workoutSteps": children,
    }


def map_plan_day(plan_day: dict[str, Any], *, plan_ref: str | None = None) -> dict[str, Any]:
    """返回完整本地预览与 Workout payload；有任何问题则抛出全部 issues。"""
    issues: list[dict[str, Any]] = []
    day = plan_day.get("date")
    try:
        date.fromisoformat(day)
    except (TypeError, ValueError):
        issues.append({"code": "INVALID_DATE", "message": f"无效训练日期：{day}"})
    plan_ref = plan_ref or plan_day.get("plan_ref")
    if not plan_ref:
        issues.append({"code": "MISSING_PLAN_REF", "message": "缺少 plan_ref"})
    title = (plan_day.get("title") or "未命名训练").strip()
    source_movements = plan_day.get("movements") or []
    if not source_movements:
        issues.append({"code": "EMPTY_WORKOUT", "message": "训练日没有动作"})

    # 每项是 {name, mapping, groups:[{count, set_type, weight, reps, rest, source_start/end}]}
    mapped_movements: list[dict[str, Any]] = []
    for movement_index, movement in enumerate(source_movements, 1):
        name = (movement.get("name") or "").strip()
        mapping = EXERCISE_WHITELIST.get(name)
        if mapping is None:
            issues.append(
                {
                    "code": "UNKNOWN_EXERCISE",
                    "movement": name or f"第 {movement_index} 个动作",
                    "message": f"未映射动作：{name or movement_index}",
                }
            )
            continue
        if movement.get("single_side") is True:
            issues.append({"code": "SINGLE_SIDE_UNSUPPORTED", "movement": name, "message": f"{name}：单边动作未支持"})
        if movement.get("amrap") is True:
            issues.append({"code": "AMRAP_UNSUPPORTED", "movement": name, "message": f"{name}：AMRAP 未支持"})
        sets = _sets(movement)
        if not sets:
            issues.append({"code": "EMPTY_MOVEMENT", "movement": name, "message": f"{name}：没有组次"})
            continue

        normalized_sets: list[dict[str, Any]] = []
        for set_number, item in enumerate(sets, 1):
            set_type = item.get("set_type") or "working"
            prefix = f"{name} 第 {set_number} 组"
            if set_type not in {"working", "warmup"}:
                issues.append({"code": "SET_TYPE_UNSUPPORTED", "movement": name, "set_number": set_number, "message": f"{prefix}：组类型 {set_type} 未支持"})
            reps = _number(item.get("reps"))
            if reps is None or reps <= 0 or not reps.is_integer():
                issues.append({"code": "REPS_REQUIRED", "movement": name, "set_number": set_number, "message": f"{prefix}：需要正整数 reps，计时组首版不支持"})
            weight_raw = item.get("weight")
            weight = _number(weight_raw)
            if weight_raw is not None and (weight is None or weight < 0):
                issues.append({"code": "INVALID_WEIGHT", "movement": name, "set_number": set_number, "message": f"{prefix}：重量无效"})
            unit = item.get("unit")
            if weight_raw is not None and unit != "kg":
                issues.append({"code": "UNIT_UNSUPPORTED", "movement": name, "set_number": set_number, "message": f"{prefix}：单位 {unit} 未支持"})
            rest = _number(_rest_rule(movement, item))
            if _rest_rule(movement, item) is not None and (rest is None or rest < 0):
                issues.append({"code": "INVALID_REST", "movement": name, "set_number": set_number, "message": f"{prefix}：休息秒数无效"})
            if item.get("rounds") is not None:
                issues.append({"code": "ROUNDS_UNSUPPORTED", "movement": name, "set_number": set_number, "message": f"{prefix}：rounds/组合组未支持"})
            normalized_sets.append(
                {
                    "set_type": set_type,
                    "weight": weight,
                    "reps": reps,
                    # 有 reps 时 duration_seconds 只参与 source_hash，不参与步骤/休息/合并。
                    "rest": rest,
                    "source_number": set_number,
                }
            )

        groups: list[dict[str, Any]] = []
        for item in normalized_sets:
            signature = (item["set_type"], item["weight"], item["reps"], item["rest"])
            if groups and groups[-1]["signature"] == signature:
                groups[-1]["count"] += 1
                groups[-1]["source_end"] = item["source_number"]
            else:
                groups.append(
                    {
                        **item,
                        "signature": signature,
                        "count": 1,
                        "source_start": item["source_number"],
                        "source_end": item["source_number"],
                    }
                )
        mapped_movements.append({"name": name, "mapping": mapping, "groups": groups})

    if issues:
        raise WorkoutMappingError(issues)

    hash_value = source_hash(plan_day, plan_ref=plan_ref)
    source_key = f"xunji-plan:v1:{plan_ref}:{day}"
    steps: list[dict[str, Any]] = []
    preview_movements: list[dict[str, Any]] = []
    order = 1
    total_sets = 0
    warmup_sets = 0
    repeat_groups = 0
    rest_seconds = 0.0
    for movement in mapped_movements:
        group_previews = []
        for group in movement["groups"]:
            count = group["count"]
            total_sets += count
            warmup_sets += count if group["set_type"] == "warmup" else 0
            rest_seconds += (group["rest"] or 0.0) * count
            source_range = (
                str(group["source_start"])
                if group["source_start"] == group["source_end"]
                else f"{group['source_start']}-{group['source_end']}"
            )
            work = _work_step(
                order + 1 if count > 1 else order,
                name=movement["name"],
                mapping=movement["mapping"],
                set_type=group["set_type"],
                weight=group["weight"],
                reps=group["reps"],
                source_sets=source_range,
            )
            children = [work]
            if group["rest"] is not None and group["rest"] > 0:
                children.append(_rest_step(order + 2 if count > 1 else order + 1, group["rest"]))
            if count > 1:
                repeat_groups += 1
                steps.append(_repeat_step(order, count, children))
                order += 1 + len(children)
            else:
                steps.extend(children)
                order += len(children)
            group_previews.append(
                {
                    "count": count,
                    "source_sets": source_range,
                    "set_type": group["set_type"],
                    "weight_kg": group["weight"],
                    "reps": group["reps"],
                    "rest_seconds": group["rest"],
                }
            )
        preview_movements.append(
            {
                "name": movement["name"],
                "garmin_display_name": movement["mapping"]["display_name"],
                "category": movement["mapping"]["category"],
                "exerciseName": movement["mapping"]["exerciseName"],
                "support_level": movement["mapping"]["support_level"],
                "groups": group_previews,
            }
        )

    payload = {
        "sportType": dict(SPORT),
        "subSportType": None,
        "workoutName": _workout_name(title, day),
        "description": f"source_key={source_key}; source_hash={hash_value}; managed_by=fitness-app",
        "estimatedDistanceUnit": {"unitKey": None},
        "workoutSegments": [
            {"segmentOrder": 1, "sportType": dict(SPORT), "workoutSteps": steps}
        ],
        "avgTrainingSpeed": None,
        # 源计划没有动作做功时长；这里仅给休息总时长，不虚构做功秒数。
        "estimatedDurationInSecs": int(rest_seconds),
        "estimatedDistanceInMeters": 0,
        "estimateType": None,
    }
    return {
        "source_key": source_key,
        "source_hash": hash_value,
        "content_hash": content_hash(plan_day, plan_ref=plan_ref),
        "preview_only": True,
        "remote_write_eligible": False,
        "workout": payload,
        "movements": preview_movements,
        "stats": {
            "movements": len(mapped_movements),
            "sets": total_sets,
            "warmup_sets": warmup_sets,
            "working_sets": total_sets - warmup_sets,
            "repeat_groups": repeat_groups,
            "top_level_steps": len(steps),
            "rest_seconds": int(rest_seconds),
        },
    }


def _walk_work_steps(steps: list[dict[str, Any]]) -> Iterator[tuple[dict[str, Any], int, float | None]]:
    """展开当前映射器生成的 direct/repeat 结构，拒绝不认识的复杂结构。"""
    index = 0
    while index < len(steps):
        step = steps[index]
        step_type = step.get("type")
        if step_type == "RepeatGroupDTO":
            count = step.get("numberOfIterations")
            if not isinstance(count, int) or count < 1:
                raise ValueError("RepeatGroupDTO 的 numberOfIterations 无效")
            children = step.get("workoutSteps") or []
            work = [child for child in children if child.get("category") or child.get("exerciseName")]
            rests = [child for child in children if (child.get("stepType") or {}).get("stepTypeKey") == "rest"]
            if len(work) != 1 or len(rests) > 1 or len(children) != len(work) + len(rests):
                raise ValueError("仅支持每组一个工作步骤和可选休息步骤")
            rest_value = rests[0].get("endConditionValue") if rests else None
            yield work[0], count, rest_value
            index += 1
            continue
        if step_type == "ExecutableStepDTO" and (step.get("category") or step.get("exerciseName")):
            rest_value = None
            if index + 1 < len(steps):
                following = steps[index + 1]
                if (following.get("stepType") or {}).get("stepTypeKey") == "rest":
                    rest_value = following.get("endConditionValue")
                    index += 1
            yield step, 1, rest_value
            index += 1
            continue
        raise ValueError(f"无法反向展开的步骤：{step_type}")


def expand_workout(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """反向展开为动作和逐组序列，用于与 source_set_projection 对账。"""
    reverse = {
        (item["category"], item["exerciseName"]): name for name, item in EXERCISE_WHITELIST.items()
    }
    # P2/P3 实测：Garmin 创建后会把通用 Bench Press 和 Lateral Raise 的
    # exerciseName 规范化为空串，category 保持不变；只接受已观测的精确别名。
    reverse[("BENCH_PRESS", "")] = "器械推胸"
    reverse[("LATERAL_RAISE", "")] = "侧平举"
    segments = payload.get("workoutSegments") or []
    if len(segments) != 1:
        raise ValueError("仅支持一个 workoutSegment")
    expanded: list[dict[str, Any]] = []
    for work, count, rest in _walk_work_steps(segments[0].get("workoutSteps") or []):
        pair = (work.get("category"), work.get("exerciseName"))
        name = reverse.get(pair)
        if name is None:
            raise ValueError(f"未知 Garmin 动作枚举：{pair}")
        if work.get("endCondition", {}).get("conditionTypeKey") != "reps":
            raise ValueError("反向展开仅支持 reps 工作步骤")
        step_type = work.get("stepType", {}).get("stepTypeKey")
        if step_type not in {"warmup", "interval"}:
            raise ValueError(f"未知工作步骤类型：{step_type}")
        set_type = "warmup" if step_type == "warmup" else "working"
        if not expanded or expanded[-1]["name"] != name:
            expanded.append({"name": name, "sets": []})
        for _ in range(count):
            expanded[-1]["sets"].append(
                {
                    "set_type": set_type,
                    "weight": work.get("weightValue"),
                    "unit": "kg",
                    "reps": work.get("endConditionValue"),
                    "rest_seconds": rest,
                    "duration_seconds": None,
                    "rounds": None,
                }
            )
    return expanded


def source_set_projection(movements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """提取必须往返一致的字段；源 duration_seconds/left_weight 故意不在其内。"""
    result = []
    for movement in movements:
        name = (movement.get("name") or "").strip()
        for item in _sets(movement):
            result.append(
                {
                    "name": name,
                    "set_type": item.get("set_type") or "working",
                    "weight": _number(item.get("weight")),
                    "unit": item.get("unit") or "kg",
                    "reps": _number(item.get("reps")),
                    "rest_seconds": _number(_rest_rule(movement, item)),
                }
            )
    return result
