"""V6-4：映射复核 / 纠错 service 层（列表、更新、采纳、批量、目录、stale）。"""
from __future__ import annotations

import json
from datetime import date

import pytest
from garminconnect import exercises as garmin_exercises
from sqlalchemy import select

from app.models import (
    ExerciseMapping,
    ExerciseMappingAudit,
    ExerciseMappingCandidate,
    GarminPlanSync,
)
from app.services.exercise_mapping import (
    MappingValueError,
    accept_candidate,
    activate_mapping,
    batch_activate,
    disable_mapping,
    get_mapping_detail,
    list_mappings,
    list_stale_syncs,
    load_mapping_snapshot_hash,
    search_catalog,
    seed_mappings,
    update_mapping,
)


def _get_by_name(session, name: str) -> ExerciseMapping:
    return session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.xunji_name == name)
    ).one()


def _add_draft(
    session,
    *,
    name: str,
    category: str | None = "BENCH_PRESS",
    exercise: str | None = "DUMBBELL_BENCH_PRESS",
    display: str | None = "Dumbbell Bench Press",
    confidence: str | None = "high",
    weight_strategy: str = "per_hand",
) -> ExerciseMapping:
    row = ExerciseMapping(
        xunji_name=name,
        garmin_category=category,
        garmin_exercise_name=exercise,
        garmin_display_name=display,
        weight_strategy=weight_strategy,
        status="draft",
        confidence=confidence,
        source="test",
        verified_level="none",
        mapping_version=1,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _add_candidate(
    session,
    *,
    xunji_name: str,
    category: str = "BENCH_PRESS",
    exercise: str = "BARBELL_BENCH_PRESS",
    display: str = "Barbell Bench Press",
    rank: int = 1,
    status: str = "pending",
) -> ExerciseMappingCandidate:
    row = ExerciseMappingCandidate(
        xunji_name=xunji_name,
        garmin_category=category,
        garmin_exercise_name=exercise,
        garmin_display_name=display,
        confidence="high",
        reason="test",
        rank=rank,
        status=status,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---------- 列表（4）----------


def test_list_mappings_pagination(session):
    seed_mappings(session)
    result = list_mappings(session, page=1, page_size=10)
    assert len(result["items"]) == 10
    assert result["total"] == 16
    assert result["page"] == 1
    assert result["page_size"] == 10
    assert result["pages"] == 2
    page2 = list_mappings(session, page=2, page_size=10)
    assert len(page2["items"]) == 6
    assert page2["pages"] == 2


def test_list_mappings_filter_status(session):
    seed_mappings(session)
    _add_draft(session, name="测试草稿动作A")
    result = list_mappings(session, status="draft")
    assert result["total"] >= 1
    assert all(item["status"] == "draft" for item in result["items"])


def test_list_mappings_filter_confidence(session):
    seed_mappings(session)
    _add_draft(session, name="高置信草稿", confidence="high")
    _add_draft(
        session,
        name="低置信草稿",
        confidence="low",
        exercise="BENCH_PRESS",
        display="Bench Press",
    )
    result = list_mappings(session, confidence="high", status="draft")
    assert result["total"] >= 1
    assert all(item["confidence"] == "high" for item in result["items"])


def test_list_mappings_keyword_case_insensitive(session):
    seed_mappings(session)
    by_zh = list_mappings(session, keyword="哑铃卧推")
    assert any(item["xunji_name"] == "哑铃卧推" for item in by_zh["items"])
    by_en = list_mappings(session, keyword="dumbbell bench")
    assert any(
        (item["garmin_display_name"] or "").lower().find("dumbbell bench") >= 0
        for item in by_en["items"]
    )


# ---------- 详情（1）----------


def test_get_mapping_detail_includes_candidates(session):
    seed_mappings(session)
    row = _get_by_name(session, "哑铃卧推")
    c1 = _add_candidate(session, xunji_name="哑铃卧推", rank=1)
    c2 = _add_candidate(
        session,
        xunji_name="哑铃卧推",
        rank=2,
        exercise="BENCH_PRESS",
        display="Bench Press",
    )
    detail = get_mapping_detail(session, row.id)
    assert detail is not None
    assert detail["xunji_name"] == "哑铃卧推"
    assert [c["id"] for c in detail["candidates"]] == [c1.id, c2.id]


# ---------- 更新（5）----------


def test_update_mapping_changes_fields_and_bumps_version(session):
    seed_mappings(session)
    row = _get_by_name(session, "哑铃卧推")
    before_version = row.mapping_version
    before_category = row.garmin_category
    before_exercise = row.garmin_exercise_name
    item = update_mapping(
        session,
        row.id,
        garmin_display_name="DB Bench Press (edited)",
        reason="rename display",
    )
    assert item is not None
    assert item["garmin_display_name"] == "DB Bench Press (edited)"
    assert item["mapping_version"] == before_version + 1
    assert item["garmin_category"] == before_category
    assert item["garmin_exercise_name"] == before_exercise


def test_update_mapping_rejects_invalid_category(session):
    seed_mappings(session)
    row = _get_by_name(session, "哑铃卧推")
    with pytest.raises(MappingValueError) as exc_info:
        update_mapping(session, row.id, garmin_category="NOT_A_CATEGORY")
    assert exc_info.value.code == "INVALID_CATEGORY"


def test_update_mapping_rejects_invalid_exercise(session):
    seed_mappings(session)
    row = _get_by_name(session, "哑铃卧推")
    with pytest.raises(MappingValueError) as exc_info:
        update_mapping(
            session,
            row.id,
            garmin_category="BENCH_PRESS",
            garmin_exercise_name="NOT_A_REAL_EXERCISE",
        )
    assert exc_info.value.code == "INVALID_EXERCISE"


def test_update_mapping_writes_audit(session):
    seed_mappings(session)
    row = _get_by_name(session, "哑铃卧推")
    update_mapping(
        session,
        row.id,
        garmin_display_name="Audited Name",
        reason="audit check",
    )
    audit = session.scalars(
        select(ExerciseMappingAudit)
        .where(ExerciseMappingAudit.mapping_id == row.id)
        .order_by(ExerciseMappingAudit.id.desc())
    ).first()
    assert audit is not None
    assert audit.action == "update"
    before = json.loads(audit.before_json)
    after = json.loads(audit.after_json)
    assert "garmin_display_name" in before
    assert after["garmin_display_name"] == "Audited Name"
    assert audit.reason == "audit check"


def test_update_mapping_allows_empty_exercise_name(session):
    # Garmin 目录静态表里没有任何 exercise 为空串的条目，但 P2/P3 实测 Garmin
    # 创建后会把通用 Bench Press / Lateral Raise 的 exerciseName 规范化为空串。
    # 复核页需要能如实记录远端实际显示值，故空串必须合法。
    seed_mappings(session)
    row = _get_by_name(session, "器械推胸")
    item = update_mapping(
        session,
        row.id,
        garmin_category="BENCH_PRESS",
        garmin_exercise_name="",
        garmin_display_name="Bench Press",
    )
    assert item is not None
    assert item["garmin_exercise_name"] == ""
    assert item["garmin_category"] == "BENCH_PRESS"

    # 对照：空串仍必须配 category
    with pytest.raises(MappingValueError) as caught:
        update_mapping(session, row.id, garmin_category=None, garmin_exercise_name="")
    assert caught.value.code in {"INVALID_CATEGORY", "INVALID_EXERCISE"}


# ---------- 采纳 / 停用（3）----------


def test_activate_requires_category(session):
    row = _add_draft(
        session,
        name="无分类草稿",
        category=None,
        exercise=None,
        display=None,
        confidence="medium",
    )
    with pytest.raises(MappingValueError) as exc_info:
        activate_mapping(session, row.id)
    assert exc_info.value.code == "MISSING_CATEGORY"


def test_activate_sets_active_and_audits(session):
    seed_mappings(session)
    row = _add_draft(session, name="待采纳草稿")
    item = activate_mapping(session, row.id, reason="looks good")
    assert item["status"] == "active"
    assert item["mapping_version"] == 2
    audit = session.scalars(
        select(ExerciseMappingAudit)
        .where(ExerciseMappingAudit.mapping_id == row.id)
        .order_by(ExerciseMappingAudit.id.desc())
    ).first()
    assert audit is not None
    assert audit.action == "activate"
    assert json.loads(audit.after_json)["status"] == "active"


def test_disable_sets_disabled_and_audits(session):
    seed_mappings(session)
    row = _get_by_name(session, "卷腹")
    before_version = row.mapping_version
    item = disable_mapping(session, row.id, reason="wrong mapping")
    assert item["status"] == "disabled"
    assert item["mapping_version"] == before_version + 1
    audit = session.scalars(
        select(ExerciseMappingAudit)
        .where(ExerciseMappingAudit.mapping_id == row.id)
        .order_by(ExerciseMappingAudit.id.desc())
    ).first()
    assert audit is not None
    assert audit.action == "disable"


# ---------- 候选采纳（2）----------


def test_accept_candidate_applies_and_rejects_siblings(session):
    seed_mappings(session)
    row = _add_draft(session, name="候选采纳测试")
    chosen = _add_candidate(
        session,
        xunji_name="候选采纳测试",
        rank=1,
        exercise="BARBELL_BENCH_PRESS",
        display="Barbell Bench Press",
    )
    sibling = _add_candidate(
        session,
        xunji_name="候选采纳测试",
        rank=2,
        exercise="BENCH_PRESS",
        display="Bench Press",
    )
    item = accept_candidate(session, row.id, chosen.id, weight_strategy="total")
    assert item["status"] == "active"
    assert item["garmin_exercise_name"] == "BARBELL_BENCH_PRESS"
    assert item["weight_strategy"] == "total"
    session.refresh(chosen)
    session.refresh(sibling)
    assert chosen.status == "accepted"
    assert sibling.status == "rejected"


def test_accept_candidate_validates_category(session):
    seed_mappings(session)
    row = _add_draft(session, name="坏候选测试")
    bad = _add_candidate(
        session,
        xunji_name="坏候选测试",
        category="NOT_A_CATEGORY",
        exercise="WHATEVER",
        display="Bad",
    )
    with pytest.raises(MappingValueError) as exc_info:
        accept_candidate(session, row.id, bad.id)
    assert exc_info.value.code == "INVALID_CATEGORY"


# ---------- 批量（2）----------


def test_batch_activate_only_high_confidence(session):
    seed_mappings(session)
    high = _add_draft(session, name="批量高置信", confidence="high")
    low = _add_draft(
        session,
        name="批量低置信",
        confidence="low",
        exercise="BENCH_PRESS",
        display="Bench Press",
    )
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    assert result["activated"] >= 1
    session.refresh(high)
    session.refresh(low)
    assert high.status == "active"
    assert low.status == "draft"


def test_batch_activate_skips_rows_without_category(session):
    seed_mappings(session)
    no_cat = _add_draft(
        session,
        name="无分类批量",
        category=None,
        exercise=None,
        display=None,
        confidence="high",
    )
    result = batch_activate(session, confidence="high", only_confirmed_catalog=True)
    session.refresh(no_cat)
    assert no_cat.status == "draft"
    assert result["activated"] >= 0


# ---------- 目录搜索（2）----------


def test_search_catalog_by_term():
    rows = search_catalog(q="bench")
    assert rows
    assert all("bench" in (r["name"] or "").lower() for r in rows)


def test_search_catalog_limit_capped():
    rows = search_catalog(q="", limit=999)
    assert len(rows) <= 100


# ---------- stale（1）----------


def test_list_stale_syncs_detects_changed_mapping(session):
    seed_mappings(session)
    names = ["哑铃卧推"]
    old_hash = load_mapping_snapshot_hash(session, names)
    payload = {
        "workoutName": "训记｜测试｜2026-11-10",
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "workoutSteps": [
                    {
                        "type": "ExecutableStepDTO",
                        "description": "哑铃卧推｜源组 1-3",
                        "category": "BENCH_PRESS",
                        "exerciseName": "DUMBBELL_BENCH_PRESS",
                    }
                ],
            }
        ],
    }
    sync = GarminPlanSync(
        plan_ref="universal:1",
        training_date=date(2026, 11, 10),
        source_key="xunji-plan:v1:universal:1:2026-11-10",
        source_hash="abc",
        payload_json=json.dumps(payload, ensure_ascii=False),
        workout_id="w1",
        workout_schedule_id="s1",
        status="synced",
        mapping_hash=old_hash,
    )
    session.add(sync)
    session.commit()

    row = _get_by_name(session, "哑铃卧推")
    update_mapping(
        session,
        row.id,
        garmin_display_name="Dumbbell Bench Press v2",
        reason="force stale",
    )

    stale = list_stale_syncs(session, limit=50)
    match = next((s for s in stale if s["sync_id"] == sync.id), None)
    assert match is not None
    assert match["stored_hash"] != match["current_hash"]
    assert match["stored_hash"] == old_hash
    assert match["plan_ref"] == "universal:1"
