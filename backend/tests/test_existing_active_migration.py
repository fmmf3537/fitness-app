"""ADR-P0-5：存量迁移 B 策略（migrate_existing_active）与报告。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.models import ExerciseMapping, ExerciseMappingAudit
from app.services.exercise_mapping_relation import (
    B_POLICY_NOTE,
    migrate_existing_active,
)


def _add_mapping(session, **kwargs) -> ExerciseMapping:
    defaults = {
        "xunji_name": "P05-默认",
        "garmin_category": "BENCH_PRESS",
        "garmin_exercise_name": "DUMBBELL_BENCH_PRESS",
        "garmin_display_name": "Dumbbell Bench Press",
        "weight_strategy": "per_hand",
        "status": "active",
        "confidence": "high",
        "source": "auto",
        "verified_level": "catalog",
        "mapping_version": 1,
        "note": None,
        "relation": "EXACT",
        "match_basis": "rule_features",
        "decision_source": None,
    }
    defaults.update(kwargs)
    row = ExerciseMapping(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---- B 策略标记（4）----


def test_similar_active_becomes_human_policy(session):
    row = _add_mapping(
        session,
        xunji_name="P05-similar-hp",
        relation="SIMILAR",
        decision_source=None,
    )
    migrate_existing_active(session)
    session.refresh(row)
    assert row.decision_source == "human_policy"
    assert row.status == "active"


def test_similar_active_note_annotated(session):
    row = _add_mapping(
        session,
        xunji_name="P05-similar-note",
        relation="SIMILAR",
        decision_source=None,
        note="器械不符：哑铃→杠铃",
    )
    migrate_existing_active(session)
    session.refresh(row)
    assert B_POLICY_NOTE in (row.note or "")


def test_similar_note_not_duplicated(session):
    row = _add_mapping(
        session,
        xunji_name="P05-similar-note-once",
        relation="SIMILAR",
        decision_source=None,
        note="已有备注",
    )
    migrate_existing_active(session)
    migrate_existing_active(session)
    session.refresh(row)
    assert (row.note or "").count(B_POLICY_NOTE) == 1


def test_exact_active_untouched(session):
    row = _add_mapping(
        session,
        xunji_name="P05-exact-keep",
        relation="EXACT",
        decision_source=None,
        verified_level="catalog",
        confidence="high",
        mapping_version=2,
        note="seed ok",
    )
    before = (
        row.decision_source,
        row.status,
        row.mapping_version,
        row.note,
        row.confidence,
        row.verified_level,
        row.relation,
    )
    migrate_existing_active(session)
    session.refresh(row)
    assert (
        row.decision_source,
        row.status,
        row.mapping_version,
        row.note,
        row.confidence,
        row.verified_level,
        row.relation,
    ) == before
    assert row.decision_source is None


# ---- 退出 active（3）----


def test_unverified_target_exits_active(session):
    row = _add_mapping(
        session,
        xunji_name="P05-unverified",
        relation="EXACT",
        verified_level="none",
    )
    report = migrate_existing_active(session)
    session.refresh(row)
    assert row.status == "draft"
    assert report["exited_active"] >= 1
    detail = next(
        d for d in report["exited_details"] if d["xunji_name"] == "P05-unverified"
    )
    assert detail["reason"] == "target_unverified"


def test_catalog_missing_exits_active(session):
    row = _add_mapping(
        session,
        xunji_name="P05-catalog-missing",
        relation="EXACT",
        verified_level="catalog",
        garmin_category="BENCH_PRESS",
        garmin_exercise_name="NOT_IN_CATALOG_XYZ",
        garmin_display_name="Not In Catalog",
    )
    report = migrate_existing_active(session)
    session.refresh(row)
    assert row.status == "draft"
    detail = next(
        d
        for d in report["exited_details"]
        if d["xunji_name"] == "P05-catalog-missing"
    )
    assert detail["reason"] == "catalog_missing"


def test_exit_writes_audit(session):
    row = _add_mapping(
        session,
        xunji_name="P05-exit-audit",
        relation="EXACT",
        verified_level="none",
    )
    migrate_existing_active(session)
    audits = list(
        session.scalars(
            select(ExerciseMappingAudit).where(
                ExerciseMappingAudit.mapping_id == row.id,
                ExerciseMappingAudit.action == "migrate_exit_active",
            )
        ).all()
    )
    assert len(audits) == 1


# ---- 不误伤（3）----


def test_draft_rows_untouched(session):
    row = _add_mapping(
        session,
        xunji_name="P05-draft-keep",
        status="draft",
        relation="SIMILAR",
        decision_source=None,
        note=None,
        mapping_version=1,
    )
    before = (
        row.status,
        row.decision_source,
        row.note,
        row.mapping_version,
        row.relation,
    )
    migrate_existing_active(session)
    session.refresh(row)
    assert (
        row.status,
        row.decision_source,
        row.note,
        row.mapping_version,
        row.relation,
    ) == before


def test_not_applicable_rows_untouched(session):
    row = _add_mapping(
        session,
        xunji_name="P05-na-keep",
        status="not_applicable",
        not_applicable_reason="stretch",
        relation=None,
        garmin_exercise_name=None,
        garmin_display_name=None,
        confidence=None,
        verified_level=None,
        decision_source=None,
        note=None,
        mapping_version=1,
    )
    before = (
        row.status,
        row.decision_source,
        row.note,
        row.mapping_version,
        row.relation,
    )
    migrate_existing_active(session)
    session.refresh(row)
    assert (
        row.status,
        row.decision_source,
        row.note,
        row.mapping_version,
        row.relation,
    ) == before


def test_migration_does_not_change_relation_or_verified_level(session):
    verified_at = datetime(2026, 1, 15, 12, 0, 0)
    row = _add_mapping(
        session,
        xunji_name="P05-fields-keep",
        relation="SIMILAR",
        verified_level="catalog",
        verified_at=verified_at,
        confidence="medium",
    )
    before = (
        row.relation,
        row.verified_level,
        row.verified_at,
        row.confidence,
    )
    migrate_existing_active(session)
    session.refresh(row)
    assert (
        row.relation,
        row.verified_level,
        row.verified_at,
        row.confidence,
    ) == before


# ---- 幂等（2）----


def test_second_run_is_noop(session):
    _add_mapping(session, xunji_name="P05-idem-similar", relation="SIMILAR")
    _add_mapping(
        session,
        xunji_name="P05-idem-exit",
        relation="EXACT",
        verified_level="none",
    )
    first = migrate_existing_active(session)
    assert first["updated"] >= 1
    assert first["exited_active"] >= 1
    second = migrate_existing_active(session)
    assert second["updated"] == 0
    assert second["exited_active"] == 0


def test_second_run_does_not_add_audit(session):
    row = _add_mapping(
        session,
        xunji_name="P05-idem-audit",
        relation="EXACT",
        verified_level="none",
    )
    migrate_existing_active(session)
    count_after_first = session.scalar(
        select(func.count()).select_from(ExerciseMappingAudit).where(
            ExerciseMappingAudit.mapping_id == row.id,
            ExerciseMappingAudit.action == "migrate_exit_active",
        )
    )
    migrate_existing_active(session)
    count_after_second = session.scalar(
        select(func.count()).select_from(ExerciseMappingAudit).where(
            ExerciseMappingAudit.mapping_id == row.id,
            ExerciseMappingAudit.action == "migrate_exit_active",
        )
    )
    assert count_after_first == 1
    assert count_after_second == 1


# ---- 报告（3）----


def test_report_counts_are_full_table(session):
    _add_mapping(session, xunji_name="P05-rpt-exact", relation="EXACT")
    _add_mapping(session, xunji_name="P05-rpt-similar", relation="SIMILAR")
    _add_mapping(
        session,
        xunji_name="P05-rpt-draft",
        status="draft",
        relation="CATEGORY",
    )
    _add_mapping(
        session,
        xunji_name="P05-rpt-na",
        status="not_applicable",
        not_applicable_reason="cardio",
        relation=None,
        garmin_exercise_name=None,
        confidence=None,
        verified_level=None,
    )
    report = migrate_existing_active(session)
    total = session.scalar(select(func.count()).select_from(ExerciseMapping))
    assert sum(report["by_relation"].values()) == total
    assert sum(report["by_status"].values()) == total


def test_report_lists_high_risk(session):
    names = []
    for i in range(3):
        name = f"P05-high-risk-{i}"
        names.append(name)
        _add_mapping(session, xunji_name=name, relation="SIMILAR")
    _add_mapping(session, xunji_name="P05-high-risk-exact", relation="EXACT")
    report = migrate_existing_active(session)
    risk_names = {item["xunji_name"] for item in report["high_risk"]}
    for name in names:
        assert name in risk_names
    assert "P05-high-risk-exact" not in risk_names
    assert len(report["high_risk"]) <= 100


def test_report_exited_details_capped(session):
    for i in range(105):
        _add_mapping(
            session,
            xunji_name=f"P05-exit-cap-{i:03d}",
            relation="EXACT",
            verified_level="none",
        )
    report = migrate_existing_active(session)
    assert report["exited_active"] == 105
    assert len(report["exited_details"]) == 100
