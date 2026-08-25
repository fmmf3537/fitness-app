"""V3-8 报告追问对话 API 测试：401/404/422 三态、POST→GET 历史闭环、
重复 client_request_id 幂等。"""
import datetime

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AIReport, ReportChatMessage


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


@pytest.fixture
def fake_llm(monkeypatch):
    """拦截服务层默认 chat_fn 对 adapters.llm.chat 的调用。"""
    from app.adapters import llm

    calls = []

    def fake(messages, **kwargs):
        calls.append(messages)
        return {"content": "教练回复", "prompt_tokens": 12, "completion_tokens": 6}

    monkeypatch.setattr(llm, "chat", fake)
    return calls


@pytest.fixture
def report(session):
    row = AIReport(
        user_id=1,
        type="session_review",
        period_start=datetime.date(2026, 8, 3),
        period_end=datetime.date(2026, 8, 3),
        model="deepseek-chat",
        content_md="# 点评\n内容",
        score=80,
    )
    session.add(row)
    session.commit()
    return row


def test_get_messages_requires_auth(client, report):
    resp = client.get(f"/api/ai-reports/{report.id}/messages")
    assert resp.status_code == 401


def test_post_message_requires_auth(client, report):
    resp = client.post(
        f"/api/ai-reports/{report.id}/messages",
        json={"content": "问题", "client_request_id": "c1"},
    )
    assert resp.status_code == 401


def test_get_messages_report_not_found(client, auth):
    resp = client.get("/api/ai-reports/9999/messages", headers=auth)
    assert resp.status_code == 404


def test_post_message_report_not_found(client, auth, fake_llm):
    resp = client.post(
        "/api/ai-reports/9999/messages",
        json={"content": "问题", "client_request_id": "c1"},
        headers=auth,
    )
    assert resp.status_code == 404
    assert len(fake_llm) == 0


def test_post_message_blank_content_422(client, auth, report, fake_llm):
    resp = client.post(
        f"/api/ai-reports/{report.id}/messages",
        json={"content": "   ", "client_request_id": "c1"},
        headers=auth,
    )
    assert resp.status_code == 422
    assert len(fake_llm) == 0


def test_post_message_too_long_422(client, auth, report, fake_llm):
    resp = client.post(
        f"/api/ai-reports/{report.id}/messages",
        json={"content": "长" * 1001, "client_request_id": "c1"},
        headers=auth,
    )
    assert resp.status_code == 422
    assert len(fake_llm) == 0


def test_post_message_over_limit_422(client, auth, session, report, fake_llm):
    for i in range(100):
        session.add(
            ReportChatMessage(
                report_id=report.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"消息{i}",
            )
        )
    session.commit()
    resp = client.post(
        f"/api/ai-reports/{report.id}/messages",
        json={"content": "问题", "client_request_id": "c-over"},
        headers=auth,
    )
    assert resp.status_code == 422
    assert "对话过长" in resp.json()["detail"]
    assert len(fake_llm) == 0


def test_post_then_get_history_roundtrip(client, auth, report, fake_llm):
    resp = client.post(
        f"/api/ai-reports/{report.id}/messages",
        json={"content": "这次训练强度如何？", "client_request_id": "c1"},
        headers=auth,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_message"]["role"] == "user"
    assert data["user_message"]["content"] == "这次训练强度如何？"
    assert data["assistant_message"]["role"] == "assistant"
    assert data["assistant_message"]["content"] == "教练回复"
    assert data["assistant_message"]["prompt_tokens"] == 12

    resp = client.get(f"/api/ai-reports/{report.id}/messages", headers=auth)
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "这次训练强度如何？"
    assert messages[1]["content"] == "教练回复"


def test_duplicate_client_request_id_returns_same_pair(client, auth, session, report, fake_llm):
    payload = {"content": "问题", "client_request_id": "c-dup"}
    r1 = client.post(f"/api/ai-reports/{report.id}/messages", json=payload, headers=auth)
    r2 = client.post(f"/api/ai-reports/{report.id}/messages", json=payload, headers=auth)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["user_message"]["id"] == r2.json()["user_message"]["id"]
    assert r1.json()["assistant_message"]["id"] == r2.json()["assistant_message"]["id"]
    assert len(fake_llm) == 1  # 不重复调 LLM

    total = session.query(ReportChatMessage).filter_by(report_id=report.id).count()
    assert total == 2  # 只落一对
