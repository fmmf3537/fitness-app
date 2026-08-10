"""M4 融合匹配引擎：严格按 PRD §5.1 伪代码实现。

- 第一轮：时间重叠率（重叠时长 / 较短区间时长）≥ 0.6 → auto_matched；
- 第二轮：起止差 ≤ 30min → match_candidate(status='pending', reason='time_close')，
  两侧记录从待配池移除；
- 剩余：训记单边 → xunji_only；佳明单边 → garmin_only，
  佳明活动类型为力量训练时额外写 match_candidate(reason='garmin_only_strength')；
- 幂等：已被 workout 或 pending 候选引用的原始记录不再参与匹配，重复运行不产生重复数据。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import GarminActivity, MatchCandidate, Workout, XunjiTrain
from app.services.fuse import fuse_workout

OVERLAP_THRESHOLD = 0.6
CLOSE_DELTA = timedelta(minutes=30)
STRENGTH_TYPES = {
    "strength_training",
    "strength",
    "weight_training",
    "indoor_strength_training",
}


def overlap_ratio(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    """重叠率 = 重叠时长 / 较短区间时长（PRD §5.1 第一轮）。"""
    shorter = min((a_end - a_start).total_seconds(), (b_end - b_start).total_seconds())
    if shorter <= 0:
        return 0.0
    overlap = (min(a_end, b_end) - max(a_start, b_start)).total_seconds()
    return max(overlap, 0.0) / shorter


# 训记 start_ms/end_ms 是 epoch 毫秒（绝对时刻），佳明侧存 startTimeLocal（北京墙钟）。
# 两侧比较前必须统一渲染到 +08:00：用固定时区而非服务器本地时区，
# 保证在非 +08:00 机器（如 UTC 的 CI runner、海外服务器）上匹配结果一致。
XUNJI_TZ = timezone(timedelta(hours=8))


def _xunji_interval(train: XunjiTrain) -> tuple[datetime, datetime] | None:
    if train.start_ms is None or train.end_ms is None:
        return None
    return (
        datetime.fromtimestamp(train.start_ms / 1000, tz=XUNJI_TZ).replace(tzinfo=None),
        datetime.fromtimestamp(train.end_ms / 1000, tz=XUNJI_TZ).replace(tzinfo=None),
    )


def _garmin_interval(activity: GarminActivity) -> tuple[datetime, datetime] | None:
    if activity.start_ts is None or activity.end_ts is None:
        return None
    return (activity.start_ts, activity.end_ts)


def _processed_ids(session: Session) -> tuple[set, set]:
    """已被 workout 或 pending 候选引用的原始记录 id（保证重复运行幂等）。"""
    done_x = {r[0] for r in session.query(Workout.xunji_train_id).filter(Workout.xunji_train_id.isnot(None))}
    done_g = {r[0] for r in session.query(Workout.garmin_activity_id).filter(Workout.garmin_activity_id.isnot(None))}
    pending = session.query(MatchCandidate).filter(MatchCandidate.status == "pending").all()
    for c in pending:
        done_x.add(c.xunji_train_id)
        done_g.add(c.garmin_activity_id)
    return done_x, done_g


def match_day(session: Session, day: date) -> dict:
    """对某一天执行训记×佳明匹配与融合，返回 {"workouts": [...], "candidates": [...]}。"""
    datestr = day.isoformat()
    trains = session.query(XunjiTrain).filter(XunjiTrain.datestr == datestr).all()
    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    activities = (
        session.query(GarminActivity)
        .filter(GarminActivity.start_ts >= day_start, GarminActivity.start_ts < day_end)
        .all()
    )

    done_x, done_g = _processed_ids(session)
    unmatched_x = [t for t in trains if t.id not in done_x]
    unmatched_g = [a for a in activities if a.id not in done_g]

    workouts: list[Workout] = []
    candidates: list[MatchCandidate] = []

    # 第一轮：时间重叠 ≥ 60% → 自动匹配
    pairs: list[tuple[XunjiTrain, GarminActivity]] = []
    for x in list(unmatched_x):
        xi = _xunji_interval(x)
        if xi is None:
            continue
        for g in list(unmatched_g):
            gi = _garmin_interval(g)
            if gi is None:
                continue
            if overlap_ratio(xi[0], xi[1], gi[0], gi[1]) >= OVERLAP_THRESHOLD:
                pairs.append((x, g))
                unmatched_x.remove(x)
                unmatched_g.remove(g)
                break

    # 第二轮：起止差 ≤ 30min → 待确认队列
    for x in list(unmatched_x):
        xi = _xunji_interval(x)
        if xi is None:
            continue
        for g in list(unmatched_g):
            gi = _garmin_interval(g)
            if gi is None:
                continue
            if abs(xi[0] - gi[0]) <= CLOSE_DELTA or abs(xi[1] - gi[1]) <= CLOSE_DELTA:
                candidates.append(MatchCandidate(
                    xunji_train_id=x.id,
                    garmin_activity_id=g.id,
                    reason="time_close",
                    status="pending",
                ))
                unmatched_x.remove(x)
                unmatched_g.remove(g)
                break

    # 自动匹配对 → 融合
    for x, g in pairs:
        workouts.append(fuse_workout(session, day, xunji=x, garmin=g, match_status="auto_matched"))

    # 剩余训记单边
    for x in unmatched_x:
        workouts.append(fuse_workout(session, day, xunji=x, match_status="xunji_only"))

    # 剩余佳明单边（力量类型提示可生成训记草稿）
    for g in unmatched_g:
        w = fuse_workout(session, day, garmin=g, match_status="garmin_only")
        workouts.append(w)
        if (g.activity_type or "").lower() in STRENGTH_TYPES:
            candidates.append(MatchCandidate(
                workout_id=w.id,
                garmin_activity_id=g.id,
                reason="garmin_only_strength",
                status="pending",
            ))

    session.add_all(candidates)
    session.commit()
    return {"workouts": workouts, "candidates": candidates}
