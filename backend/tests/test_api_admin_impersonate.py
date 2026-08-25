"""M4-4 管理员代查看 / 代同步 API 测试。"""
from datetime import date
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AuditLog, Workout
from app.services import sync as sync_mod
from app.services import users as user_service


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.fixture
def admin_headers(client, session):
    alice = user_service.get_user_by_username(session, "alice")
    alice.role = "admin"
    session.commit()
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pass"}
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def regular_headers(client, session):
    try:
        user_service.create_user(session, username="bob", password="test-pass")
    except ValueError:
        pass
    r = client.post(
        "/api/auth/login", json={"username": "bob", "password": "test-pass"}
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def bob(session):
    existing = user_service.get_user_by_username(session, "bob")
    if existing is not None:
        return existing
    return user_service.create_user(session, username="bob", password="test-pass")


class TestAdminImpersonateAuth:
    def test_unauthenticated_401(self, client, bob):
        assert client.get(f"/api/admin/impersonate/{bob.id}/workouts").status_code == 401

    def test_non_admin_403(self, client, regular_headers, bob):
        assert (
            client.get(
                f"/api/admin/impersonate/{bob.id}/workouts", headers=regular_headers
            ).status_code
            == 403
        )


class TestAdminImpersonateView:
    def test_list_target_workouts(self, client, admin_headers, bob, session):
        session.add(
            Workout(user_id=bob.id, date=date(2026, 8, 1), title="bob-w1")
        )
        session.add(
            Workout(user_id=bob.id, date=date(2026, 8, 2), title="bob-w2")
        )
        session.commit()

        resp = client.get(
            f"/api/admin/impersonate/{bob.id}/workouts", headers=admin_headers
        )
        assert resp.status_code == 200
        titles = {w["title"] for w in resp.json()["workouts"]}
        assert titles == {"bob-w1", "bob-w2"}

        audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "impersonate_view_workouts")
        ).all()
        assert len(audits) >= 1
        assert audits[-1].target_user_id == bob.id

    def test_unknown_user_404(self, client, admin_headers):
        resp = client.get(
            "/api/admin/impersonate/999999/workouts", headers=admin_headers
        )
        assert resp.status_code == 404

    def test_sync_day_calls_daily_sync(self, client, admin_headers, bob, monkeypatch, session):
        mock = Mock(return_value={"status": "success", "date": "2026-08-10"})
        monkeypatch.setattr(sync_mod, "daily_sync", mock)

        resp = client.post(
            f"/api/admin/impersonate/{bob.id}/sync/2026-08-10",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock.assert_called_once()
        assert mock.call_args.kwargs.get("user_id") == bob.id
        assert mock.call_args.args[0] == date(2026, 8, 10)

        audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "impersonate_sync")
        ).all()
        assert any(a.target_user_id == bob.id for a in audits)
        assert all("impersonate_" in a.action for a in audits)
