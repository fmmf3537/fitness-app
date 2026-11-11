"""生成用户确认的 Garmin 动作白名单和逐日逐组本地预览。

只读本地 SQLite 与字典候选，零网络请求，不生成远端对象，不调用 Garmin。
运行（项目根目录）：
  outputs/garmin_p0/newlib-venv/Scripts/python.exe scripts/build_garmin_sync_preview.py
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from analyze_garmin_exercise_mappings import MAPPINGS
from garminconnect.exercises import BY_NAME

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "outputs" / "garmin_p0"
COVERAGE_PATH = OUTPUT_DIR / "movement_coverage.json"
WHITELIST_JSON_PATH = OUTPUT_DIR / "garmin_exercise_whitelist.json"
WHITELIST_MD_PATH = OUTPUT_DIR / "garmin_exercise_whitelist.md"
PREVIEW_JSON_PATH = OUTPUT_DIR / "daily_sync_preview.json"
PREVIEW_MD_PATH = OUTPUT_DIR / "daily_sync_preview.md"
DATABASE_PATH = ROOT / "backend" / "data" / "app.db"

WEIGHT_KG = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def day_date(day: dict[str, Any]) -> str | None:
    return day.get("date") or day.get("datestr")


def day_title(day: dict[str, Any]) -> str:
    return day.get("title") or (day.get("workout") or {}).get("name") or "未命名训练"


def day_movements(day: dict[str, Any]) -> list[dict[str, Any]]:
    return day.get("movements") or (day.get("workout") or {}).get("movements") or []


def rest_rule(movement: dict[str, Any], item: dict[str, Any]) -> float | int | None:
    if item.get("rest_seconds") is not None:
        return item["rest_seconds"]
    set_type = item.get("set_type") or "working"
    key = "warmup_rest_seconds" if set_type == "warmup" else "rest_seconds"
    return movement.get(key)


def build_set_preview(
    movement: dict[str, Any], item: dict[str, Any], set_number: int, mapping: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    set_type = item.get("set_type") or "working"
    reps = item.get("reps")
    weight = item.get("weight")
    unit = item.get("unit")
    if set_type not in {"working", "warmup"}:
        blockers.append(f"不支持的组类型：{set_type}")
    if not isinstance(reps, (int, float)) or reps <= 0:
        blockers.append("缺少有效次数，首版不按计时动作猜测")
    if unit != "kg":
        blockers.append(f"不支持的重量单位：{unit}")
    if not isinstance(weight, (int, float)) or weight < 0:
        blockers.append("缺少有效 kg 重量")
    if movement.get("single_side") is True:
        blockers.append("单边动作尚未验证")
    if movement.get("amrap") is True:
        blockers.append("AMRAP 尚未支持")
    if item.get("rounds") is not None:
        blockers.append("rounds/组合组尚未支持")

    rest = rest_rule(movement, item)
    rec = mapping["recommended"]
    step = {
        "previewOnly": True,
        "validationStatus": "pending_end_to_end",
        "stepTypeKey": "warmup" if set_type == "warmup" else "interval",
        "category": rec["category"],
        "exerciseName": rec["exerciseName"],
        "endCondition": "reps" if isinstance(reps, (int, float)) and reps > 0 else None,
        "endConditionValue": float(reps) if isinstance(reps, (int, float)) else None,
        "targetType": NO_TARGET,
        "weightValue": float(weight) if isinstance(weight, (int, float)) else None,
        "weightUnit": WEIGHT_KG if isinstance(weight, (int, float)) else None,
    }
    preview = {
        "setNumber": set_number,
        "setType": set_type,
        "weightKg": float(weight) if isinstance(weight, (int, float)) else None,
        "reps": reps,
        "restRuleAfterSetSeconds": rest,
        "sourceDurationSeconds": item.get("duration_seconds"),
        "sourceDurationUsedAsRest": False,
        "leftWeightUsed": False,
        "garminStepPreview": step,
        "restStepPreview": (
            {"endCondition": "time", "seconds": rest, "validationStatus": "pending_end_to_end"}
            if isinstance(rest, (int, float)) and rest > 0
            else None
        ),
        "blockers": blockers,
    }
    return preview, blockers


def build_day_preview(plan_ref: str, plan_name: str, day: dict[str, Any]) -> dict[str, Any]:
    date = day_date(day)
    source_key = f"xunji-plan:v1:{plan_ref}:{date}"
    movements = []
    day_blockers = ["完整 Workout 创建、回读和手表显示尚未验收"]
    for movement in day_movements(day):
        name = (movement.get("name") or "").strip()
        mapping = MAPPINGS.get(name)
        if mapping is None:
            raise ValueError(f"出现未进入白名单的动作：{date} / {name}")
        if mapping["level"] != "clear":
            raise ValueError(f"动作语义仍未确认：{date} / {name}")
        sets = movement.get("sets") if movement.get("sets") is not None else movement.get("target_sets")
        set_previews = []
        movement_blockers = []
        for index, item in enumerate(sets or [], 1):
            preview, blockers = build_set_preview(movement, item, index, mapping)
            set_previews.append(preview)
            movement_blockers.extend(blockers)
        if any(item["setType"] == "warmup" for item in set_previews):
            movement_blockers.append("热身 stepType 与热身休息尚需完整回读和手表验收")
        rec = mapping["recommended"]
        movements.append(
            {
                "name": name,
                "garminDisplayName": rec["name"],
                "category": rec["category"],
                "exerciseName": rec["exerciseName"],
                "mappingStatus": "user_confirmed_catalog_pending_end_to_end",
                "mappingNote": rec.get("note") or "",
                "sets": set_previews,
                "blockers": sorted(set(movement_blockers)),
            }
        )
        day_blockers.extend(movement_blockers)
    return {
        "date": date,
        "title": day_title(day),
        "planRef": plan_ref,
        "planName": plan_name,
        "sourceKey": source_key,
        "sourceHash": canonical_hash(day),
        "workoutNamePreview": f"训记｜{day_title(day)}｜{date}",
        "previewOnly": True,
        "remoteWritePerformed": False,
        "remoteWriteEligible": False,
        "linkedWorkoutId": None,
        "linkedWorkoutScheduleId": None,
        "blockers": sorted(set(day_blockers)),
        "totals": {
            "movements": len(movements),
            "sets": sum(len(m["sets"]) for m in movements),
            "warmupSets": sum(s["setType"] == "warmup" for m in movements for s in m["sets"]),
            "workingSets": sum(s["setType"] == "working" for m in movements for s in m["sets"]),
        },
        "movements": movements,
    }


def load_days() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    coverage = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
    wanted = set(coverage["analysis_dates"])
    uri = f"file:{DATABASE_PATH.resolve().as_posix()}?mode=ro"
    found: list[dict[str, Any]] = []
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT plan_ref, plan_json FROM xunji_plan "
            "WHERE plan_json IS NOT NULL AND plan_json <> '' ORDER BY id"
        ).fetchall()
    for plan_ref, raw_json in rows:
        data = json.loads(raw_json)
        plan = data.get("plan") or {}
        status = plan.get("status") or data.get("status")
        if status == "ended":
            continue
        plan_name = plan.get("title") or plan.get("name") or data.get("title") or data.get("name")
        for day in data.get("days") or []:
            if day_date(day) in wanted and day_movements(day):
                found.append(build_day_preview(plan_ref, plan_name, day))
    if {day["date"] for day in found} != wanted or len(found) != len(wanted):
        raise ValueError("训练日缺失或同一天出现多个计划，停止生成预览")
    found.sort(key=lambda day: day["date"])
    return coverage, found


def write_whitelist(generated_at: str) -> dict[str, Any]:
    rows = []
    for name, mapping in MAPPINGS.items():
        rec = mapping["recommended"]
        found = BY_NAME.get(rec["name"])
        if not found or (found["category"], found["exercise"]) != (
            rec["category"], rec["exerciseName"]
        ):
            raise ValueError(f"白名单动作不在字典中：{name}")
        rows.append(
            {
                "xunjiName": name,
                "garminDisplayName": rec["name"],
                "category": rec["category"],
                "exerciseName": rec["exerciseName"],
                "status": "user_confirmed_catalog_pending_end_to_end",
                "userConfirmed": True,
                "dictionaryVerified": True,
                "endToEndVerified": False,
                "remoteWriteEligible": False,
                "weightStrategy": "xunji_weight_kg_raw_value_left_weight_ignored",
                "note": rec.get("note") or "",
            }
        )
    result = {
        "schema": "fitness-app.garmin-exercise-whitelist.v1",
        "generatedAt": generated_at,
        "confirmedAt": "2026-11-10",
        "scope": "当前训记计划中的 15 个动作",
        "networkRequests": 0,
        "remoteWritePerformed": False,
        "status": "mapping_confirmed_pending_end_to_end",
        "confirmation": {
            "哑铃臂屈伸": "站姿过头 → Overhead Dumbbell Triceps Extension",
            "器械推胸": "接受通用 Bench Press",
            "绳索Pallof推": "接受 Cable Core Press",
            "哑铃上斜俯身侧平举": "上斜反向飞鸟 → Incline Reverse Fly",
        },
        "weightRule": "weightValue=float(weight)，kg 原值不乘 1000；left_weight 不参与",
        "movements": rows,
    }
    WHITELIST_JSON_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Garmin 动作白名单（用户确认版）",
        "",
        f"> 生成时间：{generated_at}  ",
        "> 状态：15 个动作映射已确认，尚待完整 Workout 创建、回读和手表端到端验收。  ",
        "> 本次零网络请求，未写入 Garmin；`remoteWriteEligible=false` 是故意保留的安全门禁。",
        "",
        "| 训记动作 | Garmin 名称 | category | exerciseName | 状态 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['xunjiName']} | {row['garminDisplayName']} | `{row['category']}` | "
            f"`{row['exerciseName']}` | 用户确认，待端到端验证 |"
        )
    lines += [
        "",
        "## 统一重量规则",
        "",
        "- `weightValue=float(weight)`，kg 原值传递，**不乘 1000**。",
        "- `left_weight` 不参与计算。",
        "- 白名单只解决动作语义，不代表热身、休息、完整训练或手表显示已经验证。",
    ]
    WHITELIST_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def write_preview(coverage: dict[str, Any], days: list[dict[str, Any]], generated_at: str) -> None:
    totals = {
        "trainingDays": len(days),
        "movements": len({m["name"] for day in days for m in day["movements"]}),
        "sets": sum(day["totals"]["sets"] for day in days),
        "warmupSets": sum(day["totals"]["warmupSets"] for day in days),
        "workingSets": sum(day["totals"]["workingSets"] for day in days),
    }
    baseline = coverage["totals"]
    assert totals["trainingDays"] == baseline["training_days"]
    assert totals["movements"] == baseline["movements"]
    assert totals["sets"] == baseline["sets"]
    assert totals["warmupSets"] == baseline["warmup_sets"]
    assert totals["workingSets"] == baseline["working_sets"]
    result = {
        "schema": "fitness-app.garmin-daily-sync-preview.v1",
        "generatedAt": generated_at,
        "asOf": coverage["as_of"],
        "networkRequests": 0,
        "remoteWritePerformed": False,
        "status": "preview_only_pending_end_to_end",
        "totals": totals,
        "rules": {
            "sets": "逐组完整展示，不用第一组代表全部，不在本预览中合并重复组",
            "weight": "weightValue 使用训记 weight 的 kg 原值，不乘 1000；left_weight 不参与",
            "endCondition": "有 reps 时使用 reps；源 duration_seconds 仅留痕，不作为休息",
            "rest": "组级 rest_seconds → 动作级 rest_seconds；热身使用 warmup_rest_seconds",
            "writeGate": "白名单确认不等于允许上传；完整创建、回读和手表验收前禁止远端写入",
        },
        "days": days,
    }
    PREVIEW_JSON_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Garmin 逐日同步预览（本地只读）",
        "",
        f"> 生成时间：{generated_at}  ",
        "> 本次零网络请求，未创建、更新、安排或删除任何 Garmin 内容。",
        "",
        "## 结论",
        "",
        f"- 15 个动作映射均已确认，覆盖 **{totals['trainingDays']} 个训练日、{totals['sets']} 组**。",
        f"- 正式组 {totals['workingSets']}，热身组 {totals['warmupSets']}；以下逐组完整列出。",
        "- 当前仍是 `preview_only_pending_end_to_end`，不是已同步，也未开放远端写入门禁。",
        "",
        "## 预览规则",
        "",
        "- 重量使用训记 `weight` 的 kg 原值，不乘 1000；`left_weight` 不参与。",
        "- 有次数时使用 `reps`；源 `duration_seconds` 仅留痕，不作为组间休息。",
        "- 休息采用组级 `rest_seconds` → 动作级 `rest_seconds`；热身采用 `warmup_rest_seconds`。",
        "- 本预览按原始 51 组展示，不在此处合并重复组；生产映射器需另做反向展开测试。",
        "- 末组休息、热身步骤和完整训练结构仍须通过创建后回读及 FR955 显示验收。",
    ]
    for day in days:
        t = day["totals"]
        lines += [
            "",
            f"## {day['date']}｜{day['title']}",
            "",
            f"- 计划：{day['planName']} (`{day['planRef']}`)",
            f"- 规模：{t['movements']} 个动作、{t['sets']} 组（热身 {t['warmupSets']} / 正式 {t['workingSets']}）",
            f"- Workout 名称预览：`{day['workoutNamePreview']}`",
            f"- `source_key`：`{day['sourceKey']}`",
            f"- `source_hash`：`{day['sourceHash']}`",
            "- 远端关联：未关联；本预览没有查询或修改远端对象。",
        ]
        for movement in day["movements"]:
            lines += [
                "",
                f"### {movement['name']} → {movement['garminDisplayName']}",
                "",
                f"`{movement['category']}` / `{movement['exerciseName']}`",
                "",
                "| 组 | 类型 | 重量 kg | 次数 | 休息规则（秒） | Garmin 工作步骤预览 |",
                "|---:|---|---:|---:|---:|---|",
            ]
            for item in movement["sets"]:
                rest = item["restRuleAfterSetSeconds"]
                step = item["garminStepPreview"]
                set_type = "热身" if item["setType"] == "warmup" else "正式"
                lines.append(
                    f"| {item['setNumber']} | {set_type} | {item['weightKg']:g} | {item['reps']:g} | "
                    f"{rest if rest is not None else '—'} | `{step['stepTypeKey']}` / reps / "
                    f"weightValue={step['weightValue']:g} |"
                )
            if movement["blockers"]:
                lines += ["", "待验证：" + "；".join(movement["blockers"])]
    lines += [
        "",
        "## 上门禁",
        "",
        "两天均保持 `remoteWriteEligible=false`。下一步若做真实 P1，只能先创建专用测试训练，完成回读和手表验收后再决定是否开放整日同步。",
    ]
    PREVIEW_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    generated_at = datetime.now().isoformat(timespec="seconds")
    coverage, days = load_days()
    write_whitelist(generated_at)
    write_preview(coverage, days, generated_at)
    print(
        json.dumps(
            {
                "whitelistMovements": len(MAPPINGS),
                "trainingDays": len(days),
                "sets": sum(day["totals"]["sets"] for day in days),
                "networkRequests": 0,
                "remoteWritePerformed": False,
            },
            ensure_ascii=False,
        )
    )
    for path in (WHITELIST_JSON_PATH, WHITELIST_MD_PATH, PREVIEW_JSON_PATH, PREVIEW_MD_PATH):
        print(f"OUTPUT={path}")


if __name__ == "__main__":
    main()
