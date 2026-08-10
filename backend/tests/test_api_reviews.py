"""V2-2 复盘中心 API：手动生成 / 状态轮询 / 导出（Markdown / PDF）。"""
from datetime import date
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import ai_reports as ai_reports_api
from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AIReport
from app.services import ai as ai_service


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


def make_weekly_report(session, period_start=date(2026, 8, 3),
                       period_end=date(2026, 8, 9), content="# 本周概览\n本周训练 3 次。"):
    r = AIReport(
        type="weekly", period_start=period_start, period_end=period_end,
        model="deepseek-chat", prompt_tokens=100, completion_tokens=50,
        cost_estimate=0.001, content_md=content,
    )
    session.add(r)
    session.commit()
    return r


class SyncManager:
    """测试用同步生成管理器：立即以注入 session + 假 chat_fn 执行。"""

    def __init__(self, session, running=()):
        self.session = session
        self.running = set(running)
        self.calls = []

    def start(self, rtype, day_str=None):
        if rtype in self.running:
            return False
        self.calls.append((rtype, day_str))
        chat_fn = Mock(return_value={
            "content": "## 概览\n假报告", "prompt_tokens": 1,
            "completion_tokens": 1, "model": "deepseek-chat"})
        if rtype == "weekly":
            ai_service.run_weekly_review(day_str, session=self.session, chat_fn=chat_fn)
        else:
            ai_service.run_monthly_review(day_str, session=self.session, chat_fn=chat_fn)
        return True

    def is_running(self, rtype):
        return rtype in self.running

    def last_error(self, rtype):
        return None


@pytest.fixture
def sync_manager(session):
    manager = SyncManager(session)
    app.dependency_overrides[ai_reports_api.get_review_manager] = lambda: manager
    try:
        yield manager
    finally:
        app.dependency_overrides.pop(ai_reports_api.get_review_manager, None)


# ---------- 导出 ----------

class TestExport:
    def test_requires_auth(self, client, session):
        r = make_weekly_report(session)
        assert client.get(f"/api/ai-reports/{r.id}/export?format=md").status_code == 401

    def test_export_markdown(self, client, auth, session):
        r = make_weekly_report(session)
        resp = client.get(f"/api/ai-reports/{r.id}/export?format=md", headers=auth)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "attachment" in resp.headers["content-disposition"]
        assert "weekly_2026-08-03_2026-08-09.md" in resp.headers["content-disposition"]
        assert "周复盘" in resp.text
        assert "本周训练 3 次" in resp.text

    def test_export_pdf(self, client, auth, session):
        r = make_weekly_report(session)
        resp = client.get(f"/api/ai-reports/{r.id}/export?format=pdf", headers=auth)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")
        assert "weekly_2026-08-03_2026-08-09.pdf" in resp.headers["content-disposition"]

    def test_export_invalid_format_422(self, client, auth, session):
        r = make_weekly_report(session)
        resp = client.get(f"/api/ai-reports/{r.id}/export?format=txt", headers=auth)
        assert resp.status_code == 422

    def test_export_not_found(self, client, auth):
        resp = client.get("/api/ai-reports/999/export?format=md", headers=auth)
        assert resp.status_code == 404


# ---------- 手动生成 + 状态轮询 ----------

class TestGenerate:
    def test_generate_weekly_and_poll_status(self, client, auth, session, sync_manager):
        resp = client.post(
            "/api/ai-reports/generate",
            json={"type": "weekly", "date": "2026-08-09"},
            headers=auth,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"
        assert resp.json()["period_start"] == "2026-08-03"
        assert sync_manager.calls == [("weekly", "2026-08-09")]

        status = client.get(
            "/api/ai-reports/generate/status?type=weekly", headers=auth
        ).json()
        assert status["running"] is False
        assert status["report"] is not None
        assert status["report"]["type"] == "weekly"
        assert status["report"]["date"] == "2026-08-03"

    def test_generate_monthly(self, client, auth, session, sync_manager):
        resp = client.post(
            "/api/ai-reports/generate",
            json={"type": "monthly", "date": "2026-07-31"},
            headers=auth,
        )
        assert resp.status_code == 200
        assert resp.json()["period_start"] == "2026-07-01"
        assert resp.json()["period_end"] == "2026-07-31"

    def test_generate_existing_report_returns_exists(
            self, client, auth, session, sync_manager):
        make_weekly_report(session)
        resp = client.post(
            "/api/ai-reports/generate",
            json={"type": "weekly", "date": "2026-08-05"},
            headers=auth,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "exists"
        assert data["report"]["date"] == "2026-08-03"
        assert sync_manager.calls == []  # 未触发新生成

    def test_generate_conflict_when_running(
            self, client, auth, session, sync_manager):
        sync_manager.running.add("weekly")
        resp = client.post(
            "/api/ai-reports/generate", json={"type": "weekly"}, headers=auth
        )
        assert resp.status_code == 409

    def test_generate_invalid_type_422(self, client, auth):
        resp = client.post(
            "/api/ai-reports/generate", json={"type": "daily"}, headers=auth
        )
        assert resp.status_code == 422

    def test_generate_invalid_date_422(self, client, auth):
        resp = client.post(
            "/api/ai-reports/generate",
            json={"type": "weekly", "date": "2026-08"},
            headers=auth,
        )
        assert resp.status_code == 422

    def test_generate_requires_auth(self, client):
        resp = client.post("/api/ai-reports/generate", json={"type": "weekly"})
        assert resp.status_code == 401

    def test_status_empty(self, client, auth, sync_manager):
        status = client.get(
            "/api/ai-reports/generate/status?type=monthly", headers=auth
        ).json()
        assert status["running"] is False
        assert status["report"] is None


# ---------- 生成管理器（后台线程） ----------

class TestReviewGenerateManager:
    def _wait_done(self, manager, rtype, timeout=5.0):
        import time

        deadline = time.time() + timeout
        while manager.is_running(rtype) and time.time() < deadline:
            time.sleep(0.05)
        assert not manager.is_running(rtype)

    def test_start_runs_runner_and_tracks_state(self):
        done = []
        manager = ai_reports_api.ReviewGenerateManager(
            runners={"weekly": lambda day: done.append(day)}
        )
        assert manager.start("weekly", "2026-08-09") is True
        self._wait_done(manager, "weekly")
        assert done == ["2026-08-09"]
        assert manager.last_error("weekly") is None

    def test_conflict_while_running(self):
        import threading

        gate = threading.Event()
        manager = ai_reports_api.ReviewGenerateManager(
            runners={"weekly": lambda day: gate.wait(2)}
        )
        assert manager.start("weekly") is True
        assert manager.is_running("weekly") is True
        assert manager.start("weekly") is False  # 重复触发被拒绝
        gate.set()
        self._wait_done(manager, "weekly")

    def test_runner_exception_captured(self):
        def boom(day):
            raise RuntimeError("runner failed")

        manager = ai_reports_api.ReviewGenerateManager(runners={"monthly": boom})
        assert manager.start("monthly", "2026-07-31") is True
        self._wait_done(manager, "monthly")
        assert "runner failed" in manager.last_error("monthly")

    def test_default_runner_uses_service(self, monkeypatch):
        called = []

        def fake_run(day, *, session=None, chat_fn=None):
            called.append(day)
            return {"status": "success"}

        import app.db as db_mod

        monkeypatch.setattr(ai_service, "run_weekly_review", fake_run)
        monkeypatch.setattr(db_mod, "SessionLocal", lambda: Mock())
        manager = ai_reports_api.ReviewGenerateManager()
        assert manager.start("weekly", "2026-08-09") is True
        self._wait_done(manager, "weekly")
        assert called == ["2026-08-09"]
        assert manager.last_error("weekly") is None
