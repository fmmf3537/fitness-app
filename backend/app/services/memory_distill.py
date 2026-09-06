"""V5-2 AI 教练长期记忆：L2 每日批提炼 + 注入用 tag/段组装。"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.llm import LLMError
from app.models import (
    CoachChatMessage,
    CoachMemory,
    JobRun,
    ReportChatMessage,
)
from app.services.coach_memory import (
    build_memory_section,
    list_preferences,
    search_memory,
)
from app.services.stats import classify_part

logger = logging.getLogger(__name__)

MAX_DAILY_INPUT_CHARS = 8000  # 单次提炼输入截断（防对话爆量）
MAX_MEMORY_PER_DISTILL = 3  # 单次提炼产出 ≤3 条摘要

_DISTILL_SYSTEM = (
    "你是用户的 AI 健身教练助手。用户与你的对话历史中可能包含"
    "\"长期偏好/伤病/忌讳/目标/要求\"等需要被记住的信息。\n"
    "请提炼成结构化摘要，便于后续对话中按主题检索。\n"
    "输出 JSON：\n"
    '[{"summary": "（一句话要点，30-80 字）", '
    '"tags": "（逗号分隔关键词，最多 5 个，用于检索）"}, ...]\n'
    "最多 3 条；只提炼长期有意义的内容，普通问答不必提炼；不要编造。"
)

_ROLE_ZH = {"user": "用户", "assistant": "教练"}
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.S | re.I)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min)
    end = datetime.combine(day + timedelta(days=1), time.min)
    return start, end


def _query_today_messages(
    session: Session, day: date
) -> tuple[list[tuple[int, list[tuple[str, str]]]], list[tuple[int, list[tuple[str, str]]]]]:
    """查当天新增 report_chat / coach_chat 消息（按 created_at ∈ [day 00:00, next)）。

    返回 (report_chat_convs, coach_chat_convs)：
    每项为 (ref_id, [(role, content), ...])，report 按 report_id 分组，
    coach_chat 当天全部消息作为一组，ref_id 取当日首条消息 id。
    """
    start, end = _day_bounds(day)

    report_rows = list(
        session.scalars(
            select(ReportChatMessage)
            .where(
                ReportChatMessage.created_at >= start,
                ReportChatMessage.created_at < end,
            )
            .order_by(ReportChatMessage.report_id, ReportChatMessage.id)
        ).all()
    )
    report_convs: dict[int, list[tuple[str, str]]] = {}
    for row in report_rows:
        report_convs.setdefault(row.report_id, []).append((row.role, row.content or ""))
    report_out = [(rid, msgs) for rid, msgs in report_convs.items()]

    coach_rows = list(
        session.scalars(
            select(CoachChatMessage)
            .where(
                CoachChatMessage.created_at >= start,
                CoachChatMessage.created_at < end,
            )
            .order_by(CoachChatMessage.id)
        ).all()
    )
    coach_out: list[tuple[int, list[tuple[str, str]]]] = []
    if coach_rows:
        ref_id = coach_rows[0].id
        msgs = [(r.role, r.content or "") for r in coach_rows]
        coach_out.append((ref_id, msgs))

    return report_out, coach_out


def _format_messages_for_distill(messages: list) -> str:
    """把 [(role, content), ...] 格式化成「用户：…/教练：…」多行文本，上限 8k 字截断。"""
    lines: list[str] = []
    for item in messages or []:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            role, content = item[0], item[1]
        elif isinstance(item, dict):
            role, content = item.get("role"), item.get("content")
        else:
            continue
        label = _ROLE_ZH.get(str(role or "").strip().lower(), str(role or "未知"))
        lines.append(f"{label}：{content or ''}")
    text = "\n".join(lines)
    if len(text) > MAX_DAILY_INPUT_CHARS:
        return text[:MAX_DAILY_INPUT_CHARS]
    return text


def _parse_distill_json(raw: str) -> list[dict]:
    """解析提炼 LLM 输出为 list[dict]；失败抛 LLMError。"""
    text = (raw or "").strip()
    if not text:
        raise LLMError("提炼输出为空")

    candidates = [text]
    m = _JSON_FENCE_RE.search(text)
    if m:
        candidates.insert(0, m.group(1).strip())

    data = None
    last_err: Exception | None = None
    for cand in candidates:
        try:
            data = json.loads(cand)
            break
        except (json.JSONDecodeError, TypeError) as exc:
            last_err = exc
            # 尝试截取首个 [...] 数组
            start, end = cand.find("["), cand.rfind("]")
            if start >= 0 and end > start:
                try:
                    data = json.loads(cand[start : end + 1])
                    break
                except (json.JSONDecodeError, TypeError) as exc2:
                    last_err = exc2
    if data is None:
        raise LLMError(f"提炼输出不是合法 JSON：{last_err}") from last_err

    if not isinstance(data, list):
        raise LLMError("提炼输出 schema 校验失败：须为 list")
    out: list[dict] = []
    for item in data[:MAX_MEMORY_PER_DISTILL]:
        if not isinstance(item, dict):
            raise LLMError("提炼输出 schema 校验失败：元素须为 dict")
        if "summary" not in item or "tags" not in item:
            raise LLMError("提炼输出 schema 校验失败：须含 summary 与 tags")
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        tags = item.get("tags")
        if tags is None:
            tags_str = ""
        elif isinstance(tags, list):
            tags_str = ",".join(str(t).strip() for t in tags if str(t).strip())
        else:
            tags_str = str(tags).strip()
        out.append({"summary": summary, "tags": tags_str})
    return out


def _call_distill_llm(text: str, *, chat_fn: Callable) -> list[dict]:
    """调 LLM 把对话提炼成 [{"summary", "tags"}, ...]，≤3 条。失败抛 LLMError。"""
    messages = [
        {"role": "system", "content": _DISTILL_SYSTEM},
        {"role": "user", "content": text},
    ]
    try:
        result = chat_fn(messages)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"提炼 LLM 调用失败：{exc}") from exc

    if isinstance(result, dict):
        content = result.get("content") or ""
    else:
        content = str(result or "")
    return _parse_distill_json(content)


def _memory_exists(session: Session, source: str, ref_id: int) -> bool:
    """按 (source, ref_id) 查是否已提炼过。"""
    stmt = select(CoachMemory).where(CoachMemory.source == source)
    if source == "report_chat":
        stmt = stmt.where(CoachMemory.ref_report_id == ref_id)
    else:
        stmt = stmt.where(CoachMemory.ref_chat_id == ref_id)
    return session.scalars(stmt).first() is not None


def distill_messages_to_memory(
    session: Session,
    messages: list,
    source: str,
    ref_id: int,
    *,
    chat_fn: Callable | None = None,
) -> int:
    """把单条对话提炼入 coach_memory；按 (source, ref_id) 幂等。

    返回新插入条数（0 表示去重跳过或 LLM 失败）。
    """
    if _memory_exists(session, source, ref_id):
        return 0

    text = _format_messages_for_distill(messages)
    if not text.strip():
        return 0

    if chat_fn is None:
        from app.adapters import llm

        chat_fn = lambda msgs: llm.chat(  # noqa: E731
            msgs, session=session, purpose="memory_distill"
        )

    try:
        items = _call_distill_llm(text, chat_fn=chat_fn)
    except LLMError as exc:
        logger.warning("V5-2 distill_messages_to_memory LLM 失败：%s", exc)
        return 0

    if not items:
        return 0

    for item in items:
        row = CoachMemory(
            summary=item["summary"],
            tags=item["tags"] or None,
            source=source,
            ref_report_id=ref_id if source == "report_chat" else None,
            ref_chat_id=ref_id if source == "coach_chat" else None,
            active=True,
        )
        session.add(row)
    session.commit()
    return len(items)


def _write_memory_distill_job(
    session: Session,
    started_at: datetime,
    *,
    status: str,
    error: str | None,
    detail: dict,
) -> None:
    run = JobRun(
        job_name="memory_distill",
        started_at=started_at,
        finished_at=datetime.now(),
        status=status,
        error=error,
        detail_json=json.dumps(detail, ensure_ascii=False, default=str),
    )
    session.add(run)
    session.commit()


def distill_daily_memory(
    session: Session, day: date, *, chat_fn: Callable | None = None
) -> dict:
    """每日批提炼：任何异常写 JobRun(job_name='memory_distill') 但不向外抛。"""
    started_at = datetime.now()
    out: dict[str, Any] = {
        "date": day.isoformat() if isinstance(day, date) else str(day),
        "conversations_processed": 0,
        "memories_added": 0,
        "errors": [],
    }
    llm_failed = False

    try:
        if chat_fn is None:
            from app.adapters import llm

            base_chat = lambda msgs: llm.chat(  # noqa: E731
                msgs, session=session, purpose="memory_distill"
            )
        else:
            base_chat = chat_fn

        def tracking_chat(msgs):
            nonlocal llm_failed
            try:
                return base_chat(msgs)
            except Exception as exc:  # noqa: BLE001
                llm_failed = True
                raise LLMError(str(exc)) from exc

        report_convs, coach_convs = _query_today_messages(session, day)
        for ref_id, msgs in report_convs:
            try:
                n = distill_messages_to_memory(
                    session, msgs, "report_chat", ref_id, chat_fn=tracking_chat
                )
                out["conversations_processed"] += 1
                out["memories_added"] += n
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"report_chat:{ref_id}:{exc}")
                logger.warning("V5-2 report_chat 提炼失败 ref=%s：%s", ref_id, exc)

        for ref_id, msgs in coach_convs:
            try:
                n = distill_messages_to_memory(
                    session, msgs, "coach_chat", ref_id, chat_fn=tracking_chat
                )
                out["conversations_processed"] += 1
                out["memories_added"] += n
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"coach_chat:{ref_id}:{exc}")
                logger.warning("V5-2 coach_chat 提炼失败 ref=%s：%s", ref_id, exc)

        status = "failed" if (out["errors"] or llm_failed) else "success"
        error = "; ".join(out["errors"]) if out["errors"] else (
            "llm_failed" if llm_failed else None
        )
        _write_memory_distill_job(
            session, started_at, status=status, error=error, detail=out
        )
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(str(exc))
        logger.warning("V5-2 distill_daily_memory 失败：%s", exc)
        try:
            _write_memory_distill_job(
                session,
                started_at,
                status="failed",
                error=str(exc),
                detail=out,
            )
        except Exception as write_exc:  # noqa: BLE001
            logger.warning("V5-2 memory_distill JobRun 写入失败：%s", write_exc)

    return out


def build_query_tags(workout_dict: dict | None, report_type: str) -> list[str]:
    """聚合本次上下文 tag：动作名 + body_part + garmin 活动类型 + 报告类型。"""
    tags: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        t = str(value).strip() if value is not None else ""
        if t and t not in seen:
            seen.add(t)
            tags.append(t)

    wd = workout_dict or {}
    for mv in wd.get("movements") or []:
        if not isinstance(mv, dict):
            continue
        name = mv.get("name")
        add(name)
        if name:
            part = classify_part(str(name))
            if part and part != "其他":
                add(part)

    wtags = wd.get("tags")
    if isinstance(wtags, str):
        add(wtags)
    elif isinstance(wtags, (list, tuple)):
        for t in wtags:
            add(t)

    add(report_type)
    if report_type == "chat":
        add("对话")

    return tags


def compose_memory_section_for(
    session: Session,
    workout_dict: dict | None,
    report_type: str,
    *,
    l3: dict | None = None,  # V5-3
) -> str:
    """build_query_tags + search_memory + list_preferences + build_memory_section。

    空数据返回 ""；检索/偏好查询失败时兜底返回 ""（不阻断主流程）。
    l3 由调用方预计算并传入（V5-3）。
    """
    try:
        query_tags = build_query_tags(workout_dict or {}, report_type)
        memories = search_memory(session, query_tags, limit=5)
        prefs = list_preferences(session, active_only=True)
        l1 = [p.content for p in prefs if p.content]
        l2 = [m.summary for m in memories if m.summary]
        return build_memory_section(l1, l2, l3)  # l3 直接传入
    except Exception as exc:  # noqa: BLE001
        logger.warning("V5-3 compose_memory_section_for 失败，返回空段：%s", exc)
        return ""
