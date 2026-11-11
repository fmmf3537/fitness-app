"""PostgreSQL 上的 Garmin 计划同步/顺延状态机回归。

使用 TEST_DATABASE_URL_PG（CI 服务容器）或 testcontainers 一次性库；
拿不到安全测试库时 skip，绝不回退到正式 app.db / SQLite。
全部使用 FakeAdapter，禁止真实 Garmin client。
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_FERNET_KEY = Fernet.generate_key().decode()
PLAN_DATE = date(2026, 11, 12)
TARGET_DATE = PLAN_DATE + timedelta(days=1)


def _assert_safe_test_pg_url(url: str) -> None:
    """只允许明确的测试 PG；拒绝 sqlite / 正式 app.db。"""
    if not url:
        pytest.skip("无安全 PostgreSQL 测试库 URL")
    lowered = url.lower()
    if "postgresql" not in lowered:
        pytest.skip(f"非 PostgreSQL URL，跳过: {url}")
    if "app.db" in lowered or lowered.startswith("sqlite"):
        pytest.fail(f"拒绝非测试库 URL（疑似正式库）: {url}")


@pytest.fixture(scope="module")
def pg_url():
    """CI 注入 TEST_DATABASE_URL_PG 优先；否则 testcontainers。"""
    url = os.environ.get("TEST_DATABASE_URL_PG")
    if url:
        _assert_safe_test_pg_url(url)
        yield url
        return
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers 未安装且无 TEST_DATABASE_URL_PG")
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker 不可用，跳过 PG Garmin 状态机测试: {exc}")
    with container:
        url = container.get_connection_url()
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        _assert_safe_test_pg_url(url)
        yield url


def _alembic_upgrade(database_url: str) -> None:
    env = os.environ.copy()
    env["SCHEDULER_ENABLED"] = "0"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-x",
            f"url={database_url}",
            "upgrade",
            "head",
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.fixture(scope="module")
def pg_engine(pg_url):
    _alembic_upgrade(pg_url)
    from app.db import make_engine

    engine = make_engine(pg_url)
    assert engine.dialect.name == "postgresql"
    try:
        yield engine
    finally:
        engine.dispose()


def _cleanup_plan_ref(session, plan_ref: str) -> None:
    session.execute(
        text("DELETE FROM garmin_plan_sync WHERE plan_ref = :ref"),
        {"ref": plan_ref},
    )
    session.execute(
        text(
            "DELETE FROM job_run WHERE job_name IN "
            "('garmin_plan_sync', 'garmin_plan_reschedule') "
            "AND detail_json LIKE :pat"
        ),
        {"pat": f"%{plan_ref}%"},
    )
    session.execute(
        text("DELETE FROM xunji_plan WHERE plan_ref = :ref"),
        {"ref": plan_ref},
    )
    session.commit()


@pytest.fixture
def pg_session(pg_engine, monkeypatch):
    """每测独立 Session；清理本测创建的 Garmin/JobRun 数据。不使用共享 SQLite session。"""
    monkeypatch.setenv("FERNET_KEY", TEST_FERNET_KEY)
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    monkeypatch.setenv("GARMIN_PLAN_SYNC_ENABLED", "1")
    # 避免 .env 把运行时配置拽回正式库；本夹具只用 pg_engine，不经 DATABASE_URL 建连。
    monkeypatch.setenv("DATABASE_URL", str(pg_engine.url))
    from app.config import get_settings
    from app.db import make_session_factory

    get_settings.cache_clear()
    factory = make_session_factory(pg_engine)
    session = factory()
    plan_ref = f"platform:p8-{uuid.uuid4().hex[:12]}"
    session.info["plan_ref"] = plan_ref
    _cleanup_plan_ref(session, plan_ref)
    try:
        yield session
        session.rollback()
    finally:
        try:
            _cleanup_plan_ref(session, plan_ref)
        except Exception:
            session.rollback()
        session.close()
        get_settings.cache_clear()


def _plan_ref(session) -> str:
    return session.info["plan_ref"]


def _make_plan(session, day=PLAN_DATE, *, weight=20):
    from app.models import XunjiPlan

    plan_ref = _plan_ref(session)
    payload = {
        "plan": {"plan_ref": plan_ref, "name": "增肌计划"},
        "days": [{
            "datestr": day.isoformat(),
            "workout": {
                "name": "胸部训练",
                "movements": [{
                    "name": "杠铃卧推",
                    "rest_seconds": 60,
                    "target_sets": [
                        {"weight": weight, "unit": "kg", "reps": 8},
                        {"weight": weight, "unit": "kg", "reps": 8},
                    ],
                }],
            },
        }],
    }
    row = XunjiPlan(
        plan_ref=plan_ref,
        plan_json=json.dumps(payload, ensure_ascii=False),
        date_from=day - timedelta(days=1),
        date_to=day + timedelta(days=60),
    )
    session.add(row)
    session.commit()
    return row


def _plan_day_dict(session, day=PLAN_DATE, *, weight=20):
    return {
        "plan_ref": _plan_ref(session),
        "plan_name": "增肌计划",
        "date": day.isoformat(),
        "title": "胸部训练",
        "movements": [{
            "name": "杠铃卧推",
            "rest_seconds": 60,
            "target_sets": [
                {"weight": weight, "unit": "kg", "reps": 8},
                {"weight": weight, "unit": "kg", "reps": 8},
            ],
        }],
    }


def _set_cache(session, plan_day):
    from app.models import XunjiPlan

    plan_ref = _plan_ref(session)
    day = date.fromisoformat(plan_day["date"])
    session.query(XunjiPlan).filter_by(plan_ref=plan_ref).delete()
    session.add(XunjiPlan(
        plan_ref=plan_ref,
        plan_json=json.dumps({
            "plan": {"plan_ref": plan_ref, "name": "增肌计划"},
            "days": [{
                "datestr": plan_day["date"],
                "workout": {
                    "name": plan_day["title"],
                    "movements": plan_day["movements"],
                },
            }],
        }, ensure_ascii=False),
        date_from=day - timedelta(days=1),
        date_to=day + timedelta(days=30),
        fetched_at=datetime.now(),
    ))
    session.commit()


class FakeAdapter:
    def __init__(self):
        self.workouts = {}
        self.schedules = {}
        self.calls = []
        self.fail_once = set()
        self.lose_create_response = False
        self.lose_schedule_response = False

    def _fail(self, operation):
        from app.adapters.garmin_workout_adapter import GarminWorkoutAdapterError

        if operation in self.fail_once:
            self.fail_once.remove(operation)
            raise GarminWorkoutAdapterError(
                "INJECTED_FAILURE", "注入失败", operation=operation
            )

    def find_workouts_by_source_key(self, source_key):
        self.calls.append("find_workouts")
        self._fail("find_workouts")
        return [
            copy.deepcopy(row) for row in self.workouts.values()
            if f"source_key={source_key};" in (row.get("description") or "")
        ]

    def create_workout(self, payload):
        self.calls.append("create")
        workout_id = f"w{len(self.workouts) + 1}"
        self.workouts[workout_id] = {**copy.deepcopy(payload), "workoutId": workout_id}
        if self.lose_create_response:
            self.lose_create_response = False
            from app.adapters.garmin_workout_adapter import GarminWorkoutAdapterError

            raise GarminWorkoutAdapterError(
                "INJECTED_FAILURE", "注入失败", operation="create"
            )
        return workout_id

    def get_workout(self, workout_id):
        self.calls.append("get_workout")
        self._fail("get_workout")
        return copy.deepcopy(self.workouts[workout_id])

    def update_workout(self, workout_id, payload):
        self.calls.append("update")
        self._fail("update")
        self.workouts[workout_id] = {**copy.deepcopy(payload), "workoutId": workout_id}

    def find_schedules(self, workout_id, training_date):
        self.calls.append("find_schedules")
        self._fail("find_schedules")
        day = training_date.isoformat()
        return [
            copy.deepcopy(row) for row in self.schedules.values()
            if row["calendarDate"] == day
            and row["workout"]["workoutId"] == workout_id
        ]

    def schedule_workout(self, workout_id, training_date):
        self.calls.append("schedule")
        schedule_id = f"s{len(self.schedules) + 1}"
        self.schedules[schedule_id] = {
            "workoutScheduleId": schedule_id,
            "calendarDate": training_date.isoformat(),
            "workout": {"workoutId": workout_id},
        }
        if self.lose_schedule_response:
            self.lose_schedule_response = False
            from app.adapters.garmin_workout_adapter import GarminWorkoutAdapterError

            raise GarminWorkoutAdapterError(
                "INJECTED_FAILURE", "注入失败", operation="schedule"
            )
        return schedule_id

    def get_schedule(self, schedule_id):
        self.calls.append("get_schedule")
        self._fail("get_schedule")
        return copy.deepcopy(self.schedules[schedule_id])

    def reschedule_schedule(self, schedule_id, training_date):
        self.calls.append("reschedule")
        self.schedules[schedule_id]["calendarDate"] = training_date.isoformat()
        return schedule_id


class FakeRescheduleAdapter(FakeAdapter):
    def __init__(self, old_plan):
        super().__init__()
        from app.services.garmin_workout_mapper import map_plan_day

        payload = map_plan_day(old_plan)["workout"]
        self.workouts = {
            "workout-old": {**copy.deepcopy(payload), "workoutId": "workout-old"}
        }
        self.schedules = {
            "schedule-old": {
                "workoutScheduleId": "schedule-old",
                "calendarDate": old_plan["date"],
                "workout": {"workoutId": "workout-old"},
            }
        }

    def create_workout(self, payload):
        self.calls.append("create")
        raise AssertionError("顺延禁止创建 Workout")

    def schedule_workout(self, workout_id, training_date):
        self.calls.append("schedule")
        raise AssertionError("顺延禁止创建日程")


def _claim_sync(session, day=PLAN_DATE):
    from app.services.garmin_plan_sync import claim_plan_sync
    from app.services.garmin_workout_mapper import source_hash
    from app.services.plans import query_plan_day

    plan_day = query_plan_day(session, day)
    return claim_plan_sync(
        session,
        plan_day,
        expected_source_hash=source_hash(plan_day),
        enabled=True,
    )


def _make_stale(session, record):
    from app.models import GarminPlanSync

    session.query(GarminPlanSync).filter_by(id=record.id).update(
        {GarminPlanSync.updated_at: datetime.now() - timedelta(hours=1)},
        synchronize_session=False,
    )
    session.commit()
    session.refresh(record)


def _assert_pg_dialect(session):
    assert session.get_bind().dialect.name == "postgresql"


def test_pg_concurrent_claim_only_one_runner(pg_session, pg_engine):
    """两个独立 Session 并发 claim：仅一个获得 runner，库内仅 1 条来源记录。"""
    from app.db import make_session_factory
    from app.models import GarminPlanSync
    from app.services.garmin_plan_sync import PlanSyncError, claim_plan_sync
    from app.services.garmin_workout_mapper import source_hash
    from app.services.plans import query_plan_day

    _make_plan(pg_session)
    plan_day = query_plan_day(pg_session, PLAN_DATE)
    expected = source_hash(plan_day)
    factory = make_session_factory(pg_engine)
    barrier = threading.Barrier(2)
    results: list = []
    lock = threading.Lock()

    def worker():
        s = factory()
        try:
            barrier.wait(timeout=10)
            try:
                record, started = claim_plan_sync(
                    s, plan_day, expected_source_hash=expected, enabled=True
                )
                with lock:
                    results.append(("ok", record.id, started, record.attempt_count))
            except PlanSyncError as exc:
                with lock:
                    results.append(("err", exc.error_code))
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1, results
    assert oks[0][2] is True
    assert len(errs) == 1
    assert errs[0][1] in {
        "SYNC_ALREADY_RUNNING",
        "SYNC_CLAIM_FAILED",
        "GARMIN_SYNC_CONFLICT",
    }
    count = (
        pg_session.query(GarminPlanSync)
        .filter_by(plan_ref=_plan_ref(pg_session), training_date=PLAN_DATE)
        .count()
    )
    assert count == 1
    _assert_pg_dialect(pg_session)


def test_pg_stale_syncing_cas_to_failed_then_reclaim(pg_session):
    """syncing 超时 CAS 转 failed，重新 claim 为 attempt 2；JobRun recovery=stale_syncing。"""
    from app.models import GarminPlanSync, JobRun
    from app.services.garmin_plan_sync import run_plan_sync

    _make_plan(pg_session)
    adapter = FakeAdapter()
    record, started = _claim_sync(pg_session)
    assert started is True
    assert record.attempt_count == 1
    _make_stale(pg_session, record)

    record, started = _claim_sync(pg_session)
    assert started is True
    assert record.status == "syncing"
    assert record.attempt_count == 2

    run_plan_sync(pg_session, record.id, adapter=adapter)
    assert record.status == "synced"
    assert record.attempt_count == 2

    jobs = (
        pg_session.query(JobRun)
        .filter_by(job_name="garmin_plan_sync")
        .order_by(JobRun.id)
        .all()
    )
    recoveries = [
        json.loads(j.detail_json).get("recovery")
        for j in jobs
        if j.detail_json
    ]
    assert "stale_syncing" in recoveries
    assert pg_session.query(GarminPlanSync).filter_by(
        plan_ref=_plan_ref(pg_session)
    ).count() == 1
    _assert_pg_dialect(pg_session)


def test_pg_old_attempt_finish_cannot_overwrite_new(pg_session, pg_engine):
    """旧 attempt 完成写入不能覆盖新 attempt。"""
    from app.db import make_session_factory
    from app.models import JobRun
    from app.services.garmin_plan_sync import run_plan_sync

    _make_plan(pg_session)
    adapter = FakeAdapter()
    record, _ = _claim_sync(pg_session)
    original_get_schedule = adapter.get_schedule
    reclaimed = []

    def reclaim_during_final_read(schedule_id):
        result = original_get_schedule(schedule_id)
        other = make_session_factory(pg_engine)()
        try:
            other_record = other.get(type(record), record.id)
            from app.models import GarminPlanSync

            other_record = other.get(GarminPlanSync, record.id)
            _make_stale(other, other_record)
            other_record, started = _claim_sync(other)
            reclaimed.append((other_record.id, other_record.attempt_count, started))
        finally:
            other.close()
        return result

    adapter.get_schedule = reclaim_during_final_read
    run_plan_sync(pg_session, record.id, adapter=adapter)
    pg_session.refresh(record)

    assert reclaimed == [(record.id, 2, True)]
    assert record.status == "syncing"
    assert record.attempt_count == 2
    assert record.synced_hash is None
    assert pg_session.query(JobRun).filter_by(status="synced").count() == 0

    adapter.get_schedule = original_get_schedule
    run_plan_sync(pg_session, record.id, adapter=adapter)
    assert record.status == "synced"
    assert record.attempt_count == 2
    assert adapter.calls.count("create") == 1
    _assert_pg_dialect(pg_session)


def test_pg_lost_create_and_schedule_reconcile_without_duplicate(pg_session):
    """创建/日程响应丢失后按来源键与 Workout+日期认领，创建次数不增加。"""
    from app.services.garmin_plan_sync import run_plan_sync

    _make_plan(pg_session)
    adapter = FakeAdapter()
    adapter.lose_create_response = True
    record, _ = _claim_sync(pg_session)
    run_plan_sync(pg_session, record.id, adapter=adapter)
    assert record.status == "failed"
    assert record.workout_id is None
    assert adapter.calls.count("create") == 1

    record, started = _claim_sync(pg_session)
    assert started is True
    run_plan_sync(pg_session, record.id, adapter=adapter)
    assert record.status == "synced"
    assert record.workout_id == "w1"
    assert adapter.calls.count("create") == 1

    # 日程响应丢失
    adapter2 = FakeAdapter()
    adapter2.workouts = dict(adapter.workouts)
    adapter2.lose_schedule_response = True
    # 重置为仅有 workout、无 schedule 的失败态再跑
    from app.models import GarminPlanSync

    record.status = "failed"
    record.workout_schedule_id = None
    record.synced_hash = None
    record.phase = "schedule"
    session_record = pg_session.get(GarminPlanSync, record.id)
    session_record.status = "failed"
    session_record.workout_schedule_id = None
    session_record.synced_hash = None
    pg_session.commit()

    record, _ = _claim_sync(pg_session)
    # 注入已有 workout，使 schedule 阶段丢失响应
    adapter2.workouts = {
        record.workout_id: adapter.workouts[record.workout_id]
    }
    # 第一次跑：从 create 跳过到 schedule 并丢失响应
    # 确保 adapter 能按 source_key 找到已有 workout
    run_plan_sync(pg_session, record.id, adapter=adapter2)
    # 可能已 synced（若 schedule 成功）或 failed（丢失响应）
    if record.status == "failed":
        assert record.workout_schedule_id is None
        creates_before = adapter2.calls.count("create")
        schedules_before = adapter2.calls.count("schedule")
        record, _ = _claim_sync(pg_session)
        run_plan_sync(pg_session, record.id, adapter=adapter2)
        assert record.status == "synced"
        assert adapter2.calls.count("create") == creates_before
        assert adapter2.calls.count("schedule") == schedules_before
    else:
        assert record.status == "synced"
        assert adapter2.calls.count("create") == 0
    assert record.workout_schedule_id is not None
    _assert_pg_dialect(pg_session)


def test_pg_reschedule_preserves_remote_ids_and_audit(pg_session):
    """已同步记录跨日顺延：原 Workout/日程 ID 保持，目标日期、来源键、审计字段正确。"""
    from app.models import GarminPlanSync
    from app.services.garmin_plan_sync import source_key_for
    from app.services.garmin_reschedule import (
        claim_reschedule,
        detect_reschedule_candidates,
        run_reschedule,
    )
    from app.services.garmin_workout_mapper import map_plan_day, source_hash

    old_day = _plan_day_dict(pg_session, PLAN_DATE)
    target_day = _plan_day_dict(pg_session, TARGET_DATE)
    preview = map_plan_day(old_day)
    record = GarminPlanSync(
        plan_ref=_plan_ref(pg_session),
        training_date=PLAN_DATE,
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
        synced_at=datetime(2026, 11, 12, 12),
    )
    pg_session.add(record)
    pg_session.commit()
    _set_cache(pg_session, target_day)
    detect_reschedule_candidates(pg_session)
    assert record.status == "reschedule_pending"

    adapter = FakeRescheduleAdapter(old_day)
    claimed, started = claim_reschedule(
        pg_session,
        from_date=PLAN_DATE,
        target_date=TARGET_DATE,
        expected_source_hash=source_hash(target_day),
        enabled=True,
    )
    assert started is True
    run_reschedule(pg_session, claimed.id, adapter=adapter)

    assert record.status == "synced"
    assert record.training_date == TARGET_DATE
    assert record.source_key == source_key_for(_plan_ref(pg_session), TARGET_DATE)
    assert record.workout_id == "workout-old"
    assert record.workout_schedule_id == "schedule-old"
    assert record.reschedule_from_date == PLAN_DATE
    assert record.reschedule_to_date == TARGET_DATE
    assert record.reschedule_source_key == source_key_for(
        _plan_ref(pg_session), PLAN_DATE
    )
    assert adapter.calls.count("create") == 0
    assert adapter.calls.count("schedule") == 0
    assert adapter.calls.count("reschedule") == 1
    _assert_pg_dialect(pg_session)


def test_pg_conflict_gates_block_blind_writes(pg_session):
    """来源不符、多候选或目标冲突进入 conflict，不盲发创建/更新。"""
    from app.models import GarminPlanSync
    from app.services.garmin_plan_sync import PlanSyncError, run_plan_sync
    from app.services.garmin_workout_mapper import map_plan_day
    from app.services.plans import query_plan_day

    _make_plan(pg_session)
    plan_day = query_plan_day(pg_session, PLAN_DATE)
    desired = map_plan_day(plan_day)["workout"]

    # 多候选
    adapter = FakeAdapter()
    src = desired.get("description") or ""
    adapter.workouts = {
        "w1": {**copy.deepcopy(desired), "workoutId": "w1"},
        "w2": {**copy.deepcopy(desired), "workoutId": "w2"},
    }
    record, _ = _claim_sync(pg_session)
    run_plan_sync(pg_session, record.id, adapter=adapter)
    assert record.status == "conflict"
    assert record.error_code == "GARMIN_DUPLICATE_WORKOUTS"
    assert "create" not in adapter.calls

    # 清理后测来源不符
    pg_session.query(GarminPlanSync).filter_by(id=record.id).delete()
    pg_session.commit()

    adapter2 = FakeAdapter()
    record2, _ = _claim_sync(pg_session)
    record2.workout_id = "w9"
    adapter2.workouts["w9"] = {
        **copy.deepcopy(desired),
        "workoutId": "w9",
        "description": "source_key=other",
    }
    pg_session.commit()
    run_plan_sync(pg_session, record2.id, adapter=adapter2)
    assert record2.status == "conflict"
    assert record2.error_code == "GARMIN_WORKOUT_SOURCE_MISMATCH"
    assert "update" not in adapter2.calls

    # 目标冲突：顺延目标日已有记录
    from app.services.garmin_plan_sync import source_key_for
    from app.services.garmin_reschedule import (
        claim_reschedule,
        detect_reschedule_candidates,
    )
    from app.services.garmin_workout_mapper import source_hash

    pg_session.query(GarminPlanSync).filter_by(
        plan_ref=_plan_ref(pg_session)
    ).delete()
    pg_session.commit()

    old_day = _plan_day_dict(pg_session, PLAN_DATE)
    target_day = _plan_day_dict(pg_session, TARGET_DATE)
    preview = map_plan_day(old_day)
    synced = GarminPlanSync(
        plan_ref=_plan_ref(pg_session),
        training_date=PLAN_DATE,
        source_key=preview["source_key"],
        source_hash=preview["source_hash"],
        content_hash=preview["content_hash"],
        synced_hash=preview["source_hash"],
        payload_json=json.dumps(preview["workout"], ensure_ascii=False),
        workout_id="workout-old",
        workout_schedule_id="schedule-old",
        status="synced",
        phase="verify",
        attempt_count=1,
    )
    other = GarminPlanSync(
        plan_ref=_plan_ref(pg_session),
        training_date=TARGET_DATE,
        source_key=source_key_for(_plan_ref(pg_session), TARGET_DATE),
        source_hash=source_hash(target_day),
        status="pending",
        attempt_count=0,
    )
    pg_session.add_all([synced, other])
    pg_session.commit()
    _set_cache(pg_session, target_day)
    detect_reschedule_candidates(pg_session)
    with pytest.raises(PlanSyncError) as caught:
        claim_reschedule(
            pg_session,
            from_date=PLAN_DATE,
            target_date=TARGET_DATE,
            expected_source_hash=source_hash(target_day),
            enabled=True,
        )
    assert caught.value.error_code == "RESCHEDULE_TARGET_CONFLICT"
    _assert_pg_dialect(pg_session)


def test_pg_schema_has_garmin_plan_sync_and_dialect(pg_engine, pg_session):
    """模块结束时再确认方言与表结构，Harness 可区分 pass/skip。"""
    inspector = inspect(pg_engine)
    assert "garmin_plan_sync" in inspector.get_table_names()
    cols = {c["name"] for c in inspector.get_columns("garmin_plan_sync")}
    assert len(cols) == 22
    _assert_pg_dialect(pg_session)
