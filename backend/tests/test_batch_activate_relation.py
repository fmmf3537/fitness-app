"""ADR-P0-4：batch_activate 按 relation / verified_level / 器械不符筛选。"""
from __future__ import annotations

from sqlalchemy import select

from app.models import ExerciseMapping, ExerciseMappingAudit
from app.services.exercise_mapping import activate_mapping, batch_activate


def _add_mapping(session, **kwargs) -> ExerciseMapping:
    defaults = {
        "xunji_name": "P04-默认",
        "garmin_category": "BENCH_PRESS",
        "garmin_exercise_name": "DUMBBELL_BENCH_PRESS",
        "garmin_display_name": "Dumbbell Bench Press",
        "weight_strategy": "per_hand",
        "status": "draft",
        "confidence": "high",
        "source": "auto",
        "verified_level": "catalog",
        "mapping_version": 1,
        "note": None,
        "relation": "EXACT",
        "match_basis": "same_name",
    }
    defaults.update(kwargs)
    row = ExerciseMapping(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---- 应自动确认（2）----


def test_activates_exact_high_verified(session):
    row = _add_mapping(session, xunji_name="P04-exact-catalog")
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert result["activated"] == 1
    assert row.status == "active"
    assert row.decision_source == "rule"


def test_activates_exact_displayed_level(session):
    row = _add_mapping(
        session,
        xunji_name="P04-exact-displayed",
        verified_level="displayed",
    )
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert result["activated"] == 1
    assert row.status == "active"
    assert row.decision_source == "rule"


# ---- 不应自动确认（6）----


def test_skips_similar(session):
    row = _add_mapping(session, xunji_name="P04-similar", relation="SIMILAR")
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert row.status == "draft"
    assert result["activated"] == 0
    assert result["skipped_reasons"]["relation_not_exact"] >= 1


def test_skips_category(session):
    row = _add_mapping(session, xunji_name="P04-category", relation="CATEGORY")
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert row.status == "draft"
    assert result["activated"] == 0
    assert result["skipped_reasons"]["relation_not_exact"] >= 1


def test_skips_missing_relation(session):
    row = _add_mapping(session, xunji_name="P04-no-relation", relation=None)
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert row.status == "draft"
    assert result["activated"] == 0
    assert result["skipped_reasons"]["relation_missing"] >= 1


def test_skips_unverified_target(session):
    row = _add_mapping(
        session,
        xunji_name="P04-unverified",
        verified_level=None,
    )
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert row.status == "draft"
    assert result["activated"] == 0
    assert result["skipped_reasons"]["target_unverified"] >= 1


def test_skips_equipment_mismatch_note(session):
    row = _add_mapping(
        session,
        xunji_name="P04-equip-mismatch",
        note="器械不符：哑铃 vs 杠铃",
    )
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert row.status == "draft"
    assert result["activated"] == 0
    assert result["skipped_reasons"]["equipment_mismatch"] >= 1


def test_skips_when_catalog_pair_missing(session):
    row = _add_mapping(
        session,
        xunji_name="P04-catalog-missing",
        garmin_exercise_name="NOT_A_REAL_EXERCISE_XYZ",
        garmin_display_name="Not Real",
    )
    blocked = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert row.status == "draft"
    assert blocked["activated"] == 0
    assert blocked["skipped_reasons"]["catalog_missing"] >= 1

    # only_confirmed_catalog=False 时目录开关关闭，仍由 relation/verified 决定 → 应激活
    allowed = batch_activate(session, confidence="high", only_confirmed_catalog=False)
    session.refresh(row)
    assert allowed["activated"] == 1
    assert row.status == "active"
    assert row.decision_source == "rule"


# ---- 不得误伤（3）----


def test_does_not_touch_active_rows(session):
    row = _add_mapping(session, xunji_name="P04-already-active", status="active")
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert row.status == "active"
    assert result["activated"] == 0
    assert sum(result["relation_breakdown"].values()) == 0


def test_does_not_touch_not_applicable_rows(session):
    row = _add_mapping(
        session,
        xunji_name="P04-na",
        status="not_applicable",
        garmin_category=None,
        garmin_exercise_name=None,
        garmin_display_name=None,
        not_applicable_reason="stretch",
    )
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert row.status == "not_applicable"
    assert result["activated"] == 0


def test_does_not_change_relation_or_confidence(session):
    row = _add_mapping(
        session,
        xunji_name="P04-preserve-fields",
        relation="EXACT",
        match_basis="alias",
        confidence="high",
        verified_level="catalog",
        verified_at=None,
    )
    before = {
        "relation": row.relation,
        "match_basis": row.match_basis,
        "confidence": row.confidence,
        "verified_level": row.verified_level,
        "verified_at": row.verified_at,
    }
    batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(row)
    assert row.status == "active"
    assert row.relation == before["relation"]
    assert row.match_basis == before["match_basis"]
    assert row.confidence == before["confidence"]
    assert row.verified_level == before["verified_level"]
    assert row.verified_at == before["verified_at"]


# ---- 报告与审计（3）----


def test_skipped_equals_sum_of_reasons(session):
    _add_mapping(session, xunji_name="P04-sum-exact")  # activate
    _add_mapping(session, xunji_name="P04-sum-similar", relation="SIMILAR")
    _add_mapping(session, xunji_name="P04-sum-missing", relation=None)
    _add_mapping(session, xunji_name="P04-sum-unverif", verified_level=None)
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    assert result["skipped"] == sum(result["skipped_reasons"].values())
    assert result["activated"] == 1


def test_relation_breakdown_counts_scanned_rows(session):
    _add_mapping(session, xunji_name="P04-bd-exact", relation="EXACT")
    _add_mapping(session, xunji_name="P04-bd-similar", relation="SIMILAR")
    _add_mapping(session, xunji_name="P04-bd-null", relation=None)
    # low confidence 不在扫描范围
    _add_mapping(
        session,
        xunji_name="P04-bd-low",
        confidence="low",
        relation="EXACT",
    )
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    assert sum(result["relation_breakdown"].values()) == 3
    assert result["relation_breakdown"].get("EXACT", 0) == 1
    assert result["relation_breakdown"].get("SIMILAR", 0) == 1
    assert result["relation_breakdown"].get("null", 0) == 1


def test_audit_written_for_each_activation(session):
    a = _add_mapping(session, xunji_name="P04-audit-a")
    b = _add_mapping(session, xunji_name="P04-audit-b")
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    assert result["activated"] == 2
    for row in (a, b):
        audits = session.scalars(
            select(ExerciseMappingAudit).where(
                ExerciseMappingAudit.mapping_id == row.id,
                ExerciseMappingAudit.action == "activate",
                ExerciseMappingAudit.reason == "batch_activate",
            )
        ).all()
        assert len(audits) == 1


# ---- 单行人工激活（2）----


def test_manual_activate_sets_human_source(session):
    row = _add_mapping(session, xunji_name="P04-manual-human")
    activate_mapping(session, row.id, reason="manual review")
    session.refresh(row)
    assert row.status == "active"
    assert row.decision_source == "human"


def test_manual_activate_allows_similar(session):
    row = _add_mapping(
        session,
        xunji_name="P04-manual-similar",
        relation="SIMILAR",
        match_basis="semantic_review",
    )
    activate_mapping(session, row.id, reason="accept similar")
    session.refresh(row)
    assert row.status == "active"
    assert row.relation == "SIMILAR"
    assert row.decision_source == "human"
