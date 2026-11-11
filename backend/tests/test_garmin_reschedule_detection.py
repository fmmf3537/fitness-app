"""顺延候选检测：仅临时 SQLite，禁止任何 Garmin 外呼。"""
import json
from datetime import date, datetime, timedelta
from unittest.mock import Mock

import pytest

import app.main  # noqa: F401 先加载应用，再由 env_vars 隔离临时数据库
from app.models import GarminPlanSync, XunjiPlan
from app.services.garmin_plan_sync import (
    GarminWorkoutAdapter,
    PlanSyncError,
    claim_plan_sync,
    source_key_for,
    sync_status_view,
)
from app.services.garmin_reschedule import (
    detect_reschedule_candidates,
    list_reschedule_candidates,
)
from app.services.garmin_workout_mapper import content_hash, source_hash

PLAN_REF = "platform:155"
OLD_DATE = date(2026, 11, 10)
TARGET_DATE = OLD_DATE + timedelta(days=1)
_UNSET = object()


def _movement(weight=20, reps=10):
    return {
        "name": "哑铃卧推",
        "rest_seconds": 60,
        "target_sets": [
            {"weight": weight, "unit": "kg", "reps": reps},
            {"weight": weight, "unit": "kg", "reps": reps},
        ],
    }


def _plan_day(day=OLD_DATE, *, weight=20, title="胸部训练", plan_ref=PLAN_REF):
    return {
        "plan_ref": plan_ref,
        "plan_name": "增肌计划",
        "date": day.isoformat(),
        "title": title,
        "movements": [_movement(weight=weight)],
    }


def _set_cache(session, plan_days, *, plan_ref=PLAN_REF):
    session.query(XunjiPlan).delete()
    days = [
        {
            "datestr": item["date"],
            "workout": {
                "name": item["title"],
                "movements": item["movements"],
            },
        }
        for item in plan_days
    ]
    dates = [date.fromisoformat(item["date"]) for item in plan_days]
    row = XunjiPlan(
        plan_ref=plan_ref,
        plan_json=json.dumps(
            {"plan": {"plan_ref": plan_ref, "name": "增肌计划"}, "days": days},
            ensure_ascii=False,
        ),
        date_from=min(dates) - timedelta(days=1),
        date_to=max(dates) + timedelta(days=30),
        fetched_at=datetime.now(),
    )
    session.add(row)
    session.commit()
    return row


def _add_record(
    session,
    plan_day,
    *,
    content=_UNSET,
    status="synced",
    workout_id="workout-old",
    schedule_id="schedule-old",
):
    current_hash = source_hash(plan_day)
    row = GarminPlanSync(
        plan_ref=plan_day["plan_ref"],
        training_date=date.fromisoformat(plan_day["date"]),
        source_key=source_key_for(plan_day["plan_ref"], plan_day["date"]),
        source_hash=current_hash,
        content_hash=(
            content_hash(plan_day) if content is _UNSET else content
        ),
        synced_hash=current_hash,
        payload_json="{}",
        workout_id=workout_id,
        workout_schedule_id=schedule_id,
        status=status,
        phase="verify",
        attempt_count=2,
        synced_at=datetime(2026, 11, 10, 12, 0, 0),
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture(autouse=True)
def forbid_garmin(monkeypatch):
    factory = Mock(side_effect=AssertionError("顺延检测不得实例化 Garmin 适配器"))
    monkeypatch.setattr(GarminWorkoutAdapter, "from_settings", factory)
    yield factory


def test_unique_next_day_candidate_is_local_and_idempotent(session, forbid_garmin):
    old_day = _plan_day()
    target_day = _plan_day(TARGET_DATE)
    record = _add_record(session, old_day)
    _set_cache(session, [target_day])
    original = (
        record.training_date,
        record.source_key,
        record.source_hash,
        record.synced_hash,
        record.payload_json,
        record.workout_id,
        record.workout_schedule_id,
        record.attempt_count,
    )

    result = detect_reschedule_candidates(session)

    assert result["pending"] == 1
    assert result["conflicts"] == 0
    assert result["changed_records"] == 1
    assert record.status == "reschedule_pending"
    assert record.phase == "reschedule"
    assert record.reschedule_to_date == TARGET_DATE
    assert original == (
        record.training_date,
        record.source_key,
        record.source_hash,
        record.synced_hash,
        record.payload_json,
        record.workout_id,
        record.workout_schedule_id,
        record.attempt_count,
    )
    candidate = result["items"][0]
    assert candidate["from_date"] == OLD_DATE.isoformat()
    assert candidate["to_date"] == TARGET_DATE.isoformat()
    assert candidate["previous_source_hash"] == source_hash(old_day)
    assert candidate["source_hash"] == source_hash(target_day)
    assert candidate["content_hash"] == content_hash(old_day)
    assert list_reschedule_candidates(session) == [candidate]
    forbid_garmin.assert_not_called()

    second = detect_reschedule_candidates(session)
    assert second["pending"] == 1
    assert second["changed_records"] == 0
    assert session.query(GarminPlanSync).count() == 1


def test_legacy_record_backfills_only_while_source_day_exists(session):
    record = _add_record(session, _plan_day(), content=None)
    _set_cache(session, [_plan_day()])

    result = detect_reschedule_candidates(session)

    assert result["backfilled"] == 1
    assert record.content_hash == content_hash(_plan_day())
    assert record.status == "synced"
    assert record.reschedule_to_date is None


def test_legacy_record_without_old_source_is_not_guessed(session):
    record = _add_record(session, _plan_day(), content=None)
    _set_cache(session, [_plan_day(TARGET_DATE)])

    result = detect_reschedule_candidates(session)

    assert result["pending"] == 0
    assert result["backfilled"] == 0
    assert record.status == "synced"
    assert record.content_hash is None


def test_same_day_content_change_is_update_not_reschedule(session):
    old_day = _plan_day()
    changed_day = _plan_day(weight=22.5)
    record = _add_record(session, old_day)
    _set_cache(session, [changed_day])

    result = detect_reschedule_candidates(session)

    assert result["pending"] == 0
    assert record.status == "synced"
    assert record.content_hash == content_hash(changed_day)
    view = sync_status_view(
        record,
        source_key=record.source_key,
        source_hash=source_hash(changed_day),
    )
    assert view["status"] == "update_available"


def test_first_cross_day_association_requires_same_content(session):
    record = _add_record(session, _plan_day())
    _set_cache(session, [_plan_day(TARGET_DATE, weight=22.5)])

    result = detect_reschedule_candidates(session)

    assert result["pending"] == 0
    assert record.status == "synced"
    assert record.reschedule_to_date is None


def test_existing_target_record_becomes_conflict_without_id_changes(session):
    record = _add_record(session, _plan_day())
    target = _add_record(
        session,
        _plan_day(TARGET_DATE),
        workout_id="workout-target",
        schedule_id="schedule-target",
    )
    _set_cache(session, [_plan_day(TARGET_DATE)])

    result = detect_reschedule_candidates(session)

    assert result["pending"] == 0
    assert result["conflicts"] == 1
    assert record.status == "conflict"
    assert record.error_code == "RESCHEDULE_TARGET_CONFLICT"
    assert record.workout_id == "workout-old"
    assert record.workout_schedule_id == "schedule-old"
    assert target.workout_id == "workout-target"


def test_duplicate_target_candidates_are_ambiguous(session):
    record = _add_record(session, _plan_day())
    _set_cache(session, [_plan_day(TARGET_DATE), _plan_day(TARGET_DATE)])

    result = detect_reschedule_candidates(session)

    assert result["pending"] == 0
    assert result["conflicts"] == 1
    assert record.error_code == "RESCHEDULE_CANDIDATE_AMBIGUOUS"


def test_pending_candidate_tracks_content_then_handles_missing_target(session):
    record = _add_record(session, _plan_day())
    _set_cache(session, [_plan_day(TARGET_DATE)])
    detect_reschedule_candidates(session)

    _set_cache(session, [_plan_day(TARGET_DATE, weight=22.5)])
    changed = detect_reschedule_candidates(session)
    assert changed["pending"] == 1
    assert record.status == "reschedule_pending"
    assert record.content_hash == content_hash(_plan_day(TARGET_DATE, weight=22.5))
    assert changed["items"][0]["source_hash"] == source_hash(
        _plan_day(TARGET_DATE, weight=22.5)
    )

    session.query(XunjiPlan).delete()
    session.commit()
    missing = detect_reschedule_candidates(session)
    assert missing["pending"] == 0
    assert missing["conflicts"] == 1
    assert record.error_code == "RESCHEDULE_TARGET_MISSING"

    _set_cache(session, [_plan_day(TARGET_DATE, weight=22.5)])
    restored = detect_reschedule_candidates(session)
    assert restored["pending"] == 1
    assert record.status == "reschedule_pending"


def test_old_plan_return_clears_pending_without_remote_write(session):
    record = _add_record(session, _plan_day())
    _set_cache(session, [_plan_day(TARGET_DATE)])
    detect_reschedule_candidates(session)

    _set_cache(session, [_plan_day()])
    result = detect_reschedule_candidates(session)

    assert result["pending"] == 0
    assert record.status == "synced"
    assert record.phase == "verify"
    assert record.reschedule_to_date is None
    assert record.source_hash == record.synced_hash


def test_unsynced_record_is_not_a_reschedule_candidate(session):
    record = _add_record(
        session,
        _plan_day(),
        status="pending",
        workout_id=None,
        schedule_id=None,
    )
    record.synced_hash = None
    session.commit()
    _set_cache(session, [_plan_day(TARGET_DATE)])

    result = detect_reschedule_candidates(session)

    assert result["pending"] == 0
    assert record.status == "pending"
    assert record.reschedule_to_date is None


def test_normal_sync_cannot_bypass_pending_reschedule(session):
    target_day = _plan_day(TARGET_DATE)
    _add_record(session, _plan_day())
    _set_cache(session, [target_day])
    detect_reschedule_candidates(session)

    with pytest.raises(PlanSyncError) as caught:
        claim_plan_sync(
            session,
            target_day,
            expected_source_hash=source_hash(target_day),
            enabled=True,
        )

    assert caught.value.error_code == "RESCHEDULE_CONFIRMATION_REQUIRED"
    assert session.query(GarminPlanSync).count() == 1


@pytest.fixture
def client(env_vars, session, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.db import get_session
    from app.main import app

    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_candidate_api_and_upcoming_status_are_read_only(client, session, forbid_garmin):
    today = date.today()
    old_day = _plan_day(today - timedelta(days=1))
    target_day = _plan_day(today)
    _add_record(session, old_day)
    _set_cache(session, [target_day])
    detect_reschedule_candidates(session)
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/plans/garmin/reschedules", headers=auth)
    upcoming = client.get("/api/plans/upcoming?days=1", headers=auth)
    status = client.get(f"/api/plans/{today.isoformat()}/garmin/sync", headers=auth)

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["items"][0]["to_date"] == today.isoformat()
    assert upcoming.json()["days"][0]["garmin_sync"]["status"] == "reschedule_pending"
    assert status.json()["status"] == "reschedule_pending"
    assert status.json()["reschedule_from_date"] == old_day["date"]
    assert status.json()["reschedule_to_date"] == target_day["date"]
    forbid_garmin.assert_not_called()


def test_consecutive_candidate_api_uses_current_synced_date(
    client, session, forbid_garmin
):
    today = date.today()
    original_date = today - timedelta(days=2)
    current_date = today - timedelta(days=1)
    current_day = _plan_day(current_date)
    target_day = _plan_day(today)
    record = _add_record(session, current_day)
    record.reschedule_from_date = original_date
    record.reschedule_source_key = source_key_for(PLAN_REF, original_date)
    record.reschedule_to_date = current_date
    session.commit()
    _set_cache(session, [target_day])
    detect_reschedule_candidates(session)
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    candidates = client.get("/api/plans/garmin/reschedules", headers=auth)
    status = client.get(f"/api/plans/{today.isoformat()}/garmin/sync", headers=auth)

    assert candidates.status_code == 200
    assert candidates.json()["items"][0]["from_date"] == current_date.isoformat()
    assert candidates.json()["items"][0]["to_date"] == today.isoformat()
    assert status.status_code == 200
    assert status.json()["status"] == "reschedule_pending"
    assert status.json()["reschedule_from_date"] == current_date.isoformat()
    assert status.json()["reschedule_to_date"] == today.isoformat()
    assert record.training_date == current_date
    assert record.source_hash == source_hash(current_day)
    forbid_garmin.assert_not_called()
