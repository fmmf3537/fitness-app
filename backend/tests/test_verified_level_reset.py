"""ADR-P1-2：Garmin 目标变化后重置 verified_level。"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select

from app.models import ExerciseMapping, ExerciseMappingAudit
from app.services.exercise_mapping import update_mapping


def _add_row(
    session,
    *,
    name: str,
    category: str = "BENCH_PRESS",
    exercise: str = "DUMBBELL_BENCH_PRESS",
    display: str = "Dumbbell Bench Press",
    weight_strategy: str = "per_hand",
    status: str = "active",
    verified_level: str = "displayed",
    verified_at: datetime | None = None,
    mapping_version: int = 3,
    relation: str | None = "EXACT",
    match_basis: str | None = "ALIAS",
    decision_source: str | None = "human",
    confidence: str | None = "high",
) -> ExerciseMapping:
    if verified_at is None:
        verified_at = datetime(2026, 1, 15, 12, 0, 0)
    row = ExerciseMapping(
        xunji_name=name,
        garmin_category=category,
        garmin_exercise_name=exercise,
        garmin_display_name=display,
        weight_strategy=weight_strategy,
        status=status,
        verified_level=verified_level,
        verified_at=verified_at,
        mapping_version=mapping_version,
        relation=relation,
        match_basis=match_basis,
        decision_source=decision_source,
        confidence=confidence,
        source="test",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _latest_audit(session, mapping_id: int) -> ExerciseMappingAudit | None:
    return session.scalars(
        select(ExerciseMappingAudit)
        .where(ExerciseMappingAudit.mapping_id == mapping_id)
        .order_by(ExerciseMappingAudit.id.desc())
    ).first()


def _audit_count(session, mapping_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ExerciseMappingAudit)
            .where(ExerciseMappingAudit.mapping_id == mapping_id)
        )
        or 0
    )


# ---------- 目标变化 → 重置（5）----------


def test_exercise_change_resets_to_catalog(session):
    row = _add_row(session, name="重置-改exercise")
    item = update_mapping(
        session,
        row.id,
        garmin_exercise_name="BARBELL_BENCH_PRESS",
    )
    assert item is not None
    session.refresh(row)
    assert row.verified_level == "catalog"
    assert row.verified_at is None
    assert item["verified_level"] == "catalog"
    # _mapping_item_dict 不暴露 verified_at（行视图只给 verified_level），
    # 上面已断言行属性，这里不再索引 dict。


def test_category_change_resets(session):
    row = _add_row(session, name="重置-改category")
    item = update_mapping(
        session,
        row.id,
        garmin_category="LATERAL_RAISE",
        garmin_exercise_name="DUMBBELL_LATERAL_RAISE",
    )
    assert item is not None
    session.refresh(row)
    assert row.verified_level == "catalog"
    assert row.verified_at is None
    assert row.garmin_category == "LATERAL_RAISE"
    assert row.garmin_exercise_name == "DUMBBELL_LATERAL_RAISE"


def test_invalid_target_becomes_none(session):
    # 空串通过 _validate_exercise_pair，但不在静态目录中 → 目标无效。
    row = _add_row(session, name="重置-无效目标")
    item = update_mapping(
        session,
        row.id,
        garmin_exercise_name="",
    )
    assert item is not None
    session.refresh(row)
    assert row.verified_level == "none"
    assert row.verified_at is None


def test_invalid_target_exits_active(session):
    row = _add_row(session, name="重置-退出active", status="active")
    update_mapping(session, row.id, garmin_exercise_name="")
    session.refresh(row)
    assert row.verified_level == "none"
    assert row.status == "draft"


def test_valid_target_keeps_active(session):
    row = _add_row(session, name="重置-保持active", status="active")
    update_mapping(
        session,
        row.id,
        garmin_exercise_name="BARBELL_BENCH_PRESS",
    )
    session.refresh(row)
    assert row.verified_level == "catalog"
    assert row.status == "active"


# ---------- 不重置（4）----------


def test_display_name_change_does_not_reset(session):
    ts = datetime(2026, 2, 1, 8, 30, 0)
    row = _add_row(
        session,
        name="不重置-display",
        verified_level="displayed",
        verified_at=ts,
    )
    version_before = row.mapping_version
    update_mapping(
        session,
        row.id,
        garmin_display_name="DB Bench Press (edited)",
    )
    session.refresh(row)
    assert row.verified_level == "displayed"
    assert row.verified_at == ts
    assert row.mapping_version == version_before + 1


def test_weight_strategy_change_does_not_reset(session):
    ts = datetime(2026, 2, 2, 9, 0, 0)
    row = _add_row(
        session,
        name="不重置-weight",
        verified_level="displayed",
        verified_at=ts,
        weight_strategy="per_hand",
    )
    update_mapping(session, row.id, weight_strategy="total")
    session.refresh(row)
    assert row.verified_level == "displayed"
    assert row.verified_at == ts
    assert row.weight_strategy == "total"


def test_status_change_does_not_reset(session):
    ts = datetime(2026, 2, 3, 10, 0, 0)
    row = _add_row(
        session,
        name="不重置-status",
        status="active",
        verified_level="displayed",
        verified_at=ts,
    )
    update_mapping(session, row.id, status="disabled")
    session.refresh(row)
    assert row.verified_level == "displayed"
    assert row.verified_at == ts
    assert row.status == "disabled"


def test_same_target_resubmitted_does_not_reset(session):
    ts = datetime(2026, 2, 4, 11, 0, 0)
    row = _add_row(
        session,
        name="不重置-相同目标",
        exercise="DUMBBELL_BENCH_PRESS",
        verified_level="displayed",
        verified_at=ts,
    )
    update_mapping(
        session,
        row.id,
        garmin_exercise_name="DUMBBELL_BENCH_PRESS",
    )
    session.refresh(row)
    assert row.verified_level == "displayed"
    assert row.verified_at == ts


# ---------- 审计与版本（2）----------


def test_target_change_audit_contains_previous_level(session):
    ts = datetime(2026, 3, 1, 12, 0, 0)
    row = _add_row(
        session,
        name="审计-previous_level",
        verified_level="displayed",
        verified_at=ts,
    )
    update_mapping(
        session,
        row.id,
        garmin_exercise_name="BARBELL_BENCH_PRESS",
        reason="target change audit",
    )
    audit = _latest_audit(session, row.id)
    assert audit is not None
    assert audit.action == "update"
    before = json.loads(audit.before_json)
    after = json.loads(audit.after_json)
    assert before["verified_level"] == "displayed"
    assert before["verified_at"] == ts.isoformat()
    assert after["verified_level"] == "catalog"
    assert after["verified_at"] is None
    assert after["previous_verified_level"] == "displayed"
    assert after["previous_verified_at"] == ts.isoformat()
    assert after["target_valid"] is True


def test_mapping_version_bumped_once(session):
    row = _add_row(session, name="版本-只加一", mapping_version=5)
    update_mapping(
        session,
        row.id,
        garmin_exercise_name="BARBELL_BENCH_PRESS",
    )
    session.refresh(row)
    assert row.mapping_version == 6
    assert row.verified_level == "catalog"


# ---------- 不误伤（2）----------


def test_no_updates_returns_without_reset(session):
    ts = datetime(2026, 4, 1, 13, 0, 0)
    row = _add_row(
        session,
        name="空更新-零副作用",
        verified_level="displayed",
        verified_at=ts,
        mapping_version=4,
        status="active",
    )
    audits_before = _audit_count(session, row.id)
    item = update_mapping(session, row.id)
    assert item is not None
    session.refresh(row)
    assert row.verified_level == "displayed"
    assert row.verified_at == ts
    assert row.mapping_version == 4
    assert row.status == "active"
    assert _audit_count(session, row.id) == audits_before


def test_reset_does_not_touch_relation_or_decision_source(session):
    row = _add_row(
        session,
        name="不误伤-语义字段",
        relation="SIMILAR",
        match_basis="TOKEN",
        decision_source="human_policy",
        confidence="low",
    )
    update_mapping(
        session,
        row.id,
        garmin_exercise_name="BARBELL_BENCH_PRESS",
    )
    session.refresh(row)
    assert row.verified_level == "catalog"
    assert row.verified_at is None
    assert row.relation == "SIMILAR"
    assert row.match_basis == "TOKEN"
    assert row.decision_source == "human_policy"
    assert row.confidence == "low"
