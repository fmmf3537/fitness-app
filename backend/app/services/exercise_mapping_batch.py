"""批量把候选生成结果落库；不访问网络（候选用离线目录）、不调 LLM。

对 xunji_movements.json 全量动作一次性写入 exercise_mapping（status=draft /
not_applicable）与 exercise_mapping_candidate；提供覆盖率看板只读统计。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import ExerciseMapping, ExerciseMappingCandidate
from app.services.exercise_mapping import seed_mappings
from app.services.exercise_mapping_candidates import (
    Candidate,
    classify_applicability,
    equipment_mismatch_note,
    generate_candidates,
)

_MOVEMENTS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "xunji_movements.json"
)

_NOTE_NOT_APPLICABLE = "非力量动作，不参与 Garmin 力量训练写入"
_NOTE_NO_CANDIDATE = "无自动候选，需人工指定或 LLM 兜底"

_SKIP_STATUSES = frozenset({"active", "disabled"})
_REFRESHABLE_STATUSES = frozenset({"draft", "not_applicable"})


def _is_protected(row: ExerciseMapping) -> bool:
    """该 draft 行是否应被刷新跳过（人工改过 或 由 LLM 填充）。"""
    return bool(row.mapping_version and row.mapping_version > 1) or row.source == "llm"


def _load_movement_names() -> list[str]:
    with open(_MOVEMENTS_PATH, encoding="utf-8") as f:
        names = json.load(f)
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ValueError(f"动作名表格式非法: {_MOVEMENTS_PATH}")
    return list(names)


def _infer_weight_strategy(xunji_name: str) -> str:
    """按器械/动作名推断重量语义声明（本切片不做换算）。"""
    if "哑铃" in xunji_name:
        return "per_hand"
    if any(token in xunji_name for token in ("卷腹", "转体", "平板", "支撑")):
        return "bodyweight"
    return "total"


def _pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator * 100.0 / denominator, 1)


def _apply_not_applicable(row: ExerciseMapping, reason: str | None) -> None:
    row.status = "not_applicable"
    row.not_applicable_reason = reason
    row.garmin_category = None
    row.garmin_exercise_name = None
    row.garmin_display_name = None
    row.weight_strategy = None
    row.confidence = None
    row.note = _NOTE_NOT_APPLICABLE


def _apply_candidates(row: ExerciseMapping, name: str, cands: list[Candidate]) -> None:
    row.status = "draft"
    row.not_applicable_reason = None
    if cands:
        top = cands[0]
        row.garmin_category = top.garmin_category
        row.garmin_exercise_name = top.garmin_exercise_name
        row.garmin_display_name = top.garmin_display_name
        row.confidence = top.confidence
        row.weight_strategy = _infer_weight_strategy(name)
        row.note = equipment_mismatch_note(name, top.garmin_display_name)
    else:
        row.garmin_category = None
        row.garmin_exercise_name = None
        row.garmin_display_name = None
        row.confidence = None
        row.weight_strategy = None
        row.note = _NOTE_NO_CANDIDATE


def _candidate_rows(name: str, cands: list[Candidate]) -> list[ExerciseMappingCandidate]:
    return [
        ExerciseMappingCandidate(
            xunji_name=name,
            garmin_category=c.garmin_category,
            garmin_exercise_name=c.garmin_exercise_name,
            garmin_display_name=c.garmin_display_name,
            confidence=c.confidence,
            reason=c.reason,
            rank=c.rank,
            status="pending",
        )
        for c in cands
    ]


def generate_all(
    session: Session,
    *,
    refresh_drafts: bool = False,
    force_refresh: bool = False,
) -> dict[str, int]:
    """对全部 1091 个训记动作批量生成映射并落库。幂等。

    返回统计字典，至少包含这些键：
        total             处理过的动作总数（== 1091）
        inserted          新建的 exercise_mapping 行数
        refreshed         被重算的 draft 行数（仅 refresh_drafts=True）
        skipped_active    因已是 active/disabled 而跳过的行数
        skipped_protected 因手改/LLM 受保护而跳过的 draft 行数
                          （仅 refresh_drafts=True 且非 force_refresh）
        not_applicable    标为 not_applicable 的行数
        with_candidate    至少写入 1 个候选的动作数
        no_candidate      无任何候选的动作数
        candidates        写入 exercise_mapping_candidate 的行数
        seeded            本次新写入的 seed 行数
    """
    names = _load_movement_names()

    # 先确保 V6-1 的 16 条已验收映射存在且为 active，否则批处理会把它们建成 draft，
    # 导致「已端到端验证」的动作退回待复核、现有 Garmin 写入功能退化。
    # seed_mappings 幂等（同名行跳过、不覆盖用户改动），且必须在读取 existing 之前
    # 执行——否则 existing 快照不含 seed 行，后面会重复插入撞唯一约束。
    seeded = seed_mappings(session).get("inserted", 0)

    existing = {
        row.xunji_name: row
        for row in session.scalars(select(ExerciseMapping)).all()
    }

    stats = {
        "total": len(names),
        "inserted": 0,
        "refreshed": 0,
        "skipped_active": 0,
        "skipped_protected": 0,
        "not_applicable": 0,
        "with_candidate": 0,
        "no_candidate": 0,
        "candidates": 0,
        "seeded": seeded,
    }

    to_write: list[tuple[str, list[Candidate]]] = []
    new_mappings: list[ExerciseMapping] = []

    for name in names:
        row = existing.get(name)

        if row is None:
            applicable, reason = classify_applicability(name)
            mapping = ExerciseMapping(
                xunji_name=name,
                source="auto",
                verified_level="none",
                mapping_version=1,
            )
            if not applicable:
                _apply_not_applicable(mapping, reason)
                cands: list[Candidate] = []
                stats["not_applicable"] += 1
            else:
                cands = generate_candidates(name, limit=3)
                _apply_candidates(mapping, name, cands)
                if cands:
                    stats["with_candidate"] += 1
                else:
                    stats["no_candidate"] += 1
            new_mappings.append(mapping)
            to_write.append((name, cands))
            stats["inserted"] += 1
            continue

        if row.status in _SKIP_STATUSES:
            stats["skipped_active"] += 1
            continue

        if row.status in _REFRESHABLE_STATUSES and not refresh_drafts:
            continue

        if (
            row.status in _REFRESHABLE_STATUSES
            and refresh_drafts
            and not force_refresh
            and _is_protected(row)
        ):
            stats["skipped_protected"] += 1
            continue

        if row.status in _REFRESHABLE_STATUSES and refresh_drafts:
            applicable, reason = classify_applicability(name)
            if not applicable:
                _apply_not_applicable(row, reason)
                cands = []
                stats["not_applicable"] += 1
            else:
                cands = generate_candidates(name, limit=3)
                _apply_candidates(row, name, cands)
                if cands:
                    stats["with_candidate"] += 1
                else:
                    stats["no_candidate"] += 1
            to_write.append((name, cands))
            stats["refreshed"] += 1
            continue

        # 未知 status：保守跳过，避免覆盖
        stats["skipped_active"] += 1

    if new_mappings:
        session.add_all(new_mappings)

    if to_write:
        write_names = [n for n, _ in to_write]
        session.execute(
            delete(ExerciseMappingCandidate).where(
                ExerciseMappingCandidate.xunji_name.in_(write_names),
                ExerciseMappingCandidate.status == "pending",
            )
        )
        cand_objs: list[ExerciseMappingCandidate] = []
        for name, cands in to_write:
            if not cands:
                continue
            cand_objs.extend(_candidate_rows(name, cands))
        if cand_objs:
            session.add_all(cand_objs)
            stats["candidates"] = len(cand_objs)

    session.commit()
    return stats


def coverage_stats(session: Session) -> dict[str, Any]:
    """覆盖率看板数据（只读）。"""
    names = _load_movement_names()
    total = len(names)

    rows = list(session.scalars(select(ExerciseMapping)).all())
    db_count = len(rows)

    by_status = {
        "draft": 0,
        "active": 0,
        "disabled": 0,
        "not_applicable": 0,
        "missing": max(0, total - db_count),
    }
    by_confidence = {
        "high": 0,
        "medium": 0,
        "low": 0,
        "none": 0,
        "not_applicable": 0,
    }
    by_verified_level = {
        "none": 0,
        "catalog": 0,
        "created": 0,
        "displayed": 0,
    }

    with_candidate = 0
    high = 0

    for row in rows:
        status = row.status or "draft"
        if status in by_status and status != "missing":
            by_status[status] += 1

        if status == "not_applicable":
            by_confidence["not_applicable"] += 1
        elif row.confidence in ("high", "medium", "low"):
            by_confidence[row.confidence] += 1
            if row.confidence == "high":
                high += 1
        else:
            by_confidence["none"] += 1

        level = row.verified_level or "none"
        if level in by_verified_level:
            by_verified_level[level] += 1
        else:
            by_verified_level["none"] += 1

        if row.garmin_category is not None:
            with_candidate += 1

    strength_total = 0
    for name in names:
        applicable, _ = classify_applicability(name)
        if applicable:
            strength_total += 1

    # 力量类且已有主推候选：garmin_category 非空（not_applicable 不会有）
    strength_with_candidate = with_candidate

    return {
        "total": total,
        "by_status": by_status,
        "by_confidence": by_confidence,
        "by_verified_level": by_verified_level,
        "coverage": {
            "with_candidate": with_candidate,
            "with_candidate_pct": _pct(with_candidate, total),
            "high": high,
            "high_pct": _pct(high, total),
            "strength_total": strength_total,
            "strength_with_candidate": strength_with_candidate,
            "strength_with_candidate_pct": _pct(
                strength_with_candidate, strength_total
            ),
        },
    }
