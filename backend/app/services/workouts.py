"""V3-11 训练删除/恢复：软删除 + 源墓碑（防同步复活）。

- 删除：workout 打 deleted_at；关联 garmin_activity/xunji_train 打 excluded=True
  （同步 upsert 跳过更新、匹配器不扫描，彻底防复活）；关联 session_review /
  next_advice 报告及追问消息删除；match_candidate 相关行清理；
- 恢复：清 deleted_at 与两侧墓碑（不重建 AI 报告，用户可在 AI 报告页手动重生成）；
- 不触碰 garmin_daily 日汇总与 body_metric（假设，已记入任务）。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    AIReport,
    GarminActivity,
    MatchCandidate,
    ReportChatMessage,
    Workout,
    XunjiTrain,
)

# 仅单次训练维度的报告随 workout 删除；weekly/monthly/plan_review 是周期报告，保留
_DELETE_REPORT_TYPES = ("session_review", "next_advice")


def delete_workout(session: Session, workout_id: int, *,
                   user_id: int | None = None) -> Workout | None:
    """软删除一次训练。幂等：已删除时直接返回现状；不存在或不属于该用户返回 None。"""
    w = session.get(Workout, workout_id)
    if w is None or w.user_id != user_id:
        return None
    if w.deleted_at is not None:
        return w

    w.deleted_at = datetime.now()
    if w.garmin_activity_id is not None:
        activity = session.get(GarminActivity, w.garmin_activity_id)
        if activity is not None:
            activity.excluded = True
    if w.xunji_train_id is not None:
        train = session.get(XunjiTrain, w.xunji_train_id)
        if train is not None:
            train.excluded = True

    reports = (
        session.query(AIReport)
        .filter(AIReport.workout_id == w.id, AIReport.type.in_(_DELETE_REPORT_TYPES))
        .all()
    )
    report_ids = [r.id for r in reports]
    if report_ids:
        # ReportChatMessage.report_id 虽有 ondelete=CASCADE，但 SQLite 默认不启用
        # 外键约束，这里显式删除保证跨库行为一致
        session.query(ReportChatMessage).filter(
            ReportChatMessage.report_id.in_(report_ids)
        ).delete(synchronize_session=False)
        session.query(AIReport).filter(AIReport.id.in_(report_ids)).delete(
            synchronize_session=False
        )

    session.query(MatchCandidate).filter(MatchCandidate.workout_id == w.id).delete(
        synchronize_session=False
    )
    session.commit()
    return w


def restore_workout(session: Session, workout_id: int, *,
                    user_id: int | None = None) -> Workout | None:
    """恢复已删除的训练：清 deleted_at 与两侧墓碑。不存在/未删除/不属于该用户返回 None。"""
    w = session.get(Workout, workout_id)
    if w is None or w.user_id != user_id or w.deleted_at is None:
        return None

    w.deleted_at = None
    if w.garmin_activity_id is not None:
        activity = session.get(GarminActivity, w.garmin_activity_id)
        if activity is not None:
            activity.excluded = False
    if w.xunji_train_id is not None:
        train = session.get(XunjiTrain, w.xunji_train_id)
        if train is not None:
            train.excluded = False
    session.commit()
    return w


def list_deleted_workouts(session: Session, *, user_id: int | None = None) -> list[Workout]:
    """已删除训练列表（删除时间倒序），供「已删除的训练」页恢复操作。"""
    return (
        session.query(Workout)
        .filter(Workout.deleted_at.isnot(None), Workout.user_id == user_id)
        .order_by(Workout.deleted_at.desc(), Workout.id.desc())
        .all()
    )
