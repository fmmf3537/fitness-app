"""V3-8 报告追问对话：消息装配、LLM 调用、幂等与成本护栏。

装配规则（任务书）：
system = 教练人设 + 报告全文（超 8000 字截断保留尾部结论）+ 报告元信息
→ 最近 20 条历史消息 → 新用户消息。

token 记账与 compute_cost 复用 services/ai.py 模式，落库到 assistant 消息行；
provider 取 settings 当前默认（与报告生成同一来源）。
"""
from typing import Callable

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters import llm
from app.models import AIReport, ReportChatMessage

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 1000  # 单条用户消息上限（字）
HISTORY_WINDOW = 20  # 携带的历史消息窗口
MAX_MESSAGES_PER_REPORT = 100  # 单报告消息总数护栏
REPORT_CONTENT_LIMIT = 8000  # system 中报告正文截断阈值

_TYPE_LABELS = {
    "session_review": "单次点评",
    "next_advice": "下次建议",
    "weekly": "周复盘",
    "monthly": "月复盘",
    "plan_review": "计划复盘",
}


class ReportChatError(Exception):
    """报告追问对话服务层异常基类。"""


class ReportNotFoundError(ReportChatError):
    """报告不存在。"""


class ChatMessageLimitError(ReportChatError):
    """单报告消息总数达上限。"""


def _truncate_report_content(content: str, limit: int = REPORT_CONTENT_LIMIT) -> str:
    """报告正文超 limit 字时截断，保留尾部结论。"""
    if len(content) <= limit:
        return content
    return "……（报告前文已截断）\n" + content[-limit:]


def build_system_prompt(report: AIReport) -> str:
    """教练人设 + 报告元信息 + 报告全文。"""
    type_label = _TYPE_LABELS.get(report.type, report.type or "-")
    meta_lines = [
        f"报告类型：{type_label}（{report.type}）",
        f"日期：{report.period_start.isoformat() if report.period_start else '-'}",
        f"评分：{report.score if report.score is not None else '无'}",
    ]
    return (
        "你是一位专业、亲切的 AI 健身教练。用户正在阅读你之前生成的一份训练报告，"
        "并对其中内容有疑问。请基于报告全文，用中文简洁、具体地解答用户的追问，"
        "必要时给出可执行的补充建议；不要编造报告中没有的数据，"
        "不确定时明确说明。\n\n"
        "【报告元信息】\n"
        + "\n".join(meta_lines)
        + "\n\n【报告全文】\n"
        + _truncate_report_content(report.content_md or "")
    )


def build_messages(
    report: AIReport,
    history: list[ReportChatMessage],
    user_content: str,
    *,
    window: int = HISTORY_WINDOW,
) -> list[dict]:
    """system → 最近 window 条历史 → 新用户消息。"""
    messages = [{"role": "system", "content": build_system_prompt(report)}]
    for msg in history[-window:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_content})
    return messages


def _message_count(session: Session, report_id: int) -> int:
    return session.scalar(
        select(func.count(ReportChatMessage.id)).where(
            ReportChatMessage.report_id == report_id
        )
    )


def _find_pair_by_request_id(
    session: Session, client_request_id: str
) -> tuple[ReportChatMessage, ReportChatMessage | None] | None:
    """按幂等键找回已落库的用户消息及其 assistant 回复。"""
    user_msg = session.scalars(
        select(ReportChatMessage).where(
            ReportChatMessage.client_request_id == client_request_id
        )
    ).first()
    if user_msg is None:
        return None
    reply = session.scalars(
        select(ReportChatMessage)
        .where(
            ReportChatMessage.report_id == user_msg.report_id,
            ReportChatMessage.id > user_msg.id,
            ReportChatMessage.role == "assistant",
        )
        .order_by(ReportChatMessage.id)
    ).first()
    return user_msg, reply


def list_messages(session: Session, report_id: int) -> list[ReportChatMessage]:
    """该报告的对话历史（按时间正序）。"""
    report = session.get(AIReport, report_id)
    if report is None:
        raise ReportNotFoundError(f"报告 {report_id} 不存在")
    return list(
        session.scalars(
            select(ReportChatMessage)
            .where(ReportChatMessage.report_id == report_id)
            .order_by(ReportChatMessage.id)
        )
    )


def post_message(
    session: Session,
    report_id: int,
    content: str,
    client_request_id: str,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
) -> tuple[ReportChatMessage, ReportChatMessage]:
    """落用户消息 → 调 LLM → 落 assistant 回复，返回两条消息。

    幂等：client_request_id 已存在时直接返回已落库的消息对，不重复调 LLM。
    """
    report = session.get(AIReport, report_id)
    if report is None:
        raise ReportNotFoundError(f"报告 {report_id} 不存在")

    content = (content or "").strip()
    if not content:
        raise ValueError("消息内容不能为空")
    if len(content) > MAX_CONTENT_LENGTH:
        raise ValueError(f"消息过长（上限 {MAX_CONTENT_LENGTH} 字）")

    existing = _find_pair_by_request_id(session, client_request_id)
    if existing is not None:
        return existing

    if _message_count(session, report_id) >= MAX_MESSAGES_PER_REPORT:
        raise ChatMessageLimitError(
            f"对话过长：单报告消息总数已达 {MAX_MESSAGES_PER_REPORT} 条上限"
        )

    user_msg = ReportChatMessage(
        report_id=report_id,
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

    # 历史窗口：新消息之前的最近 20 条
    history = list(
        session.scalars(
            select(ReportChatMessage)
            .where(
                ReportChatMessage.report_id == report_id,
                ReportChatMessage.id < user_msg.id,
            )
            .order_by(ReportChatMessage.id)
        )
    )
    messages = build_messages(report, history, content)

    if chat_fn is None:
        chat_fn = lambda msgs: llm.chat(  # noqa: E731
            msgs, session=session, purpose="report_chat"
        )
    result = chat_fn(messages)

    reply_content = llm.strip_think(result.get("content"))
    prompt_tokens = result.get("prompt_tokens") or 0
    completion_tokens = result.get("completion_tokens") or 0
    try:
        provider = llm.get_default_provider(session)
    except Exception as exc:  # noqa: BLE001 - provider 读取失败回退默认，不计费偏差容忍
        logger.warning("读取默认 provider 失败，回退 %s：%s", llm.DEFAULT_PROVIDER, exc)
        provider = llm.DEFAULT_PROVIDER
    model = result.get("model") or llm.PROVIDERS[provider]["default_model"]
    cost = llm.compute_cost(provider, prompt_tokens, completion_tokens)

    assistant_msg = ReportChatMessage(
        report_id=report_id,
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
