"""V1-7 身体数据同步训记三段式流程测试（TDD）。

铁律验证：
- 未确认前绝不发送 confirmed=True（预览只发 dry_run=True）；
- 确认后才 dry_run=False + confirmed=True，成功后置 synced_to_xunji=TRUE；
- 身高/血压/血糖（仅本地指标）调同步接口一律 400 拒绝。
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.body_metrics import get_body_client
from app.db import get_session
from app.main import app
from app.models import BodyMetric
from app.services.body_metrics import upsert_body_metric


class FakeBodyClient:
    """记录每次调用的假训记身体数据客户端。"""

    def __init__(self):
        self.calls: list[dict] = []

    def upsert_body_metrics(self, records, dry_run=True, confirmed=False):
        self.calls.append(
            {"records": records, "dry_run": dry_run, "confirmed": confirmed}
        )
        if dry_run:
            return {"res": {"summary": "将更新 2026-08-03 体重 72.4kg"}}
        return {"res": {"summary": "已更新 1 条"}}


@pytest.fixture
def fake_client():
    return FakeBodyClient()


@pytest.fixture
def client(session, monkeypatch, fake_client):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings

    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_body_client] = lambda: fake_client
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth(client, session):
    from app.services import users as _us
    try:
        _us.create_user(session, username="alice", password="test-pass", role="user")
    except ValueError:
        pass  # alice 已由 conftest session 预建（id=1）
    _b = client.post("/api/auth/login", json={"username": "alice", "password": "test-pass"}).json()
    return {"Authorization": f"Bearer {_b['token']}"}


def _add_weight(session, value=72.4):
    return upsert_body_metric(session, date(2026, 8, 3), "weight", value, user_id=1)


class TestPreview:
    def test_preview_sends_dry_run_only(self, client, auth, session, fake_client):
        row = _add_weight(session)
        resp = client.post(f"/api/body-metrics/{row.id}/sync-xunji", json={}, headers=auth)

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "preview"
        assert "72.4" in data["summary"]

        # 未确认前绝不发送 confirmed=True，只发 dry_run=True
        assert len(fake_client.calls) == 1
        call = fake_client.calls[0]
        assert call["dry_run"] is True
        assert call["confirmed"] is not True
        assert call["records"] == [
            {"datestr": "2026-08-03", "type": "weight", "value": 72.4}
        ]

    def test_preview_does_not_mark_synced(self, client, auth, session):
        row = _add_weight(session)
        client.post(f"/api/body-metrics/{row.id}/sync-xunji", json={}, headers=auth)
        session.refresh(row)
        assert row.synced_to_xunji is False


class TestConfirm:
    def test_confirm_sends_confirmed_and_marks_synced(
        self, client, auth, session, fake_client
    ):
        row = _add_weight(session)
        resp = client.post(
            f"/api/body-metrics/{row.id}/sync-xunji",
            json={"confirmed": True},
            headers=auth,
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "synced"

        call = fake_client.calls[0]
        assert call["dry_run"] is False
        assert call["confirmed"] is True

        session.refresh(row)
        assert row.synced_to_xunji is True

    def test_full_three_step_flow(self, client, auth, session, fake_client):
        """完整三段式：dry_run 预览 → 用户确认 → confirmed 执行。"""
        row = _add_weight(session)
        r1 = client.post(f"/api/body-metrics/{row.id}/sync-xunji", json={}, headers=auth)
        assert r1.json()["status"] == "preview"
        assert fake_client.calls[0]["dry_run"] is True

        r2 = client.post(
            f"/api/body-metrics/{row.id}/sync-xunji",
            json={"confirmed": True},
            headers=auth,
        )
        assert r2.json()["status"] == "synced"
        assert fake_client.calls[1]["dry_run"] is False
        assert fake_client.calls[1]["confirmed"] is True


class TestLocalOnlyTypesRejected:
    @pytest.mark.parametrize(
        "type_,value",
        [
            ("height", 175.0),
            ("bp_systolic", 120.0),
            ("bp_diastolic", 80.0),
            ("blood_glucose", 5.5),
        ],
    )
    def test_sync_local_only_type_400(
        self, client, auth, session, fake_client, type_, value
    ):
        """身高/血压/血糖训记 API 无对应类型，同步一律 400 且不发任何请求。"""
        row = upsert_body_metric(session, date(2026, 8, 3), type_, value, user_id=1)
        resp = client.post(f"/api/body-metrics/{row.id}/sync-xunji", json={}, headers=auth)
        assert resp.status_code == 400
        assert fake_client.calls == []

    def test_bodyfat_sync_allowed(self, client, auth, session, fake_client):
        """体脂率（bodyfat）允许同步。"""
        row = upsert_body_metric(session, date(2026, 8, 3), "bodyfat", 18.2, user_id=1)
        resp = client.post(f"/api/body-metrics/{row.id}/sync-xunji", json={}, headers=auth)
        assert resp.status_code == 200
        assert fake_client.calls[0]["records"][0]["type"] == "bodyfat"


class TestEdgeCases:
    def test_not_found_404(self, client, auth):
        resp = client.post("/api/body-metrics/9999/sync-xunji", json={}, headers=auth)
        assert resp.status_code == 404

    def test_requires_auth(self, client):
        resp = client.post("/api/body-metrics/1/sync-xunji", json={})
        assert resp.status_code == 401
