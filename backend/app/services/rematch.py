"""单边训练手动重新匹配：只读预览与确认后原地融合。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    GarminActivity,
    MatchCandidate,
    Workout,
    WorkoutFeedback,
    XunjiTrain,
)
from app.services.fuse import build_fused_workout_values, update_fused_workout
from app.services.matcher import (
    _garmin_interval,
    _invalidate_workout_analysis,
    _xunji_interval,
    classify_pair,
    overlap_ratio,
)


class RematchValidationError(ValueError):
    """所选训练不满足重新匹配条件。"""


def _visible_workout(session: Session, workout_id: int) -> Workout:
    workout = session.get(Workout, workout_id)
    if workout is None or workout.deleted_at is not None:
        raise RematchValidationError("训练不存在或已删除")
    return workout


def _pair_from_workouts(
    session: Session, first: Workout, second: Workout,
) -> tuple[Workout, Workout, XunjiTrain, GarminActivity]:
    if first.id == second.id or first.date != second.date:
        raise RematchValidationError("请选择同一天的两条不同训练")
    if first.match_status == "xunji_only" and second.match_status == "garmin_only":
        x_workout, g_workout = first, second
    elif first.match_status == "garmin_only" and second.match_status == "xunji_only":
        x_workout, g_workout = second, first
    else:
        raise RematchValidationError("仅支持一条仅训记和一条仅佳明的训练")
    train = session.get(XunjiTrain, x_workout.xunji_train_id)
    activity = session.get(GarminActivity, g_workout.garmin_activity_id)
    if train is None or activity is None or train.excluded or activity.excluded:
        raise RematchValidationError("原始记录不可用，无法重新匹配")
    return x_workout, g_workout, train, activity


def _match_score(train: XunjiTrain, activity: GarminActivity, kind: str) -> tuple:
    xi = _xunji_interval(train)
    gi = _garmin_interval(activity)
    ratio = overlap_ratio(xi[0], xi[1], gi[0], gi[1]) if xi and gi else 0.0
    start_delta = abs((xi[0] - gi[0]).total_seconds()) if xi and gi else float("inf")
    return (1 if kind == "auto" else 0, ratio, -start_delta)


def _find_pair(
    session: Session, workout_ids: list[int],
) -> tuple[Workout, Workout, XunjiTrain, GarminActivity, str] | None:
    if len(workout_ids) == 2:
        x_workout, g_workout, train, activity = _pair_from_workouts(
            session,
            _visible_workout(session, workout_ids[0]),
            _visible_workout(session, workout_ids[1]),
        )
        kind = classify_pair(train, activity)
        return (x_workout, g_workout, train, activity, kind) if kind else None
    if len(workout_ids) != 1:
        raise RematchValidationError("请提供一条单边训练或两条待匹配训练")

    source = _visible_workout(session, workout_ids[0])
    if source.match_status not in ("xunji_only", "garmin_only"):
        raise RematchValidationError("仅支持重新匹配单边训练")
    opposite_status = "garmin_only" if source.match_status == "xunji_only" else "xunji_only"
    opposites = session.query(Workout).filter(
        Workout.date == source.date,
        Workout.deleted_at.is_(None),
        Workout.match_status == opposite_status,
    ).order_by(Workout.id).all()
    matches = []
    for opposite in opposites:
        try:
            x_workout, g_workout, train, activity = _pair_from_workouts(
                session, source, opposite,
            )
        except RematchValidationError:
            continue
        kind = classify_pair(train, activity)
        if kind:
            matches.append((
                _match_score(train, activity, kind),
                x_workout, g_workout, train, activity, kind,
            ))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], -item[1].id), reverse=True)
    return matches[0][1:]


def _preview_payload(pair) -> dict:
    if pair is None:
        return {"action": "unmatched", "message": "没有找到符合时间条件的另一侧单边训练"}
    x_workout, g_workout, train, activity, kind = pair
    xi = _xunji_interval(train)
    gi = _garmin_interval(activity)
    ratio = overlap_ratio(xi[0], xi[1], gi[0], gi[1]) if xi and gi else 0.0
    values = build_fused_workout_values(
        x_workout.date, xunji=train, garmin=activity,
        match_status="auto_matched" if kind == "auto" else "manual_matched",
    )
    return {
        "action": "merge" if kind == "auto" else "candidate",
        "reason": kind,
        "overlap_ratio": ratio,
        "xunji_workout_id": x_workout.id,
        "garmin_workout_id": g_workout.id,
        "keep_workout_id": x_workout.id,
        "xunji_train": {
            "id": train.id, "title": train.title,
            "start_ms": train.start_ms, "end_ms": train.end_ms,
        },
        "garmin_activity": {
            "id": activity.id, "name": activity.name,
            "start_ts": activity.start_ts.isoformat() if activity.start_ts else None,
            "end_ts": activity.end_ts.isoformat() if activity.end_ts else None,
        },
        "workout": {
            "date": values["date"].isoformat(),
            "title": values["title"],
            "match_status": values["match_status"],
            "duration_s": values["duration_s"],
            "calories": values["calories"],
            "avg_hr": values["avg_hr"],
            "max_hr": values["max_hr"],
        },
    }


def preview_rematch(session: Session, workout_ids: list[int]) -> dict:
    """只读预览；一条 id 时自动寻找最佳另一侧，两条 id 时校验指定组合。"""
    return _preview_payload(_find_pair(session, workout_ids))


def _migrate_feedback(session: Session, keep_id: int, duplicate_id: int) -> None:
    keep_feedback = session.get(WorkoutFeedback, keep_id)
    duplicate_feedback = session.get(WorkoutFeedback, duplicate_id)
    if keep_feedback is not None and duplicate_feedback is not None:
        raise RematchValidationError("两条训练都有训练后反馈，为避免覆盖请先手动处理")
    if duplicate_feedback is not None:
        duplicate_feedback.workout_id = keep_id
        session.flush()


def confirm_rematch(session: Session, workout_ids: list[int]) -> dict:
    """确认后执行；必须传入预览确定的两条 id，避免确认时匹配对象发生变化。"""
    if len(workout_ids) != 2:
        raise RematchValidationError("确认重新匹配时必须提供预览中的两条训练 id")
    pair = _find_pair(session, workout_ids)
    if pair is None:
        raise RematchValidationError("两条训练不满足自动合并或时间接近条件")
    x_workout, g_workout, train, activity, kind = pair
    _migrate_feedback(session, x_workout.id, g_workout.id)

    pending = session.query(MatchCandidate).filter(
        MatchCandidate.status == "pending",
        (MatchCandidate.workout_id == g_workout.id)
        | (MatchCandidate.garmin_activity_id == activity.id)
        | (MatchCandidate.xunji_train_id == train.id),
    ).order_by(MatchCandidate.id).all()
    now = datetime.now()
    if kind == "auto":
        _invalidate_workout_analysis(session, x_workout.id)
        _invalidate_workout_analysis(session, g_workout.id)
        update_fused_workout(
            x_workout, x_workout.date,
            xunji=train, garmin=activity, match_status="auto_matched",
        )
        for candidate in pending:
            candidate.workout_id = x_workout.id
            candidate.xunji_train_id = train.id
            candidate.garmin_activity_id = activity.id
            candidate.status = "merged"
            candidate.resolved_at = now
        session.delete(g_workout)
        session.commit()
        return {
            "action": "merge", "workout_id": x_workout.id,
            "candidate_ids": [c.id for c in pending],
        }

    _invalidate_workout_analysis(session, g_workout.id)
    candidate = pending[0] if pending else MatchCandidate(status="pending")
    for extra in pending[1:]:
        session.delete(extra)
    candidate.workout_id = x_workout.id
    candidate.xunji_train_id = train.id
    candidate.garmin_activity_id = activity.id
    candidate.reason = "time_close"
    candidate.status = "pending"
    candidate.resolved_at = None
    session.add(candidate)
    session.delete(g_workout)
    session.commit()
    return {
        "action": "candidate", "workout_id": x_workout.id,
        "candidate_id": candidate.id,
    }
