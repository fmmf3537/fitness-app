"""多用户用户管理 CRUD 服务（multiuser-v2）。

- 密码一律经 app.utils.password.hash_password（bcrypt, cost=12）哈希，
  绝不存储明文或可逆加密结果；
- 删除采用软停用（is_active=False），禁止物理删除用户行；
- 所有写操作在 session.commit() 后返回，异常时 session.rollback()；
- 每个写操作写入一条 AuditLog 审计记录。
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AuditLog, User
from app.utils.password import hash_password, verify_password

MIN_PASSWORD_LENGTH = 6


def _get_session(session: Session | None) -> Session:
    return session or SessionLocal()


def _write_audit(session: Session, *, actor_user_id: int, action: str,
                 target_user_id: int | None = None,
                 target_table: str | None = "users",
                 target_id: int | None = None,
                 summary: dict | None = None) -> None:
    """向当前事务追加一条审计日志（不单独 commit，由调用方统一提交）。"""
    session.add(AuditLog(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        action=action,
        target_table=target_table,
        target_id=target_id,
        summary_json=json.dumps(summary, ensure_ascii=False) if summary is not None else None,
    ))


def create_user(session: Session | None = None, *, username: str, password: str,
                role: str = "user", is_active: bool = True) -> User:
    """创建用户。用户名唯一；密码经 bcrypt 哈希后存储；写 create_user 审计。"""
    session = _get_session(session)

    username = (username or "").strip()
    if not username:
        raise ValueError("用户名不能为空")
    if not password:
        raise ValueError("密码不能为空")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"密码长度不能少于 {MIN_PASSWORD_LENGTH} 位")
    if get_user_by_username(session, username) is not None:
        raise ValueError("用户名已存在")

    try:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        session.add(user)
        session.flush()  # 取得 user.id 供审计使用
        _write_audit(
            session,
            actor_user_id=user.id,
            action="create_user",
            target_user_id=user.id,
            target_id=user.id,
            summary={"username": username, "role": role},
        )
        session.commit()
        return user
    except Exception:
        session.rollback()
        raise


def get_user_by_id(session: Session | None, user_id: int) -> User | None:
    """按主键查询用户，不存在返回 None。"""
    session = _get_session(session)
    return session.get(User, user_id)


def get_user_by_username(session: Session | None, username: str) -> User | None:
    """按用户名查询用户，不存在返回 None。"""
    session = _get_session(session)
    return session.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()


def list_users(session: Session | None) -> list[User]:
    """列出全部用户，按 id 升序。"""
    session = _get_session(session)
    return list(session.execute(select(User).order_by(User.id)).scalars().all())


def update_user(session: Session | None, user_id: int, *, new_password: str | None = None,
                new_role: str | None = None, is_active: bool | None = None,
                actor_user_id: int | None = None) -> User:
    """更新用户。仅更新传入的非 None 字段；新密码重新哈希；写 update_user 审计。"""
    session = _get_session(session)
    user = session.get(User, user_id)
    if user is None:
        raise ValueError(f"用户不存在: id={user_id}")

    changed: dict = {}
    if new_password is not None:
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"密码长度不能少于 {MIN_PASSWORD_LENGTH} 位")
        user.password_hash = hash_password(new_password)
        changed["password"] = True
    if new_role is not None:
        user.role = new_role
        changed["role"] = new_role
    if is_active is not None:
        user.is_active = is_active
        changed["is_active"] = is_active

    try:
        _write_audit(
            session,
            actor_user_id=actor_user_id if actor_user_id is not None else user.id,
            action="update_user",
            target_user_id=user.id,
            target_id=user.id,
            summary={"username": user.username, "changed": changed},
        )
        session.commit()
        return user
    except Exception:
        session.rollback()
        raise


def deactivate_user(session: Session | None, user_id: int, *,
                    actor_user_id: int | None = None) -> User:
    """软停用用户（is_active=False），禁止物理删除；写 deactivate_user 审计。"""
    session = _get_session(session)
    user = session.get(User, user_id)
    if user is None:
        raise ValueError(f"用户不存在: id={user_id}")

    try:
        user.is_active = False
        _write_audit(
            session,
            actor_user_id=actor_user_id if actor_user_id is not None else user.id,
            action="deactivate_user",
            target_user_id=user.id,
            target_id=user.id,
            summary={"username": user.username},
        )
        session.commit()
        return user
    except Exception:
        session.rollback()
        raise


def verify_user_password(session: Session | None, username: str, password: str) -> User | None:
    """校验用户名与密码。

    账号不存在、密码错误或账号被停用（is_active=False）均返回 None，不抛异常。
    """
    session = _get_session(session)
    user = get_user_by_username(session, username)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
