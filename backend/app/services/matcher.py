"""M4 融合匹配引擎：严格按 PRD §5.1 伪代码实现。

- 第一轮：时间重叠率（重叠时长 / 较短区间时长）≥ 0.6 → auto_matched；
- 第二轮：起止差 ≤ 30min → match_candidate(status='pending', reason='time_close')，
  两侧记录从待配池移除；
- 剩余：训记单边 → xunji_only；佳明单边 → garmin_only，
  佳明活动类型为力量训练时额外写 match_candidate(reason='garmin_only_strength')；
- 幂等：已被 workout 或 pending 候选引用的原始记录不再参与匹配，重复运行不产生重复数据；
- V2-7b：已配对 workout 的训记原始记录若晚于 workout.updated_at 重新拉取过，
  就地刷新 movements_json 并重生成当日 AI 报告（见 _refresh_stale_workouts）。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import AIReport, GarminActivity, MatchCandidate, Workout, XunjiTrain
from app.services.fuse import _extract_movements, fuse_workout

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
    """已被 workout 或 pending 候选引用的原始记录 id（保证重复运行幂等）。

    注意：不过滤 deleted_at——已软删除 workout 的源 id 仍算“已处理”，
    与 excluded 墓碑共同保证删除后不被重建（V3-11）。
    """
    done_x = {r[0] for r in session.query(Workout.xunji_train_id).filter(Workout.xunji_train_id.isnot(None))}
    done_g = {r[0] for r in session.query(Workout.garmin_activity_id).filter(Workout.garmin_activity_id.isnot(None))}
    pending = session.query(MatchCandidate).filter(MatchCandidate.status == "pending").all()
    for c in pending:
        done_x.add(c.xunji_train_id)
        done_g.add(c.garmin_activity_id)
    return done_x, done_g


def match_day(session: Session, day: date, *, chat_fn=None) -> dict:
    """对某一天执行训记×佳明匹配与融合。

    返回 {"workouts": [...], "candidates": [...], "refreshed": [workout_id, ...]}。
    chat_fn 透传给 AI 重生成（测试注入）；为 None 时走 adapters.llm.chat。
    """
    datestr = day.isoformat()
    # excluded=True 为删除墓碑（V3-11）：不参与匹配
    trains = (
        session.query(XunjiTrain)
        .filter(XunjiTrain.datestr == datestr, XunjiTrain.excluded.is_(False))
        .all()
    )
    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    activities = (
        session.query(GarminActivity)
        .filter(
            GarminActivity.start_ts >= day_start,
            GarminActivity.start_ts < day_end,
            GarminActivity.excluded.is_(False),
        )
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
    refreshed = _refresh_stale_workouts(session, day, chat_fn=chat_fn)
    return {"workouts": workouts, "candidates": candidates, "refreshed": refreshed}


def _refresh_stale_workouts(session: Session, day: date, *, chat_fn=None) -> list[int]:
    """V2-7b 缺陷3：已配对 workout 的训记原始记录若在 workout.updated_at 之后
    重新拉取过（fetched_at 更新），就地用 fuse._extract_movements 重算
    movements_json（不新建 workout 行、不动匹配关系），并删除该 workout 当日
    已有的 session_review / next_advice 后重生成，保证 AI 报告基于最新数据。

    返回刷新的 workout id 列表。AI 重生成失败不阻断匹配主流程
    （daily_sync 的 AI 阶段会再次尝试）。
    """
    # 延迟导入：避免 services 层模块间循环依赖
    from app.services.ai import run_daily_next_advices, run_daily_reviews

    workouts = (
        session.query(Workout)
        .filter(
            Workout.date == day,
            Workout.xunji_train_id.isnot(None),
            Workout.deleted_at.is_(None),
        )
        .order_by(Workout.id)
        .all()
    )
    refreshed: list[int] = []
    for w in workouts:
        train = session.get(XunjiTrain, w.xunji_train_id)
        if train is None or train.fetched_at is None or w.updated_at is None:
            continue
        if train.fetched_at <= w.updated_at:
            continue
        w.movements_json = _extract_movements(train)
        refreshed.append(w.id)

    if not refreshed:
        return []

    # 删除当日旧 AI 报告（两种类型），提交后重生成
    session.query(AIReport).filter(
        AIReport.workout_id.in_(refreshed),
        AIReport.type.in_(("session_review", "next_advice")),
        AIReport.period_start == day,
    ).delete(synchronize_session=False)
    session.commit()

    try:
        run_daily_reviews(session, day, chat_fn=chat_fn)
        run_daily_next_advices(session, day, chat_fn=chat_fn)
    except Exception:  # noqa: BLE001 - AI 重生成失败不阻断匹配，daily_sync AI 阶段会重试
        pass
    return refreshed
