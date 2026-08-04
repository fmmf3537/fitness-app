"""M4 字段级融合：严格按 PRD §5.2。

动作维度（movements_json）→ 训记；时长/热量/心率 → 佳明；
标题 → 训记（佳明活动类型作标签，存 workout.tags）。
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session

from app.models import GarminActivity, Workout, XunjiTrain


def _extract_movements(train: XunjiTrain | None) -> str | None:
    """从训记原始记录 raw_json 中提取 movements 列表（原样保留 name/sets）。"""
    if train is None or not train.raw_json:
        return None
    try:
        raw = json.loads(train.raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    movements = raw.get("movements")
    if not movements:
        return None
    return json.dumps(movements, ensure_ascii=False)


def fuse_workout(
    session: Session,
    day: date,
    *,
    xunji: XunjiTrain | None = None,
    garmin: GarminActivity | None = None,
    match_status: str,
) -> Workout:
    """按 PRD §5.2 融合两侧原始记录，产出 workout 行（保留两侧外键）。"""
    if xunji is None and garmin is None:
        raise ValueError("xunji 与 garmin 至少提供一个")
    workout = Workout(
        date=day,
        title=(xunji.title if xunji else None) or (garmin.name if garmin else None),
        xunji_train_id=xunji.id if xunji else None,
        garmin_activity_id=garmin.id if garmin else None,
        match_status=match_status,
        tags=garmin.activity_type if garmin else None,
        duration_s=garmin.duration_s if garmin else None,
        calories=garmin.calories if garmin else None,
        avg_hr=garmin.avg_hr if garmin else None,
        max_hr=garmin.max_hr if garmin else None,
        movements_json=_extract_movements(xunji),
    )
    session.add(workout)
    session.commit()
    return workout
