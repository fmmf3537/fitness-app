"""训记动作全集变更：集合 diff、疑似改名候选、人工判定应用（ADR §8）。

比较解析后的名称集合（非文本行 diff）；疑似改名只产出候选、不自动继承。
"""
from __future__ import annotations

import difflib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExerciseMapping
from app.services.exercise_mapping import _write_audit
from app.services.exercise_mapping_batch import _load_movement_names
from app.services.exercise_mapping_candidates import _norm  # noqa: F401 — 按 ADR-P1-1 复用
from app.services.exercise_tokens import EQUIPMENT_TOKENS, MOVEMENT_TOKENS

RENAME_CANDIDATE_THRESHOLD = 0.5

_DELETE_NOTE = "训记已移除该动作（catalog_change）"
_VALID_ACTIONS = frozenset({"rename", "new", "delete"})


def _token_hits(name: str, tokens: dict[str, str]) -> set[str]:
    """长键优先抽取命中的中文词根键。"""
    remaining = name
    hits: set[str] = set()
    for zh in sorted(tokens.keys(), key=len, reverse=True):
        if zh and zh in remaining:
            hits.add(zh)
            remaining = remaining.replace(zh, "\0" * len(zh), 1)
    return hits


def _pair_reasons(old: str, new: str) -> list[str]:
    reasons: list[str] = []
    if _token_hits(old, MOVEMENT_TOKENS) & _token_hits(new, MOVEMENT_TOKENS):
        reasons.append("same_movement_token")
    if _token_hits(old, EQUIPMENT_TOKENS) & _token_hits(new, EQUIPMENT_TOKENS):
        reasons.append("same_equipment_token")
    return reasons


def _rename_candidates(removed: list[str], added: list[str]) -> list[dict[str, Any]]:
    """贪心配对：每个 removed / added 最多各出现一次，按 score 降序。"""
    scored: list[tuple[float, str, str, list[str]]] = []
    for old in removed:
        for new in added:
            score = difflib.SequenceMatcher(None, old, new).ratio()
            reasons = _pair_reasons(old, new)
            if score >= RENAME_CANDIDATE_THRESHOLD or reasons:
                scored.append((score, old, new, reasons))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))

    used_old: set[str] = set()
    used_new: set[str] = set()
    out: list[dict[str, Any]] = []
    for score, old, new, reasons in scored:
        if old in used_old or new in used_new:
            continue
        used_old.add(old)
        used_new.add(new)
        out.append(
            {
                "from": old,
                "to": new,
                "score": round(score, 6),
                "reasons": reasons,
            }
        )
    return out


def _current_db_names(session: Session) -> set[str]:
    """当前仍参与全集比较的映射名（已确认删除的 disabled 行排除，避免 CI 反复失败）。"""
    rows = session.scalars(
        select(ExerciseMapping.xunji_name).where(
            ExerciseMapping.status != "disabled"
        )
    ).all()
    return set(rows)


def _get_by_name(session: Session, name: str) -> ExerciseMapping | None:
    return session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.xunji_name == name)
    ).first()


def catalog_diff(session: Session, names: list[str] | None = None) -> dict:
    """比较「当前 JSON 动作全集」与「数据库映射行」，返回结构化差异。

    names 为 None 时从 app/data/xunji_movements.json 读取。
    """
    if names is None:
        names = _load_movement_names()
    json_names = set(names)
    db_names = _current_db_names(session)

    added = sorted(json_names - db_names)
    removed = sorted(db_names - json_names)
    unchanged = len(json_names & db_names)
    candidates = _rename_candidates(removed, added)

    return {
        "current_total": len(json_names),
        "db_total": len(db_names),
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
        "rename_candidates": candidates,
        "needs_confirmation": bool(added or removed),
    }


def apply_catalog_change(
    session: Session,
    *,
    action: str,
    old_name: str | None = None,
    new_name: str | None = None,
    actor: str = "user",
) -> dict:
    """应用人工判定。action ∈ {"rename", "new", "delete"}。"""
    if action not in _VALID_ACTIONS:
        raise ValueError(f"非法 action: {action!r}，期望 rename/new/delete")

    if action == "rename":
        return _apply_rename(session, old_name=old_name, new_name=new_name, actor=actor)
    if action == "new":
        return _apply_new(session, new_name=new_name, actor=actor)
    return _apply_delete(session, old_name=old_name, actor=actor)


def _apply_rename(
    session: Session,
    *,
    old_name: str | None,
    new_name: str | None,
    actor: str,
) -> dict:
    if not old_name or not new_name:
        raise ValueError("rename 需要 old_name 与 new_name")

    row = _get_by_name(session, old_name)
    if row is None:
        existing_new = _get_by_name(session, new_name)
        if existing_new is not None:
            return {
                "action": "rename",
                "xunji_name": new_name,
                "mapping_id": existing_new.id,
                "changed": False,
            }
        raise ValueError(f"改名源不存在: {old_name!r}")

    if old_name == new_name:
        return {
            "action": "rename",
            "xunji_name": new_name,
            "mapping_id": row.id,
            "changed": False,
        }

    conflict = _get_by_name(session, new_name)
    if conflict is not None:
        raise ValueError(f"改名目标已存在: {new_name!r}")

    before = {"xunji_name": row.xunji_name, "mapping_version": row.mapping_version}
    row.xunji_name = new_name
    row.mapping_version = int(row.mapping_version or 0) + 1
    after = {"xunji_name": row.xunji_name, "mapping_version": row.mapping_version}
    _write_audit(
        session,
        row,
        action="rename",
        before=before,
        after=after,
        reason="catalog_change",
        actor=actor,
    )
    session.commit()
    return {
        "action": "rename",
        "xunji_name": new_name,
        "mapping_id": row.id,
        "changed": True,
    }


def _apply_new(
    session: Session,
    *,
    new_name: str | None,
    actor: str,
) -> dict:
    if not new_name:
        raise ValueError("new 需要 new_name")

    existing = _get_by_name(session, new_name)
    if existing is not None:
        return {
            "action": "new",
            "xunji_name": new_name,
            "mapping_id": existing.id,
            "changed": False,
        }

    del actor  # new 不写审计；保留参数以统一 apply_catalog_change 签名
    row = ExerciseMapping(
        xunji_name=new_name,
        status="draft",
        relation=None,
        match_basis=None,
        unmapped_reason=None,
        confidence=None,
        verified_level=None,
        source="auto",
        mapping_version=1,
    )
    session.add(row)
    session.commit()
    return {
        "action": "new",
        "xunji_name": new_name,
        "mapping_id": row.id,
        "changed": True,
    }


def _apply_delete(
    session: Session,
    *,
    old_name: str | None,
    actor: str,
) -> dict:
    if not old_name:
        raise ValueError("delete 需要 old_name")

    row = _get_by_name(session, old_name)
    if row is None:
        raise ValueError(f"删除目标不存在: {old_name!r}")

    note = row.note or ""
    already = row.status == "disabled" and _DELETE_NOTE in note
    if already:
        return {
            "action": "delete",
            "xunji_name": old_name,
            "mapping_id": row.id,
            "changed": False,
        }

    before = {"status": row.status, "note": row.note}
    row.status = "disabled"
    if _DELETE_NOTE not in note:
        row.note = f"{note}\n{_DELETE_NOTE}".strip() if note else _DELETE_NOTE
    after = {"status": row.status, "note": row.note}
    _write_audit(
        session,
        row,
        action="delete",
        before=before,
        after=after,
        reason="catalog_change",
        actor=actor,
    )
    session.commit()
    return {
        "action": "delete",
        "xunji_name": old_name,
        "mapping_id": row.id,
        "changed": True,
    }
