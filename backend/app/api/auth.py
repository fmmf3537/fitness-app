"""多用户 token 认证（multiuser-v2 M2-3/M2-4，PRD §7）。

- POST /api/auth/login：username + password 登录，校验通过写入 auth_token 表
  （secrets.token_urlsafe(32)，7 天过期），返回 token / user_id / role；
  校验失败统一 401，不区分「用户不存在」与「密码错误」以避免用户枚举。
- POST /api/auth/logout：Bearer token 软失效（is_active=False）。
- get_current_user_id：业务 API 的认证依赖，校验 Bearer token 并返回 user_id，
  业务查询一律按该 user_id 过滤，杜绝跨用户数据泄漏。

M2-4 已切换：全部业务 API 使用 get_current_user_id，旧「单口令 → 内存 token」
分支与 require_auth / _ACTIVE_TOKENS 已删除。
"""
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AuthToken, User
from app.services.users import verify_user_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_TTL = timedelta(days=7)


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(req: LoginRequest, session: Session = Depends(get_session)) -> dict:
    user = verify_user_password(session, req.username, req.password)
    if user is None:
        # 统一提示，不区分「用户不存在」「密码错误」「已停用」，避免用户枚举
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = secrets.token_urlsafe(32)
    session.add(AuthToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.utcnow() + TOKEN_TTL,
    ))
    session.commit()
    return {"token": token, "user_id": user.id, "role": user.role}


def _get_active_token(session: Session, token: str) -> AuthToken | None:
    """查询有效令牌：is_active=True 且未过期；未命中返回 None。"""
    row = session.execute(
        select(AuthToken).where(AuthToken.token == token)
    ).scalar_one_or_none()
    if row is None or not row.is_active or row.expires_at <= datetime.utcnow():
        return None
    return row


def _parse_bearer(authorization: str | None) -> str:
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return authorization[len(prefix):]


@router.post("/logout")
def logout(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    token = _parse_bearer(authorization)
    row = _get_active_token(session, token)
    if row is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    row.is_active = False  # 软失效，保留行便于审计
    session.commit()
    return {"ok": True}


def get_current_user_id(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> int:
    """FastAPI 依赖：校验 Bearer token，命中返回 user_id，否则一律 401。"""
    token = _parse_bearer(authorization)
    row = _get_active_token(session, token)
    if row is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return row.user_id


def get_current_user(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> User:
    """FastAPI 依赖：校验 Bearer token，命中返回 User 对象（含 role），否则 401。

    M2-5 新增：供需要管理员视角的端点解析角色并支持 ?user_id= 代查看覆盖。
    不改动 get_current_user_id 的既有签名与行为。
    """
    token = _parse_bearer(authorization)
    row = _get_active_token(session, token)
    if row is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return user


def resolve_viewer(principal: User, override_user_id: int | None = None) -> int:
    """解析「被查看用户」：

    - 管理员显式传 ?user_id= 时返回该 id，以代查看目标用户数据；
    - 普通用户传 override 一律忽略，维持自身隔离（不接受越权）；
    - 未传 override 时返回自身 id。
    """
    if override_user_id is not None and principal.role == "admin":
        return override_user_id
    return principal.id
