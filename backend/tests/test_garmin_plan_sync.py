"""Garmin 计划同步状态表、只读预览/状态 API 与列表摘要测试。

所有测试只使用临时 SQLite；生产代码不导入 Garmin 客户端，零真实外呼。
"""
import json
from datetime import date, datetime, timedelta

import pytest

import app.main  # noqa: F401  提前加载配置，随后由 env_vars 重设临时数据库
from app.models import GarminPlanSync, XunjiPlan

PLAN_DATE = date(2026, 11, 10)
PLAN_REF = "platform:155"


def _movement(name="哑铃卧推", *, weight=20, reps=10):
    return {
        "name": name,
        "rest_seconds": 60,
        "target_sets": [
            {"weight": weight, "unit": "kg", "reps": reps},
            {"weight": weight, "unit": "kg", "reps": reps},
        ],
    }


def _make_plan(session, movements=None, *, day=PLAN_DATE):
    payload = {
        "plan": {"plan_ref": PLAN_REF, "name": "增肌计划"},
        "days": [
            {
                "datestr": day.isoformat(),
                "workout": {
                    "name": "胸部训练",
                    "movements": movements if movements is not None else [_movement()],
                },
            }
        ],
    }
    row = XunjiPlan(
        plan_ref=PLAN_REF,
        plan_json=json.dumps(payload, ensure_ascii=False),
        date_from=day - timedelta(days=1),
        date_to=day + timedelta(days=60),
    )
    session.add(row)
    session.commit()
    return row


def _add_sync_record(
    session,
    plan_day,
    *,
    status="synced",
    synced_hash=None,
    workout_id="workout-1",
    workout_schedule_id="schedule-1",
):
    from app.services.garmin_plan_sync import source_key_for
    from app.services.garmin_workout_mapper import source_hash

    current_hash = source_hash(plan_day)
    row = GarminPlanSync(
        plan_ref=plan_day["plan_ref"],
        training_date=date.fromisoformat(plan_day["date"]),
        source_key=source_key_for(plan_day["plan_ref"], plan_day["date"]),
        source_hash=current_hash,
        synced_hash=current_hash if synced_hash is None else synced_hash,
        status=status,
        phase="verify",
        workout_id=workout_id,
        workout_schedule_id=workout_schedule_id,
        attempt_count=2,
        synced_at=datetime(2026, 11, 10, 12, 0, 0),
    )
    session.add(row)
    session.commit()
    return row


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


@pytest.fixture
def auth(client):
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_preview_and_status_require_auth(client):
    day = PLAN_DATE.isoformat()
    assert client.get(f"/api/plans/{day}/garmin/preview").status_code == 401
    assert client.get(f"/api/plans/{day}/garmin/sync").status_code == 401


def test_preview_returns_complete_payload_without_persisting_sync(client, auth, session):
    _make_plan(session)

    response = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/preview", headers=auth
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preview_only"] is True
    assert body["remote_write_eligible"] is False
    assert body["source_key"] == f"xunji-plan:v1:{PLAN_REF}:{PLAN_DATE.isoformat()}"
    assert len(body["source_hash"]) == 64
    assert body["stats"] == {
        "movements": 1,
        "sets": 2,
        "warmup_sets": 0,
        "working_sets": 2,
        "repeat_groups": 1,
        "top_level_steps": 1,
        "rest_seconds": 120,
    }
    repeat = body["workout"]["workoutSegments"][0]["workoutSteps"][0]
    assert repeat["type"] == "RepeatGroupDTO"
    assert repeat["numberOfIterations"] == 2
    assert repeat["workoutSteps"][0]["weightValue"] == 20.0
    assert body["sync"]["status"] == "not_synced"
    assert session.query(GarminPlanSync).count() == 0


def test_preview_rejects_all_unknown_movements(client, auth, session):
    _make_plan(session, [_movement("未知动作甲"), _movement("未知动作乙")])

    response = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/preview", headers=auth
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "PLAN_MAPPING_UNSUPPORTED"
    assert [issue["movement"] for issue in detail["issues"]] == ["未知动作甲", "未知动作乙"]
    assert all(issue["code"] == "UNKNOWN_EXERCISE" for issue in detail["issues"])


def test_missing_training_day_returns_404(client, auth):
    for endpoint in ("preview", "sync"):
        response = client.get(
            f"/api/plans/{PLAN_DATE.isoformat()}/garmin/{endpoint}", headers=auth
        )
        assert response.status_code == 404


def test_status_without_record_is_not_synced(client, auth, session):
    _make_plan(session)

    response = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/sync", headers=auth
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_synced"
    assert body["workout_id"] is None
    assert body["workout_schedule_id"] is None
    assert body["attempt_count"] == 0


def test_matching_verified_hash_and_ids_is_synced(client, auth, session):
    _make_plan(session)
    from app.services.plans import query_plan_day

    plan_day = query_plan_day(session, PLAN_DATE)
    _add_sync_record(session, plan_day)

    response = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/sync", headers=auth
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "synced"
    assert body["phase"] == "verify"
    assert body["workout_id"] == "workout-1"
    assert body["workout_schedule_id"] == "schedule-1"
    assert body["attempt_count"] == 2
    assert body["synced_at"] == "2026-11-10T12:00:00"


def test_plan_change_marks_update_and_upcoming_matches_preview(client, auth, session):
    today = date.today()
    row = _make_plan(session, day=today)
    from app.services.plans import query_plan_day

    _add_sync_record(session, query_plan_day(session, today))
    payload = json.loads(row.plan_json)
    payload["days"][0]["workout"]["movements"][0]["target_sets"][0]["weight"] = 22.5
    row.plan_json = json.dumps(payload, ensure_ascii=False)
    session.commit()

    status_response = client.get(
        f"/api/plans/{today.isoformat()}/garmin/sync", headers=auth
    )
    preview_response = client.get(
        f"/api/plans/{today.isoformat()}/garmin/preview", headers=auth
    )
    upcoming_response = client.get("/api/plans/upcoming?days=1", headers=auth)

    assert status_response.status_code == 200
    assert preview_response.status_code == 200
    assert upcoming_response.status_code == 200
    assert status_response.json()["status"] == "update_available"
    assert preview_response.json()["sync"] == status_response.json()
    assert upcoming_response.json()["days"][0]["garmin_sync"] == status_response.json()


@pytest.mark.parametrize("status", ["pending", "syncing", "failed", "conflict", "source_removed"])
def test_unfinished_statuses_are_preserved(client, auth, session, status):
    _make_plan(session)
    from app.services.plans import query_plan_day

    record = _add_sync_record(
        session,
        query_plan_day(session, PLAN_DATE),
        status=status,
        synced_hash="",
        workout_id=None,
        workout_schedule_id=None,
    )
    record.phase = "create"
    record.error_code = "TEST_ERROR"
    record.last_error = "脱敏错误"
    session.commit()

    response = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/sync", headers=auth
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == status
    assert body["phase"] == "create"
    assert body["error_code"] == "TEST_ERROR"
    assert body["last_error"] == "脱敏错误"


def test_upcoming_adds_training_summary_and_rest_null(client, auth, session):
    today = date.today()
    _make_plan(session, day=today)

    response = client.get("/api/plans/upcoming?days=2", headers=auth)

    assert response.status_code == 200
    days = response.json()["days"]
    assert days[0]["garmin_sync"]["status"] == "not_synced"
    assert len(days[0]["garmin_sync"]["source_hash"]) == 64
    assert days[0]["movements"][0] == {
        "name": "哑铃卧推",
        "target_sets": _movement()["target_sets"],
    }
    assert "_garmin_source" not in days[0]
    assert days[1]["is_rest"] is True
    assert days[1]["garmin_sync"] is None


def test_sync_post_is_disabled_by_default(client, auth, session):
    _make_plan(session)
    from app.services.garmin_workout_mapper import source_hash
    from app.services.plans import query_plan_day

    current_hash = source_hash(query_plan_day(session, PLAN_DATE))
    response = client.post(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/sync",
        headers=auth,
        json={"source_hash": current_hash},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "GARMIN_PLAN_SYNC_DISABLED"
    assert session.query(GarminPlanSync).count() == 0
