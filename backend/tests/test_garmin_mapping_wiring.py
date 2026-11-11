"""V6-6a：计划预览/同步接入 DB 映射（证明 DB 映射生效，非白名单碰巧通过）。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.main  # noqa: F401
from app.models import (
    ExerciseMapping,
    ExerciseMappingCandidate,
    GarminPlanSync,
    XunjiPlan,
)
from app.services.exercise_mapping import (
    load_all_mappings,
    load_mapping_snapshot_hash,
)
from app.services.garmin_plan_sync import claim_plan_sync
from app.services.garmin_reschedule import (
    detect_reschedule_candidates,
    preview_reschedule,
)
from app.services.garmin_workout_mapper import (
    EXERCISE_WHITELIST,
    WorkoutMappingError,
    expand_workout,
    map_plan_day,
    source_hash,
)
from app.services.plans import query_plan_day

# 故意选用不在 EXERCISE_WHITELIST 中的动作，避免「碰巧白名单也能过」
CUSTOM_NAME = "海豹杠铃划船"
CUSTOM_CATEGORY = "ROW"
CUSTOM_EXERCISE = "BARBELL_ROW"
CUSTOM_DISPLAY = "Barbell Row"

PLAN_DATE = date(2026, 11, 12)
OLD_DATE = date(2026, 11, 10)
TARGET_DATE = OLD_DATE + timedelta(days=1)
PLAN_REF = "platform:155"


def _make_set(weight=20, reps=10):
    return {
        "set_type": "working",
        "weight": weight,
        "left_weight": weight,
        "unit": "kg",
        "reps": reps,
        "duration_seconds": 60,
        "rest_seconds": 60,
        "rounds": None,
    }


def _make_day(name: str = CUSTOM_NAME, *, day: date = PLAN_DATE, sets=None):
    return {
        "plan_ref": PLAN_REF,
        "date": day.isoformat(),
        "title": "DB 映射接线测试",
        "movements": [
            {
                "name": name,
                "sets": sets if sets is not None else [_make_set()],
                "rest_seconds": 60,
                "warmup_rest_seconds": 30,
                "single_side": False,
                "amrap": False,
            }
        ],
    }


def _add_mapping(
    session,
    *,
    name: str = CUSTOM_NAME,
    category: str = CUSTOM_CATEGORY,
    exercise: str = CUSTOM_EXERCISE,
    display: str = CUSTOM_DISPLAY,
    status: str = "active",
    weight_strategy: str = "total",
    mapping_version: int = 1,
) -> ExerciseMapping:
    row = ExerciseMapping(
        xunji_name=name,
        garmin_category=category,
        garmin_exercise_name=exercise,
        garmin_display_name=display,
        weight_strategy=weight_strategy,
        status=status,
        confidence="high",
        source="test",
        verified_level="catalog",
        mapping_version=mapping_version,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _add_candidate(
    session,
    *,
    xunji_name: str = CUSTOM_NAME,
    category: str = CUSTOM_CATEGORY,
    exercise: str = CUSTOM_EXERCISE,
    display: str = CUSTOM_DISPLAY,
    rank: int = 1,
) -> ExerciseMappingCandidate:
    row = ExerciseMappingCandidate(
        xunji_name=xunji_name,
        garmin_category=category,
        garmin_exercise_name=exercise,
        garmin_display_name=display,
        confidence="high",
        reason="test",
        rank=rank,
        status="pending",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _set_plan_cache(session, plan_day: dict) -> XunjiPlan:
    session.query(XunjiPlan).delete()
    day = date.fromisoformat(plan_day["date"])
    row = XunjiPlan(
        plan_ref=plan_day["plan_ref"],
        plan_json=json.dumps(
            {
                "plan": {"plan_ref": plan_day["plan_ref"], "name": "增肌计划"},
                "days": [
                    {
                        "datestr": plan_day["date"],
                        "workout": {
                            "name": plan_day["title"],
                            "movements": [
                                {
                                    "name": m["name"],
                                    "rest_seconds": m.get("rest_seconds", 60),
                                    "target_sets": m.get("sets")
                                    or m.get("target_sets")
                                    or [_make_set()],
                                }
                                for m in plan_day["movements"]
                            ],
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        date_from=day - timedelta(days=1),
        date_to=day + timedelta(days=60),
        fetched_at=datetime.now(),
    )
    session.add(row)
    session.commit()
    return row


def _reschedule_plan_day(day: date = OLD_DATE, *, weight: float = 20) -> dict:
    """与既有顺延测试同形，保证 content_hash 跨日可比。"""
    return {
        "plan_ref": PLAN_REF,
        "plan_name": "增肌计划",
        "date": day.isoformat(),
        "title": "背部训练",
        "movements": [
            {
                "name": CUSTOM_NAME,
                "rest_seconds": 60,
                "target_sets": [
                    {"weight": weight, "unit": "kg", "reps": 8},
                    {"weight": weight, "unit": "kg", "reps": 8},
                ],
            }
        ],
    }


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings
    from app.db import get_session
    from app.main import app

    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.fixture
def auth_headers(client):
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()[
        "token"
    ]
    return {"Authorization": f"Bearer {token}"}


# ---------- load_all_mappings ----------


def test_load_all_mappings_includes_draft(session):
    assert CUSTOM_NAME not in EXERCISE_WHITELIST
    _add_mapping(session, status="draft")
    mappings = load_all_mappings(session)
    assert CUSTOM_NAME in mappings
    assert mappings[CUSTOM_NAME]["status"] == "draft"
    assert mappings[CUSTOM_NAME]["category"] == CUSTOM_CATEGORY


def test_load_all_mappings_excludes_not_applicable(session):
    _add_mapping(session, status="not_applicable")
    mappings = load_all_mappings(session)
    assert CUSTOM_NAME not in mappings


def test_load_all_mappings_fallback_when_empty(session):
    count = session.scalar(select(func.count()).select_from(ExerciseMapping)) or 0
    assert count == 0
    mappings = load_all_mappings(session)
    assert len(mappings) == 16
    assert set(mappings) == set(EXERCISE_WHITELIST)


# ---------- map_plan_day / expand_workout ----------


def test_map_plan_day_uses_db_mapping(session):
    assert CUSTOM_NAME not in EXERCISE_WHITELIST
    _add_mapping(session, status="active")
    result = map_plan_day(
        _make_day(CUSTOM_NAME), mappings=load_all_mappings(session)
    )
    movement = result["movements"][0]
    assert movement["name"] == CUSTOM_NAME
    assert movement["category"] == CUSTOM_CATEGORY
    assert movement["exerciseName"] == CUSTOM_EXERCISE


def test_map_plan_day_rejects_draft_mapping(session):
    _add_mapping(session, status="draft")
    with pytest.raises(WorkoutMappingError) as caught:
        map_plan_day(_make_day(CUSTOM_NAME), mappings=load_all_mappings(session))
    codes = {issue["code"] for issue in caught.value.issues}
    assert "MAPPING_NOT_APPROVED" in codes
    assert "UNKNOWN_EXERCISE" not in codes


def test_expand_workout_roundtrip_with_db_mapping(session):
    _add_mapping(session, status="active")
    mappings = load_all_mappings(session)
    payload = map_plan_day(_make_day(CUSTOM_NAME), mappings=mappings)["workout"]
    expanded = expand_workout(payload, mappings=mappings)
    assert expanded[0]["name"] == CUSTOM_NAME
    assert expanded[0]["sets"][0]["reps"] == 10


# ---------- preview endpoint ----------


def test_preview_endpoint_uses_db_mapping(client, auth_headers, session):
    assert CUSTOM_NAME not in EXERCISE_WHITELIST
    _add_mapping(session, status="active")
    _set_plan_cache(session, _make_day(CUSTOM_NAME))

    resp = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/preview",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    movement = next(m for m in body["movements"] if m["name"] == CUSTOM_NAME)
    assert movement["category"] == CUSTOM_CATEGORY
    assert movement["exerciseName"] == CUSTOM_EXERCISE
    assert "pending_review" in body


def test_preview_endpoint_returns_pending_review(client, auth_headers, session):
    _add_mapping(session, status="draft")
    _add_candidate(
        session,
        category="ROW",
        exercise="BARBELL_ROW",
        display="Barbell Row",
        rank=1,
    )
    _set_plan_cache(session, _make_day(CUSTOM_NAME))

    resp = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/preview",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "pending_review" in body
    pending = body["pending_review"]
    assert any(item["xunji_name"] == CUSTOM_NAME for item in pending)
    hit = next(item for item in pending if item["xunji_name"] == CUSTOM_NAME)
    assert hit["suggested_category"]
    assert hit["suggested_exercise"]


def test_preview_endpoint_pending_review_empty_when_all_active(
    client, auth_headers, session
):
    _add_mapping(session, status="active")
    _set_plan_cache(session, _make_day(CUSTOM_NAME))

    resp = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/preview",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "pending_review" in body
    assert body["pending_review"] == []


# ---------- claim_plan_sync mapping_hash ----------


def test_claim_plan_sync_writes_mapping_hash(session):
    _add_mapping(session, status="active")
    _set_plan_cache(session, _make_day(CUSTOM_NAME))
    plan_day = query_plan_day(session, PLAN_DATE)
    assert plan_day is not None

    record, started = claim_plan_sync(
        session,
        plan_day,
        expected_source_hash=source_hash(plan_day),
        enabled=True,
    )
    assert started is True
    assert record.mapping_hash
    assert len(record.mapping_hash) == 64
    assert record.mapping_hash == load_mapping_snapshot_hash(
        session, [CUSTOM_NAME]
    )


def test_mapping_hash_changes_after_mapping_edit(session):
    row = _add_mapping(session, status="active", mapping_version=1)
    _set_plan_cache(session, _make_day(CUSTOM_NAME))
    plan_day = query_plan_day(session, PLAN_DATE)
    assert plan_day is not None

    record, started = claim_plan_sync(
        session,
        plan_day,
        expected_source_hash=source_hash(plan_day),
        enabled=True,
    )
    assert started is True
    hash_before = record.mapping_hash
    assert hash_before and len(hash_before) == 64

    row.garmin_exercise_name = "INVERTED_ROW"
    row.mapping_version = int(row.mapping_version or 0) + 1
    record.status = "failed"
    session.commit()

    record2, started2 = claim_plan_sync(
        session,
        plan_day,
        expected_source_hash=source_hash(plan_day),
        enabled=True,
    )
    assert started2 is True
    assert record2.mapping_hash
    assert len(record2.mapping_hash) == 64
    assert record2.mapping_hash != hash_before


# ---------- reschedule preview ----------


def test_reschedule_preview_uses_db_mapping(session):
    assert CUSTOM_NAME not in EXERCISE_WHITELIST
    _add_mapping(session, status="active")
    old_day = _reschedule_plan_day(OLD_DATE)
    target_day = _reschedule_plan_day(TARGET_DATE)
    mappings = load_all_mappings(session)
    preview = map_plan_day(old_day, mappings=mappings)

    record = GarminPlanSync(
        plan_ref=PLAN_REF,
        training_date=OLD_DATE,
        source_key=preview["source_key"],
        source_hash=preview["source_hash"],
        content_hash=preview["content_hash"],
        synced_hash=preview["source_hash"],
        payload_json=json.dumps(preview["workout"], ensure_ascii=False),
        workout_id="workout-old",
        workout_schedule_id="schedule-old",
        status="synced",
        phase="verify",
        attempt_count=2,
        synced_at=datetime(2026, 11, 10, 12),
    )
    session.add(record)
    session.commit()

    # 原日消失、次日出现且 content_hash 相同 → reschedule_pending
    _set_plan_cache(session, target_day)
    detect_reschedule_candidates(session)
    session.refresh(record)
    assert record.status == "reschedule_pending"

    result = preview_reschedule(
        session, from_date=OLD_DATE, target_date=TARGET_DATE
    )
    movement = next(m for m in result["movements"] if m["name"] == CUSTOM_NAME)
    assert movement["category"] == CUSTOM_CATEGORY
    assert movement["exerciseName"] == CUSTOM_EXERCISE
