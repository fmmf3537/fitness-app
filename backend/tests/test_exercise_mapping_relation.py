"""ADR-P0-1：classify_relation 纯函数 + backfill_relations 幂等。"""
from __future__ import annotations

from types import SimpleNamespace

from app.models import ExerciseMapping
from app.services.exercise_mapping_relation import (
    MATCH_BASIS_VALUES,
    RELATION_CATEGORY,
    RELATION_EXACT,
    RELATION_SIMILAR,
    RELATION_UNMAPPED,
    RELATIONS,
    UNMAPPED_REASON_VALUES,
    backfill_relations,
    classify_relation,
)


def _row(**kwargs) -> SimpleNamespace:
    defaults = {
        "xunji_name": "哑铃卧推",
        "garmin_category": "BENCH_PRESS",
        "garmin_exercise_name": "DUMBBELL_BENCH_PRESS",
        "garmin_display_name": "Dumbbell Bench Press",
        "status": "draft",
        "source": "auto",
        "relation": None,
        "match_basis": None,
        "unmapped_reason": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---- 正常排除（2）----


def test_not_applicable_yields_none():
    row = _row(status="not_applicable", garmin_exercise_name="BENCH_PRESS")
    assert classify_relation(row) == (None, None, None)


def test_not_applicable_never_unmapped():
    row = _row(status="not_applicable", garmin_exercise_name=None)
    result = classify_relation(row)
    assert result == (None, None, None)
    assert result[0] != RELATION_UNMAPPED


# ---- UNMAPPED（2）----


def test_empty_target_is_unmapped():
    row = _row(status="draft", garmin_exercise_name=None, source="auto")
    assert classify_relation(row) == (RELATION_UNMAPPED, None, "no_equivalent")


def test_unmapped_reason_in_allowed_values():
    row = _row(status="draft", garmin_exercise_name=None)
    _relation, _basis, reason = classify_relation(row)
    assert reason in UNMAPPED_REASON_VALUES


# ---- seed 与人工（3）----


def test_seed_is_exact():
    row = _row(
        xunji_name="哑铃卧推",
        source="seed",
        garmin_exercise_name="DUMBBELL_BENCH_PRESS",
        garmin_display_name="Dumbbell Bench Press",
    )
    assert classify_relation(row) == (RELATION_EXACT, "semantic_review", None)


def test_seed_generic_target_is_category():
    row = _row(
        xunji_name="器械推胸",
        source="seed",
        garmin_category="BENCH_PRESS",
        garmin_exercise_name="BENCH_PRESS",
        garmin_display_name="Bench Press",
    )
    relation, match_basis, unmapped_reason = classify_relation(row)
    assert relation == RELATION_CATEGORY
    assert match_basis == "semantic_review"
    assert unmapped_reason is None


def test_manual_source_is_exact():
    row = _row(
        source="manual",
        garmin_exercise_name="DUMBBELL_BENCH_PRESS",
        garmin_display_name="Dumbbell Bench Press",
    )
    assert classify_relation(row) == (RELATION_EXACT, "semantic_review", None)


# ---- 大类目标（1）----


def test_generic_target_is_category():
    row = _row(
        xunji_name="弯举",
        source="auto",
        garmin_category="CURL",
        garmin_exercise_name="CURL",
        garmin_display_name="Curl",
    )
    relation, match_basis, _ = classify_relation(row)
    assert relation == RELATION_CATEGORY
    assert match_basis == "rule_features"


# ---- 自动映射的 SIMILAR 判据（6）----


def test_equipment_mismatch_is_similar():
    row = _row(
        xunji_name="下斜杠铃卧推",
        source="auto",
        garmin_category="BENCH_PRESS",
        garmin_exercise_name="DECLINE_DUMBBELL_BENCH_PRESS",
        garmin_display_name="Decline Dumbbell Bench Press",
    )
    assert classify_relation(row)[0] == RELATION_SIMILAR


def test_qualifier_mismatch_is_similar():
    row = _row(
        xunji_name="器械耸肩",
        source="auto",
        garmin_category="SHRUG",
        garmin_exercise_name="BEHIND_THE_BACK_SMITH_MACHINE_SHRUG",
        garmin_display_name="Behind-the-Back Smith Machine Shrug",
    )
    assert classify_relation(row)[0] == RELATION_SIMILAR


def test_posture_mismatch_is_similar():
    row = _row(
        xunji_name="上斜哑铃卧推",
        source="auto",
        garmin_category="BENCH_PRESS",
        garmin_exercise_name="DUMBBELL_BENCH_PRESS",
        garmin_display_name="Dumbbell Bench Press",
    )
    assert classify_relation(row)[0] == RELATION_SIMILAR


def test_no_posture_words_is_not_similar():
    """无姿态词不得因 posture 路径误判 SIMILAR（ADR §10.1 陷阱 2）。"""
    row = _row(
        xunji_name="哑铃卧推",
        source="auto",
        garmin_category="BENCH_PRESS",
        garmin_exercise_name="DUMBBELL_BENCH_PRESS",
        garmin_display_name="Dumbbell Bench Press",
    )
    assert classify_relation(row) == (RELATION_EXACT, "rule_features", None)


def test_clean_match_is_exact():
    row = _row(
        xunji_name="绳索夹胸",
        source="auto",
        garmin_category="FLY",
        garmin_exercise_name="CABLE_CROSSOVER",
        garmin_display_name="Cable Crossover",
    )
    assert classify_relation(row) == (RELATION_EXACT, "rule_features", None)


def test_alias_never_appears_in_relation():
    assert "ALIAS" not in RELATIONS
    for value in RELATIONS:
        assert value != "ALIAS"
    assert "alias" in MATCH_BASIS_VALUES


# ---- 回填幂等（3，走 session 夹具）----


def _add_mapping(session, **kwargs) -> ExerciseMapping:
    defaults = {
        "xunji_name": "测试动作",
        "garmin_category": "BENCH_PRESS",
        "garmin_exercise_name": "DUMBBELL_BENCH_PRESS",
        "garmin_display_name": "Dumbbell Bench Press",
        "weight_strategy": "per_hand",
        "status": "draft",
        "confidence": "high",
        "source": "auto",
        "verified_level": "catalog",
        "mapping_version": 1,
    }
    defaults.update(kwargs)
    row = ExerciseMapping(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_backfill_is_idempotent(session):
    _add_mapping(session, xunji_name="幂等-A")
    _add_mapping(
        session,
        xunji_name="幂等-B",
        garmin_exercise_name=None,
        garmin_display_name=None,
        confidence=None,
    )
    first = backfill_relations(session)
    assert first["updated"] >= 1
    second = backfill_relations(session)
    assert second["updated"] == 0


def test_backfill_does_not_touch_existing_relation(session):
    row = _add_mapping(
        session,
        xunji_name="已设-SIMILAR",
        relation="SIMILAR",
        match_basis="other",
        unmapped_reason=None,
    )
    backfill_relations(session)
    session.refresh(row)
    assert row.relation == "SIMILAR"
    assert row.match_basis == "other"


def test_backfill_does_not_change_status_or_confidence(session):
    row = _add_mapping(
        session,
        xunji_name="字段不动",
        status="active",
        confidence="medium",
        mapping_version=3,
        verified_level="displayed",
    )
    before = (
        row.status,
        row.confidence,
        row.mapping_version,
        row.verified_level,
    )
    backfill_relations(session)
    session.refresh(row)
    assert (
        row.status,
        row.confidence,
        row.mapping_version,
        row.verified_level,
    ) == before


# ---- 报告字段（2）----


def test_report_counts_consistent(session):
    _add_mapping(session, xunji_name="报告-exact")
    _add_mapping(
        session,
        xunji_name="报告-unmapped",
        garmin_exercise_name=None,
        garmin_display_name=None,
        confidence=None,
    )
    _add_mapping(
        session,
        xunji_name="报告-na",
        status="not_applicable",
        not_applicable_reason="stretch",
        garmin_exercise_name=None,
        confidence=None,
    )
    report = backfill_relations(session)
    assert report["updated"] == sum(report["by_relation"].values())
    assert (
        report["scanned"]
        == report["updated"] + report["skipped_not_applicable"]
    )


def test_report_lists_active_similar(session):
    _add_mapping(
        session,
        xunji_name="下斜杠铃卧推",
        status="active",
        source="auto",
        garmin_category="BENCH_PRESS",
        garmin_exercise_name="DECLINE_DUMBBELL_BENCH_PRESS",
        garmin_display_name="Decline Dumbbell Bench Press",
        confidence="medium",
    )
    report = backfill_relations(session)
    names = [item["xunji_name"] for item in report["active_similar"]]
    assert "下斜杠铃卧推" in names
