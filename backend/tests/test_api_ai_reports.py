"""V1-3 AI 报告 API 测试。"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AIReport, Workout


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
def auth(client, session):
    from app.services import users as _us
    try:
        _us.create_user(session, username="alice", password="test-pass", role="user")
    except ValueError:
        pass  # alice 已由 conftest session 预建（id=1）
    _b = client.post("/api/auth/login", json={"username": "alice", "password": "test-pass"}).json()
    return {"Authorization": f"Bearer {_b['token']}"}


class TestListAIReports:
    def test_requires_auth(self, client):
        assert client.get("/api/ai-reports?date=2026-08-03").status_code == 401

    def test_returns_reports_for_date(self, client, auth, session):
        w = Workout(date=date(2026, 8, 3), title="胸", match_status="auto_matched")
        session.add(w)
        session.commit()
        session.add(
            AIReport(
                user_id=1,
                type="session_review",
                workout_id=w.id,
                period_start=date(2026, 8, 3),
                period_end=date(2026, 8, 3),
                model="deepseek-chat",
                prompt_tokens=100,
                completion_tokens=20,
                cost_estimate=0.0001,
                content_md="点评",
            )
        )
        session.commit()

        resp = client.get("/api/ai-reports?date=2026-08-03", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "2026-08-03"
        assert len(data["reports"]) == 1
        assert data["reports"][0]["workout_title"] == "胸"
        assert data["reports"][0]["content_md"] == "点评"

    def test_returns_empty_list_when_no_reports(self, client, auth):
        resp = client.get("/api/ai-reports?date=2026-08-03", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["reports"] == []

    def test_invalid_date_format_returns_422(self, client, auth):
        resp = client.get("/api/ai-reports?date=2026-08", headers=auth)
        assert resp.status_code == 422


class TestGetAIReport:
    def test_returns_single_report(self, client, auth, session):
        w = Workout(date=date(2026, 8, 3), title="背", match_status="auto_matched")
        session.add(w)
        session.commit()
        report = AIReport(
            user_id=1,
            type="session_review",
            workout_id=w.id,
            period_start=date(2026, 8, 3),
            period_end=date(2026, 8, 3),
            model="deepseek-chat",
            prompt_tokens=100,
            completion_tokens=20,
            content_md="详情",
        )
        session.add(report)
        session.commit()

        resp = client.get(f"/api/ai-reports/{report.id}", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["id"] == report.id
        assert resp.json()["workout_title"] == "背"

    def test_not_found(self, client, auth):
        resp = client.get("/api/ai-reports/999", headers=auth)
        assert resp.status_code == 404


class TestRecentAIReports:
    """省略 date 时返回最近报告列表（V1 前端报告列表页）。"""

    def _make_report(self, session, idx, report_type="session_review", created_at=None):
        from datetime import datetime as dt
        report = AIReport(
            user_id=1,
            type=report_type,
            period_start=date(2026, 8, 1 + idx),
            period_end=date(2026, 8, 1 + idx),
            model="deepseek-chat",
            content_md=f"报告{idx}",
            created_at=created_at or dt(2026, 8, 1 + idx, 10, 0, 0),
        )
        session.add(report)
        session.commit()
        return report

    def test_requires_auth(self, client):
        assert client.get("/api/ai-reports").status_code == 401

    def test_returns_recent_reports_desc(self, client, auth, session):
        for i in range(3):
            self._make_report(session, i)
        resp = client.get("/api/ai-reports", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reports"]) == 3
        # created_at 倒序
        created = [r["created_at"] for r in data["reports"]]
        assert created == sorted(created, reverse=True)
        item = data["reports"][0]
        for field in ("id", "type", "date", "model", "created_at", "content_md"):
            assert field in item
        assert item["content_md"] == "报告2"

    def test_limit(self, client, auth, session):
        for i in range(3):
            self._make_report(session, i)
        resp = client.get("/api/ai-reports?limit=2", headers=auth)
        assert resp.status_code == 200
        assert len(resp.json()["reports"]) == 2

    def test_limit_over_100_returns_422(self, client, auth):
        assert client.get("/api/ai-reports?limit=101", headers=auth).status_code == 422

    def test_type_filter(self, client, auth, session):
        self._make_report(session, 0, report_type="session_review")
        self._make_report(session, 1, report_type="weekly")
        resp = client.get("/api/ai-reports?type=weekly", headers=auth)
        assert resp.status_code == 200
        reports = resp.json()["reports"]
        assert len(reports) == 1
        assert reports[0]["type"] == "weekly"

    def test_empty(self, client, auth):
        resp = client.get("/api/ai-reports", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["reports"] == []
