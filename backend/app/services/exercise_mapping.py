"""训记→Garmin 动作映射：seed 与 DB 加载（查库在此，mapper 仍为纯函数）。"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any

from garminconnect import exercises as garmin_exercises
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ExerciseMapping,
    ExerciseMappingAudit,
    ExerciseMappingCandidate,
    GarminPlanSync,
)
from app.services.garmin_workout_mapper import EXERCISE_WHITELIST

# 内部哨兵：区分「显式传 None」与「未传该字段」
_UNSET: object = object()

_VALID_STATUSES = frozenset({"draft", "active", "disabled", "not_applicable"})
_VALID_WEIGHT_STRATEGIES = frozenset(
    {"total", "per_hand", "bodyweight", "assisted"}
)

# ADR §5.1：批量自动确认只接受语义精确的关系。
AUTO_CONFIRM_RELATIONS: frozenset[str] = frozenset({"EXACT"})
# ADR §5.1：目标有效性检查——verified_level 至少到达 catalog
_TARGET_VALID_LEVELS: frozenset[str] = frozenset({"catalog", "created", "displayed"})
NOTE_EQUIPMENT_MISMATCH_PREFIX = "器械不符"


class MappingValueError(ValueError):
    """带机器可读 code 的校验错误。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _infer_weight_strategy(xunji_name: str, display_name: str) -> str:
    """按器械名推断重量语义声明（本切片不做换算）。"""
    if "Dumbbell" in display_name or "哑铃" in xunji_name:
        return "per_hand"
    if any(token in xunji_name for token in ("卷腹", "转体", "平板")):
        return "bodyweight"
    return "total"


# 2026-11-12 人工复核 16 条 seed 时的结论备注（不进 EXERCISE_WHITELIST，
# 因为白名单条目结构只有 display_name/category/exerciseName/support_level）。
SEED_NOTES: dict[str, str] = {
    "器械推胸": "Garmin 无坐姿推胸机条目，用通用 Bench Press 表达（显示为分类名）",
    "侧平举": "2026-11-12 复核改为哑铃专用项；同日真机目视确认 Connect 显示「哑铃侧平举」",
}

# 视为「已端到端验收」的 support_level；其余只算目录级验证
_END_TO_END_SUPPORT_LEVELS = frozenset({"p0_verified", "p2_verified", "p3_verified"})


def build_seed_rows() -> list[dict[str, Any]]:
    """把 EXERCISE_WHITELIST 转成 exercise_mapping 行。

    `verified_level` 按 support_level 派生：
    - p0/p2/p3_verified → displayed（已端到端验收并目视确认）
    - 其它（如 catalog_verified）→ catalog（仅目录核对，待真机复验）
    """
    rows: list[dict[str, Any]] = []
    for xunji_name, item in EXERCISE_WHITELIST.items():
        display_name = item["display_name"]
        support_level = item["support_level"]
        note = f"seed from EXERCISE_WHITELIST, support_level={support_level}"
        extra = SEED_NOTES.get(xunji_name)
        if extra:
            note = f"{note}；{extra}"
        rows.append(
            {
                "xunji_name": xunji_name,
                "garmin_category": item["category"],
                "garmin_exercise_name": item["exerciseName"],
                "garmin_display_name": display_name,
                "weight_strategy": _infer_weight_strategy(xunji_name, display_name),
                "status": "active",
                "source": "seed",
                "verified_level": (
                    "displayed"
                    if support_level in _END_TO_END_SUPPORT_LEVELS
                    else "catalog"
                ),
                "mapping_version": 1,
                "note": note,
            }
        )
    return rows


SEED_MAPPINGS: list[dict[str, Any]] = build_seed_rows()


# 前端按 support_level 决定「已端到端验证 / 待远端验收」文案
# （GarminPlanPreviewModal.jsx:124 判断 p0_verified/p2_verified/p3_verified）。
# DB 侧存的是 verified_level（none/catalog/created/displayed），这里派生为 UI 语义：
# created/displayed = 已真实创建或已目视确认 → 端到端已验证
# 其余（none/catalog）→ 仅目录映射，待远端验收
_END_TO_END_VERIFIED = "p3_verified"
_PENDING_REMOTE = "user_confirmed_catalog_pending_end_to_end"


def _support_level_for(verified_level: str | None) -> str:
    """verified_level → 前端可读的 support_level（仅影响展示文案）。"""
    if (verified_level or "").lower() in {"created", "displayed"}:
        return _END_TO_END_VERIFIED
    return _PENDING_REMOTE


def _row_to_mapping_dict(row: ExerciseMapping) -> dict[str, Any]:
    return {
        "category": row.garmin_category,
        "exerciseName": row.garmin_exercise_name,
        "display_name": row.garmin_display_name,
        # mapper 的预览段会读 support_level（garmin_workout_mapper.py 预览组装）
        "support_level": _support_level_for(row.verified_level),
        "weight_strategy": row.weight_strategy,
        "status": row.status,
    }


def _whitelist_as_mappings() -> dict[str, dict[str, Any]]:
    """EXERCISE_WHITELIST 派生的等价字典，形状可直接喂给 map_plan_day。"""
    result: dict[str, dict[str, Any]] = {}
    for seed in SEED_MAPPINGS:
        result[seed["xunji_name"]] = {
            "category": seed["garmin_category"],
            "exerciseName": seed["garmin_exercise_name"],
            "display_name": seed["garmin_display_name"],
            # seed 的 16 条全部是 p0/p2/p3_verified（都已端到端验收），
            # 前端只判断是否属于这三者，故统一给等价常量即可。
            "support_level": _END_TO_END_VERIFIED,
            "weight_strategy": seed["weight_strategy"],
            "status": seed["status"],
        }
    return result


def seed_mappings(session: Session) -> dict[str, int]:
    """幂等写入 seed：按 xunji_name 已存在则跳过（不覆盖用户改过的行）。"""
    existing = {
        name
        for name in session.scalars(select(ExerciseMapping.xunji_name)).all()
    }
    inserted = 0
    skipped = 0
    for seed in build_seed_rows():
        if seed["xunji_name"] in existing:
            skipped += 1
            continue
        session.add(ExerciseMapping(**seed))
        inserted += 1
    session.commit()
    return {"inserted": inserted, "skipped": skipped}


def load_active_mappings(session: Session) -> dict[str, dict[str, Any]]:
    """返回 active 映射；表为空（未 seed）时回退 EXERCISE_WHITELIST 等价字典。"""
    total = session.scalar(select(func.count()).select_from(ExerciseMapping)) or 0
    if total == 0:
        return _whitelist_as_mappings()
    rows = session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.status == "active")
    ).all()
    return {row.xunji_name: _row_to_mapping_dict(row) for row in rows}


def load_all_mappings(
    session: Session, *, include_excluded: bool = False
) -> dict[str, dict[str, Any]]:
    """返回映射字典，形状同 load_active_mappings。

    参数：
    - include_excluded=False（默认，同步路径用）：不返回 status='not_applicable' 的行。
      同步路径在 ADR-P0-3 之前仍以「未知动作」处理它们，避免静默丢动作。
    - include_excluded=True（预览路径用）：**包含** not_applicable 行，
      由 mapper 显式判定为「正常排除」并进入 excluded 列表（ADR §4.2）。

    与 load_active_mappings 的区别：不过滤 draft/disabled，让 mapper 的 status 判定生效——
    draft 的行会产出 MAPPING_NOT_APPROVED（而不是 UNKNOWN_EXERCISE），
    前端据此显示「此动作映射尚未复核」的引导。
    空表时回退 EXERCISE_WHITELIST 等价字典（两种模式相同）。
    """
    total = session.scalar(select(func.count()).select_from(ExerciseMapping)) or 0
    if total == 0:
        return _whitelist_as_mappings()
    stmt = select(ExerciseMapping)
    if not include_excluded:
        stmt = stmt.where(ExerciseMapping.status != "not_applicable")
    rows = session.scalars(stmt).all()
    return {row.xunji_name: _row_to_mapping_dict(row) for row in rows}


def load_mapping_snapshot_hash(session: Session, xunji_names: list[str]) -> str:
    """对给定动作名集合的 active 映射做稳定 sha256 快照。

    缺失映射按 (name, None, None, None, 0) 参与哈希。
    """
    if not xunji_names:
        return hashlib.sha256(b"[]").hexdigest()

    rows = session.scalars(
        select(ExerciseMapping).where(
            ExerciseMapping.xunji_name.in_(xunji_names),
            ExerciseMapping.status == "active",
        )
    ).all()
    by_name = {row.xunji_name: row for row in rows}

    snapshot: list[list[Any]] = []
    for name in sorted(xunji_names):
        row = by_name.get(name)
        if row is None:
            snapshot.append([name, None, None, None, 0])
        else:
            snapshot.append(
                [
                    name,
                    row.garmin_category,
                    row.garmin_exercise_name,
                    row.weight_strategy,
                    row.mapping_version,
                ]
            )
    blob = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _pending_candidate_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(
            ExerciseMappingCandidate.xunji_name,
            func.count(),
        )
        .where(ExerciseMappingCandidate.status == "pending")
        .group_by(ExerciseMappingCandidate.xunji_name)
    ).all()
    return {name: int(count) for name, count in rows}


def _mapping_item_dict(
    row: ExerciseMapping,
    *,
    candidate_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "xunji_name": row.xunji_name,
        "garmin_category": row.garmin_category,
        "garmin_exercise_name": row.garmin_exercise_name,
        "garmin_display_name": row.garmin_display_name,
        "weight_strategy": row.weight_strategy,
        "status": row.status,
        "confidence": row.confidence,
        "source": row.source,
        "verified_level": row.verified_level,
        "mapping_version": row.mapping_version,
        "not_applicable_reason": row.not_applicable_reason,
        "note": row.note,
        "candidate_count": candidate_count,
    }


def _candidate_dict(row: ExerciseMappingCandidate) -> dict[str, Any]:
    return {
        "id": row.id,
        "xunji_name": row.xunji_name,
        "garmin_category": row.garmin_category,
        "garmin_exercise_name": row.garmin_exercise_name,
        "garmin_display_name": row.garmin_display_name,
        "confidence": row.confidence,
        "reason": row.reason,
        "rank": row.rank,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def _write_audit(
    session: Session,
    row: ExerciseMapping,
    *,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reason: str | None,
    actor: str,
) -> None:
    session.add(
        ExerciseMappingAudit(
            mapping_id=row.id,
            xunji_name=row.xunji_name,
            action=action,
            before_json=(
                json.dumps(before, ensure_ascii=False) if before is not None else None
            ),
            after_json=(
                json.dumps(after, ensure_ascii=False) if after is not None else None
            ),
            reason=reason,
            actor=actor,
        )
    )


def _catalog_pair_exists(category: str, exercise_name: str) -> bool:
    for entry in garmin_exercises.EXERCISES:
        if (
            entry.get("category") == category
            and entry.get("exercise", "") == exercise_name
        ):
            return True
    return False


def _validate_category(category: str | None) -> None:
    if category not in garmin_exercises.CATEGORIES:
        raise MappingValueError(
            "INVALID_CATEGORY",
            f"无效 garmin_category: {category!r}",
        )


def _validate_exercise_pair(category: str | None, exercise_name: str) -> None:
    # 空串是合法值：P2/P3 实测 Garmin 创建后会把通用 Bench Press 与 Lateral Raise
    # 的 exerciseName 规范化为空串（category 保留），Garmin 目录静态表里查不到这种组合，
    # 但用户在复核页需要能如实记录远端实际显示值。
    if exercise_name == "":
        if not category:
            raise MappingValueError(
                "INVALID_EXERCISE", "空 exerciseName 必须配合有效 category"
            )
        return
    if not category or not _catalog_pair_exists(category, exercise_name):
        raise MappingValueError(
            "INVALID_EXERCISE",
            f"目录中不存在组合 ({category!r}, {exercise_name!r})",
        )


def list_mappings(
    session: Session,
    *,
    status: str | None = None,
    confidence: str | None = None,
    verified_level: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """分页列表，按 status → confidence → xunji_name 排序。"""
    page = max(int(page or 1), 1)
    page_size = max(int(page_size or 1), 1)

    stmt = select(ExerciseMapping)
    if status is not None:
        stmt = stmt.where(ExerciseMapping.status == status)
    if confidence is not None:
        stmt = stmt.where(ExerciseMapping.confidence == confidence)
    if verified_level is not None:
        stmt = stmt.where(ExerciseMapping.verified_level == verified_level)
    if keyword:
        needle = f"%{keyword.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(ExerciseMapping.xunji_name).like(needle),
                func.lower(
                    func.coalesce(ExerciseMapping.garmin_display_name, "")
                ).like(needle),
            )
        )

    total = session.scalar(
        select(func.count()).select_from(stmt.subquery())
    ) or 0
    pages = int(math.ceil(total / page_size)) if page_size else 0

    status_order = case(
        (ExerciseMapping.status == "draft", 0),
        (ExerciseMapping.status == "active", 1),
        (ExerciseMapping.status == "disabled", 2),
        (ExerciseMapping.status == "not_applicable", 3),
        else_=9,
    )
    confidence_order = case(
        (ExerciseMapping.confidence == "high", 0),
        (ExerciseMapping.confidence == "medium", 1),
        (ExerciseMapping.confidence == "low", 2),
        else_=3,
    )
    rows = session.scalars(
        stmt.order_by(
            status_order,
            confidence_order,
            ExerciseMapping.xunji_name.asc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    counts = _pending_candidate_counts(session)
    items = [
        _mapping_item_dict(row, candidate_count=counts.get(row.xunji_name, 0))
        for row in rows
    ]
    return {
        "items": items,
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


def get_mapping_detail(session: Session, mapping_id: int) -> dict | None:
    """详情：mapping 全字段 + candidates（按 rank 升序，含 accepted/rejected）。"""
    row = session.get(ExerciseMapping, mapping_id)
    if row is None:
        return None
    candidates = session.scalars(
        select(ExerciseMappingCandidate)
        .where(ExerciseMappingCandidate.xunji_name == row.xunji_name)
        .order_by(
            ExerciseMappingCandidate.rank.asc(),
            ExerciseMappingCandidate.id.asc(),
        )
    ).all()
    return {
        "id": row.id,
        "xunji_name": row.xunji_name,
        "garmin_category": row.garmin_category,
        "garmin_exercise_name": row.garmin_exercise_name,
        "garmin_display_name": row.garmin_display_name,
        "weight_strategy": row.weight_strategy,
        "status": row.status,
        "not_applicable_reason": row.not_applicable_reason,
        "confidence": row.confidence,
        "source": row.source,
        "verified_level": row.verified_level,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "mapping_version": row.mapping_version,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "candidates": [_candidate_dict(c) for c in candidates],
    }


def update_mapping(
    session: Session,
    mapping_id: int,
    *,
    garmin_category: Any = _UNSET,
    garmin_exercise_name: Any = _UNSET,
    garmin_display_name: Any = _UNSET,
    weight_strategy: Any = _UNSET,
    status: Any = _UNSET,
    reason: str | None = None,
    actor: str = "user",
    _unset: object = _UNSET,
) -> dict | None:
    """部分更新 + 写审计 + mapping_version += 1。

    只更新显式传入的字段（用哨兵区分「传 None」与「不传」）。
    """
    del _unset  # 暴露哨兵形状供调用方对照；实际默认值用模块级 _UNSET
    row = session.get(ExerciseMapping, mapping_id)
    if row is None:
        return None

    updates: dict[str, Any] = {}
    if garmin_category is not _UNSET:
        _validate_category(garmin_category)
        updates["garmin_category"] = garmin_category
    if garmin_exercise_name is not _UNSET:
        if not isinstance(garmin_exercise_name, str):
            raise MappingValueError(
                "INVALID_EXERCISE",
                f"无效 garmin_exercise_name: {garmin_exercise_name!r}",
            )
        effective_category = (
            updates["garmin_category"]
            if "garmin_category" in updates
            else row.garmin_category
        )
        _validate_exercise_pair(effective_category, garmin_exercise_name)
        updates["garmin_exercise_name"] = garmin_exercise_name
    if garmin_display_name is not _UNSET:
        updates["garmin_display_name"] = garmin_display_name
    if weight_strategy is not _UNSET:
        if weight_strategy not in _VALID_WEIGHT_STRATEGIES:
            raise MappingValueError(
                "INVALID_WEIGHT_STRATEGY",
                f"无效 weight_strategy: {weight_strategy!r}",
            )
        updates["weight_strategy"] = weight_strategy
    if status is not _UNSET:
        if status not in _VALID_STATUSES:
            raise MappingValueError(
                "INVALID_STATUS",
                f"无效 status: {status!r}",
            )
        updates["status"] = status

    if not updates:
        return _mapping_item_dict(
            row,
            candidate_count=_pending_candidate_counts(session).get(row.xunji_name, 0),
        )

    # ADR §9：Garmin 目标变化后不得继承旧目标的验证等级。
    target_changed = (
        ("garmin_category" in updates
         and updates["garmin_category"] != row.garmin_category)
        or ("garmin_exercise_name" in updates
            and updates["garmin_exercise_name"] != row.garmin_exercise_name)
    )

    before_keys = set(updates)
    if target_changed:
        before_keys.update({"verified_level", "verified_at"})
        if "status" not in before_keys:
            before_keys.add("status")

    def _audit_value(key: str) -> Any:
        value = getattr(row, key)
        if key == "verified_at" and value is not None:
            return value.isoformat()
        return value

    before = {key: _audit_value(key) for key in before_keys}
    for key, value in updates.items():
        setattr(row, key, value)
    row.mapping_version = int(row.mapping_version or 0) + 1

    if target_changed:
        previous_level = row.verified_level
        previous_at = row.verified_at
        # 目标有效性依据**新的** category/exercise 判断
        target_valid = bool(row.garmin_category) and _catalog_pair_exists(
            row.garmin_category, row.garmin_exercise_name or ""
        )
        row.verified_level = "catalog" if target_valid else "none"
        row.verified_at = None
        # ADR §9 第 3 条：目标无效时不得保持 active
        if not target_valid and row.status == "active":
            row.status = "draft"
        audit_extra = {
            "previous_verified_level": previous_level,
            "previous_verified_at": (
                previous_at.isoformat() if previous_at else None
            ),
            "target_valid": target_valid,
        }
    else:
        audit_extra = {}

    after = {key: _audit_value(key) for key in before_keys}
    after.update(audit_extra)
    _write_audit(
        session,
        row,
        action="update",
        before=before,
        after=after,
        reason=reason,
        actor=actor,
    )
    session.commit()
    session.refresh(row)
    return _mapping_item_dict(
        row,
        candidate_count=_pending_candidate_counts(session).get(row.xunji_name, 0),
    )


def activate_mapping(
    session: Session,
    mapping_id: int,
    *,
    reason: str | None = None,
    actor: str = "user",
) -> dict | None:
    """采纳为 active。garmin_category 不能为空。"""
    row = session.get(ExerciseMapping, mapping_id)
    if row is None:
        return None
    if not row.garmin_category:
        raise MappingValueError(
            "MISSING_CATEGORY",
            "采纳前必须设置 garmin_category",
        )
    before = {"status": row.status}
    row.status = "active"
    row.mapping_version = int(row.mapping_version or 0) + 1
    row.decision_source = "human"
    after = {"status": row.status}
    _write_audit(
        session,
        row,
        action="activate",
        before=before,
        after=after,
        reason=reason,
        actor=actor,
    )
    session.commit()
    session.refresh(row)
    return _mapping_item_dict(
        row,
        candidate_count=_pending_candidate_counts(session).get(row.xunji_name, 0),
    )


def disable_mapping(
    session: Session,
    mapping_id: int,
    *,
    reason: str | None = None,
    actor: str = "user",
) -> dict | None:
    """停用。写审计 action='disable'，mapping_version += 1。"""
    row = session.get(ExerciseMapping, mapping_id)
    if row is None:
        return None
    before = {"status": row.status}
    row.status = "disabled"
    row.mapping_version = int(row.mapping_version or 0) + 1
    after = {"status": row.status}
    _write_audit(
        session,
        row,
        action="disable",
        before=before,
        after=after,
        reason=reason,
        actor=actor,
    )
    session.commit()
    session.refresh(row)
    return _mapping_item_dict(
        row,
        candidate_count=_pending_candidate_counts(session).get(row.xunji_name, 0),
    )


def accept_candidate(
    session: Session,
    mapping_id: int,
    candidate_id: int,
    *,
    weight_strategy: str | None = None,
    reason: str | None = None,
    actor: str = "user",
) -> dict | None:
    """采纳指定候选：写入 mapping、置 active，并拒绝同动作其他 pending 候选。"""
    row = session.get(ExerciseMapping, mapping_id)
    if row is None:
        return None
    candidate = session.get(ExerciseMappingCandidate, candidate_id)
    if candidate is None or candidate.xunji_name != row.xunji_name:
        return None

    _validate_category(candidate.garmin_category)
    exercise_name = candidate.garmin_exercise_name or ""
    _validate_exercise_pair(candidate.garmin_category, exercise_name)
    if weight_strategy is not None and weight_strategy not in _VALID_WEIGHT_STRATEGIES:
        raise MappingValueError(
            "INVALID_WEIGHT_STRATEGY",
            f"无效 weight_strategy: {weight_strategy!r}",
        )

    before = {
        "garmin_category": row.garmin_category,
        "garmin_exercise_name": row.garmin_exercise_name,
        "garmin_display_name": row.garmin_display_name,
        "weight_strategy": row.weight_strategy,
        "status": row.status,
    }
    row.garmin_category = candidate.garmin_category
    row.garmin_exercise_name = exercise_name
    row.garmin_display_name = candidate.garmin_display_name
    if weight_strategy is not None:
        row.weight_strategy = weight_strategy
    row.status = "active"
    row.mapping_version = int(row.mapping_version or 0) + 1
    after = {
        "garmin_category": row.garmin_category,
        "garmin_exercise_name": row.garmin_exercise_name,
        "garmin_display_name": row.garmin_display_name,
        "weight_strategy": row.weight_strategy,
        "status": row.status,
    }

    now = datetime.now()
    candidate.status = "accepted"
    candidate.resolved_at = now
    siblings = session.scalars(
        select(ExerciseMappingCandidate).where(
            ExerciseMappingCandidate.xunji_name == row.xunji_name,
            ExerciseMappingCandidate.id != candidate.id,
            ExerciseMappingCandidate.status == "pending",
        )
    ).all()
    for sibling in siblings:
        sibling.status = "rejected"
        sibling.resolved_at = now

    _write_audit(
        session,
        row,
        action="activate",
        before=before,
        after=after,
        reason=reason,
        actor=actor,
    )
    session.commit()
    session.refresh(row)
    return _mapping_item_dict(
        row,
        candidate_count=_pending_candidate_counts(session).get(row.xunji_name, 0),
    )


def batch_activate(
    session: Session,
    *,
    confidence: str = "high",
    only_confirmed_catalog: bool = True,
    actor: str = "user",
) -> dict:
    """按 ADR §5.1 批量启用：仅 EXACT + high + 目标有效 + 无器械不符。

    返回 activated / skipped / skipped_reasons / relation_breakdown。
    不修改 relation / match_basis / confidence / verified_level。
    """
    rows = session.scalars(
        select(ExerciseMapping).where(
            ExerciseMapping.status == "draft",
            ExerciseMapping.confidence == confidence,
            ExerciseMapping.garmin_category.is_not(None),
        )
    ).all()

    activated = 0
    skipped_reasons = {
        "relation_not_exact": 0,
        "relation_missing": 0,
        "target_unverified": 0,
        "equipment_mismatch": 0,
        "catalog_missing": 0,
    }
    relation_breakdown: dict[str, int] = {}

    for row in rows:
        rel_key = row.relation if row.relation is not None else "null"
        relation_breakdown[rel_key] = relation_breakdown.get(rel_key, 0) + 1

        exercise_name = row.garmin_exercise_name
        if not exercise_name:
            skipped_reasons["catalog_missing"] += 1
            continue

        if row.relation is None:
            skipped_reasons["relation_missing"] += 1
            continue
        if row.relation not in AUTO_CONFIRM_RELATIONS:
            skipped_reasons["relation_not_exact"] += 1
            continue

        if row.verified_level not in _TARGET_VALID_LEVELS:
            skipped_reasons["target_unverified"] += 1
            continue

        if (row.note or "").startswith(NOTE_EQUIPMENT_MISMATCH_PREFIX):
            skipped_reasons["equipment_mismatch"] += 1
            continue

        if only_confirmed_catalog and not _catalog_pair_exists(
            row.garmin_category or "", exercise_name
        ):
            skipped_reasons["catalog_missing"] += 1
            continue

        before = {"status": row.status}
        row.status = "active"
        row.mapping_version = int(row.mapping_version or 0) + 1
        row.decision_source = "rule"
        after = {"status": row.status}
        _write_audit(
            session,
            row,
            action="activate",
            before=before,
            after=after,
            reason="batch_activate",
            actor=actor,
        )
        activated += 1

    session.commit()
    skipped = sum(skipped_reasons.values())
    return {
        "activated": activated,
        "skipped": skipped,
        "skipped_reasons": skipped_reasons,
        "relation_breakdown": relation_breakdown,
    }


def batch_reset_to_draft(
    session: Session, *, actor: str = "user"
) -> dict:
    """把「算法批量激活」的行退回 draft，便于用修复后的算法重算。

    只处理：status='active' 且 source != 'seed' 且 mapping_version > 1
    （即 V6-4 batch_activate 激活过的行；16 条人工验收的 seed 永不回退）。
    不改 garmin_category / garmin_exercise_name / configured 字段，只改 status 并写审计
    （action='reset'、reason='batch_reset'、before/after 含 status，
    `mapping_version` **不再增加**——回退不改变映射内容）。

    返回 {"reset": n, "skipped": m}；skipped 统计被排除的 active 行数
    （seed 或 version==1 的人工行）。
    """
    rows = session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.status == "active")
    ).all()

    reset = 0
    skipped = 0
    for row in rows:
        if row.source == "seed" or int(row.mapping_version or 0) <= 1:
            skipped += 1
            continue
        before = {"status": row.status}
        row.status = "draft"
        after = {"status": row.status}
        _write_audit(
            session,
            row,
            action="reset",
            before=before,
            after=after,
            reason="batch_reset",
            actor=actor,
        )
        reset += 1

    session.commit()
    return {"reset": reset, "skipped": skipped}


def search_catalog(
    *,
    q: str = "",
    category: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """在 Garmin 离线目录里搜索，返回 [{"category","exercise","name"}]。"""
    capped = min(max(int(limit or 0), 0), 100)
    term = (q or "").strip()
    if term:
        rows = list(garmin_exercises.find(term))
    else:
        rows = list(garmin_exercises.EXERCISES)
    if category:
        rows = [r for r in rows if r.get("category") == category]
    return [
        {
            "category": r.get("category", ""),
            "exercise": r.get("exercise", ""),
            "name": r.get("name", ""),
        }
        for r in rows[:capped]
    ]


def search_by_xunji_name(
    q: str,
    *,
    limit: int = 20,
    candidates_per_movement: int = 2,
) -> list[dict]:
    """按中文（或任意）片段匹配训记动作名，再给出各自的 Garmin 候选。

    做的是「子串匹配训记动作名 → 复用 generate_candidates」，
    不新增任何打分逻辑。

    返回（按匹配质量排序，长度越接近 q 越靠前）：
    [
      {"xunji_name": "上斜哑铃卧推", "match_rank": 0,
       "category": "BENCH_PRESS", "exercise": "INCLINE_DUMBBELL_BENCH_PRESS",
       "name": "Incline Dumbbell Bench Press",
       "confidence": "high", "rank": 1, "reason": "..."},
      ...
    ]

    规则：
    - q 去空白后为空 → 返回 []
    - 只在 `_load_movement_names()` 的全集里做**子串**匹配（大小写不敏感，
      直接 str 包含即可；中文不需要 casefold）
    - 匹配到的动作按「长度升序」排序（短名更可能是用户想精确找的那个），
      再按名字排序保证稳定
    - 每个动作最多取 `candidates_per_movement` 条候选（默认 2）
    - 候选为空的动作**跳过**（不回空行）
    - 总条数不超过 `limit`
    - 没有任何匹配 → []
    """
    from app.services.exercise_mapping_batch import _load_movement_names
    from app.services.exercise_mapping_candidates import generate_candidates

    term = (q or "").strip()
    if not term:
        return []

    capped = max(int(limit or 0), 0)
    per_move = max(int(candidates_per_movement or 0), 0)
    if capped == 0 or per_move == 0:
        return []

    needle = term.casefold()
    matched = [
        name
        for name in _load_movement_names()
        if needle in name.casefold()
    ]
    matched.sort(key=lambda n: (len(n), n))

    items: list[dict] = []
    for match_rank, xunji_name in enumerate(matched):
        if len(items) >= capped:
            break
        cands = generate_candidates(xunji_name, limit=per_move)
        if not cands:
            continue
        for cand in cands:
            if len(items) >= capped:
                break
            items.append(
                {
                    "xunji_name": xunji_name,
                    "match_rank": match_rank,
                    "category": cand.garmin_category,
                    "exercise": cand.garmin_exercise_name,
                    "name": cand.garmin_display_name,
                    "confidence": cand.confidence,
                    "rank": cand.rank,
                    "reason": cand.reason,
                }
            )
    return items


def _extract_xunji_names_from_payload(payload_json: str | None) -> list[str] | None:
    """从本地 Workout payload 的 step.description 提取训记动作名。

    description 形如 ``哑铃卧推｜源组 1-3``；解析失败返回 None（调用方跳过）。
    """
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    segments = payload.get("workoutSegments") or []
    if not segments or not isinstance(segments, list):
        return None

    names: list[str] = []

    def _walk(steps: Any) -> None:
        if not isinstance(steps, list):
            return
        for step in steps:
            if not isinstance(step, dict):
                continue
            desc = step.get("description")
            if isinstance(desc, str) and "｜" in desc:
                name = desc.split("｜", 1)[0].strip()
                if name:
                    names.append(name)
            children = step.get("workoutSteps")
            if children:
                _walk(children)

    first = segments[0] if segments else None
    if not isinstance(first, dict):
        return None
    _walk(first.get("workoutSteps") or [])
    if not names:
        return None
    # 去重且保序
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def list_stale_syncs(session: Session, *, limit: int = 50) -> list[dict]:
    """找出「已同步但映射已变」的记录。"""
    capped = max(int(limit or 0), 0)
    records = session.scalars(
        select(GarminPlanSync)
        .where(
            GarminPlanSync.status == "synced",
            GarminPlanSync.mapping_hash.is_not(None),
        )
        .order_by(GarminPlanSync.id.desc())
    ).all()

    stale: list[dict] = []
    for record in records:
        if len(stale) >= capped:
            break
        names = _extract_xunji_names_from_payload(record.payload_json)
        if not names:
            continue
        current_hash = load_mapping_snapshot_hash(session, names)
        stored = record.mapping_hash
        if not stored or stored == current_hash:
            continue
        stale.append(
            {
                "sync_id": record.id,
                "plan_ref": record.plan_ref,
                "training_date": (
                    record.training_date.isoformat()
                    if record.training_date
                    else None
                ),
                "workout_id": record.workout_id,
                "workout_schedule_id": record.workout_schedule_id,
                "stored_hash": stored,
                "current_hash": current_hash,
            }
        )
    return stale
