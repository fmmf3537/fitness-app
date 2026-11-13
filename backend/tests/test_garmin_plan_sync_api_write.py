"""确认同步 POST 的 HTTP 契约；manager 只 claim，不真实启动 Garmin 外呼。"""
import json
from datetime import date, datetime, timedelta

import pytest

import app.main  # noqa: F401
from app.models import GarminPlanSync, XunjiPlan
from app.services.garmin_plan_sync import (
    claim_plan_sync,
    get_garmin_plan_sync_manager,
    sync_status_view,
)
from app.services.garmin_workout_mapper import source_hash
from app.services.plans import query_plan_day

DAY = date(2026, 11, 12)
PLAN_REF = "platform:155"


def make_plan(session, movement="杠铃卧推"):
    payload = {
        "plan": {"plan_ref": PLAN_REF, "name": "增肌计划"},
        "days": [{
            "datestr": DAY.isoformat(),
            "workout": {
                "name": "胸部训练",
                "movements": [{
                    "name": movement, "rest_seconds": 60,
                    "target_sets": [{"weight": 20, "unit": "kg", "reps": 8}],
                }],
            },
        }],
    }
    row = XunjiPlan(
        plan_ref=PLAN_REF,
        plan_json=json.dumps(payload, ensure_ascii=False),
        date_from=DAY - timedelta(days=1), date_to=DAY + timedelta(days=30),
    )
    session.add(row)
    session.commit()


class ClaimOnlyManager:
    def start(self, session, plan_day, *, expected_source_hash, enabled):
        record, started = claim_plan_sync(
            session, plan_day,
            expected_source_hash=expected_source_hash, enabled=enabled,
        )
        return {
            "started": started,
            "sync": sync_status_view(
                record, source_key=record.source_key, source_hash=record.source_hash
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

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_garmin_plan_sync_manager] = lambda: ClaimOnlyManager()
    with TestClient(app) as test_client:
        token = test_client.post(
            "/api/auth/login", json={"password": "test-pass"}
        ).json()["token"]
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def current_hash(session):
    return source_hash(query_plan_day(session, DAY))


def test_confirm_post_returns_202_and_claims_without_remote_call(client, session):
    make_plan(session)
    preview = client.get(f"/api/plans/{DAY}/garmin/preview")
    assert preview.status_code == 200
    assert preview.json()["remote_write_eligible"] is True

    response = client.post(
        f"/api/plans/{DAY}/garmin/sync",
        json={"source_hash": preview.json()["source_hash"]},
    )

    assert response.status_code == 202
    assert response.json()["started"] is True
    assert response.json()["sync"]["status"] == "syncing"
    record = session.query(GarminPlanSync).one()
    assert record.status == "syncing"
    assert record.attempt_count == 1


def test_confirm_post_requires_auth(client, session):
    make_plan(session)
    client.headers.pop("Authorization")
    response = client.post(
        f"/api/plans/{DAY}/garmin/sync", json={"source_hash": "0" * 64}
    )
    assert response.status_code == 401


def test_stale_preview_hash_returns_structured_409(client, session):
    make_plan(session)
    response = client.post(
        f"/api/plans/{DAY}/garmin/sync", json={"source_hash": "0" * 64}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PLAN_CHANGED"
    assert session.query(GarminPlanSync).count() == 0


def test_unknown_exercise_returns_all_mapping_issues(client, session):
    """全部动作都无法映射时整体仍是失败（ADR-P0-3b 后契约有变）。

    ADR §7 引入部分同步后：单个未知动作会被跳过、其余照常写入（见
    test_plan_sync_partial.py）；但当天**没有任何可写动作**时不得创建空 Workout，
    必须整体失败（ADR §7.2 边界行为第 2 条），错误细项改为 NO_WRITABLE_MOVEMENTS。
    """
    make_plan(session, movement="未映射动作")
    response = client.post(
        f"/api/plans/{DAY}/garmin/sync", json={"source_hash": current_hash(session)}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "PLAN_MAPPING_UNSUPPORTED"
    assert detail["issues"][0]["code"] == "NO_WRITABLE_MOVEMENTS"
    # 缺口明细必须携带，便于前端说明"哪些动作被跳过"
    assert [m["name"] for m in detail["skipped"]] == ["未映射动作"]
    assert detail["skipped"][0]["reason"] == "UNKNOWN_EXERCISE"


def test_already_synced_returns_200_without_new_attempt(client, session):
    make_plan(session)
    plan_day = query_plan_day(session, DAY)
    current = source_hash(plan_day)
    session.add(GarminPlanSync(
        plan_ref=PLAN_REF, training_date=DAY,
        source_key=f"xunji-plan:v1:{PLAN_REF}:{DAY}",
        source_hash=current, synced_hash=current,
        workout_id="w1", workout_schedule_id="s1",
        status="synced", phase="verify", attempt_count=3,
    ))
    session.commit()

    response = client.post(
        f"/api/plans/{DAY}/garmin/sync", json={"source_hash": current}
    )
    assert response.status_code == 200
    assert response.json()["started"] is False
    assert response.json()["sync"]["status"] == "synced"
    assert session.query(GarminPlanSync).one().attempt_count == 3


def test_running_claim_returns_409(client, session):
    make_plan(session)
    plan_day = query_plan_day(session, DAY)
    current = source_hash(plan_day)
    session.add(GarminPlanSync(
        plan_ref=PLAN_REF, training_date=DAY,
        source_key=f"xunji-plan:v1:{PLAN_REF}:{DAY}", source_hash=current,
        status="syncing", phase="create", attempt_count=1,
    ))
    session.commit()

    response = client.post(
        f"/api/plans/{DAY}/garmin/sync", json={"source_hash": current}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SYNC_ALREADY_RUNNING"


def test_stale_running_status_recovers_and_confirm_retries(client, session):
    make_plan(session)
    plan_day = query_plan_day(session, DAY)
    current = source_hash(plan_day)
    record = GarminPlanSync(
        plan_ref=PLAN_REF,
        training_date=DAY,
        source_key=f"xunji-plan:v1:{PLAN_REF}:{DAY}",
        source_hash=current,
        status="syncing",
        phase="create",
        attempt_count=1,
        updated_at=datetime.now() - timedelta(hours=1),
    )
    session.add(record)
    session.commit()

    status = client.get(f"/api/plans/{DAY}/garmin/sync")

    assert status.status_code == 200
    assert status.json()["status"] == "failed"
    assert status.json()["error_code"] == "GARMIN_SYNC_INTERRUPTED"
    session.refresh(record)
    assert record.status == "failed"
    assert record.attempt_count == 1

    confirmed = client.post(
        f"/api/plans/{DAY}/garmin/sync", json={"source_hash": current}
    )
    assert confirmed.status_code == 202
    assert confirmed.json()["started"] is True
    session.refresh(record)
    assert record.status == "syncing"
    assert record.attempt_count == 2
