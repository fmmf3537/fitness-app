"""M4-3 管理员健康面板 API。"""
from __future__ import annotations

import os
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config import get_settings
from app.db import get_session
from app.models import JobRun, LLMCall, MatchCandidate, Setting, User

router = APIRouter(prefix="/api/admin", tags=["admin-health"])


def require_admin(
    principal: User = Depends(get_current_user),
) -> User:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    return principal


def _month_start() -> datetime:
    today = date.today()
    return datetime(today.year, today.month, 1)


def _garmin_token_state(row: Setting | None) -> str:
    if row is None:
        return "n/a"
    if row.garmin_token_store_enc:
        return "ok"
    if row.garmin_email_enc or row.garmin_password_enc:
        return "expired"
    return "missing"


def _last_sync_at(session: Session, user_id: int) -> str | None:
    started = session.scalars(
        select(JobRun.started_at)
        .where(
            JobRun.user_id == user_id,
            JobRun.job_name.in_(("daily_sync", "sync_all_users")),
        )
        .order_by(JobRun.started_at.desc())
        .limit(1)
    ).first()
    return started.isoformat() if started else None


def _monthly_llm_cost(session: Session, user_id: int) -> float:
    total = session.scalar(
        select(func.coalesce(func.sum(LLMCall.cost_estimate), 0.0)).where(
            LLMCall.user_id == user_id,
            LLMCall.created_at >= _month_start(),
        )
    )
    return round(float(total or 0.0), 4)


def _pending_match_count(session: Session, user_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(MatchCandidate)
            .where(
                MatchCandidate.user_id == user_id,
                MatchCandidate.status == "pending",
            )
        )
        or 0
    )


def _db_size_bytes(session: Session) -> int | None:
    try:
        url = get_settings().database_url
        if url.startswith("sqlite:///"):
            path = url[len("sqlite:///"):]
            if path == ":memory:":
                return None
            return os.path.getsize(path) if os.path.exists(path) else None
        size = session.execute(text("SELECT pg_database_size(current_database())")).scalar()
        return int(size) if size is not None else None
    except Exception:
        return None


def _last_backup_at(session: Session) -> str | None:
    started = session.scalars(
        select(JobRun.started_at)
        .where(JobRun.job_name == "db_backup_daily")
        .order_by(JobRun.started_at.desc())
        .limit(1)
    ).first()
    return started.isoformat() if started else None


@router.get("/health")
def admin_health(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
) -> dict:
    users_out: list[dict] = []
    for user in session.scalars(select(User).order_by(User.id)):
        setting = session.scalars(
            select(Setting).where(Setting.user_id == user.id)
        ).first()
        users_out.append({
            "user_id": user.id,
            "username": user.username,
            "is_active": bool(user.is_active),
            "garmin_token_state": _garmin_token_state(setting),
            "last_sync_at": _last_sync_at(session, user.id),
            "monthly_llm_cost": _monthly_llm_cost(session, user.id),
            "pending_match_count": _pending_match_count(session, user.id),
        })
    return {
        "users": users_out,
        "system": {
            "db_size_bytes": _db_size_bytes(session),
            "last_backup_at": _last_backup_at(session),
            "scheduler_running": True,
        },
    }
