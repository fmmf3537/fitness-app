"""V5-4 AI 教练独立聊天：服务层装配/幂等/护栏/记忆注入 + API 鉴权。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import CoachChatMessage, CoachMemory, CoachPreference, LLMCall
from app.services.coach_chat import (
    MAX_CONTENT_LENGTH,
    MAX_MESSAGES_TOTAL,
    ChatMessageLimitError,
    clear_messages,
    list_messages,
    post_message,
)


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
def auth_user(client):
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def add_message(session, role, content, client_request_id=None):
    msg = CoachChatMessage(
        role=role,
        content=content,
        client_request_id=client_request_id,
    )
    session.add(msg)
    session.commit()
    return msg


def fake_chat_with_spy(result=None):
    calls = []

    def fake(messages):
        calls.append(messages)
        return result or {
            "content": "教练回复",
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }

    return fake, calls


def test_post_message_success_persists_both(session):
    fake, calls = fake_chat_with_spy({"content": "你好呀", "prompt_tokens": 8, "completion_tokens": 4})

    user_msg, assistant_msg = post_message(
        session, "你好", "crid-ok", chat_fn=fake
    )

    assert len(calls) == 1
    rows = list(session.scalars(select(CoachChatMessage).order_by(CoachChatMessage.id)))
    assert len(rows) == 2
    assert user_msg.role == "user" and user_msg.content == "你好"
    assert assistant_msg.role == "assistant" and assistant_msg.content == "你好呀"
    assert rows[0].id == user_msg.id and rows[1].id == assistant_msg.id


def test_post_message_idempotent_returns_existing_pair(session):
    fake, calls = fake_chat_with_spy()

    u1, a1 = post_message(session, "问题", "crid-dup", chat_fn=fake)
    u2, a2 = post_message(session, "问题", "crid-dup", chat_fn=fake)

    assert len(calls) == 1
    assert (u1.id, a1.id) == (u2.id, a2.id)
    assert session.query(CoachChatMessage).count() == 2


def test_post_message_empty_content_raises_value_error(session):
    fake, calls = fake_chat_with_spy()
    with pytest.raises(ValueError):
        post_message(session, "", "crid-empty", chat_fn=fake)
    assert len(calls) == 0


def test_post_message_too_long_raises_value_error(session):
    fake, calls = fake_chat_with_spy()
    with pytest.raises(ValueError):
        post_message(session, "长" * (MAX_CONTENT_LENGTH + 1), "crid-long", chat_fn=fake)
    assert len(calls) == 0


def test_post_message_over_total_limit_raises_chat_message_limit(session):
    for i in range(MAX_MESSAGES_TOTAL):
        add_message(session, "user" if i % 2 == 0 else "assistant", f"消息{i}")
    fake, calls = fake_chat_with_spy()

    with pytest.raises(ChatMessageLimitError):
        post_message(session, "超限问题", "crid-limit", chat_fn=fake)
    assert len(calls) == 0


def test_post_message_injects_memory_section_in_system(session):
    session.add(
        CoachPreference(content="须知：右膝旧伤", tags="膝盖", source="user", active=True)
    )
    session.add(
        CoachMemory(
            summary="历史：深蹲减负",
            tags="深蹲,膝盖",
            source="report_chat",
            ref_report_id=1,
            active=True,
        )
    )
    session.add(
        CoachMemory(
            summary="历史：忌讳空腹练",
            tags="饮食,训练",
            source="coach_chat",
            ref_chat_id=1,
            active=True,
        )
    )
    session.commit()
    fake, calls = fake_chat_with_spy()

    post_message(session, "今天练什么", "crid-mem", chat_fn=fake)

    system = calls[0][0]["content"]
    assert "用户长期记忆" in system
    assert "须知：右膝旧伤" in system
    assert "历史：深蹲减负" in system
    assert "历史：忌讳空腹练" in system


def test_post_message_includes_l3_when_longterm_stats_returns_data(session, monkeypatch):
    l3 = {"训练频率": "3 次/周（36 个训练日，共 12 周）", "总容量": "12000 kg"}

    def fake_l3(sess, anchor, *, weeks=12):
        return l3

    monkeypatch.setattr("app.services.longterm_stats.query_longterm_stats", fake_l3)
    fake, calls = fake_chat_with_spy()

    post_message(session, "看看长期", "crid-l3", chat_fn=fake)

    system = calls[0][0]["content"]
    assert "长期统计：" in system
    assert "训练频率：3 次/周（36 个训练日，共 12 周）" in system


def test_post_message_l3_failure_does_not_raise(session, monkeypatch):
    def boom(sess, anchor, *, weeks=12):
        raise RuntimeError("stats down")

    monkeypatch.setattr("app.services.longterm_stats.query_longterm_stats", boom)
    fake, calls = fake_chat_with_spy()

    user_msg, assistant_msg = post_message(
        session, "还能聊吗", "crid-l3-fail", chat_fn=fake
    )

    assert len(calls) == 1
    system = calls[0][0]["content"]
    assert "用户长期记忆" not in system
    assert "长期统计：" not in system
    assert user_msg.content == "还能聊吗"
    assert assistant_msg.content == "教练回复"


def test_list_messages_returns_in_id_ascending_order(session):
    for i in range(5):
        add_message(session, "user" if i % 2 == 0 else "assistant", f"m{i}")

    rows = list_messages(session)
    assert [r.content for r in rows] == [f"m{i}" for i in range(5)]
    assert [r.id for r in rows] == sorted(r.id for r in rows)


def test_list_messages_truncates_to_limit(session):
    for i in range(250):
        add_message(session, "user" if i % 2 == 0 else "assistant", f"m{i}")

    rows = list_messages(session, limit=200)
    assert len(rows) == 200
    assert rows[0].content == "m50"
    assert rows[-1].content == "m249"
    assert [r.id for r in rows] == sorted(r.id for r in rows)


def test_clear_messages_deletes_all_and_returns_count(session):
    for i in range(5):
        add_message(session, "user" if i % 2 == 0 else "assistant", f"m{i}")

    deleted = clear_messages(session)
    assert deleted == 5
    assert session.query(CoachChatMessage).count() == 0
    assert list_messages(session) == []


def test_post_message_writes_llm_call_accounting_row(session, monkeypatch):
    from app.adapters import llm

    def fake_llm_chat(messages, session=None, purpose=None, **kwargs):
        session.add(
            LLMCall(
                provider="deepseek",
                model="deepseek-chat",
                purpose=purpose,
                prompt_tokens=10,
                completion_tokens=5,
                cost_estimate=0.0,
                status="ok",
            )
        )
        session.commit()
        return {
            "content": "记账回复",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "model": "deepseek-chat",
        }

    monkeypatch.setattr(llm, "chat", fake_llm_chat)

    post_message(session, "记账一下", "crid-acct")

    rows = list(session.scalars(select(LLMCall)))
    assert len(rows) == 1
    assert rows[0].purpose == "coach_chat"
    assert rows[0].prompt_tokens == 10
    assert rows[0].completion_tokens == 5


def test_api_endpoint_requires_auth(client):
    resp = client.get("/api/coach/chat")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "未登录"


def test_api_post_400_on_value_error(client, auth_user):
    resp = client.post(
        "/api/coach/chat",
        json={"content": "", "client_request_id": "crid-api-empty"},
        headers=auth_user,
    )
    assert resp.status_code == 400
