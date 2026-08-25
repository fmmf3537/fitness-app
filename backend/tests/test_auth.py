"""多用户 token 认证测试（multiuser-v2 M2-3）。

覆盖：登录成功落库、错误密码/不存在用户/已停用用户 401 且不落库、
get_current_user_id 对有效/无效/过期/缺失/格式错误 token 的行为、
logout 软失效后 token 不可再用。
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.auth import get_current_user_id
from app.db import get_session
from app.main import app
from app.models import AuthToken
from app.services import users as user_service


@pytest.fixture
def client(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def user(session):
    # 复用 conftest session 预建的 alice(id=1, password="test-pass", role="user")
    u = user_service.get_user_by_username(session, "alice")
    assert u is not None, "conftest 应预建 alice"
    return u


def _token_rows(session) -> list[AuthToken]:
    return list(session.execute(select(AuthToken)).scalars().all())


def _current_user_id(session, authorization):
    """直接调用依赖函数（绕过 FastAPI 注入），HTTPException 原样抛出。"""
    return get_current_user_id(authorization=authorization, session=session)


# ---------- 登录 ----------

def test_login_success_returns_token_and_persists(client, session, user):
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "test-pass"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["user_id"] == user.id
    assert body["role"] == "user"

    rows = _token_rows(session)
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == user.id
    assert row.token == body["token"]
    assert row.is_active is True
    assert row.expires_at > datetime.utcnow()
    assert row.expires_at <= datetime.utcnow() + timedelta(days=7, minutes=1)


def test_login_wrong_password_401_no_token(client, session, user):
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong123"})
    assert resp.status_code == 401
    assert _token_rows(session) == []


def test_login_unknown_user_401_no_token(client, session):
    resp = client.post("/api/auth/login", json={"username": "ghost", "password": "test-pass"})
    assert resp.status_code == 401
    assert _token_rows(session) == []


def test_login_same_message_for_unknown_user_and_wrong_password(client, session, user):
    """统一提示，不区分「用户不存在」与「密码错误」，避免用户枚举。"""
    r1 = client.post("/api/auth/login", json={"username": "ghost", "password": "test-pass"})
    r2 = client.post("/api/auth/login", json={"username": "alice", "password": "wrong123"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]


def test_login_deactivated_user_401_no_token(client, session, user):
    user_service.deactivate_user(session, user.id)
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "test-pass"})
    assert resp.status_code == 401
    assert _token_rows(session) == []


# ---------- get_current_user_id ----------

def test_get_current_user_id_valid_token(session, user):
    session.add(AuthToken(
        user_id=user.id, token="tok-valid",
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    session.commit()
    assert _current_user_id(session, "Bearer tok-valid") == user.id


def test_get_current_user_id_missing_header_401(session):
    with pytest.raises(HTTPException) as exc:
        _current_user_id(session, None)
    assert exc.value.status_code == 401


def test_get_current_user_id_bad_format_401(session, user):
    with pytest.raises(HTTPException) as exc:
        _current_user_id(session, "tok-valid")
    assert exc.value.status_code == 401


def test_get_current_user_id_unknown_token_401(session):
    with pytest.raises(HTTPException) as exc:
        _current_user_id(session, "Bearer not-a-real-token")
    assert exc.value.status_code == 401


def test_get_current_user_id_expired_token_401(session, user):
    session.add(AuthToken(
        user_id=user.id, token="tok-expired",
        expires_at=datetime.utcnow() - timedelta(seconds=1),
    ))
    session.commit()
    with pytest.raises(HTTPException) as exc:
        _current_user_id(session, "Bearer tok-expired")
    assert exc.value.status_code == 401


def test_get_current_user_id_inactive_token_401(session, user):
    session.add(AuthToken(
        user_id=user.id, token="tok-inactive", is_active=False,
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    session.commit()
    with pytest.raises(HTTPException) as exc:
        _current_user_id(session, "Bearer tok-inactive")
    assert exc.value.status_code == 401


# ---------- 登出 ----------

def test_logout_invalidates_token(client, session, user):
    token = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pass"}
    ).json()["token"]

    resp = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    # 软失效：行仍在，is_active=False，get_current_user_id 不再接受
    rows = _token_rows(session)
    assert len(rows) == 1 and rows[0].is_active is False
    with pytest.raises(HTTPException) as exc:
        _current_user_id(session, f"Bearer {token}")
    assert exc.value.status_code == 401

    # 登出后再次登出同样 401
    resp2 = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 401


def test_logout_without_token_401(client):
    assert client.post("/api/auth/logout").status_code == 401
    assert client.post(
        "/api/auth/logout", headers={"Authorization": "Bearer not-a-real-token"}
    ).status_code == 401


def test_logout_does_not_affect_other_tokens(client, session, user):
    t1 = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pass"}
    ).json()["token"]
    t2 = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pass"}
    ).json()["token"]
    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {t1}"})
    assert _current_user_id(session, f"Bearer {t2}") == user.id
