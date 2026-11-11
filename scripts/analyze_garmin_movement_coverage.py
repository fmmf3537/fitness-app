"""只读分析本地训记计划缓存的 Garmin 动作覆盖情况。

不加载应用配置、不读取凭据、不发起网络请求。默认以只读 URI 打开 SQLite。
运行（项目根目录）：
  backend/.venv/Scripts/python.exe scripts/analyze_garmin_movement_coverage.py --as-of 2026-11-10
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VERIFIED_MAPPINGS = {
    "杠铃卧推": {"category": "BENCH_PRESS", "exerciseName": "BARBELL_BENCH_PRESS"}
}


def plan_days(data: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for raw in data.get("days") or []:
        if not isinstance(raw, dict):
            continue
        day_str = raw.get("date") or raw.get("datestr")
        movements = raw.get("movements") or (raw.get("workout") or {}).get("movements") or []
        if not day_str or not movements:
            continue
        try:
            day_date = date.fromisoformat(day_str)
        except (TypeError, ValueError):
            continue
        normalized = []
        for mv in movements:
            sets = mv.get("sets") if mv.get("sets") is not None else mv.get("target_sets")
            normalized.append({**mv, "sets": sets or []})
        result.append({
            "date": day_date,
            "title": raw.get("title") or (raw.get("workout") or {}).get("name"),
            "movements": normalized,
        })
    return result


def contiguous_group_count(movement: dict[str, Any]) -> int:
    """按处方连续性估算 Garmin 段数，不把不同重量/次数/休息合并。"""
    groups = 0
    previous = None
    for item in movement.get("sets") or []:
        set_type = item.get("set_type") or "working"
        rest = item.get("rest_seconds")
        if rest is None:
            rest = movement.get(
                "warmup_rest_seconds" if set_type == "warmup" else "rest_seconds"
            )
        signature = (
            set_type,
            item.get("weight"),
            item.get("unit"),
            item.get("reps"),
            item.get("duration_seconds"),
            rest,
            item.get("rounds"),
        )
        if signature != previous:
            groups += 1
            previous = signature
    return groups


def compact_values(values: set[Any]) -> str:
    if not values:
        return "—"
    ordered = sorted(values, key=lambda v: (float(v) if isinstance(v, (int, float)) else str(v)))
    return "、".join(f"{v:g}" if isinstance(v, float) else str(v) for v in ordered)


def analyze(rows: list[tuple[str, str, str, str, str, str]], as_of: date) -> dict[str, Any]:
    plans = []
    all_days = []
    for plan_ref, raw_json, date_from, date_to, fetched_at, _ in rows:
        data = json.loads(raw_json)
        plan = data.get("plan") or {}
        status = plan.get("status") or data.get("status")
        days = plan_days(data) if status != "ended" else []
        title = plan.get("title") or plan.get("name") or data.get("title") or data.get("name")
        plans.append({
            "plan_ref": plan_ref,
            "title": title,
            "status": status,
            "date_from": date_from,
            "date_to": date_to,
            "fetched_at": fetched_at,
            "training_days_in_cache": len(days),
        })
        all_days.extend({"plan_ref": plan_ref, "plan_name": title, **day} for day in days)

    current_end = as_of + timedelta(days=29)
    current_days = [d for d in all_days if as_of <= d["date"] <= current_end]
    historical_days = [d for d in all_days if d not in current_days]
    analysis_days = current_days or historical_days
    scope = "current_30d" if current_days else "historical_cache_fallback"

    stats: dict[str, dict[str, Any]] = {}
    for day in analysis_days:
        for movement in day["movements"]:
            name = (movement.get("name") or "未命名动作").strip()
            sets = movement.get("sets") or []
            row = stats.setdefault(name, {
                "name": name,
                "training_days": set(),
                "occurrences": 0,
                "total_sets": 0,
                "set_types": Counter(),
                "units": set(),
                "weighted_sets": 0,
                "unweighted_sets": 0,
                "weights": set(),
                "reps": set(),
                "contiguous_groups": 0,
                "single_side_flag": False,
                "single_side_name": False,
                "amrap": False,
                "rounds_sets": 0,
                "missing_reps_and_duration_sets": 0,
                "rest_seconds": set(),
                "warmup_rest_seconds": set(),
            })
            row["training_days"].add(day["date"].isoformat())
            row["occurrences"] += 1
            row["total_sets"] += len(sets)
            row["contiguous_groups"] += contiguous_group_count(movement)
            row["single_side_flag"] |= movement.get("single_side") is True
            row["single_side_name"] |= "单侧" in name or name.endswith("_single")
            row["amrap"] |= movement.get("amrap") is True
            if movement.get("rest_seconds") is not None:
                row["rest_seconds"].add(movement["rest_seconds"])
            if movement.get("warmup_rest_seconds") is not None:
                row["warmup_rest_seconds"].add(movement["warmup_rest_seconds"])
            for item in sets:
                set_type = item.get("set_type") or "unspecified"
                row["set_types"][set_type] += 1
                if item.get("unit") is not None:
                    row["units"].add(item["unit"])
                weight = item.get("weight")
                if isinstance(weight, (int, float)):
                    row["weighted_sets"] += 1
                    row["weights"].add(float(weight))
                else:
                    row["unweighted_sets"] += 1
                reps = item.get("reps")
                if isinstance(reps, (int, float)):
                    row["reps"].add(float(reps))
                if reps is None and not item.get("duration_seconds"):
                    row["missing_reps_and_duration_sets"] += 1
                if item.get("rounds") is not None:
                    row["rounds_sets"] += 1

    movements = []
    for row in stats.values():
        blockers = []
        checks = []
        if row["name"] not in VERIFIED_MAPPINGS:
            blockers.append("Garmin 动作枚举未验证")
        warmup_sets = row["set_types"].get("warmup", 0)
        if warmup_sets:
            blockers.append(f"含 {warmup_sets} 组热身，热身步骤待实测")
        if row["single_side_flag"] or row["single_side_name"]:
            blockers.append("含单边语义，重量与动作映射需人工确认")
        if row["amrap"]:
            blockers.append("AMRAP 首版不支持")
        if row["rounds_sets"]:
            blockers.append("rounds/组合组首版不支持")
        non_kg = {u for u in row["units"] if u != "kg"}
        if non_kg:
            blockers.append(f"非 kg 单位：{sorted(non_kg)}")
        if row["missing_reps_and_duration_sets"]:
            blockers.append("存在无次数且无时长组")
        if row["unweighted_sets"]:
            checks.append(f"{row['unweighted_sets']} 组无数值重量，需确认自重/未加载显示")
        if len(row["weights"]) > 1:
            checks.append("含变重组，必须拆分连续处方段")
        if len(row["reps"]) > 1:
            checks.append("含变次数组，必须拆分连续处方段")
        if row["name"] in VERIFIED_MAPPINGS:
            checks.append("已有 P0 动作枚举与 kg 重量实测")

        movements.append({
            "name": row["name"],
            "training_days": len(row["training_days"]),
            "dates": sorted(row["training_days"]),
            "occurrences": row["occurrences"],
            "total_sets": row["total_sets"],
            "warmup_sets": warmup_sets,
            "working_sets": row["set_types"].get("working", 0),
            "other_sets": row["total_sets"] - warmup_sets - row["set_types"].get("working", 0),
            "weighted_sets": row["weighted_sets"],
            "unweighted_sets": row["unweighted_sets"],
            "weights": sorted(row["weights"]),
            "reps": sorted(row["reps"]),
            "units": sorted(row["units"]),
            "contiguous_groups": row["contiguous_groups"],
            "rest_seconds": sorted(row["rest_seconds"]),
            "warmup_rest_seconds": sorted(row["warmup_rest_seconds"]),
            "single_side_flag": row["single_side_flag"],
            "single_side_name": row["single_side_name"],
            "verified_mapping": row["name"] in VERIFIED_MAPPINGS,
            "sync_ready_now": not blockers,
            "blockers": blockers,
            "checks": checks,
        })

    movements.sort(key=lambda m: (-m["total_sets"], m["name"]))
    totals = {
        "training_days": len({d["date"].isoformat() for d in analysis_days}),
        "movements": len(movements),
        "sets": sum(m["total_sets"] for m in movements),
        "warmup_sets": sum(m["warmup_sets"] for m in movements),
        "working_sets": sum(m["working_sets"] for m in movements),
        "weighted_sets": sum(m["weighted_sets"] for m in movements),
        "unweighted_sets": sum(m["unweighted_sets"] for m in movements),
        "contiguous_groups": sum(m["contiguous_groups"] for m in movements),
        "verified_movements": sum(m["verified_mapping"] for m in movements),
        "sync_ready_movements": sum(m["sync_ready_now"] for m in movements),
        "variable_weight_movements": sum(len(m["weights"]) > 1 for m in movements),
        "unweighted_movements": sum(m["unweighted_sets"] > 0 for m in movements),
        "single_side_semantic_movements": sum(
            m["single_side_flag"] or m["single_side_name"] for m in movements
        ),
    }
    totals["verified_movement_coverage_pct"] = round(
        100 * totals["verified_movements"] / totals["movements"], 1
    ) if totals["movements"] else 0.0
    totals["verified_set_coverage_pct"] = round(
        100 * sum(m["total_sets"] for m in movements if m["verified_mapping"]) / totals["sets"], 1
    ) if totals["sets"] else 0.0

    return {
        "as_of": as_of.isoformat(),
        "scope": scope,
        "scope_warning": None if current_days else (
            "本地缓存不包含当前 30 天训练日；以下为历史缓存基线，不代表当前计划。"
        ),
        "current_30d": {
            "from": as_of.isoformat(),
            "to": current_end.isoformat(),
            "training_days": len({d["date"].isoformat() for d in current_days}),
        },
        "plans": plans,
        "analysis_dates": sorted({d["date"].isoformat() for d in analysis_days}),
        "training_day_details": [
            {
                "date": d["date"].isoformat(),
                "title": d["title"],
                "movement_count": len(d["movements"]),
                "sets": sum(len(m.get("sets") or []) for m in d["movements"]),
                "movement_names": [(m.get("name") or "未命名动作").strip() for m in d["movements"]],
            }
            for d in sorted(analysis_days, key=lambda item: item["date"])
        ],
        "totals": totals,
        "movements": movements,
        "network_requests": 0,
    }


def report_markdown(result: dict[str, Any]) -> str:
    t = result["totals"]
    lines = [
        "# Garmin 动作覆盖分析（本地只读）",
        "",
        f"> 分析基准日：{result['as_of']}  ",
        f"> 数据范围：{result['scope']}  ",
        "> 本报告不访问训记或 Garmin 网络接口，不代表已完成任何远端映射验证。",
        "",
        "## 结论",
        "",
    ]
    if result["scope_warning"]:
        lines += [
            f"**{result['scope_warning']}**",
            "",
            f"当前 30 天缓存内训练日为 **{result['current_30d']['training_days']}**，不能据此判断用户当前没有计划。",
            "",
        ]
    lines += [
        f"本次样本包含 **{t['training_days']} 个训练日、{t['movements']} 个动作、{t['sets']} 组**。",
        f"已实测 Garmin 枚举覆盖 **{t['verified_movements']}/{t['movements']} 个动作（{t['verified_movement_coverage_pct']}%）**，"
        f"按组数覆盖 **{t['verified_set_coverage_pct']}%**；当前立即可同步动作 **{t['sync_ready_movements']} 个**。",
        "",
        f"- 正式组：{t['working_sets']}；热身组：{t['warmup_sets']}。",
        f"- 有数值重量：{t['weighted_sets']} 组；无数值重量：{t['unweighted_sets']} 组。",
        f"- 变重动作：{t['variable_weight_movements']} 个；含单边语义动作：{t['single_side_semantic_movements']} 个。",
        f"- 按连续相同处方估算，需要至少 {t['contiguous_groups']} 个 Garmin 工作/重复段（不含独立休息步）。",
        "- 由于整日同步不允许跳过未知动作，样本中的所有动作都必须完成验证后，该训练日才可同步。",
        "",
        "## 数据范围",
        "",
        "| plan_ref | 计划 | 状态 | 缓存声明范围 | 抓取时间 | 缓存训练日 |",
        "|---|---|---|---|---|---:|",
    ]
    for p in result["plans"]:
        lines.append(
            f"| {p['plan_ref']} | {p['title']} | {p['status']} | {p['date_from']}～{p['date_to']} "
            f"| {p['fetched_at']} | {p['training_days_in_cache']} |"
        )
    lines += [
        "",
        "实际统计日期：" + "、".join(result["analysis_dates"]),
        "",
        "## 训练日分布",
        "",
        "| 日期 | 标题 | 动作数 | 组数 | 动作 |",
        "|---|---|---:|---:|---|",
    ]
    for day in result["training_day_details"]:
        lines.append(
            f"| {day['date']} | {day['title']} | {day['movement_count']} | {day['sets']} "
            f"| {'、'.join(day['movement_names'])} |"
        )
    lines += [
        "",
        "## 动作明细",
        "",
        "| 动作 | 日期 | 组数（热身/正式） | 重量 kg | 次数 | 连续处方段 | 阻塞项与检查点 |",
        "|---|---|---:|---|---|---:|---|",
    ]
    for m in result["movements"]:
        weights = compact_values(set(m["weights"])) if m["weights"] else f"无数值重量（{m['unweighted_sets']} 组）"
        reps = compact_values(set(m["reps"]))
        notes = m["blockers"] + m["checks"]
        lines.append(
            f"| {m['name']} | {'、'.join(m['dates'])} | {m['total_sets']}（{m['warmup_sets']}/{m['working_sets']}） "
            f"| {weights} | {reps} | {m['contiguous_groups']} | {'；'.join(notes)} |"
        )

    warmup = [m["name"] for m in result["movements"] if m["warmup_sets"]]
    unweighted = [m["name"] for m in result["movements"] if m["unweighted_sets"]]
    single_side = [
        m["name"] for m in result["movements"]
        if m["single_side_flag"] or m["single_side_name"]
    ]
    complex_limited = [
        m["name"] for m in result["movements"]
        if any(
            marker in blocker
            for blocker in m["blockers"]
            for marker in ("AMRAP", "rounds", "非 kg", "无次数")
        )
    ]
    special = set(warmup + unweighted + single_side + complex_limited)
    standard = [m["name"] for m in result["movements"] if m["name"] not in special]
    batches = []
    if standard:
        batches.append(("常规有重量正式组", standard, "确认 Garmin 枚举和重量策略"))
    if warmup:
        batches.append(("含热身组", warmup, "额外验证热身步骤、热身休息和正式组重量"))
    if unweighted:
        batches.append(("无数值重量", unweighted, "确认显示为自重/无负载，而非错误的 0 kg"))
    if single_side:
        batches.append(("单侧语义", single_side, "核对训记语义、左右侧重量及腕表步骤"))
    if complex_limited:
        batches.append(("其他复杂限制", complex_limited, "逐项确认支持策略，未验证前保持阻止"))
    lines += [
        "",
        "## 建议验证批次",
        "",
        "以下批次只是验证顺序，不表示可以跳过其他动作进行整日同步：",
        "",
    ]
    for index, (title, names, note) in enumerate(batches, 1):
        lines.append(f"{index}. **{title}（{len(names)} 个）**：{'、'.join(names)}。{note}。")
    if result["scope"] == "current_30d" and result["training_day_details"]:
        next_step = (
            "先结合 garminconnect 自带动作字典和现有 Workout 只读结果生成映射候选，"
            "由用户确认歧义动作；不要把所有动作手工建样例作为前置条件。"
            "随后再按逐日预览、创建回读和手表显示完成端到端验证。"
        )
    else:
        next_step = "先在用户明确允许联网后刷新训记计划缓存，再重新运行本分析。"
    lines += [
        "",
        "## 下一步",
        "",
        next_step,
        "",
        "```bash",
        "backend/.venv/Scripts/python.exe scripts/analyze_garmin_movement_coverage.py --as-of YYYY-MM-DD",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--database", type=Path, default=ROOT / "backend" / "data" / "app.db")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "garmin_p0")
    args = parser.parse_args()

    uri = f"file:{args.database.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT plan_ref, plan_json, date_from, date_to, fetched_at, id "
            "FROM xunji_plan WHERE plan_json IS NOT NULL AND plan_json <> '' ORDER BY id"
        ).fetchall()
    result = analyze(rows, args.as_of)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "movement_coverage.json"
    md_path = args.output_dir / "movement_coverage.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(report_markdown(result), encoding="utf-8")
    print(f"SCOPE={result['scope']}")
    print(f"CURRENT_30D_TRAINING_DAYS={result['current_30d']['training_days']}")
    print(f"ANALYZED_DAYS={result['totals']['training_days']}")
    print(f"MOVEMENTS={result['totals']['movements']}")
    print(f"SETS={result['totals']['sets']}")
    print(f"VERIFIED_MOVEMENTS={result['totals']['verified_movements']}")
    print(f"JSON={json_path}")
    print(f"REPORT={md_path}")


if __name__ == "__main__":
    main()
