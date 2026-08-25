"""M4-4 管理员代查看 / 代触发同步 API。"""
from __future__ import annotations

import calendar as _cal
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db import get_session
from app.models import AIReport, User, Workout
from app.services import body_metrics as body_metrics_service
from app.services import sync as sync_mod

router = APIRouter(prefix="/api/admin", tags=["admin-impersonate"])


def require_admin(
    principal: User = Depends(get_current_user),
) -> User:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    return principal


def _write_audit(
    session: Session,
    actor_user_id: int,
    target_user_id: int | None,
    action: str,
    summary: dict | None = None,
) -> None:
    from app.models import AuditLog

    session.add(AuditLog(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        action=action,
        target_table=None,
        target_id=None,
        summary_json=json.dumps(summary or {}, ensure_ascii=False, default=str),
    ))
    session.commit()


def _require_target(session: Session, user_id: int) -> User:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return target


def _serialize_workout(w: Workout) -> dict:
    return {
        "id": w.id,
        "date": w.date.isoformat(),
        "title": w.title,
        "match_status": w.match_status,
        "tags": w.tags,
        "duration_s": w.duration_s,
        "calories": w.calories,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
    }


def _serialize_report(report: AIReport) -> dict:
    return {
        "id": report.id,
        "type": report.type,
        "workout_id": report.workout_id,
        "date": report.period_start.isoformat() if report.period_start else None,
        "period_end": report.period_end.isoformat() if report.period_end else None,
        "model": report.model,
        "content_md": report.content_md,
        "cost_estimate": report.cost_estimate,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/impersonate/{user_id}/workouts")
def impersonate_list_workouts(
    user_id: int,
    session: Session = Depends(get_session),
    principal: User = Depends(require_admin),
) -> dict:
    _require_target(session, user_id)
    rows = list(
        session.scalars(
            select(Workout)
            .where(
                Workout.user_id == user_id,
                Workout.deleted_at.is_(None),
            )
            .order_by(Workout.date.desc(), Workout.id.desc())
        )
    )
    _write_audit(
        session, principal.id, user_id, "impersonate_view_workouts",
        summary={"count": len(rows)},
    )
    return {"workouts": [_serialize_workout(w) for w in rows]}


@router.get("/impersonate/{user_id}/workouts/calendar")
def impersonate_workout_calendar(
    user_id: int,
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
    session: Session = Depends(get_session),
    principal: User = Depends(require_admin),
) -> dict:
    _require_target(session, user_id)
    year, mon = int(month[:4]), int(month[5:7])
    first = date(year, mon, 1)
    last = date(year, mon, _cal.monthrange(year, mon)[1])
    rows = list(
        session.scalars(
            select(Workout)
            .where(
                Workout.user_id == user_id,
                Workout.deleted_at.is_(None),
                Workout.date >= first,
                Workout.date <= last,
            )
            .order_by(Workout.date, Workout.id)
        )
    )
    days: dict[str, dict] = {}
    for w in rows:
        key = w.date.isoformat()
        days.setdefault(key, {"date": key, "workouts": []})["workouts"].append(
            {"id": w.id, "title": w.title, "match_status": w.match_status, "tags": w.tags}
        )
    _write_audit(
        session, principal.id, user_id, "impersonate_view_workouts_calendar",
        summary={"month": month, "days": len(days)},
    )
    return {"month": month, "days": list(days.values())}


@router.get("/impersonate/{user_id}/ai-reports")
def impersonate_ai_reports(
    user_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    principal: User = Depends(require_admin),
) -> dict:
    _require_target(session, user_id)
    rows = list(
        session.scalars(
            select(AIReport)
            .where(AIReport.user_id == user_id)
            .order_by(AIReport.created_at.desc(), AIReport.id.desc())
            .limit(limit)
        )
    )
    _write_audit(
        session, principal.id, user_id, "impersonate_view_ai_reports",
        summary={"count": len(rows)},
    )
    return {"reports": [_serialize_report(r) for r in rows]}


@router.get("/impersonate/{user_id}/body-metrics")
def impersonate_body_metrics(
    user_id: int,
    session: Session = Depends(get_session),
    principal: User = Depends(require_admin),
) -> dict:
    _require_target(session, user_id)
    rows = body_metrics_service.query_body_metrics(session, user_id=user_id)
    _write_audit(
        session, principal.id, user_id, "impersonate_view_body_metrics",
        summary={"count": len(rows)},
    )
    return {"metrics": [body_metrics_service.to_dict(r) for r in rows]}


@router.post("/impersonate/{user_id}/sync/{day}")
def impersonate_sync_day(
    user_id: int,
    day: str,
    session: Session = Depends(get_session),
    principal: User = Depends(require_admin),
) -> dict:
    _require_target(session, user_id)
    try:
        day_date = date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="day 格式必须为 YYYY-MM-DD") from exc
    # 不传 session：daily_sync 自建事务；admin 会话只写 audit
    result = sync_mod.daily_sync(day_date, user_id=user_id)
    _write_audit(
        session, principal.id, user_id, "impersonate_sync",
        summary={"day": day, "status": result.get("status") if isinstance(result, dict) else None},
    )
    return {"ok": True, "user_id": user_id, "day": day, "result": result}
