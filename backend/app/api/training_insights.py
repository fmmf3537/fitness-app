"""训记协同洞察：同步回执、建议状态、计划对照、轻反馈和目标。"""
from __future__ import annotations

import json
from datetime import date, timedelta
from math import isfinite

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.models import (AIReport, AdviceAction, BodyMetric, JobRun,
                        PlanSnapshot, TrainingGoal, Workout, WorkoutFeedback)

router = APIRouter(prefix="/api/training", tags=["training"], dependencies=[Depends(require_auth)])


def _json(value, fallback=None):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def _visible_workout(session: Session, workout_id: int) -> Workout:
    workout = session.get(Workout, workout_id)
    if workout is None or workout.deleted_at is not None:
        raise HTTPException(404, "训练不存在")
    return workout


@router.get("/sync-receipt")
def sync_receipt(session: Session = Depends(get_session)) -> dict:
    """持久化的最近一次每日同步回执，含当天当前报告和待确认状态。"""
    run = (session.query(JobRun).filter(JobRun.job_name == "daily_sync")
           .order_by(JobRun.id.desc()).first())
    if run is None:
        return {"run": None}
    detail = _json(run.detail_json, {}) or {}
    day_str = detail.get("date")
    day = None
    try:
        day = date.fromisoformat(day_str) if day_str else None
    except ValueError:
        pass
    workouts = session.query(Workout).filter(Workout.date == day, Workout.deleted_at.is_(None)).all() if day else []
    ids = [w.id for w in workouts]
    reports = (session.query(AIReport).filter(AIReport.workout_id.in_(ids),
               AIReport.type.in_(["session_review", "next_advice"])).all()) if ids else []
    report_counts = {kind: sum(r.type == kind for r in reports) for kind in ("session_review", "next_advice")}
    pending = detail.get("candidates")
    return {"run": {"id": run.id, "date": day_str, "status": run.status,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "error": run.error, "sources": {k: detail.get(k) for k in
                    ("xunji_trains", "garmin_activities", "garmin_daily", "workouts", "candidates")},
                    "failed_step": detail.get("failed_step"),
                    "ai_failed": bool(detail.get("ai_reviews_failed")),
                    "changes": detail.get("workout_changes"),
                    "report_counts": report_counts, "pending": pending,
                    "workouts": [{"id": w.id, "title": w.title, "match_status": w.match_status}
                                 for w in workouts]}}


def _suggestions(report: AIReport) -> list[dict]:
    import re
    match = re.search(r"```json\s*\n([\s\S]*?)\n```", report.content_md or "")
    data = _json(match.group(1), {}) if match else {}
    if not isinstance(data, dict) or data.get("schema") != "next_advice_v1":
        return []
    suggestions = data.get("suggestions")
    return suggestions if isinstance(suggestions, list) else []


def _action_outcome(session: Session, report: AIReport, suggestion: dict) -> dict:
    """只报告后续同名动作的观察值，不把相关性描述为建议成效。"""
    source = session.get(Workout, report.workout_id) if report.workout_id else None
    movement = str(suggestion.get("movement") or "").strip().casefold()
    if source is None or not movement:
        return {"status": "unknown"}
    later = (session.query(Workout).filter(Workout.date > source.date,
             Workout.date <= source.date + timedelta(days=84), Workout.deleted_at.is_(None))
             .order_by(Workout.date, Workout.id).all())
    for workout in later:
        for mv in _json(workout.movements_json, []) or []:
            if isinstance(mv, dict) and str(mv.get("name") or "").strip().casefold() == movement:
                sets = mv.get("sets") or []
                return {"status": "observed", "date": workout.date.isoformat(),
                        "sets": [{"weight": s.get("weight"), "reps": s.get("reps")}
                                 for s in sets[:5] if isinstance(s, dict)]}
    return {"status": "not_observed"}


@router.get("/actions/{report_id}")
def get_actions(report_id: int, session: Session = Depends(get_session)) -> dict:
    report = session.get(AIReport, report_id)
    if report is None or report.type != "next_advice":
        raise HTTPException(404, "下次建议报告不存在")
    states = {a.item_index: a.status for a in session.query(AdviceAction).filter_by(report_id=report_id).all()}
    return {"report_id": report_id, "actions": [
        {"index": i, "movement": s.get("movement"), "original": s.get("original"),
         "suggested": s.get("suggested"), "reason": s.get("reason"),
         "category": s.get("category"), "status": states.get(i),
         "follow_up": _action_outcome(session, report, s)}
        for i, s in enumerate(_suggestions(report)) if isinstance(s, dict)][:3],
        "total": len(_suggestions(report))}


class ActionUpdate(BaseModel):
    status: str | None = None


@router.put("/actions/{report_id}/{item_index}")
def put_action(report_id: int, item_index: int, body: ActionUpdate,
               session: Session = Depends(get_session)) -> dict:
    report = session.get(AIReport, report_id)
    if report is None or report.type != "next_advice":
        raise HTTPException(404, "下次建议报告不存在")
    if item_index < 0 or item_index >= len(_suggestions(report)):
        raise HTTPException(404, "建议不存在")
    if body.status not in (None, "done", "skipped"):
        raise HTTPException(422, "状态只支持已处理或跳过")
    row = session.query(AdviceAction).filter_by(report_id=report_id, item_index=item_index).first()
    if body.status is None:
        if row:
            session.delete(row)
    elif row:
        row.status = body.status
    else:
        session.add(AdviceAction(report_id=report_id, item_index=item_index, status=body.status))
    session.commit()
    return {"report_id": report_id, "index": item_index, "status": body.status}


@router.get("/plan-comparison/{day}")
def plan_comparison(day: date, session: Session = Depends(get_session)) -> dict:
    snapshot = session.get(PlanSnapshot, day)
    workouts = session.query(Workout).filter(Workout.date == day, Workout.deleted_at.is_(None)).all()
    if snapshot is None:
        return {"date": day.isoformat(), "status": "no_snapshot", "movements": [],
                "workout_count": len(workouts)}
    plan = _json(snapshot.plan_json, {}) or {}
    if plan.get("is_rest"):
        return {"date": day.isoformat(), "status": "rest_day", "movements": [],
                "workout_count": len(workouts), "captured_at": snapshot.captured_at.isoformat()}
    if not workouts:
        return {"date": day.isoformat(), "status": "no_workout_data", "movements": [],
                "workout_count": 0, "captured_at": snapshot.captured_at.isoformat()}
    actual: dict[str, list] = {}
    for workout in workouts:
        for movement in _json(workout.movements_json, []) or []:
            if isinstance(movement, dict):
                name = str(movement.get("name") or "").strip().casefold()
                if name:
                    actual.setdefault(name, []).extend(movement.get("sets") or [])
    if not actual:
        return {"date": day.isoformat(), "status": "no_movement_data", "movements": [],
                "workout_count": len(workouts), "captured_at": snapshot.captured_at.isoformat()}
    compared = []
    seen = set()
    for movement in plan.get("movements") or []:
        name = str(movement.get("name") or "").strip()
        key = name.casefold()
        seen.add(key)
        expected = len(movement.get("target_sets") or [])
        sets = actual.get(key)
        completed = sum(s.get("done", True) not in (False, 0, "0", "false", "False")
                        for s in sets if isinstance(s, dict)) if sets is not None else 0
        compared.append({"name": name, "planned_sets": expected, "completed_sets": completed,
                         "status": "unmatched" if sets is None else
                         "matched" if expected == completed else "less" if completed < expected else "more"})
    for key, sets in actual.items():
        if key not in seen:
            compared.append({"name": key, "planned_sets": 0, "completed_sets": len(sets), "status": "extra"})
    return {"date": day.isoformat(), "status": "compared", "movements": compared,
            "workout_count": len(workouts), "captured_at": snapshot.captured_at.isoformat()}


class FeedbackInput(BaseModel):
    fatigue: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=1, le=5)
    discomfort: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


@router.get("/feedback/{workout_id}")
def get_feedback(workout_id: int, session: Session = Depends(get_session)) -> dict:
    _visible_workout(session, workout_id)
    row = session.get(WorkoutFeedback, workout_id)
    return {"workout_id": workout_id, "feedback": None if row is None else {
        "fatigue": row.fatigue, "soreness": row.soreness,
        "discomfort": row.discomfort, "note": row.note}}


@router.put("/feedback/{workout_id}")
def put_feedback(workout_id: int, body: FeedbackInput, session: Session = Depends(get_session)) -> dict:
    _visible_workout(session, workout_id)
    row = session.get(WorkoutFeedback, workout_id)
    if row is None:
        row = WorkoutFeedback(workout_id=workout_id)
        session.add(row)
    row.fatigue = body.fatigue
    row.soreness = body.soreness
    row.discomfort = (body.discomfort or "").strip() or None
    row.note = (body.note or "").strip() or None
    session.commit()
    return get_feedback(workout_id, session)


@router.delete("/feedback/{workout_id}")
def delete_feedback(workout_id: int, session: Session = Depends(get_session)) -> dict:
    _visible_workout(session, workout_id)
    row = session.get(WorkoutFeedback, workout_id)
    if row:
        session.delete(row)
        session.commit()
    return {"ok": True}


class GoalInput(BaseModel):
    kind: str
    target: float = Field(gt=0)
    movement: str | None = Field(default=None, max_length=100)


def _goal_payload(goal: TrainingGoal, session: Session) -> dict:
    today = date.today()
    current = None
    sample_size = 0
    if goal.kind == "sessions_week":
        start = today - timedelta(days=today.weekday())
        rows = session.query(Workout).filter(Workout.date >= start, Workout.date <= today,
                                            Workout.deleted_at.is_(None)).all()
        current = len(rows)
        sample_size = len(rows)
    elif goal.kind == "movement_weight":
        rows = session.query(Workout).filter(Workout.date >= today - timedelta(days=84),
                                            Workout.deleted_at.is_(None)).all()
        weights = []
        for w in rows:
            for mv in _json(w.movements_json, []) or []:
                if (isinstance(mv, dict)
                        and str(mv.get("name") or "").strip().casefold() == (goal.movement or "").casefold()
                        and mv.get("exetype") not in ("help", "assisted")):
                    for item in mv.get("sets") or []:
                        try:
                            if item.get("done", True) not in (False, 0, "0", "false", "False"):
                                weights.append(float(item.get("weight")))
                        except (ValueError, TypeError, AttributeError):
                            pass
        sample_size = len(weights)
        current = max(weights) if weights else None
    elif goal.kind == "body_weight":
        rows = (session.query(BodyMetric).filter(BodyMetric.type == "weight",
                BodyMetric.date >= today - timedelta(days=14)).order_by(BodyMetric.date.desc()).all())
        sample_size = len(rows)
        current = round(sum(r.value for r in rows[:7]) / min(len(rows), 7), 2) if rows else None
    return {"id": goal.id, "kind": goal.kind, "target": goal.target,
            "movement": goal.movement, "current": current, "sample_size": sample_size,
            "sufficient_data": sample_size >= (2 if goal.kind in ("body_weight", "movement_weight") else 1)}


@router.get("/goals")
def list_goals(session: Session = Depends(get_session)) -> dict:
    goals = session.query(TrainingGoal).filter(TrainingGoal.active.is_(True)).order_by(TrainingGoal.id).all()
    return {"goals": [_goal_payload(g, session) for g in goals]}


@router.post("/goals", status_code=201)
def add_goal(body: GoalInput, session: Session = Depends(get_session)) -> dict:
    if body.kind not in ("sessions_week", "movement_weight", "body_weight"):
        raise HTTPException(422, "不支持的目标类型")
    if not isfinite(body.target) or (body.kind == "sessions_week" and (body.target > 14 or not body.target.is_integer())):
        raise HTTPException(422, "目标数值无效")
    movement = (body.movement or "").strip() or None
    if body.kind == "movement_weight" and not movement:
        raise HTTPException(422, "动作目标需要动作名称")
    goal = TrainingGoal(kind=body.kind, target=body.target, movement=movement)
    session.add(goal)
    session.commit()
    return _goal_payload(goal, session)


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int, session: Session = Depends(get_session)) -> dict:
    goal = session.get(TrainingGoal, goal_id)
    if goal is None or not goal.active:
        raise HTTPException(404, "目标不存在")
    goal.active = False
    session.commit()
    return {"ok": True}
