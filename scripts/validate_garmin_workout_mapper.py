"""用本地真实计划验收 Garmin 映射器，零网络、SQLite 只读。

运行（项目根目录）：
  backend/.venv/Scripts/python.exe scripts/validate_garmin_workout_mapper.py
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.garmin_workout_mapper import (  # noqa: E402
    expand_workout,
    map_plan_day,
    source_set_projection,
)
from app.services.plans import extract_plan_days, plan_name_of, plan_status  # noqa: E402

OUTPUT_DIR = ROOT / "outputs" / "garmin_p0"
COVERAGE_PATH = OUTPUT_DIR / "movement_coverage.json"
VALIDATION_JSON_PATH = OUTPUT_DIR / "mapper_validation.json"
VALIDATION_MD_PATH = OUTPUT_DIR / "mapper_validation.md"
DATABASE_PATH = ROOT / "backend" / "data" / "app.db"


def payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_source_days() -> list[dict[str, Any]]:
    coverage = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
    wanted = set(coverage["analysis_dates"])
    uri = f"file:{DATABASE_PATH.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT plan_ref, plan_json FROM xunji_plan "
            "WHERE plan_json IS NOT NULL AND plan_json <> '' ORDER BY id"
        ).fetchall()
    result = []
    for plan_ref, raw_json in rows:
        data = json.loads(raw_json)
        if plan_status(data) == "ended":
            continue
        for source_day in extract_plan_days(data):
            day = source_day["date"].isoformat()
            if day not in wanted:
                continue
            result.append(
                {
                    "plan_ref": plan_ref,
                    "plan_name": plan_name_of(data),
                    "date": day,
                    "title": source_day["title"],
                    "movements": source_day["movements"],
                }
            )
    if len(result) != len(wanted) or {day["date"] for day in result} != wanted:
        raise ValueError("真实计划训练日缺失或同日多计划，停止验收")
    return sorted(result, key=lambda day: day["date"])


def main() -> None:
    generated_at = datetime.now().isoformat(timespec="seconds")
    days = []
    for source_day in load_source_days():
        mapped = map_plan_day(source_day)
        expanded = expand_workout(mapped["workout"])
        before = source_set_projection(source_day["movements"])
        after = source_set_projection(expanded)
        if before != after:
            raise AssertionError(f"{source_day['date']} 反向展开与源组次不一致")
        artifact_path = OUTPUT_DIR / f"workout_preview_{source_day['date']}.json"
        artifact = {
            "schema": "fitness-app.garmin-workout-preview.v1",
            "generatedAt": generated_at,
            "networkRequests": 0,
            "remoteWritePerformed": False,
            **mapped,
        }
        artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        days.append(
            {
                "date": source_day["date"],
                "title": source_day["title"],
                "planRef": source_day["plan_ref"],
                "planName": source_day["plan_name"],
                "sourceKey": mapped["source_key"],
                "sourceHash": mapped["source_hash"],
                "payloadHash": payload_hash(mapped["workout"]),
                "stats": mapped["stats"],
                "roundtripVerified": True,
                "expandedSetCount": len(after),
                "artifact": artifact_path.relative_to(ROOT).as_posix(),
                "remoteWriteEligible": False,
            }
        )

    totals = {
        "trainingDays": len(days),
        "sets": sum(day["stats"]["sets"] for day in days),
        "warmupSets": sum(day["stats"]["warmup_sets"] for day in days),
        "workingSets": sum(day["stats"]["working_sets"] for day in days),
        "repeatGroups": sum(day["stats"]["repeat_groups"] for day in days),
        "roundtripVerifiedDays": sum(day["roundtripVerified"] for day in days),
    }
    assert totals["trainingDays"] == totals["roundtripVerifiedDays"] == 2
    assert totals["sets"] == 51
    assert totals["warmupSets"] == 2
    assert totals["workingSets"] == 49
    assert all(day["expandedSetCount"] == day["stats"]["sets"] for day in days)
    result = {
        "schema": "fitness-app.garmin-mapper-validation.v1",
        "generatedAt": generated_at,
        "status": "local_validation_passed_pending_remote_e2e",
        "networkRequests": 0,
        "remoteWritePerformed": False,
        "totals": totals,
        "rules": {
            "weight": "weightValue 使用 kg 原值，left_weight 不参与",
            "grouping": "只合并同一动作内连续且 set_type/weight/reps/rest 完全相同的组",
            "duration": "有 reps 时 duration_seconds 不作为休息，也不拆分重复组",
            "roundtrip": "对动作、组序、组类型、重量、次数和休息逐项对账",
        },
        "days": days,
    }
    VALIDATION_JSON_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Garmin 本地映射器真实计划验收",
        "",
        f"> 验收时间：{generated_at}  ",
        "> 状态：本地映射与反向展开通过；未进行 Garmin 创建、回读或手表验收。  ",
        "> 本次零网络请求，SQLite 以 `mode=ro` 打开，未写入 Garmin 或数据库。",
        "",
        "## 结论",
        "",
        f"- **{totals['trainingDays']} 个真实训练日、{totals['sets']} 组全部通过反向展开对账**。",
        f"- 正式组 {totals['workingSets']}，热身组 {totals['warmupSets']}。",
        f"- 连续相同处方合并为 {totals['repeatGroups']} 个 RepeatGroupDTO；其余变重/变休息段保持独立。",
        "- 每个 payload 都保持 `remote_write_eligible=false`，不能据此直接上传。",
        "",
        "| 日期 | 训练 | 动作 | 组数（热身/正式） | RepeatGroup | 顶层步骤 | 反向展开 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for day in days:
        stats = day["stats"]
        lines.append(
            f"| {day['date']} | {day['title']} | {stats['movements']} | "
            f"{stats['sets']}（{stats['warmup_sets']}/{stats['working_sets']}） | "
            f"{stats['repeat_groups']} | {stats['top_level_steps']} | "
            f"通过，{day['expandedSetCount']} 组一致 |"
        )
    lines += ["", "## 来源与产物", ""]
    for day in days:
        lines += [
            f"### {day['date']}｜{day['title']}",
            "",
            f"- `source_key`：`{day['sourceKey']}`",
            f"- `source_hash`：`{day['sourceHash']}`",
            f"- `payload_hash`：`{day['payloadHash']}`",
            f"- 完整本地 Workout 预览：`{day['artifact']}`",
            "",
        ]
    lines += [
        "## 边界",
        "",
        "- 本验收证明本地组次转换与反向展开一致，不证明 Garmin 接受每个动作枚举或完整训练结构。",
        "- 热身、末组休息、动作名称、Connect 显示和 FR955 显示仍需专用 P1 测试。",
        "- 未新增生产 API、数据库表或 Garmin 写端点。",
    ]
    VALIDATION_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False))
    print(f"JSON={VALIDATION_JSON_PATH}")
    print(f"REPORT={VALIDATION_MD_PATH}")


if __name__ == "__main__":
    main()
