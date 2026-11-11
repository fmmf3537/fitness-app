"""离线合并训记动作、Garmin 动作字典和现有 Workout 只读结果。

不访问训记或 Garmin 网络接口。字典候选不等于创建/回读/手表实测。
运行（项目根目录）：
  outputs/garmin_p0/newlib-venv/Scripts/python.exe \
    scripts/analyze_garmin_exercise_mappings.py
"""
from __future__ import annotations

import json
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from garminconnect.exercises import BY_NAME, EXERCISES

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "outputs" / "garmin_p0"
COVERAGE_PATH = OUTPUT_DIR / "movement_coverage.json"
EXISTING_PATH = OUTPUT_DIR / "existing_workout_mappings.json"
JSON_PATH = OUTPUT_DIR / "exercise_mapping_candidates.json"
REPORT_PATH = OUTPUT_DIR / "exercise_mapping_candidates.md"


def option(name: str, category: str, exercise: str, note: str = "") -> dict[str, str]:
    return {"name": name, "category": category, "exerciseName": exercise, "note": note}


# 这是人工维护的语义候选，不是 Garmin 返回的中文映射。
# clear：中文语义与候选较直接；ambiguous：器械、姿势或显示名称仍需用户选择。
MAPPINGS: dict[str, dict[str, Any]] = {
    "哑铃卧推": {
        "level": "clear",
        "recommended": option("Dumbbell Bench Press", "BENCH_PRESS", "DUMBBELL_BENCH_PRESS"),
    },
    "器械推胸": {
        "level": "clear",
        "recommended": option(
            "Bench Press", "BENCH_PRESS", "BENCH_PRESS", "用户已接受通用 Bench Press"
        ),
    },
    "上斜哑铃飞鸟": {
        "level": "clear",
        "recommended": option("Incline Dumbbell Fly", "FLYE", "INCLINE_DUMBBELL_FLYE"),
    },
    "哑铃臂屈伸": {
        "level": "clear",
        "recommended": option(
            "Overhead Dumbbell Triceps Extension",
            "TRICEPS_EXTENSION",
            "OVERHEAD_DUMBBELL_TRICEPS_EXTENSION",
            "用户已确认站姿过头",
        ),
    },
    "绳索过头臂屈伸": {
        "level": "clear",
        "recommended": option(
            "Cable Overhead Triceps Extension",
            "TRICEPS_EXTENSION",
            "CABLE_OVERHEAD_TRICEPS_EXTENSION",
        ),
    },
    "俄罗斯转体": {
        "level": "clear",
        "recommended": option("Russian Twist", "CORE", "RUSSIAN_TWIST"),
    },
    "卷腹": {
        "level": "clear",
        "recommended": option("Crunch", "CRUNCH", "CRUNCH"),
    },
    "绳索Pallof推": {
        "level": "clear",
        "recommended": option(
            "Cable Core Press", "CORE", "CABLE_CORE_PRESS", "用户已接受 Cable Core Press"
        ),
    },
    "腿举": {
        "level": "clear",
        "recommended": option("Leg Press", "SQUAT", "LEG_PRESS"),
    },
    "杠铃深蹲": {
        "level": "clear",
        "recommended": option(
            "Barbell Back Squat", "SQUAT", "BARBELL_BACK_SQUAT", "按常规杠铃颈后深蹲理解"
        ),
    },
    "杠铃罗马尼亚硬拉": {
        "level": "clear",
        "recommended": option("Romanian Deadlift", "DEADLIFT", "ROMANIAN_DEADLIFT"),
    },
    "史密斯机推举": {
        "level": "clear",
        "recommended": option(
            "Smith Machine Overhead Press",
            "SHOULDER_PRESS",
            "SMITH_MACHINE_OVERHEAD_PRESS",
            "按腿·肩日中的肩上推举理解",
        ),
    },
    "哑铃推肩": {
        "level": "clear",
        "recommended": option(
            "Dumbbell Shoulder Press", "SHOULDER_PRESS", "DUMBBELL_SHOULDER_PRESS"
        ),
    },
    "侧平举": {
        "level": "clear",
        "recommended": option(
            "Lateral Raise", "LATERAL_RAISE", "LATERAL_RAISE", "采用与中文名称一致的通用项"
        ),
        "alternatives": [
            option(
                "Dumbbell Lateral Raise",
                "LATERAL_RAISE",
                "DUMBBELL_LATERAL_RAISE",
                "若希望 Garmin 明确显示哑铃，可在白名单中改选此项",
            )
        ],
    },
    "哑铃上斜俯身侧平举": {
        "level": "clear",
        "recommended": option(
            "Incline Reverse Fly", "FLYE", "INCLINE_REVERSE_FLYE", "用户已确认上斜反向飞鸟"
        ),
    },
}


def main() -> None:
    coverage = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
    existing = json.loads(EXISTING_PATH.read_text(encoding="utf-8"))
    if existing.get("status") != "success":
        raise SystemExit("现有 Workout 只读检查尚未成功，拒绝把空结果当成零覆盖")

    coverage_rows = {row["name"]: row for row in coverage["movements"]}
    if set(coverage_rows) != set(MAPPINGS):
        missing = sorted(set(coverage_rows) - set(MAPPINGS))
        stale = sorted(set(MAPPINGS) - set(coverage_rows))
        raise SystemExit(f"动作清单已变化；缺少={missing}，多余={stale}")

    observed_pairs = {
        (row.get("category"), row.get("exerciseName"))
        for row in existing.get("uniqueMappings") or []
    }
    rows: list[dict[str, Any]] = []
    for name, source in coverage_rows.items():
        mapping = MAPPINGS[name]
        recommended = mapping["recommended"]
        candidates = [recommended, *mapping.get("alternatives", [])]
        for candidate in candidates:
            found = BY_NAME.get(candidate["name"])
            expected = (candidate["category"], candidate["exerciseName"])
            actual = (found["category"], found["exercise"]) if found else None
            if actual != expected:
                raise SystemExit(f"字典候选不匹配：{name} / {candidate['name']} / {actual}")

        pair = (recommended["category"], recommended["exerciseName"])
        observed = pair in observed_pairs
        if observed:
            status = "existing_workout_verified"
        elif mapping["level"] == "clear":
            status = "catalog_candidate"
        else:
            status = "ambiguous"
        rows.append(
            {
                "name": name,
                "dates": source["dates"],
                "totalSets": source["total_sets"],
                "status": status,
                "recommended": recommended,
                "alternatives": mapping.get("alternatives", []),
                "question": mapping.get("question"),
                "existingWorkoutObserved": observed,
                "dictionaryVerified": True,
                "endToEndVerified": False,
            }
        )

    rows.sort(key=lambda row: (row["dates"][0], list(coverage_rows).index(row["name"])))
    totals = {
        "movements": len(rows),
        "sets": sum(row["totalSets"] for row in rows),
        "existingWorkoutVerifiedMovements": sum(
            row["status"] == "existing_workout_verified" for row in rows
        ),
        "catalogClearMovements": sum(row["status"] == "catalog_candidate" for row in rows),
        "ambiguousMovements": sum(row["status"] == "ambiguous" for row in rows),
    }
    totals["catalogClearSets"] = sum(
        row["totalSets"] for row in rows if row["status"] == "catalog_candidate"
    )
    totals["catalogClearMovementPct"] = round(
        100 * totals["catalogClearMovements"] / totals["movements"], 1
    )
    totals["catalogClearSetPct"] = round(
        100 * totals["catalogClearSets"] / totals["sets"], 1
    )
    result = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "asOf": coverage["as_of"],
        "networkRequests": 0,
        "dictionary": {
            "garminconnectVersion": version("garminconnect"),
            "exerciseRows": len(EXERCISES),
            "categories": len({row["category"] for row in EXERCISES}),
            "source": "Garmin Connect Workout editor catalog bundled in garminconnect",
        },
        "existingWorkoutCheck": {
            "checkedAt": existing["checkedAt"],
            "workoutCount": existing["workoutCount"],
            "strengthDetailsRead": existing["strengthDetailsRead"],
            "uniqueMappings": existing["uniqueMappings"],
        },
        "totals": totals,
        "importantDistinction": (
            "existing_workout_verified 仅表示推荐枚举在中国区现有 Workout 中实际返回；"
            "catalog_candidate 仅表示字典存在且语义较明确；ambiguous 仍需用户选择。"
            "三者都不等于当前训记整日训练已完成创建、回读或手表验证。"
        ),
        "movements": rows,
        "manualSamplePolicy": {
            "all15Required": False,
            "currentRecommendation": "15 个动作语义均已明确，不需要为它们逐个手工建样例。",
            "fallbackOnly": "仅在首次整日创建/回读与预期不符时，为对应单个动作补手工样例。",
        },
    }
    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    status_labels = {
        "existing_workout_verified": "现有 Workout 实测",
        "catalog_candidate": "字典明确候选",
        "ambiguous": "待确认",
    }
    lines = [
        "# 训记动作 → Garmin 动作映射候选",
        "",
        f"> 训练计划基准日：{result['asOf']}  ",
        f"> 字典：`garminconnect {result['dictionary']['garminconnectVersion']}`，"
        f"{len(EXERCISES)} 个动作、{result['dictionary']['categories']} 个类别。  ",
        f"> 现有 Workout 只读检查：{existing['checkedAt']}，中国区。  ",
        "> 本报告的“字典明确候选”不是创建、回读或手表实测；本次没有写入 Garmin。",
        "",
        "## 结论",
        "",
        f"- 当前 15 个动作中，现有 Workout 直接覆盖 **{totals['existingWorkoutVerifiedMovements']}/15**。"
        "唯一已有力量动作是杠铃卧推，不等同于哑铃卧推。",
        f"- 字典可给出较明确候选 **{totals['catalogClearMovements']}/15（{totals['catalogClearMovementPct']}%）**，"
        f"覆盖 **{totals['catalogClearSets']}/{totals['sets']} 组（{totals['catalogClearSetPct']}%）**。",
        f"- 仍有 **{totals['ambiguousMovements']} 个**动作需要选择语义或确认是否接受通用显示名。",
        "- 用户已确认站姿哑铃过头臂屈伸、通用 Bench Press、Cable Core Press 和 Incline Reverse Fly。",
        "- **不需要把 15 个动作全部手工创建一次。**手工样例只作为真实回读不符时的兜底。",
        "",
        "## 全部候选",
        "",
        "| 训记动作 | 状态 | 推荐 Garmin 名称 | category | exerciseName | 组数 |",
        "|---|---|---|---|---|---:|",
    ]
    for row in rows:
        rec = row["recommended"]
        lines.append(
            f"| {row['name']} | {status_labels[row['status']]} | {rec['name']} | "
            f"`{rec['category']}` | `{rec['exerciseName']}` | {row['totalSets']} |"
        )
    ambiguous_rows = [row for row in rows if row["status"] == "ambiguous"]
    lines += ["", f"## 仍需确认的动作（{len(ambiguous_rows)} 个）", ""]
    if not ambiguous_rows:
        lines += ["无。15 个动作的语义均已明确。", ""]
    for row in ambiguous_rows:
        lines.append(f"### {row['name']}")
        lines.append("")
        for candidate in [row["recommended"], *row["alternatives"]]:
            note = f"：{candidate['note']}" if candidate["note"] else ""
            lines.append(
                f"- **{candidate['name']}** — `{candidate['category']}` / "
                f"`{candidate['exerciseName']}`{note}"
            )
        lines += ["", row["question"], ""]
    lines += [
        "## 证据边界与下一步",
        "",
        f"- 现有 Workout 检查读取了 {existing['workoutCount']} 个 Workout 摘要和 "
        f"{existing['strengthDetailsRead']} 个力量训练详情；没有读取到当前 15 个动作的既有样例。",
        f"- {totals['catalogClearMovements']} 个明确候选可以进入白名单，但仍须通过逐日预览、创建后回读及手表显示检查，才能升级为端到端已验证。",
        "- 只有真实回读与预期不符时，才为对应动作补一个手工样例。",
        "- 动作映射覆盖不等于整日可同步：热身步骤、变重组拆分、休息和重量单位仍按 P0 验证清单处理。",
        "",
        "离线重跑：",
        "",
        "```bash",
        "outputs/garmin_p0/newlib-venv/Scripts/python.exe scripts/analyze_garmin_exercise_mappings.py",
        "```",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False))
    print(f"JSON={JSON_PATH}")
    print(f"REPORT={REPORT_PATH}")


if __name__ == "__main__":
    main()
