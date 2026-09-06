"""V5-4 AI 教练独立聊天：消息装配 + 幂等 + 成本记账 + memory_section 注入。"""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters import llm
from app.models import CoachChatMessage
from app.services.report_chat import ReportChatError

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 1000  # 单条用户消息上限（沿用 report_chat 常量）
HISTORY_WINDOW = 30  # 独立聊天窗口更大（无报告上下文，保留更多轮）
MAX_MESSAGES_TOTAL = 200  # 整库上限（独立聊天无报告分组，需有总护栏）
COACH_CHAT_SYSTEM_PROMPT = (
    "你是一位专业、亲切的 AI 健身教练。用户正在自由与你聊天："
    "可以问训练相关问题，也可以告诉你他的长期偏好/伤病/目标/忌讳等。"
    "请基于用户的长期记忆（含用户须知、过往对话要点、长期训练统计）"
    "用中文简洁、具体地回答；不要编造数据，不确定时明确说明。"
)


class ChatMessageLimitError(ReportChatError):
    """独立聊天消息总数达上限。"""


def build_system_prompt(memory_section: str = "") -> str:
    """教练人设；memory_section 非空时追加到末尾。"""
    if memory_section:
        return COACH_CHAT_SYSTEM_PROMPT + "\n\n" + memory_section
    return COACH_CHAT_SYSTEM_PROMPT


def build_messages(
    history: list[CoachChatMessage],
    user_content: str,
    memory_section: str = "",
    *,
    window: int = HISTORY_WINDOW,
) -> list[dict]:
    """system → 最近 window 条历史 → 新用户消息。"""
    messages = [{
        "role": "system",
        "content": build_system_prompt(memory_section),
    }]
    for msg in history[-window:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_content})
    return messages


def _message_count(session: Session) -> int:
    return session.scalar(select(func.count(CoachChatMessage.id))) or 0


def _find_pair_by_request_id(
    session: Session, client_request_id: str
) -> tuple[CoachChatMessage, CoachChatMessage | None] | None:
    """按幂等键找回已落库的用户消息及其 assistant 回复。"""
    user_msg = session.scalars(
        select(CoachChatMessage).where(
            CoachChatMessage.client_request_id == client_request_id
        )
    ).first()
    if user_msg is None:
        return None
    reply = session.scalars(
        select(CoachChatMessage)
        .where(
            CoachChatMessage.id > user_msg.id,
            CoachChatMessage.role == "assistant",
        )
        .order_by(CoachChatMessage.id)
    ).first()
    return user_msg, reply


def list_messages(session: Session, *, limit: int = 200) -> list[CoachChatMessage]:
    """按 id 正序返回；超过 limit 时只返回最新 limit 条。"""
    rows = list(
        session.scalars(
            select(CoachChatMessage)
            .order_by(CoachChatMessage.id.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    return rows


def clear_messages(session: Session) -> int:
    """hard delete 全部独立聊天消息，返回删除条数。"""
    count = _message_count(session)
    session.execute(delete(CoachChatMessage))
    session.commit()
    return count


def post_message(
    session: Session,
    content: str,
    client_request_id: str,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
) -> tuple[CoachChatMessage, CoachChatMessage]:
    """落用户消息 → 调 LLM → 落 assistant 回复，返回两条消息。

    幂等：client_request_id 已存在时直接返回已落库的消息对，不重复调 LLM。
    """
    content = (content or "").strip()
    if not content:
        raise ValueError("消息内容不能为空")
    if len(content) > MAX_CONTENT_LENGTH:
        raise ValueError(f"消息过长（上限 {MAX_CONTENT_LENGTH} 字）")

    existing = _find_pair_by_request_id(session, client_request_id)
    if existing is not None:
        return existing

    if _message_count(session) >= MAX_MESSAGES_TOTAL:
        raise ChatMessageLimitError(
            f"对话过长：独立聊天消息总数已达 {MAX_MESSAGES_TOTAL} 条上限"
        )

    user_msg = CoachChatMessage(
        role="user",
        content=content,
        client_request_id=client_request_id,
    )
    session.add(user_msg)
    try:
        session.commit()
    except IntegrityError:  # 并发同 client_request_id：回滚后重放已落库消息对
        session.rollback()
        pair = _find_pair_by_request_id(session, client_request_id)
        if pair is not None:
            return pair
        raise

    history = list(
        session.scalars(
            select(CoachChatMessage)
            .where(CoachChatMessage.id < user_msg.id)
            .order_by(CoachChatMessage.id)
        )
    )

    from app.services.longterm_stats import query_longterm_stats
    from app.services.memory_distill import compose_memory_section_for

    try:
        l3 = query_longterm_stats(session, date.today())
    except Exception as exc:  # noqa: BLE001
        logger.warning("V5-4 longterm_stats 失败，l3=None：%s", exc)
        l3 = None
    memory_section = compose_memory_section_for(session, {}, "chat", l3=l3)
    messages = build_messages(history, content, memory_section=memory_section)

    if chat_fn is None:
        chat_fn = lambda msgs: llm.chat(  # noqa: E731
            msgs, session=session, purpose="coach_chat"
        )
    result = chat_fn(messages)

    reply_content = llm.strip_think(result.get("content"))
    prompt_tokens = result.get("prompt_tokens") or 0
    completion_tokens = result.get("completion_tokens") or 0
    try:
        provider = llm.get_default_provider(session)
    except Exception as exc:  # noqa: BLE001 - provider 读取失败回退默认
        logger.warning("读取默认 provider 失败，回退 %s：%s", llm.DEFAULT_PROVIDER, exc)
        provider = llm.DEFAULT_PROVIDER
    model = result.get("model") or llm.PROVIDERS[provider]["default_model"]
    cost = llm.compute_cost(provider, prompt_tokens, completion_tokens)

    assistant_msg = CoachChatMessage(
        role="assistant",
        content=reply_content,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_estimate=round(cost, 6),
    )
    session.add(assistant_msg)
    session.commit()
    return user_msg, assistant_msg
