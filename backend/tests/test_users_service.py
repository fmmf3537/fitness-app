"""用户 CRUD 服务测试（multiuser-v2）。

覆盖：创建/唯一性/密码长度校验、按 id/username 查询、列表排序、
更新密码与角色、软停用、密码校验、审计日志动作齐全。
"""
import json

import pytest
from sqlalchemy import select

from app.models import AuditLog, User
from app.services import users as user_service


def _audit_actions(session, user_id: int | None = None) -> list[str]:
    stmt = select(AuditLog).order_by(AuditLog.id)
    if user_id is not None:
        stmt = stmt.where(AuditLog.target_user_id == user_id)
    return [a.action for a in session.execute(stmt).scalars().all()]


def test_create_user_success(session):
    user = user_service.create_user(
        session, username="alice_svc", password="secret123", role="admin"
    )
    assert user.id is not None
    assert user.username == "alice_svc"
    assert user.role == "admin"
    assert user.is_active is True


def test_create_user_password_is_hashed(session):
    user = user_service.create_user(session, username="bob", password="secret123")
    assert user.password_hash != "secret123"
    assert user.password_hash.startswith("$2")
    assert "$" in user.password_hash  # bcrypt 格式 $2b$12$...


def test_create_user_duplicate_username_raises(session):
    user_service.create_user(session, username="carol", password="secret123")
    with pytest.raises(ValueError, match="用户名已存在"):
        user_service.create_user(session, username="carol", password="other123")


def test_create_user_empty_username_raises(session):
    with pytest.raises(ValueError, match="用户名不能为空"):
        user_service.create_user(session, username="", password="secret123")
    with pytest.raises(ValueError, match="用户名不能为空"):
        user_service.create_user(session, username="   ", password="secret123")


def test_create_user_short_password_raises(session):
    with pytest.raises(ValueError, match="密码长度不能少于 6 位"):
        user_service.create_user(session, username="dave", password="12345")


def test_create_user_empty_password_raises(session):
    with pytest.raises(ValueError, match="密码不能为空"):
        user_service.create_user(session, username="erin", password="")


def test_create_user_writes_audit_log(session):
    user = user_service.create_user(
        session, username="frank", password="secret123", role="user"
    )
    logs = session.execute(
        select(AuditLog).where(AuditLog.action == "create_user")
    ).scalars().all()
    # 兼容 conftest 预建 alice：只校验本次创建的 frank 审计行存在且字段正确
    frank_logs = [l for l in logs if json.loads(l.summary_json).get("username") == "frank"]
    assert len(frank_logs) == 1
    log = frank_logs[0]
    assert log.actor_user_id == user.id
    assert log.target_user_id == user.id
    assert log.target_table == "users"
    assert log.target_id == user.id
    assert json.loads(log.summary_json) == {"username": "frank", "role": "user"}


def test_get_user_by_id_hit_and_miss(session):
    user = user_service.create_user(session, username="grace", password="secret123")
    found = user_service.get_user_by_id(session, user.id)
    assert found is not None and found.username == "grace"
    assert user_service.get_user_by_id(session, 99999) is None


def test_get_user_by_username_hit_and_miss(session):
    user_service.create_user(session, username="heidi", password="secret123")
    found = user_service.get_user_by_username(session, "heidi")
    assert found is not None and found.username == "heidi"
    assert user_service.get_user_by_username(session, "nobody") is None


def test_list_users_ordered_by_id(session):
    u1 = user_service.create_user(session, username="u1", password="secret123")
    u2 = user_service.create_user(session, username="u2", password="secret123")
    u3 = user_service.create_user(session, username="u3", password="secret123")
    users = user_service.list_users(session)
    # 兼容 conftest 预建 alice：仅校验本次创建的 3 个用户按 id 升序存在
    created = [u for u in users if u.username in ("u1", "u2", "u3")]
    assert [u.id for u in created] == sorted(u.id for u in (u1, u2, u3))
    assert len(created) == 3


def test_update_user_password_new_works_old_fails(session):
    user = user_service.create_user(session, username="ivan", password="oldpass1")
    updated = user_service.update_user(session, user.id, new_password="newpass1")
    assert updated.id == user.id
    assert user_service.verify_user_password(session, "ivan", "newpass1") is not None
    assert user_service.verify_user_password(session, "ivan", "oldpass1") is None


def test_update_user_role_and_is_active(session):
    user = user_service.create_user(session, username="judy", password="secret123")
    updated = user_service.update_user(
        session, user.id, new_role="admin", is_active=False
    )
    assert updated.role == "admin"
    assert updated.is_active is False
    # 未传入的字段保持不变：原密码仍可用于校验逻辑（账号已停用故返回 None，
    # 这里直接校验哈希确认密码未被重置）
    from app.utils.password import verify_password

    assert verify_password("secret123", updated.password_hash)


def test_update_user_not_found_raises(session):
    with pytest.raises(ValueError, match="用户不存在"):
        user_service.update_user(session, 99999, new_role="admin")


def test_update_user_writes_audit_log(session):
    user = user_service.create_user(session, username="kate", password="secret123")
    admin = user_service.create_user(session, username="root", password="secret123")
    user_service.update_user(
        session, user.id, new_role="admin", actor_user_id=admin.id
    )
    logs = session.execute(
        select(AuditLog).where(AuditLog.action == "update_user")
    ).scalars().all()
    assert len(logs) == 1
    log = logs[0]
    assert log.actor_user_id == admin.id
    assert log.target_user_id == user.id
    assert log.target_table == "users"
    assert json.loads(log.summary_json)["changed"] == {"role": "admin"}


def test_deactivate_user_soft_delete(session):
    user = user_service.create_user(session, username="lily", password="secret123")
    deactivated = user_service.deactivate_user(session, user.id)
    assert deactivated.is_active is False
    # 软停用：行仍在库中
    still_there = user_service.get_user_by_id(session, user.id)
    assert still_there is not None and still_there.is_active is False


def test_deactivated_user_cannot_verify_password(session):
    user = user_service.create_user(session, username="mike", password="secret123")
    assert user_service.verify_user_password(session, "mike", "secret123") is not None
    user_service.deactivate_user(session, user.id)
    assert user_service.verify_user_password(session, "mike", "secret123") is None


def test_deactivate_user_writes_audit_log(session):
    user = user_service.create_user(session, username="nina", password="secret123")
    user_service.deactivate_user(session, user.id, actor_user_id=user.id)
    logs = session.execute(
        select(AuditLog).where(AuditLog.action == "deactivate_user")
    ).scalars().all()
    assert len(logs) == 1
    log = logs[0]
    assert log.target_user_id == user.id
    assert log.target_table == "users"
    assert json.loads(log.summary_json) == {"username": "nina"}


def test_verify_user_password_unknown_user_returns_none(session):
    assert user_service.verify_user_password(session, "ghost", "whatever1") is None


def test_verify_user_password_wrong_password_returns_none(session):
    user_service.create_user(session, username="oscar", password="right123")
    assert user_service.verify_user_password(session, "oscar", "wrong123") is None


def test_audit_actions_full_lifecycle(session):
    user = user_service.create_user(session, username="pete", password="secret123")
    user_service.update_user(session, user.id, new_password="secret456")
    user_service.deactivate_user(session, user.id)
    assert _audit_actions(session, user.id) == [
        "create_user", "update_user", "deactivate_user",
    ]


def test_users_are_never_hard_deleted(session):
    """deactivate 后 users 表行数不变（软停用而非物理删除）。"""
    # 兼容 conftest 预建 alice：以相对计数校验（停用不增不减）
    before0 = len(user_service.list_users(session))
    user_service.create_user(session, username="q1", password="secret123")
    user2 = user_service.create_user(session, username="q2", password="secret123")
    before = len(user_service.list_users(session))
    user_service.deactivate_user(session, user2.id)
    after = len(user_service.list_users(session))
    assert before == after == before0 + 2
    assert isinstance(user_service.get_user_by_id(session, user2.id), User)
