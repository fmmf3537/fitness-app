"""V3-8 报告追问对话服务层测试：消息装配 / 窗口裁剪 / 截断 / strip_think /
token 成本落库 / 幂等重放 / 条数护栏 / 级联删除。"""
import datetime

import pytest
from sqlalchemy import select

from app.models import AIReport, ReportChatMessage
from app.services.report_chat import (
    MAX_MESSAGES_PER_REPORT,
    ChatMessageLimitError,
    ReportNotFoundError,
    build_messages,
    post_message,
)


def make_report(session, content_md="# 点评\n内容", score=88, rtype="session_review"):
    report = AIReport(
        type=rtype,
        period_start=datetime.date(2026, 8, 3),
        period_end=datetime.date(2026, 8, 3),
        model="deepseek-chat",
        content_md=content_md,
        score=score,
    )
    session.add(report)
    session.commit()
    return report


def add_message(session, report_id, role, content, client_request_id=None):
    msg = ReportChatMessage(
        report_id=report_id,
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
        return result or {"content": "教练回复", "prompt_tokens": 10, "completion_tokens": 5}

    return fake, calls


def test_post_message_assembly_order(session):
    """装配顺序：system（教练人设+报告） → 历史消息 → 新用户消息。"""
    report = make_report(session)
    add_message(session, report.id, "user", "第一个问题")
    add_message(session, report.id, "assistant", "第一个回答")
    fake, calls = fake_chat_with_spy()

    user_msg, assistant_msg = post_message(
        session, report.id, "第二个问题", "crid-1", chat_fn=fake
    )

    assert len(calls) == 1
    messages = calls[0]
    assert messages[0]["role"] == "system"
    assert "点评" in messages[0]["content"]  # 报告全文进 system
    assert messages[1] == {"role": "user", "content": "第一个问题"}
    assert messages[2] == {"role": "assistant", "content": "第一个回答"}
    assert messages[3] == {"role": "user", "content": "第二个问题"}
    assert user_msg.role == "user" and user_msg.content == "第二个问题"
    assert assistant_msg.role == "assistant" and assistant_msg.content == "教练回复"


def test_system_prompt_contains_report_meta(session):
    """system 提示包含报告元信息：类型 / 日期 / 评分。"""
    report = make_report(session, score=88)
    messages = build_messages(report, [], "问题")
    system = messages[0]["content"]
    assert "session_review" in system or "单次点评" in system
    assert "2026-08-03" in system
    assert "88" in system


def test_history_window_trimmed_to_20(session):
    """历史窗口只带最近 20 条。"""
    report = make_report(session)
    for i in range(25):
        add_message(session, report.id, "user" if i % 2 == 0 else "assistant", f"消息{i}")
    fake, calls = fake_chat_with_spy()

    post_message(session, report.id, "新问题", "crid-window", chat_fn=fake)

    messages = calls[0]
    # system + 20 条历史 + 1 条新消息
    assert len(messages) == 22
    assert messages[1]["content"] == "消息5"  # 最近 20 条从消息5开始
    assert messages[-2]["content"] == "消息24"
    assert messages[-1] == {"role": "user", "content": "新问题"}


def test_report_content_truncated_over_8000_chars(session):
    """报告正文超 8000 字截断并保留尾部结论。"""
    head = "头部内容" + "A" * 100
    tail = "尾部结论" + "Z" * 100
    content = head + "M" * 9000 + tail
    report = make_report(session, content_md=content)

    messages = build_messages(report, [], "问题")
    system = messages[0]["content"]
    assert tail in system
    assert head not in system


def test_strip_think_applied_to_reply(session):
    """assistant 回复过 strip_think。"""
    report = make_report(session)
    fake, _ = fake_chat_with_spy(
        {"content": "<think>内心思考</think>正式回复", "prompt_tokens": 1, "completion_tokens": 1}
    )

    _, assistant_msg = post_message(session, report.id, "问题", "crid-think", chat_fn=fake)
    assert assistant_msg.content == "正式回复"


def test_token_and_cost_persisted(session):
    """token 与成本按 ai.py 模式落库到 assistant 消息行。"""
    report = make_report(session)
    fake, _ = fake_chat_with_spy(
        {"content": "回复", "prompt_tokens": 100, "completion_tokens": 50}
    )

    _, assistant_msg = post_message(session, report.id, "问题", "crid-cost", chat_fn=fake)

    assert assistant_msg.prompt_tokens == 100
    assert assistant_msg.completion_tokens == 50
    assert assistant_msg.model == "deepseek-chat"  # 默认 provider 的默认模型
    # deepseek 单价：输入 1 元 / 输出 2 元每 1M tokens
    assert assistant_msg.cost_estimate == pytest.approx(0.0002, abs=1e-9)
    # 用户消息不计 token
    user_msg = session.scalars(
        select(ReportChatMessage).where(ReportChatMessage.role == "user")
    ).first()
    assert user_msg.prompt_tokens is None


def test_idempotent_replay_does_not_call_llm(session):
    """client_request_id 重放直接返回已落库消息对，不重复调 LLM。"""
    report = make_report(session)
    fake, calls = fake_chat_with_spy()

    u1, a1 = post_message(session, report.id, "问题", "crid-dup", chat_fn=fake)
    u2, a2 = post_message(session, report.id, "问题", "crid-dup", chat_fn=fake)

    assert len(calls) == 1
    assert (u1.id, a1.id) == (u2.id, a2.id)
    total = session.query(ReportChatMessage).filter_by(report_id=report.id).count()
    assert total == 2


def test_message_limit_100_per_report(session):
    """单报告消息总数达 100 条后拒绝新消息。"""
    report = make_report(session)
    for i in range(MAX_MESSAGES_PER_REPORT):
        add_message(session, report.id, "user" if i % 2 == 0 else "assistant", f"消息{i}")
    fake, calls = fake_chat_with_spy()

    with pytest.raises(ChatMessageLimitError):
        post_message(session, report.id, "超限问题", "crid-limit", chat_fn=fake)
    assert len(calls) == 0


def test_report_not_found(session):
    fake, _ = fake_chat_with_spy()
    with pytest.raises(ReportNotFoundError):
        post_message(session, 9999, "问题", "crid-404", chat_fn=fake)


def test_blank_content_rejected(session):
    report = make_report(session)
    fake, calls = fake_chat_with_spy()
    with pytest.raises(ValueError):
        post_message(session, report.id, "   ", "crid-blank", chat_fn=fake)
    assert len(calls) == 0


def test_cascade_delete_messages_with_report(session):
    """删除报告后追问消息级联清空。"""
    report = make_report(session)
    add_message(session, report.id, "user", "问题")
    add_message(session, report.id, "assistant", "回答")

    session.delete(report)
    session.commit()

    remaining = session.query(ReportChatMessage).filter_by(report_id=report.id).count()
    assert remaining == 0
