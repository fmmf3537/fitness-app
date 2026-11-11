"""顺延预览与确认 HTTP 契约；manager 只写本地状态，不真实外呼。"""
import json
from datetime import date, datetime, timedelta

import pytest

import app.main  # noqa: F401
from app.adapters.garmin_workout_adapter import GarminWorkoutAdapter
from app.models import GarminPlanSync, XunjiPlan
from app.services.garmin_reschedule import (
    claim_reschedule,
    detect_reschedule_candidates,
    get_garmin_reschedule_manager,
)
from app.services.garmin_plan_sync import source_key_for, sync_status_view
from app.services.garmin_workout_mapper import map_plan_day, source_hash

OLD_DAY = date(2026, 11, 10)
TARGET_DAY = OLD_DAY + timedelta(days=1)
PLAN_REF = "platform:155"


def _plan(day):
    return {
        "plan_ref": PLAN_REF,
        "plan_name": "增肌计划",
        "date": day.isoformat(),
        "title": "胸部训练",
        "movements": [{
            "name": "杠铃卧推",
            "rest_seconds": 60,
            "target_sets": [{"weight": 20, "unit": "kg", "reps": 8}],
        }],
    }


def _prepare(session):
    old = _plan(OLD_DAY)
    target = _plan(TARGET_DAY)
    preview = map_plan_day(old)
    session.add(GarminPlanSync(
        plan_ref=PLAN_REF,
        training_date=OLD_DAY,
        source_key=preview["source_key"],
        source_hash=preview["source_hash"],
        content_hash=preview["content_hash"],
        synced_hash=preview["source_hash"],
        payload_json=json.dumps(preview["workout"], ensure_ascii=False),
        workout_id="w-old",
        workout_schedule_id="s-old",
        status="synced",
        phase="verify",
        attempt_count=2,
        synced_at=datetime.now(),
    ))
    session.add(XunjiPlan(
        plan_ref=PLAN_REF,
        plan_json=json.dumps({
            "plan": {"plan_ref": PLAN_REF, "name": "增肌计划"},
            "days": [{
                "datestr": TARGET_DAY.isoformat(),
                "workout": {"name": target["title"], "movements": target["movements"]},
            }],
        }, ensure_ascii=False),
        date_from=OLD_DAY,
        date_to=TARGET_DAY + timedelta(days=30),
    ))
    session.commit()
    detect_reschedule_candidates(session)
    return target


class ClaimOnlyManager:
    def start(self, session, *, from_date, target_date, expected_source_hash, enabled):
        record, started = claim_reschedule(
            session,
            from_date=from_date,
            target_date=target_date,
            expected_source_hash=expected_source_hash,
            enabled=enabled,
        )
        view_date = record.reschedule_to_date or record.training_date
        return {
            "started": started,
            "sync": sync_status_view(
                record,
                source_key=source_key_for(record.plan_ref, view_date),
                source_hash=record.source_hash,
            ),
        }


@pytest.fixture
def client(env_vars, session, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.db import get_session
    from app.main import app

    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    monkeypatch.setenv("GARMIN_PLAN_SYNC_ENABLED", "1")
    get_settings.cache_clear()
    monkeypatch.setattr(
        GarminWorkoutAdapter,
        "from_settings",
        lambda _: (_ for _ in ()).throw(AssertionError("API 测试不得外呼")),
    )

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_garmin_reschedule_manager] = lambda: ClaimOnlyManager()
    with TestClient(app) as test_client:
        token = test_client.post(
            "/api/auth/login", json={"password": "test-pass"}
        ).json()["token"]
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_preview_and_confirm_contract_without_remote_call(client, session):
    target = _prepare(session)
    response = client.get(
        f"/api/plans/{OLD_DAY}/garmin/reschedule",
        params={"to_date": TARGET_DAY.isoformat()},
    )
    assert response.status_code == 200
    assert response.json()["from_date"] == OLD_DAY.isoformat()
    assert response.json()["source_hash"] == source_hash(target)
    assert response.json()["sync"]["status"] == "reschedule_pending"
    assert session.query(GarminPlanSync).one().attempt_count == 2

    confirmed = client.post(
        f"/api/plans/{OLD_DAY}/garmin/reschedule",
        json={"to_date": TARGET_DAY.isoformat(), "source_hash": source_hash(target)},
    )
    assert confirmed.status_code == 202
    assert confirmed.json()["started"] is True
    assert confirmed.json()["sync"]["status"] == "syncing"
    record = session.query(GarminPlanSync).one()
    assert record.training_date == OLD_DAY
    assert record.reschedule_from_date == OLD_DAY
    assert record.reschedule_source_key == source_key_for(PLAN_REF, OLD_DAY)
    assert record.attempt_count == 3


def test_success_replay_returns_200_without_new_attempt(client, session):
    target = _prepare(session)
    payload = {"to_date": TARGET_DAY.isoformat(), "source_hash": source_hash(target)}
    first = client.post(f"/api/plans/{OLD_DAY}/garmin/reschedule", json=payload)
    assert first.status_code == 202
    record = session.query(GarminPlanSync).one()
    # ClaimOnlyManager 不外呼；这里只构造 runner 全部回读成功后的本地提交形态。
    record.training_date = TARGET_DAY
    record.source_key = source_key_for(PLAN_REF, TARGET_DAY)
    record.status = "synced"
    record.phase = "verify"
    record.synced_hash = record.source_hash
    record.synced_at = datetime.now()
    session.commit()

    replay = client.post(f"/api/plans/{OLD_DAY}/garmin/reschedule", json=payload)
    assert replay.status_code == 200
    assert replay.json()["started"] is False
    assert replay.json()["sync"]["status"] == "synced"
    assert session.query(GarminPlanSync).one().attempt_count == 3


def test_stale_hash_running_auth_and_disabled_contract(client, session, monkeypatch):
    target = _prepare(session)
    stale = client.post(
        f"/api/plans/{OLD_DAY}/garmin/reschedule",
        json={"to_date": TARGET_DAY.isoformat(), "source_hash": "0" * 64},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "PLAN_CHANGED"

    good = {"to_date": TARGET_DAY.isoformat(), "source_hash": source_hash(target)}
    assert client.post(f"/api/plans/{OLD_DAY}/garmin/reschedule", json=good).status_code == 202
    running = client.post(f"/api/plans/{OLD_DAY}/garmin/reschedule", json=good)
    assert running.status_code == 409
    assert running.json()["detail"]["code"] == "SYNC_ALREADY_RUNNING"

    client.headers.pop("Authorization")
    assert client.post(
        f"/api/plans/{OLD_DAY}/garmin/reschedule", json=good
    ).status_code == 401


def test_disabled_feature_returns_503(client, session, monkeypatch):
    from app.config import get_settings

    target = _prepare(session)
    monkeypatch.setenv("GARMIN_PLAN_SYNC_ENABLED", "0")
    get_settings.cache_clear()
    response = client.post(
        f"/api/plans/{OLD_DAY}/garmin/reschedule",
        json={"to_date": TARGET_DAY.isoformat(), "source_hash": source_hash(target)},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "GARMIN_PLAN_SYNC_DISABLED"
    assert session.query(GarminPlanSync).one().status == "reschedule_pending"


def test_stale_reschedule_list_recovers_and_confirm_retries(client, session):
    target = _prepare(session)
    payload = {"to_date": TARGET_DAY.isoformat(), "source_hash": source_hash(target)}
    assert client.post(
        f"/api/plans/{OLD_DAY}/garmin/reschedule", json=payload
    ).status_code == 202
    record = session.query(GarminPlanSync).one()
    session.query(GarminPlanSync).filter_by(id=record.id).update(
        {GarminPlanSync.updated_at: datetime.now() - timedelta(hours=1)},
        synchronize_session=False,
    )
    session.commit()

    candidates = client.get("/api/plans/garmin/reschedules")

    assert candidates.status_code == 200
    assert candidates.json()["items"][0]["status"] == "failed"
    assert candidates.json()["items"][0]["error_code"] == "GARMIN_SYNC_INTERRUPTED"
    session.refresh(record)
    assert record.status == "failed"
    assert record.training_date == OLD_DAY
    assert record.workout_id == "w-old"
    assert record.workout_schedule_id == "s-old"
    assert record.attempt_count == 3

    confirmed = client.post(f"/api/plans/{OLD_DAY}/garmin/reschedule", json=payload)
    assert confirmed.status_code == 202
    assert confirmed.json()["started"] is True
    session.refresh(record)
    assert record.status == "syncing"
    assert record.attempt_count == 4
