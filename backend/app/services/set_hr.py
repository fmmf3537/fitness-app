"""V4-7 逐组心率：佳明心率时间序列与自动识别 ACTIVE 组按顺序对齐训记组次。

纯函数与 IO 分离：
- :func:`extract_hr_timeline` / :func:`extract_active_sets`：纯解析，按提示词兼容真实佳明结构
  （``metricDescriptors.metricsIndex``、GMT naive ``startTime``、``directHeartRate`` 可能为 null）。
- :func:`align_sets`：训记按全局顺序展开（跳 ``done=False``）与佳明 ACTIVE 一一配对，类别校验
  决定 confidence / match_method。
- :func:`compute_set_stats` / :func:`compute_recovery_hr`：窗口内统计与组后 30s 恢复心率。
- :func:`compute_workout_set_hr` / :func:`get_or_compute_set_hr`：编排与懒计算入口，幂等落库。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import GarminActivity, Workout, WorkoutSetHr


GARMIN_CATEGORY_MAP: dict[str, str] = {
    "DEADLIFT": "硬拉",
    "SQUAT": "深蹲",
    "BENCH_PRESS": "卧推",
    "ROW": "划船",
    "PULL_UP": "引体向上",
    "SHOULDER_PRESS": "推举",
    "CURL": "弯举",
    "LATERAL_RAISE": "侧平举",
    "TRICEPS_EXTENSION": "臂屈伸",
    "LUNGE": "弓步",
    "PUSH_UP": "俯卧撑",
    "SIT_UP": "仰卧起坐",
    "LEG_PRESS": "腿举",
    "CALF_RAISE": "提踵",
    "HIP_THRUST": "臀推",
    "PLANK": "平板支撑",
    "CRUNCH": "卷腹",
    "DIP": "双杠臂屈伸",
}


def extract_hr_timeline(raw: Any) -> list[tuple[int, int]]:
    """从解析后的 raw_json 提取 ``[(epoch_ms, hr)]`` 心率序列（按时间升序）。

    metricDescriptors 兼容 ``metricsIndex``（真实佳明）与 ``index``（旧测试 fixture）；
    过滤 timestamp 或 hr 非数值、hr 为 null 的行。无数据返回 ``[]``。
    """
    if not isinstance(raw, dict):
        return []
    details = raw.get("details")
    if not isinstance(details, dict):
        return []
    descriptors = details.get("metricDescriptors") or []
    rows = details.get("activityDetailMetrics") or []

    ts_idx: int | None = None
    hr_idx: int | None = None
    for d in descriptors:
        if not isinstance(d, dict):
            continue
        key = d.get("key")
        idx = d.get("metricsIndex")
        if not isinstance(idx, int):
            idx = d.get("index")
        if not isinstance(idx, int):
            continue
        if key == "directTimestamp":
            ts_idx = idx
        elif key == "directHeartRate":
            hr_idx = idx
    if ts_idx is None or hr_idx is None:
        return []

    need = max(ts_idx, hr_idx)
    out: list[tuple[int, int]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        metrics = r.get("metrics")
        if not isinstance(metrics, list) or len(metrics) <= need:
            continue
        ts = metrics[ts_idx]
        hr = metrics[hr_idx]
        # bool 是 int 的子类，必须先排除
        if isinstance(ts, bool) or isinstance(hr, bool):
            continue
        if not isinstance(ts, (int, float)) or not isinstance(hr, (int, float)):
            continue
        out.append((int(ts), int(round(hr))))
    out.sort(key=lambda x: x[0])
    return out


def _parse_start_ms(start_time: Any) -> int | None:
    """startTime（GMT naive ISO）→ epoch 毫秒；解析失败返回 None。"""
    if not isinstance(start_time, str):
        return None
    try:
        dt = datetime.fromisoformat(start_time).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def extract_active_sets(raw: Any) -> list[dict]:
    """从 ``exercise_sets.exerciseSets`` 取 ``setType == "ACTIVE"`` 的组（按 startTime 升序）。

    每项返回 ``{start_ms, end_ms, category, reps}``。startTime 按 GMT naive ISO 解析为 epoch 毫秒，
    **不加 8 小时**。无 exercise_sets → ``[]``。
    """
    if not isinstance(raw, dict):
        return []
    es = raw.get("exercise_sets")
    if not isinstance(es, dict):
        return []
    sets = es.get("exerciseSets")
    if not isinstance(sets, list):
        return []

    out: list[dict] = []
    for s in sets:
        if not isinstance(s, dict):
            continue
        if s.get("setType") != "ACTIVE":
            continue
        start_ms = _parse_start_ms(s.get("startTime"))
        dur = s.get("duration")
        if start_ms is None or isinstance(dur, bool) or not isinstance(dur, (int, float)):
            continue
        end_ms = start_ms + int(round(float(dur) * 1000))

        category: str | None = None
        exercises = s.get("exercises")
        if isinstance(exercises, list) and exercises:
            top = exercises[0]
            if isinstance(top, dict) and isinstance(top.get("category"), str):
                category = top["category"]

        reps = s.get("repetitionCount")
        if reps is not None:
            try:
                reps = int(reps)
            except (TypeError, ValueError):
                reps = None

        out.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "category": category,
            "reps": reps,
        })
    out.sort(key=lambda x: x["start_ms"])
    return out


def _category_matches(mapped_zh: str, movement_name: str) -> bool:
    """映射名是 movement_name 的子串即视为一致（如 硬拉 ∈ 杠铃硬拉）。"""
    return mapped_zh in movement_name


def align_sets(movements: Any, active_sets: list[dict]) -> list[dict]:
    """训记按全局顺序展开（跳 ``done is False`` 的组）与佳明 ACTIVE 一一配对，按较短侧对齐。

    每项返回 ``{movement_name, set_index, start_ms, end_ms, confidence, match_method}``：
    - 佳明 category 映射中文名后是 movement_name 子串 → ``("high", "order")``；
    - 映射名存在但不匹配 → ``("low", "order_category_mismatch")``；
    - 类别为空/未知 → 跳过校验，``("high", "order")``。
    """
    xj_seq: list[tuple[str, int]] = []
    if isinstance(movements, list):
        for mv in movements:
            if not isinstance(mv, dict):
                continue
            name = mv.get("name")
            sets = mv.get("sets")
            if not isinstance(name, str) or not isinstance(sets, list):
                continue
            for idx, s in enumerate(sets, start=1):
                if not isinstance(s, dict):
                    continue
                if s.get("done") is False:
                    continue
                xj_seq.append((name, idx))

    pairs: list[dict] = []
    n = min(len(xj_seq), len(active_sets))
    for i in range(n):
        name, sidx = xj_seq[i]
        gs = active_sets[i]
        cat = gs.get("category")
        mapped = GARMIN_CATEGORY_MAP.get(cat) if isinstance(cat, str) else None
        if mapped is not None:
            if _category_matches(mapped, name):
                conf, method = "high", "order"
            else:
                conf, method = "low", "order_category_mismatch"
        else:
            conf, method = "high", "order"
        pairs.append({
            "movement_name": name,
            "set_index": sidx,
            "start_ms": gs["start_ms"],
            "end_ms": gs["end_ms"],
            "confidence": conf,
            "match_method": method,
        })
    return pairs


def compute_set_stats(
    timeline: list[tuple[int, int]],
    start_ms: int,
    end_ms: int,
) -> dict | None:
    """窗口 ``[start_ms, end_ms]``（含端点）内 HR 点的 avg/max/min（int）；无点 → ``None``。"""
    hrs = [hr for ts, hr in timeline if start_ms <= ts <= end_ms]
    if not hrs:
        return None
    return {
        "avg": int(round(sum(hrs) / len(hrs))),
        "max": max(hrs),
        "min": min(hrs),
    }


def compute_recovery_hr(timeline: list[tuple[int, int]], end_ms: int) -> int | None:
    """在 ``[end_ms+25000, end_ms+35000]`` 窗口内取时间最接近 ``end_ms+30000`` 的点；无点 → ``None``。"""
    target = end_ms + 30000
    lo = end_ms + 25000
    hi = end_ms + 35000
    best_hr: int | None = None
    best_diff: int | None = None
    for ts, hr in timeline:
        if ts < lo or ts > hi:
            continue
        diff = abs(ts - target)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_hr = hr
    return best_hr


def _epoch_ms_to_naive_utc(ms: int) -> datetime:
    """epoch 毫秒 → naive UTC datetime（与列定义 GMT naive 对齐）。"""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def _load_workout_raw(session: Session, workout: Workout) -> dict | None:
    """加载 workout 关联佳明活动的解析后 raw_json；无 garmin/无 raw/坏 JSON → None。"""
    if workout.garmin_activity_id is None:
        return None
    activity = session.get(GarminActivity, workout.garmin_activity_id)
    if activity is None or not activity.raw_json:
        return None
    try:
        raw = json.loads(activity.raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


def _load_workout_movements(workout: Workout) -> list | None:
    """从 workout.movements_json 解析动作列表。"""
    if not workout.movements_json:
        return None
    try:
        mv = json.loads(workout.movements_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return mv if isinstance(mv, list) else None


def compute_workout_set_hr(session: Session, workout: Workout) -> list[WorkoutSetHr]:
    """编排：解析 workout → 提取/对齐/统计 → 幂等落库 → commit → 返回新行。

    任一前置条件缺失（无 garmin 关联/无 movements_json/无 exercise_sets/无心率序列），
    直接返回 ``[]``，**不删既有行**——保证详情 API 在 raw 损坏时不丢历史逐组心率。
    """
    raw = _load_workout_raw(session, workout)
    movements = _load_workout_movements(workout)
    if raw is None or movements is None:
        return []
    timeline = extract_hr_timeline(raw)
    active_sets = extract_active_sets(raw)
    if not timeline or not active_sets:
        return []

    pairs = align_sets(movements, active_sets)
    if not pairs:
        return []

    # 幂等：先删该 workout 全部旧行；expire 清掉身份映射，避免新插入同 PK 时告警
    session.query(WorkoutSetHr).filter(WorkoutSetHr.workout_id == workout.id).delete(
        synchronize_session=False
    )
    session.expire_all()
    session.flush()

    rows: list[WorkoutSetHr] = []
    for p in pairs:
        stats = compute_set_stats(timeline, p["start_ms"], p["end_ms"])
        recovery = compute_recovery_hr(timeline, p["end_ms"])
        row = WorkoutSetHr(
            workout_id=workout.id,
            movement_name=p["movement_name"],
            set_index=p["set_index"],
            hr_avg=stats["avg"] if stats else None,
            hr_max=stats["max"] if stats else None,
            hr_min=stats["min"] if stats else None,
            hr_recovery_30s=recovery,
            set_start=_epoch_ms_to_naive_utc(p["start_ms"]),
            set_end=_epoch_ms_to_naive_utc(p["end_ms"]),
            confidence=p["confidence"],
            match_method=p["match_method"],
        )
        session.add(row)
        rows.append(row)

    session.commit()
    return rows


def get_or_compute_set_hr(session: Session, workout: Workout) -> list[WorkoutSetHr]:
    """懒计算入口：已有行按 ``(movement_name, set_index)`` 序返回；无行则调编排函数。

    编排函数新插入的行也按同序返回，保证两次调用的列表顺序稳定一致。
    """
    existing = (
        session.query(WorkoutSetHr)
        .filter(WorkoutSetHr.workout_id == workout.id)
        .order_by(WorkoutSetHr.movement_name, WorkoutSetHr.set_index)
        .all()
    )
    if existing:
        return existing
    rows = compute_workout_set_hr(session, workout)
    rows.sort(key=lambda r: (r.movement_name, r.set_index))
    return rows