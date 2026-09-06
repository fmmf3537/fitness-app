"""V5-1 AI 教练长期记忆：偏好/草稿 CRUD + 记忆检索 + prompt 段组装。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CoachMemory, CoachPreference, CoachPreferenceDraft


def to_dict(row: CoachPreference) -> dict:
    """序列化教练须知（API 响应）。"""
    return {
        "id": row.id,
        "content": row.content,
        "category": row.category,
        "tags": row.tags,
        "source": row.source,
        "active": bool(row.active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def draft_to_dict(row: CoachPreferenceDraft) -> dict:
    """序列化偏好草稿（API 响应）。"""
    return {
        "id": row.id,
        "content": row.content,
        "tags": row.tags,
        "source": row.source,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def list_preferences(
    session: Session, active_only: bool = True
) -> list[CoachPreference]:
    """列出教练须知，按 updated_at 倒序。"""
    stmt = select(CoachPreference)
    if active_only:
        stmt = stmt.where(CoachPreference.active.is_(True))
    stmt = stmt.order_by(CoachPreference.updated_at.desc())
    return list(session.scalars(stmt).all())


def create_preference(
    session: Session,
    *,
    content: str,
    category: str = "manual",
    tags: str | None = None,
    source: str = "user",
) -> CoachPreference:
    """新建须知；相同 content 且 active 时幂等返回既有行。"""
    existing = session.scalars(
        select(CoachPreference).where(
            CoachPreference.content == content,
            CoachPreference.active.is_(True),
        )
    ).first()
    if existing is not None:
        return existing
    row = CoachPreference(
        content=content,
        category=category,
        tags=tags,
        source=source,
        active=True,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_preference(
    session: Session,
    pref_id: int,
    *,
    content: str | None = None,
    tags: str | None = None,
) -> CoachPreference:
    """更新须知 content/tags；不存在抛 ValueError。"""
    row = session.get(CoachPreference, pref_id)
    if row is None:
        raise ValueError(f"偏好不存在: id={pref_id}")
    if content is not None:
        row.content = content
    if tags is not None:
        row.tags = tags
    session.commit()
    session.refresh(row)
    return row


def deactivate_preference(session: Session, pref_id: int) -> None:
    """软删：active=False，不物理删除。"""
    row = session.get(CoachPreference, pref_id)
    if row is None:
        raise ValueError(f"偏好不存在: id={pref_id}")
    row.active = False
    session.commit()


def list_drafts(
    session: Session, statuses: list[str] | None = None
) -> list[CoachPreferenceDraft]:
    """列出草稿；默认仅 pending，按 created_at 倒序。"""
    if statuses is None:
        statuses = ["pending"]
    stmt = (
        select(CoachPreferenceDraft)
        .where(CoachPreferenceDraft.status.in_(statuses))
        .order_by(CoachPreferenceDraft.created_at.desc())
    )
    return list(session.scalars(stmt).all())


def accept_draft(session: Session, draft_id: int) -> CoachPreference:
    """采纳草稿 → coach_preference；content 去重时 draft.status=merged。"""
    draft = session.get(CoachPreferenceDraft, draft_id)
    if draft is None:
        raise ValueError(f"草稿不存在: id={draft_id}")

    existing = session.scalars(
        select(CoachPreference).where(
            CoachPreference.content == draft.content,
            CoachPreference.active.is_(True),
        )
    ).first()
    now = datetime.now()
    draft.resolved_at = now
    if existing is not None:
        draft.status = "merged"
        session.commit()
        return existing

    pref = CoachPreference(
        content=draft.content,
        category="ai_suggested",
        tags=draft.tags,
        source=draft.source,
        active=True,
    )
    draft.status = "accepted"
    session.add(pref)
    session.commit()
    session.refresh(pref)
    return pref


def reject_draft(session: Session, draft_id: int) -> None:
    """拒绝草稿：status=rejected + resolved_at。"""
    draft = session.get(CoachPreferenceDraft, draft_id)
    if draft is None:
        raise ValueError(f"草稿不存在: id={draft_id}")
    draft.status = "rejected"
    draft.resolved_at = datetime.now()
    session.commit()


def _tag_hit(memory_tags: str | None, query_tags: list[str]) -> bool:
    """D5 V1：任一 query tag 与 memory tags 相同或互相包含即命中。"""
    if not memory_tags or not query_tags:
        return False
    mem_parts = [t.strip() for t in memory_tags.split(",") if t.strip()]
    for qt in query_tags:
        q = (qt or "").strip()
        if not q:
            continue
        for mt in mem_parts:
            if q == mt or q in mt or mt in q:
                return True
    return False


def search_memory(
    session: Session, tags: list[str], limit: int = 5
) -> list[CoachMemory]:
    """按 tag 检索 active 记忆；无命中则返回最近 limit 条 active 兜底。"""
    rows = list(
        session.scalars(
            select(CoachMemory)
            .where(CoachMemory.active.is_(True))
            .order_by(CoachMemory.created_at.desc())
        ).all()
    )
    hits = [r for r in rows if _tag_hit(r.tags, tags)]
    if hits:
        return hits[:limit]
    return rows[:limit]


def build_memory_section(
    l1: list[str], l2: list[str], l3: dict | None = None
) -> str:
    """纯函数：组装注入 prompt 的 Markdown 记忆段；全空返回空字符串（AC5）。"""
    has_l1 = bool(l1)
    has_l2 = bool(l2)
    has_l3 = bool(l3)
    if not (has_l1 or has_l2 or has_l3):
        return ""

    parts: list[str] = ["## 用户长期记忆（AI 参考）"]
    if has_l1:
        parts.append("须知：")
        parts.extend(f"- {item}" for item in l1)
    if has_l2:
        parts.append("历史对话要点：")
        parts.extend(f"- {item}" for item in l2)
    if has_l3:
        parts.append("长期统计：")
        for key, value in l3.items():
            parts.append(f"- {key}：{value}")
    return "\n".join(parts)
