"""M4-2 管理员用户管理 API。"""
from __future__ import annotations

import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db import get_session
from app.models import AuthToken, JobRun, LLMCall, Setting, User
from app.services import users as user_service
from app.utils.password import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin-users"])


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
        target_table="users",
        target_id=target_user_id,
        summary_json=json.dumps(summary or {}, ensure_ascii=False, default=str),
    ))
    session.commit()


def _purge_tokens(session: Session, user_id: int) -> None:
    session.execute(delete(AuthToken).where(AuthToken.user_id == user_id))
    session.commit()


def _month_start() -> datetime:
    today = date.today()
    return datetime(today.year, today.month, 1)


def _bindings_for(session: Session, user_id: int) -> dict:
    row = session.scalars(select(Setting).where(Setting.user_id == user_id)).first()
    if row is None:
        return {"garmin": False, "xunji": False, "llm": False}
    return {
        "garmin": bool(row.garmin_email_enc),
        "xunji": bool(row.xunji_api_key_enc),
        "llm": bool(row.llm_keys_json_enc),
    }


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


def _serialize_user(session: Session, user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": bool(user.is_active),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "bindings": _bindings_for(session, user.id),
        "last_sync_at": _last_sync_at(session, user.id),
        "monthly_llm_cost": _monthly_llm_cost(session, user.id),
    }


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    role: str = "user"


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=1)


@router.get("/users")
def list_users(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
) -> list[dict]:
    users = user_service.list_users(session)
    return [_serialize_user(session, u) for u in users]


@router.post("/users", status_code=201)
def create_user(
    req: CreateUserRequest,
    session: Session = Depends(get_session),
    principal: User = Depends(require_admin),
) -> dict:
    role = (req.role or "user").strip()
    if role not in ("user", "admin"):
        raise HTTPException(status_code=422, detail="role 只能是 user 或 admin")
    try:
        user = user_service.create_user(
            session,
            username=req.username,
            password=req.password,
            role=role,
        )
    except ValueError as exc:
        msg = str(exc)
        if "已存在" in msg:
            raise HTTPException(status_code=409, detail="用户名已存在") from exc
        raise HTTPException(status_code=422, detail=msg) from exc
    _write_audit(
        session,
        principal.id,
        user.id,
        "admin_create_user",
        summary={"username": user.username, "role": user.role},
    )
    return _serialize_user(session, user)


@router.put("/users/{user_id}/activate")
def activate_user(
    user_id: int,
    session: Session = Depends(get_session),
    principal: User = Depends(require_admin),
) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.is_active = True
    session.commit()
    _write_audit(
        session, principal.id, user.id, "user_activate",
        summary={"username": user.username},
    )
    return {"ok": True, "id": user.id, "is_active": True}


@router.put("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: int,
    session: Session = Depends(get_session),
    principal: User = Depends(require_admin),
) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.is_active = False
    session.commit()
    _purge_tokens(session, user_id)
    _write_audit(
        session, principal.id, user.id, "user_deactivate",
        summary={"username": user.username},
    )
    return {"ok": True, "id": user.id, "is_active": False}


@router.put("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    req: ResetPasswordRequest,
    session: Session = Depends(get_session),
    principal: User = Depends(require_admin),
) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if len(req.new_password) < user_service.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"密码长度不能少于 {user_service.MIN_PASSWORD_LENGTH} 位",
        )
    user.password_hash = hash_password(req.new_password)
    session.commit()
    _purge_tokens(session, user_id)
    _write_audit(
        session, principal.id, user.id, "password_reset",
        summary={"username": user.username},
    )
    return {"ok": True, "id": user.id}
