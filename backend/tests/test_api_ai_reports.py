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
def auth(client):
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


class TestListAIReports:
    def test_requires_auth(self, client):
        assert client.get("/api/ai-reports?date=2026-08-03").status_code == 401

    def test_returns_reports_for_date(self, client, auth, session):
        w = Workout(date=date(2026, 8, 3), title="胸", match_status="auto_matched")
        session.add(w)
        session.commit()
        session.add(
            AIReport(
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
