"""V3-6 分享海报数据装配：一次聚合 report + workout 摘要 + PR 明细 + 本周计数。

设计纪律：
- 纯装配逻辑与 HTTP 解耦，便于单测；
- PR 检测复用 services/ai.py 的 query_pr_events（禁止复制粘贴）；
- movements_json 中 weight/reps 可能是字符串，统一经 _float_or_none/_int_or_none；
- 有氧动作以 metrics 字典判定（distance/avgHeartRate 等），力量动作以 sets 判定。
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models import AIReport, GarminActivity, Workout
from app.services.ai import (
    _float_or_none,
    _int_or_none,
    _parse_movements,
    query_pr_events,
)
from app.services.stats import week_monday

# 佳明活动类型中的有氧类（movements 无法判定时的兜底）
CARDIO_TAGS = {
    "running", "treadmill_running", "trail_running", "cycling", "indoor_cycling",
    "swimming", "lap_swimming", "open_water_swimming", "walking", "hiking",
    "rowing", "indoor_rowing", "elliptical", "cardio", "aerobics", "stair_climbing",
}


def _is_cardio_movement(mv: dict) -> bool:
    """有氧动作：带非空 metrics 字典（distance/avgHeartRate 等摘要）。"""
    metrics = mv.get("metrics")
    return isinstance(metrics, dict) and bool(metrics)


def _is_strength_movement(mv: dict) -> bool:
    """力量动作：带非空 sets 列表。"""
    sets = mv.get("sets")
    return isinstance(sets, list) and bool(sets)


def _valid_sets(mv: dict) -> list[dict]:
    """有效组：done != False 且 weight/reps 为正（兼容字符串数字）。"""
    out = []
    for s in mv.get("sets") or []:
        if not isinstance(s, dict) or s.get("done", True) is False:
            continue
        weight = _float_or_none(s.get("weight")) or 0.0
        reps = _int_or_none(s.get("reps")) or 0
        if weight <= 0 or reps <= 0:
            continue
        out.append({"weight": weight, "reps": reps, "unit": s.get("unit") or "kg"})
    return out


def _round_num(value: float) -> int | float:
    """60.0 → 60；60.5 → 60.5（海报展示友好）。"""
    r = round(value, 2)
    return int(r) if r == int(r) else r


def classify_workout_kind(workout: Workout, movements: list[dict]) -> str:
    """strength / cardio / mixed 判定。

    movements 可分类时按动作集合判定；无法判定（无动作）时按佳明活动类型兜底。
    """
    has_strength = any(_is_strength_movement(mv) for mv in movements if isinstance(mv, dict))
    has_cardio = any(_is_cardio_movement(mv) for mv in movements if isinstance(mv, dict))
    if has_strength and has_cardio:
        return "mixed"
    if has_strength:
        return "strength"
    if has_cardio:
        return "cardio"
    tags = (workout.tags or "").lower()
    if any(t in tags for t in CARDIO_TAGS):
        return "cardio"
    return "strength"


def movement_highlights(movements: list[dict], limit: int = 3) -> list[dict]:
    """力量动作亮点：每动作取最佳组（weight×reps 最大），按动作总容量降序取 top N。"""
    entries = []
    for mv in movements:
        if not isinstance(mv, dict) or not _is_strength_movement(mv):
            continue
        name = (mv.get("name") or "").strip()
        if not name:
            continue
        sets = _valid_sets(mv)
        if not sets:
            continue
        best = max(sets, key=lambda s: s["weight"] * s["reps"])
        volume = sum(s["weight"] * s["reps"] for s in sets)
        entries.append({
            "name": name,
            "weight": _round_num(best["weight"]),
            "unit": best["unit"],
            "reps": best["reps"],
            "volume_kg": _round_num(volume),
        })
    entries.sort(key=lambda e: e["volume_kg"], reverse=True)
    return entries[:limit]


def movements_volume_kg(movements: list[dict]) -> float:
    """力量动作总容量（kg）：全部有效组 weight×reps 求和（含无名动作）。"""
    total = 0.0
    for mv in movements:
        if not isinstance(mv, dict) or not _is_strength_movement(mv):
            continue
        total += sum(s["weight"] * s["reps"] for s in _valid_sets(mv))
    return total


def _garmin_distance_m(session: Session, workout: Workout) -> float | None:
    """融合侧佳明距离（米）：raw_json.summary.distance。"""
    if not workout.garmin_activity_id:
        return None
    row = session.get(GarminActivity, workout.garmin_activity_id)
    if not row or not row.raw_json:
        return None
    try:
        summary = json.loads(row.raw_json).get("summary") or {}
    except (json.JSONDecodeError, TypeError):
        return None
    distance = _float_or_none(summary.get("distance"))
    return distance if distance and distance > 0 else None


def _cardio_distance_m(movements: list[dict]) -> float | None:
    """有氧动作 metrics 距离合计（米）。"""
    total = 0.0
    found = False
    for mv in movements:
        if not isinstance(mv, dict) or not _is_cardio_movement(mv):
            continue
        d = _float_or_none(mv["metrics"].get("distance"))
        if d and d > 0:
            total += d
            found = True
    return total if found else None


def _cardio_avg_hr(movements: list[dict]) -> int | None:
    """有氧动作 metrics 平均心率兜底（workout.avg_hr 优先，此处为补充来源）。"""
    for mv in movements:
        if isinstance(mv, dict) and _is_cardio_movement(mv):
            hr = _int_or_none(mv["metrics"].get("avgHeartRate"))
            if hr:
                return hr
    return None


def workout_pr_details(session: Session, workout: Workout,
                       movements: list[dict]) -> list[dict]:
    """PR 明细：复用 query_pr_events 检测，再回查本次训练对应组的次数与单位。

    输出 [{"movement", "weight", "unit", "reps"}]，按动作名排序。
    """
    events = query_pr_events(session, workout.date, workout.date)
    if not events:
        return []
    names_in_workout = {
        (mv.get("name") or "").strip()
        for mv in movements if isinstance(mv, dict)
    }
    details = []
    for ev in events:
        name = ev["movement"]
        if name not in names_in_workout:
            continue
        reps, unit = None, "kg"
        for mv in movements:
            if not isinstance(mv, dict) or (mv.get("name") or "").strip() != name:
                continue
            for s in _valid_sets(mv):
                if s["weight"] == float(ev["weight"]):
                    if reps is None or s["reps"] > reps:
                        reps, unit = s["reps"], s["unit"]
        details.append({
            "movement": name,
            "weight": _round_num(float(ev["weight"])),
            "unit": unit,
            "reps": reps,
        })
    return sorted(details, key=lambda d: d["movement"])


def week_training_count(session: Session, day: date) -> int:
    """本周第 N 次训练：[本周一, 当日] 的 workout 条数（含当日）。"""
    monday = week_monday(day)
    return (
        session.query(Workout)
        .filter(Workout.date >= monday, Workout.date <= day)
        .count()
    )


def build_poster_data(session: Session, report: AIReport) -> dict[str, Any]:
    """装配海报全部数据；report 无 workout 关联时 workout 为 null、prs 为空、week_count 为 null。"""
    workout = session.get(Workout, report.workout_id) if report.workout_id else None

    subscores = None
    if report.subscores_json:
        try:
            parsed = json.loads(report.subscores_json)
            if isinstance(parsed, dict):
                subscores = parsed
        except (json.JSONDecodeError, TypeError):
            subscores = None

    day = workout.date if workout else report.period_start
    result: dict[str, Any] = {
        "report": {
            "id": report.id,
            "type": report.type,
            "date": day.isoformat() if day else None,
            "workout_title": workout.title if workout else None,
            "score": report.score,
            "one_liner": report.one_liner,
            "subscores": subscores,
        },
        "workout": None,
        "prs": [],
        "week_count": None,
    }
    if not workout:
        return result

    movements = _parse_movements(workout)
    kind = classify_workout_kind(workout, movements)
    highlights = movement_highlights(movements, limit=3)
    volume_kg = movements_volume_kg(movements)
    distance_m = _garmin_distance_m(session, workout) or _cardio_distance_m(movements)

    result["workout"] = {
        "id": workout.id,
        "date": workout.date.isoformat(),
        "title": workout.title,
        "workout_kind": kind,
        "duration_s": workout.duration_s,
        "calories": workout.calories,
        "avg_hr": workout.avg_hr,
        "max_hr": workout.max_hr,
        "distance_m": distance_m,
        "volume_kg": _round_num(volume_kg) if volume_kg > 0 else 0,
        "highlights": highlights,
        "cardio": {
            "distance_m": distance_m,
            "avg_hr": workout.avg_hr or _cardio_avg_hr(movements),
            "duration_s": workout.duration_s,
            "calories": workout.calories,
        } if kind in ("cardio", "mixed") else None,
    }
    result["prs"] = workout_pr_details(session, workout, movements)
    result["week_count"] = week_training_count(session, workout.date)
    return result
