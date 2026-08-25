"""V2-4 FIT/TCX 手动导入 API 测试（降级通道 /api/import/fit）；V3-7 扩展 GPX/KML。"""
from datetime import date, time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import GarminActivity
from tests.conftest import make_xunji_train
from tests.test_fit_import import build_fit_bytes
from tests.test_gpx_kml_import import GPX_WITH_HR

DAY = date(2026, 8, 5)


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings

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
def auth(client, session):
    from app.services import users as _us
    try:
        _us.create_user(session, username="alice", password="test-pass", role="user")
    except ValueError:
        pass  # alice 已由 conftest session 预建（id=1）
    _b = client.post("/api/auth/login", json={"username": "alice", "password": "test-pass"}).json()
    return {"Authorization": f"Bearer {_b['token']}"}


def test_upload_fit_file(client, auth, session):
    """上传 FIT：落库 + 触发当日重匹配，响应含活动与匹配结果。"""
    make_xunji_train(session, DAY, localid="x1", start=time(18, 0), end=time(19, 0))

    resp = client.post(
        "/api/import/fit",
        files={"file": ("morning.fit", build_fit_bytes(), "application/octet-stream")},
        headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["activity_id"].startswith("file_")
    assert body["date"] == "2026-08-05"
    assert body["match_status"] == "auto_matched"
    assert body["workout_id"] is not None


def test_upload_rejects_bad_extension(client, auth):
    resp = client.post(
        "/api/import/fit",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=auth,
    )
    assert resp.status_code == 422


def test_upload_corrupt_file(client, auth):
    resp = client.post(
        "/api/import/fit",
        files={"file": ("broken.fit", b"not-a-fit", "application/octet-stream")},
        headers=auth,
    )
    assert resp.status_code == 422


def test_upload_gpx_file(client, auth, session, monkeypatch):
    """V3-7 端到端：上传 GPX → 落库 garmin_activity → match_day 被调用；重复上传去重。"""
    import app.services.matcher as matcher

    fake_match = Mock(return_value={"workouts": [], "candidates": []})
    monkeypatch.setattr(matcher, "match_day", fake_match)

    resp = client.post(
        "/api/import/fit",
        files={"file": ("morning_run.gpx", GPX_WITH_HR.encode("utf-8"), "application/gpx+xml")},
        headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["activity_id"].startswith("file_")
    assert body["date"] == "2026-08-05"
    assert body["activity_type"] == "running"
    assert session.query(GarminActivity).count() == 1
    fake_match.assert_called_once()
    assert fake_match.call_args.args[1] == DAY

    # 重复上传同文件：去重不新建行
    resp2 = client.post(
        "/api/import/fit",
        files={"file": ("morning_run.gpx", GPX_WITH_HR.encode("utf-8"), "application/gpx+xml")},
        headers=auth,
    )
    assert resp2.status_code == 200
    assert session.query(GarminActivity).count() == 1
    assert fake_match.call_count == 2


def test_upload_empty_file(client, auth):
    resp = client.post(
        "/api/import/fit",
        files={"file": ("empty.gpx", b"", "application/gpx+xml")},
        headers=auth,
    )
    assert resp.status_code == 422


def test_upload_requires_auth(client):
    resp = client.post(
        "/api/import/fit",
        files={"file": ("a.fit", build_fit_bytes(), "application/octet-stream")},
    )
    assert resp.status_code == 401
