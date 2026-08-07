"""V1 趋势统计纯逻辑：部位分类 / 容量计算 / 周聚合 / 睡眠解析。

全部为纯函数（不依赖 DB session），输入为已解析的普通数据结构，便于单测。
"""
from __future__ import annotations

import json
from datetime import date, timedelta

# 部位关键词映射（顺序即优先级，先命中先返回）
_PART_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("胸", ("胸", "推胸", "卧推", "飞鸟")),
    ("背", ("背", "划船", "引体", "下拉")),
    ("腿", ("腿", "深蹲", "硬拉", "箭步", "臀")),
    ("肩", ("肩", "推举", "侧平举")),
    ("臂", ("臂", "弯举", "臂屈伸", "肱")),
    ("核心", ("腹", "核心", "平板", "卷腹")),
    ("有氧", ("跑", "骑", "泳", "有氧", "椭圆")),
]

# Garmin sleep_json 中常见的睡眠时长键（秒）
_SLEEP_KEYS = ("sleepTimeSeconds", "duration", "sleep_time_seconds")


def classify_part(movement_name: str | None) -> str:
    """按动作名关键词归类身体部位，都不中归 "其他"。"""
    if not movement_name:
        return "其他"
    for part, keywords in _PART_KEYWORDS:
        if any(k in movement_name for k in keywords):
            return part
    return "其他"


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def set_volume_kg(s) -> float:
    """单组容量（kg）：done 缺失视为 True；weight<=0 或 reps<=0（含 time 组）不计。"""
    if not isinstance(s, dict):
        return 0.0
    if not s.get("done", True):
        return 0.0
    weight = _to_float(s.get("weight"))
    reps = _to_float(s.get("reps"))
    if weight <= 0 or reps <= 0:
        return 0.0
    return weight * reps


def parse_movements(movements_json) -> list:
    """兼容 JSON 字符串 / 已解析的 list；无法解析返回 []。"""
    if isinstance(movements_json, list):
        return movements_json
    if not movements_json:
        return []
    try:
        data = json.loads(movements_json)
    except (json.JSONDecodeError, TypeError):
        return []
    return data if isinstance(data, list) else []


def _movements_kg(movements) -> float:
    total = 0.0
    for mv in movements or []:
        if not isinstance(mv, dict):
            continue
        for s in mv.get("sets") or []:
            total += set_volume_kg(s)
    return total


def movements_volume_tons(movements) -> float:
    """一次训练的容量合计（吨，round 2）。"""
    return round(_movements_kg(movements) / 1000, 2)


def week_monday(d: date) -> date:
    """该日期所在 ISO 周的周一。"""
    return d - timedelta(days=d.weekday())


def weekly_trends(workouts: list[dict], start: date, end: date) -> tuple[list[dict], list[dict]]:
    """按 ISO 周聚合容量/次数/部位频率；覆盖 [start, end] 涉及的连续每一周（零填充）。

    workouts: [{"date": date, "movements": [...]}]，范围外的记录忽略。
    返回 (weekly_volume, body_part_frequency)。
    """
    weeks: list[date] = []
    m = week_monday(start)
    last = week_monday(end)
    while m <= last:
        weeks.append(m)
        m += timedelta(days=7)

    kg_by_week = {m: 0.0 for m in weeks}
    sessions_by_week = {m: 0 for m in weeks}
    parts_by_week: dict[date, dict[str, int]] = {m: {} for m in weeks}

    for w in workouts:
        d = w.get("date")
        if not isinstance(d, date) or d < start or d > end:
            continue
        key = week_monday(d)
        kg_by_week[key] += _movements_kg(w.get("movements"))
        sessions_by_week[key] += 1
        for mv in w.get("movements") or []:
            if not isinstance(mv, dict):
                continue
            part = classify_part(mv.get("name"))
            parts_by_week[key][part] = parts_by_week[key].get(part, 0) + 1

    weekly_volume = [
        {
            "week_start": m.isoformat(),
            "volume_tons": round(kg_by_week[m] / 1000, 2),
            "sessions": sessions_by_week[m],
        }
        for m in weeks
    ]
    body_part_frequency = [
        {"week_start": m.isoformat(), "parts": parts_by_week[m]}
        for m in weeks
    ]
    return weekly_volume, body_part_frequency


def body_metrics_series(rows: list[tuple[date, str, float]]) -> dict:
    """BodyMetric 行 (date, type, value) 拆成 weight / bodyfat 两条序列（调用方保证按日期升序）。"""
    result: dict[str, list[dict]] = {"weight": [], "bodyfat": []}
    for d, metric_type, value in rows:
        if metric_type in result:
            result[metric_type].append({"date": d.isoformat(), "value": value})
    return result


def parse_sleep_hours(sleep_json) -> float | None:
    """从 Garmin sleep_json（JSON 字符串或 dict，支持一层以上嵌套）解析睡眠时长（小时，round 2）。"""
    data = sleep_json
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    for key in _SLEEP_KEYS:
        v = data.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return round(v / 3600, 2)
    for v in data.values():
        if isinstance(v, dict):
            hours = parse_sleep_hours(v)
            if hours is not None:
                return hours
    return None


def sleep_volume_series(sleep_rows: list[tuple[date, object]], workouts: list[dict]) -> list[dict]:
    """睡眠 × 当日训练容量关联；只输出有睡眠数据的天，按日期升序。"""
    kg_by_date: dict[date, float] = {}
    for w in workouts:
        d = w.get("date")
        if isinstance(d, date):
            kg_by_date[d] = kg_by_date.get(d, 0.0) + _movements_kg(w.get("movements"))

    result = []
    for d, sleep_json in sorted(sleep_rows, key=lambda r: r[0]):
        hours = parse_sleep_hours(sleep_json)
        if hours is None:
            continue
        result.append({
            "date": d.isoformat(),
            "sleep_hours": hours,
            "volume_tons": round(kg_by_date.get(d, 0.0) / 1000, 2),
        })
    return result
