"""V6-8：L2 目录动作真实创建探针（全部 Fake 适配器，零网络）。"""
from __future__ import annotations

import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import ExerciseMapping
from app.services import exercise_catalog_probe as probe_svc
from app.services.exercise_catalog_probe import (
    PROBE_MAX_ITEMS,
    ProbeResult,
    apply_probe_results,
    build_probe_payload,
    probe_batch,
    probe_one,
)
from app.services.garmin_workout_mapper import (
    CONDITION_REPS,
    NO_TARGET,
    SPORT,
    STEP_INTERVAL,
    WEIGHT_KG,
)


class FakeProbeAdapter:
    """可配置的探针 Fake：记录调用顺序，支持规范化 / 错类 / 异常。"""

    def __init__(
        self,
        *,
        normalize_exercise_to: str | None = None,
        override_category: str | None = None,
        create_error: Exception | None = None,
        get_error: Exception | None = None,
        delete_error: Exception | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.created: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.schedule_calls = 0
        self.reschedule_calls = 0
        self.normalize_exercise_to = normalize_exercise_to
        self.override_category = override_category
        self.create_error = create_error
        self.get_error = get_error
        self.delete_error = delete_error
        self._workouts: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def create_workout(self, payload: dict[str, Any]) -> str:
        self.calls.append("create")
        if self.create_error is not None:
            raise self.create_error
        self._seq += 1
        workout_id = f"probe-{self._seq}"
        stored = copy.deepcopy(payload)
        stored["workoutId"] = workout_id
        if self.normalize_exercise_to is not None or self.override_category is not None:
            for segment in stored.get("workoutSegments") or []:
                for step in segment.get("workoutSteps") or []:
                    if self.normalize_exercise_to is not None:
                        step["exerciseName"] = self.normalize_exercise_to
                    if self.override_category is not None:
                        step["category"] = self.override_category
        self._workouts[workout_id] = stored
        self.created.append(stored)
        return workout_id

    def get_workout(self, workout_id: str) -> dict[str, Any]:
        self.calls.append("get")
        if self.get_error is not None:
            raise self.get_error
        return copy.deepcopy(self._workouts[workout_id])

    def delete_workout(self, workout_id: str) -> None:
        self.calls.append("delete")
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(workout_id)
        self._workouts.pop(workout_id, None)

    def schedule_workout(self, workout_id: str, training_date: Any) -> str:
        self.calls.append("schedule")
        self.schedule_calls += 1
        raise AssertionError("probe must never schedule")

    def reschedule_schedule(self, schedule_id: str, training_date: Any) -> None:
        self.calls.append("reschedule")
        self.reschedule_calls += 1
        raise AssertionError("probe must never reschedule")


def _make_mapping(
    session,
    *,
    xunji_name: str,
    category: str,
    exercise_name: str,
    status: str = "draft",
    verified_level: str = "none",
    note: str | None = None,
) -> ExerciseMapping:
    row = ExerciseMapping(
        xunji_name=xunji_name,
        garmin_category=category,
        garmin_exercise_name=exercise_name,
        garmin_display_name=exercise_name.replace("_", " ").title(),
        weight_strategy="total",
        status=status,
        confidence="high",
        source="test",
        verified_level=verified_level,
        mapping_version=1,
        note=note,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---------- build_probe_payload ----------


def test_build_probe_payload_shape():
    payload = build_probe_payload("BENCH_PRESS", "BARBELL_BENCH_PRESS")
    assert len(payload["workoutSegments"]) == 1
    steps = payload["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 1
    assert payload["sportType"]["sportTypeKey"] == "strength_training"
    assert steps[0]["endConditionValue"] == 1.0
    assert steps[0]["weightValue"] is None
    assert steps[0]["category"] == "BENCH_PRESS"
    assert steps[0]["exerciseName"] == "BARBELL_BENCH_PRESS"


def test_build_probe_payload_name_marked_for_deletion():
    payload = build_probe_payload("LATERAL_RAISE", "LATERAL_RAISE")
    name = payload["workoutName"]
    assert name.startswith("PROBE｜")
    assert "请删除" in name


def test_build_probe_payload_uses_mapper_constants():
    payload = build_probe_payload("SQUAT", "LEG_PRESS")
    step = payload["workoutSegments"][0]["workoutSteps"][0]
    assert payload["sportType"] is SPORT
    assert payload["workoutSegments"][0]["sportType"] is SPORT
    assert step["stepType"] is STEP_INTERVAL
    assert step["endCondition"] is CONDITION_REPS
    assert step["targetType"] is NO_TARGET
    assert step["weightUnit"] is WEIGHT_KG


# ---------- probe_one ----------


def test_probe_one_verified_and_deleted():
    adapter = FakeProbeAdapter()
    result = probe_one(adapter, "BENCH_PRESS", "DUMBBELL_BENCH_PRESS")
    assert result.status == "verified"
    assert result.deleted is True
    assert result.observed_category == "BENCH_PRESS"
    assert result.observed_exercise_name == "DUMBBELL_BENCH_PRESS"
    assert adapter.calls == ["create", "get", "delete"]


def test_probe_one_normalized_empty_exercise():
    adapter = FakeProbeAdapter(normalize_exercise_to="")
    result = probe_one(adapter, "LATERAL_RAISE", "LATERAL_RAISE")
    assert result.status == "normalized"
    assert result.observed_exercise_name == ""
    assert result.note is not None
    assert "→" in result.note
    assert "''" in result.note or '""' in result.note or "（空）" in result.note


def test_probe_one_failed_category_mismatch():
    adapter = FakeProbeAdapter(override_category="OTHER")
    result = probe_one(adapter, "BENCH_PRESS", "BENCH_PRESS")
    assert result.status == "failed"
    assert result.observed_category == "OTHER"


def test_probe_one_create_error_is_failed():
    adapter = FakeProbeAdapter(create_error=RuntimeError("secret remote body 500"))
    result = probe_one(adapter, "CORE", "CRUNCH")
    assert result.status == "failed"
    assert result.note == "RuntimeError"
    assert result.note is not None
    assert "secret" not in result.note
    assert "500" not in result.note
    assert result.workout_id is None
    assert result.deleted is False


def test_probe_one_delete_error_reports_manual_cleanup():
    adapter = FakeProbeAdapter(delete_error=OSError("cannot delete remote"))
    result = probe_one(adapter, "SQUAT", "LEG_PRESS")
    assert result.status == "verified"
    assert result.deleted is False
    assert result.workout_id is not None
    assert result.note is not None
    assert "请手动删除" in result.note
    assert result.workout_id in result.note
    assert "OSError" in result.note
    assert "cannot delete" not in result.note


def test_probe_one_keep_true_skips_delete():
    adapter = FakeProbeAdapter()
    result = probe_one(adapter, "CORE", "RUSSIAN_TWIST", keep=True)
    assert result.status == "verified"
    assert result.deleted is False
    assert "delete" not in adapter.calls
    assert adapter.deleted == []


# ---------- probe_batch ----------


def test_probe_batch_dedupes_pairs():
    adapter = FakeProbeAdapter()
    pairs = [
        ("BENCH_PRESS", "BENCH_PRESS"),
        ("BENCH_PRESS", "BENCH_PRESS"),
        ("SQUAT", "LEG_PRESS"),
        ("BENCH_PRESS", "BENCH_PRESS"),
    ]
    out = probe_batch(adapter, pairs)
    assert out["processed"] == 2
    assert out["verified"] == 2
    assert len(out["results"]) == 2


def test_probe_batch_respects_max_items():
    adapter = FakeProbeAdapter()
    pairs = [(f"CAT_{i}", f"EX_{i}") for i in range(40)]
    out = probe_batch(adapter, pairs, max_items=5)
    assert out["processed"] == 5
    assert len(out["results"]) == 5
    assert out["requested"] == 40


def test_probe_batch_empty_pairs_no_calls():
    adapter = FakeProbeAdapter()
    out = probe_batch(adapter, [])
    assert out == {
        "requested": 0,
        "processed": 0,
        "verified": 0,
        "normalized": 0,
        "failed": 0,
        "results": [],
    }
    assert adapter.calls == []


def test_probe_never_schedules():
    adapter = FakeProbeAdapter()
    probe_batch(
        adapter,
        [("BENCH_PRESS", "BENCH_PRESS"), ("SQUAT", "LEG_PRESS")],
    )
    assert adapter.schedule_calls == 0
    assert adapter.reschedule_calls == 0
    assert "schedule" not in adapter.calls
    assert "reschedule" not in adapter.calls


# ---------- apply_probe_results ----------


def test_apply_marks_verified_created(session):
    row = _make_mapping(
        session,
        xunji_name="哑铃卧推",
        category="BENCH_PRESS",
        exercise_name="DUMBBELL_BENCH_PRESS",
        status="draft",
        verified_level="catalog",
    )
    result = ProbeResult(
        category="BENCH_PRESS",
        exercise_name="DUMBBELL_BENCH_PRESS",
        status="verified",
        observed_category="BENCH_PRESS",
        observed_exercise_name="DUMBBELL_BENCH_PRESS",
        observed_display_name=None,
        workout_id="w1",
        deleted=True,
        note=None,
    )
    stats = apply_probe_results(session, [result])
    session.refresh(row)
    assert stats["updated"] == 1
    assert stats["skipped"] == 0
    assert row.verified_level == "created"
    assert row.verified_at is not None
    assert row.status == "draft"
    assert row.mapping_version == 1


def test_apply_normalized_updates_exercise_name(session):
    row = _make_mapping(
        session,
        xunji_name="侧平举",
        category="LATERAL_RAISE",
        exercise_name="LATERAL_RAISE",
        status="draft",
    )
    result = ProbeResult(
        category="LATERAL_RAISE",
        exercise_name="LATERAL_RAISE",
        status="normalized",
        observed_category="LATERAL_RAISE",
        observed_exercise_name="",
        observed_display_name=None,
        workout_id="w2",
        deleted=True,
        note="exerciseName: LATERAL_RAISE → ''",
    )
    apply_probe_results(session, [result])
    session.refresh(row)
    assert row.verified_level == "created"
    assert row.verified_at is not None
    assert row.garmin_exercise_name == ""
    assert row.note is not None
    assert "L2 探针" in row.note


def test_apply_failed_does_not_change_verified_level(session):
    row = _make_mapping(
        session,
        xunji_name="卷腹",
        category="CRUNCH",
        exercise_name="CRUNCH",
        verified_level="catalog",
        note="原有备注",
    )
    before_level = row.verified_level
    result = ProbeResult(
        category="CRUNCH",
        exercise_name="CRUNCH",
        status="failed",
        observed_category=None,
        observed_exercise_name=None,
        observed_display_name=None,
        workout_id=None,
        deleted=False,
        note="RuntimeError",
    )
    apply_probe_results(session, [result])
    session.refresh(row)
    assert row.verified_level == before_level
    assert row.verified_at is None
    assert row.note is not None
    assert "L2 探针" in row.note
    assert "RuntimeError" in row.note
    assert "原有备注" in row.note


def test_apply_counts_skipped_when_no_match(session):
    stats = apply_probe_results(
        session,
        [
            ProbeResult(
                category="NO_SUCH",
                exercise_name="NO_SUCH",
                status="verified",
                observed_category="NO_SUCH",
                observed_exercise_name="NO_SUCH",
                observed_display_name=None,
                workout_id="w9",
                deleted=True,
                note=None,
            )
        ],
    )
    assert stats == {"updated": 0, "skipped": 1}


# ---------- API ----------


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings

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


def test_probe_endpoint_409_when_write_disabled(client, auth_headers, monkeypatch):
    from app.config import get_settings

    class _Disabled:
        garmin_plan_sync_enabled = False

    constructed = {"count": 0}

    def boom_from_settings(_settings):
        constructed["count"] += 1
        raise AssertionError("must not construct adapter when write disabled")

    # 端点内 `from app.config import get_settings`，patch 模块属性即可
    monkeypatch.setattr("app.config.get_settings", lambda: _Disabled())
    monkeypatch.setattr(
        "app.adapters.garmin_workout_adapter.GarminWorkoutAdapter.from_settings",
        boom_from_settings,
    )

    resp = client.post(
        "/api/exercise-mappings/probe",
        headers=auth_headers,
        json={"pairs": [{"category": "BENCH_PRESS", "exercise_name": "BENCH_PRESS"}]},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "GARMIN_WRITE_DISABLED"
    assert constructed["count"] == 0
    get_settings.cache_clear()


def test_probe_endpoint_422_when_pairs_empty(client, auth_headers, monkeypatch):
    from app.config import get_settings

    class _Enabled:
        garmin_plan_sync_enabled = True

    constructed = {"count": 0}

    def boom_from_settings(_settings):
        constructed["count"] += 1
        raise AssertionError("must not construct adapter when pairs empty")

    monkeypatch.setattr("app.config.get_settings", lambda: _Enabled())
    monkeypatch.setattr(
        "app.adapters.garmin_workout_adapter.GarminWorkoutAdapter.from_settings",
        boom_from_settings,
    )

    resp = client.post(
        "/api/exercise-mappings/probe",
        headers=auth_headers,
        json={"pairs": []},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "EMPTY_PAIRS"
    assert constructed["count"] == 0
    get_settings.cache_clear()


def test_probe_max_items_constant():
    assert PROBE_MAX_ITEMS == 30


def test_probe_module_docstring_warns_real_write():
    assert probe_svc.__doc__ is not None
    assert "真实创建并删除" in probe_svc.__doc__
