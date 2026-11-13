"""ADR-P0-1：exercise_mapping.relation / match_basis / unmapped_reason 分类与回填。

把「映射成什么」与「这个决定有多可靠」拆开（ADR §4.1）。
回填幂等：只处理 relation IS NULL 的行，不覆盖人工已设值，
也不改动 status / confidence / mapping_version / verified_level。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExerciseMapping
from app.services.exercise_mapping import (
    _TARGET_VALID_LEVELS,
    _catalog_pair_exists,
    _write_audit,
)
from app.services.exercise_mapping_candidates import (
    _norm,
    _qualifier_penalty,
    equipment_mismatch_note,
    extract_tokens,
)

RELATION_EXACT = "EXACT"
RELATION_SIMILAR = "SIMILAR"
RELATION_CATEGORY = "CATEGORY"
RELATION_UNMAPPED = "UNMAPPED"
RELATIONS = (RELATION_EXACT, RELATION_SIMILAR, RELATION_CATEGORY, RELATION_UNMAPPED)

DECISION_RULE = "rule"
DECISION_HUMAN = "human"
DECISION_HUMAN_POLICY = "human_policy"

# ADR §10.1：B 策略只适用于本次存量迁移，后续新增的 SIMILAR 不得援引。
B_POLICY_NOTE = "继承旧规则的批量使用政策（human_policy），非逐条人工语义确认"

MATCH_BASIS_VALUES = (
    "same_name",
    "alias",
    "translation",
    "semantic_review",
    "rule_features",
    "other",
)

UNMAPPED_REASON_VALUES = (
    "no_equivalent",
    "no_safe_category",
    "ambiguous",
    "other",
)

# 人工确认过、但目标只是大类通用条目的 seed（ADR §4.1：手工结论优先于机械判据）
SEED_GENERIC_TARGETS: dict[str, str] = {
    "器械推胸": "Garmin 无坐姿推胸机条目，用通用 Bench Press 表达（大类映射）",
}


def classify_relation(row: Any) -> tuple[str | None, str | None, str | None]:
    """返回 (relation, match_basis, unmapped_reason)。

    判定顺序（严格按此实现，不要自行调整）：

    1. status == "not_applicable"
       → (None, None, None)
       这些是产品定义上不写入力量 Workout 的动作（拉伸/有氧），**不是 UNMAPPED**，
       不参与 relation 分类（ADR §4.2）。

    2. garmin_exercise_name 为空
       → (UNMAPPED, None, "no_equivalent")

    3. source == "seed"（16 条人工确认）
       → name in SEED_GENERIC_TARGETS 时 (CATEGORY, "semantic_review", None)
       → 否则 (EXACT, "semantic_review", None)

    4. garmin_exercise_name == garmin_category（目标就是大类通用条目）
       → (CATEGORY, <按 6 的规则>, None)

    5. source 或人工来源（source == "manual"）
       → (EXACT, "semantic_review", None)

    6. 其余（auto/llm 生成的自动映射）按 ADR §10.1 判据：
       tokens = extract_tokens(name)
       postures = [p for p in tokens["postures"] if p]
       display_norm = _norm(garmin_display_name or "")
       posture_mismatch = bool(postures) and any(
           _norm(p) not in display_norm for p in postures
       )
       is_similar = (
           equipment_mismatch_note(name, garmin_display_name) is not None
           or _qualifier_penalty(name, display_norm) < 0
           or posture_mismatch
       )
       → (SIMILAR if is_similar else EXACT, "rule_features", None)
    """
    status = getattr(row, "status", None)
    if status == "not_applicable":
        return (None, None, None)

    garmin_exercise_name = getattr(row, "garmin_exercise_name", None)
    if not garmin_exercise_name:
        return (RELATION_UNMAPPED, None, "no_equivalent")

    source = getattr(row, "source", None)
    name = getattr(row, "xunji_name", None) or ""
    garmin_category = getattr(row, "garmin_category", None)
    garmin_display_name = getattr(row, "garmin_display_name", None)

    if source == "seed":
        if name in SEED_GENERIC_TARGETS:
            return (RELATION_CATEGORY, "semantic_review", None)
        return (RELATION_EXACT, "semantic_review", None)

    # 步骤 4：大类通用条目；match_basis 按步骤 6 固定为 rule_features
    if garmin_exercise_name == garmin_category:
        return (RELATION_CATEGORY, "rule_features", None)

    if source == "manual":
        return (RELATION_EXACT, "semantic_review", None)

    tokens = extract_tokens(name)
    postures = [p for p in tokens["postures"] if p]
    display_norm = _norm(garmin_display_name or "")
    posture_mismatch = bool(postures) and any(
        _norm(p) not in display_norm for p in postures
    )
    is_similar = (
        equipment_mismatch_note(name, garmin_display_name) is not None
        or _qualifier_penalty(name, display_norm) < 0
        or posture_mismatch
    )
    relation = RELATION_SIMILAR if is_similar else RELATION_EXACT
    return (relation, "rule_features", None)


def backfill_relations(session: Session) -> dict:
    """为 relation 为空的行回填分类。幂等，只处理 relation IS NULL 的行。

    不覆盖人工已设置的值（ADR §10.1 补充约定）。
    返回结构化报告，供迁移与验收核对。
    """
    rows = list(
        session.scalars(
            select(ExerciseMapping).where(ExerciseMapping.relation.is_(None))
        ).all()
    )

    scanned = len(rows)
    updated = 0
    skipped_not_applicable = 0
    by_relation: dict[str, int] = {
        RELATION_EXACT: 0,
        RELATION_SIMILAR: 0,
        RELATION_CATEGORY: 0,
        RELATION_UNMAPPED: 0,
    }
    by_status: dict[str, int] = {"active": 0, "draft": 0, "disabled": 0}
    active_similar: list[dict] = []

    for row in rows:
        relation, match_basis, unmapped_reason = classify_relation(row)
        if relation is None:
            skipped_not_applicable += 1
            continue

        row.relation = relation
        row.match_basis = match_basis
        row.unmapped_reason = unmapped_reason
        updated += 1
        by_relation[relation] = by_relation.get(relation, 0) + 1

        status = row.status
        if status in by_status:
            by_status[status] += 1

        if (
            status == "active"
            and relation == RELATION_SIMILAR
            and len(active_similar) < 100
        ):
            active_similar.append(
                {
                    "xunji_name": row.xunji_name,
                    "garmin_display_name": row.garmin_display_name,
                    "has_equipment_note": equipment_mismatch_note(
                        row.xunji_name, row.garmin_display_name
                    )
                    is not None,
                }
            )

    if updated:
        session.commit()

    return {
        "scanned": scanned,
        "updated": updated,
        "skipped_not_applicable": skipped_not_applicable,
        "by_relation": by_relation,
        "by_status": by_status,
        "active_similar": active_similar,
        "changed_values": [],
    }


def _append_b_policy_note(note: str | None) -> str:
    """在 note 末尾追加 B_POLICY_NOTE；已包含则原样返回（幂等）。"""
    if note and B_POLICY_NOTE in note:
        return note
    if note:
        return f"{note}；{B_POLICY_NOTE}"
    return B_POLICY_NOTE


def _invalid_target_reason(row: ExerciseMapping) -> str | None:
    """目标无效时返回 reason；有效则返回 None。优先 target_unverified。"""
    if row.verified_level not in _TARGET_VALID_LEVELS:
        return "target_unverified"
    if not _catalog_pair_exists(
        row.garmin_category or "", row.garmin_exercise_name or ""
    ):
        return "catalog_missing"
    return None


def migrate_existing_active(session: Session) -> dict:
    """ADR §10.1：把 B 策略应用到存量 active 记录，并返回迁移报告。

    步骤（严格按序）：
    1. 先确保 relation 已回填（复用 backfill_relations，幂等）。
    2. 遍历 status='active' 的行：
       a. relation == SIMILAR 且 decision_source 为空 → decision_source='human_policy'，
          保持 active，并在 note 末尾追加 B_POLICY_NOTE（若尚未包含）。
          **不得**修改 status / mapping_version / relation / verified_level。
       b. Garmin 目标无效（verified_level 不在 _TARGET_VALID_LEVELS，
          或 _catalog_pair_exists 为 False）→ status='draft'，mapping_version += 1，
          写审计 action='migrate_exit_active'，并在报告里登记明细。
       c. relation == EXACT / CATEGORY → 保持原样（保留原有来源与验证信息）。
    3. 提交并按 §10.2 返回报告。
    """
    backfill = backfill_relations(session)

    active_rows = list(
        session.scalars(
            select(ExerciseMapping).where(ExerciseMapping.status == "active")
        ).all()
    )
    scanned_active = len(active_rows)
    updated = 0
    exited_active = 0
    exited_details: list[dict] = []

    for row in active_rows:
        # a. SIMILAR 存量 → human_policy（保持 active）
        if row.relation == RELATION_SIMILAR and not row.decision_source:
            row.decision_source = DECISION_HUMAN_POLICY
            row.note = _append_b_policy_note(row.note)
            updated += 1

        # b. 目标无效 → 退出 active
        reason = _invalid_target_reason(row)
        if reason is not None:
            before = {
                "status": row.status,
                "mapping_version": row.mapping_version,
            }
            row.status = "draft"
            row.mapping_version = int(row.mapping_version or 0) + 1
            after = {
                "status": row.status,
                "mapping_version": row.mapping_version,
            }
            _write_audit(
                session,
                row,
                action="migrate_exit_active",
                before=before,
                after=after,
                reason=reason,
                actor="system",
            )
            exited_active += 1
            if len(exited_details) < 100:
                exited_details.append(
                    {
                        "xunji_name": row.xunji_name,
                        "garmin_exercise_name": row.garmin_exercise_name,
                        "verified_level": row.verified_level,
                        "reason": reason,
                    }
                )
        # c. EXACT / CATEGORY（及未命中 a/b 的其余行）保持原样

    if updated or exited_active:
        session.commit()

    by_relation: dict[str, int] = {
        RELATION_EXACT: 0,
        RELATION_SIMILAR: 0,
        RELATION_CATEGORY: 0,
        RELATION_UNMAPPED: 0,
        "null": 0,
    }
    by_status: dict[str, int] = {
        "draft": 0,
        "active": 0,
        "disabled": 0,
        "not_applicable": 0,
    }
    human_policy = 0
    high_risk: list[dict] = []

    all_rows = list(session.scalars(select(ExerciseMapping)).all())
    for row in all_rows:
        rel_key = row.relation if row.relation is not None else "null"
        by_relation[rel_key] = by_relation.get(rel_key, 0) + 1

        if row.status in by_status:
            by_status[row.status] += 1

        if row.decision_source == DECISION_HUMAN_POLICY:
            human_policy += 1

        if (
            row.status == "active"
            and row.relation == RELATION_SIMILAR
            and len(high_risk) < 100
        ):
            high_risk.append(
                {
                    "xunji_name": row.xunji_name,
                    "garmin_display_name": row.garmin_display_name,
                    "relation": row.relation,
                    "note": row.note,
                }
            )

    return {
        "backfill": backfill,
        "scanned_active": scanned_active,
        "updated": updated,
        "exited_active": exited_active,
        "by_relation": by_relation,
        "by_status": by_status,
        "human_policy": human_policy,
        "exited_details": exited_details,
        "high_risk": high_risk,
    }
