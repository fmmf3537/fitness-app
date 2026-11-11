"""V6-7：全量映射批处理 + 覆盖率看板 API。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import get_session
from app.main import app
from app.models import ExerciseMapping, ExerciseMappingCandidate
from app.services import exercise_mapping_batch as batch_svc
from app.services.exercise_mapping_candidates import generate_candidates


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


def _mapping_count(session) -> int:
    return session.scalar(select(func.count()).select_from(ExerciseMapping)) or 0


def _candidate_count(session, *, xunji_name: str | None = None) -> int:
    stmt = select(func.count()).select_from(ExerciseMappingCandidate)
    if xunji_name is not None:
        stmt = stmt.where(ExerciseMappingCandidate.xunji_name == xunji_name)
    return session.scalar(stmt) or 0


def _get_mapping(session, name: str) -> ExerciseMapping:
    return session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.xunji_name == name)
    ).one()


# ---------- 批处理（8）----------


def test_generate_all_inserts_all_movements(session):
    # generate_all 会先自动 seed V6-1 的 16 条（status=active），避免它们被建成 draft。
    stats = batch_svc.generate_all(session)
    assert stats["total"] == 1091
    assert stats["seeded"] == 16
    assert stats["inserted"] == 1091 - 16
    assert _mapping_count(session) == 1091


def test_generate_all_is_idempotent(session):
    first = batch_svc.generate_all(session)
    count_after_first = _mapping_count(session)
    cand_after_first = _candidate_count(session)
    second = batch_svc.generate_all(session)
    assert first["inserted"] == 1091 - 16
    assert first["seeded"] == 16
    assert second["inserted"] == 0
    assert second["seeded"] == 0
    assert second["refreshed"] == 0
    assert second["candidates"] == 0
    assert _mapping_count(session) == count_after_first == 1091
    assert _candidate_count(session) == cand_after_first


def test_generate_all_does_not_overwrite_active(session):
    batch_svc.generate_all(session)
    row = _get_mapping(session, "哑铃卧推")
    row.status = "active"
    row.garmin_exercise_name = "CUSTOM_ACTIVE_NAME"
    session.commit()

    batch_svc.generate_all(session, refresh_drafts=True)
    session.refresh(row)
    assert row.status == "active"
    assert row.garmin_exercise_name == "CUSTOM_ACTIVE_NAME"


def test_generate_all_does_not_overwrite_disabled(session):
    batch_svc.generate_all(session)
    row = _get_mapping(session, "哑铃卧推")
    row.status = "disabled"
    row.garmin_exercise_name = "CUSTOM_DISABLED_NAME"
    session.commit()

    batch_svc.generate_all(session, refresh_drafts=True)
    session.refresh(row)
    assert row.status == "disabled"
    assert row.garmin_exercise_name == "CUSTOM_DISABLED_NAME"


def test_generate_all_marks_not_applicable(session):
    batch_svc.generate_all(session)
    row = _get_mapping(session, "坐姿腿拉伸")
    assert row.status == "not_applicable"
    assert row.not_applicable_reason
    assert row.garmin_category is None
    assert _candidate_count(session, xunji_name="坐姿腿拉伸") == 0


def test_generate_all_writes_candidates(session):
    batch_svc.generate_all(session)
    # 哑铃卧推属于 V6-1 的 16 条 seed（active，被跳过、不产候选），
    # 因此这里用一个 seed 之外的 high 置信动作。
    row = _get_mapping(session, "海豹杠铃划船")
    assert row.confidence == "high"
    cands = session.scalars(
        select(ExerciseMappingCandidate)
        .where(ExerciseMappingCandidate.xunji_name == "海豹杠铃划船")
        .order_by(ExerciseMappingCandidate.rank)
    ).all()
    assert len(cands) >= 1
    assert [c.rank for c in cands] == list(range(1, len(cands) + 1))
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == row.garmin_category
    assert top.garmin_exercise_name == row.garmin_exercise_name
    assert top.garmin_display_name == row.garmin_display_name


def test_generate_all_candidate_idempotent(session):
    batch_svc.generate_all(session)
    first_count = _candidate_count(session)
    batch_svc.generate_all(session)
    assert _candidate_count(session) == first_count
    batch_svc.generate_all(session, refresh_drafts=True)
    assert _candidate_count(session) == first_count


def test_generate_all_keeps_accepted_candidates(session):
    batch_svc.generate_all(session)
    accepted = session.scalars(
        select(ExerciseMappingCandidate)
        .where(ExerciseMappingCandidate.xunji_name == "海豹杠铃划船")
        .order_by(ExerciseMappingCandidate.rank)
    ).first()
    assert accepted is not None
    accepted.status = "accepted"
    accepted_id = accepted.id
    session.commit()

    batch_svc.generate_all(session, refresh_drafts=True)
    still = session.get(ExerciseMappingCandidate, accepted_id)
    assert still is not None
    assert still.status == "accepted"
    assert still.xunji_name == "海豹杠铃划船"


# ---------- 刷新（2）----------


def test_refresh_drafts_false_skips_existing(session):
    batch_svc.generate_all(session)
    row = _get_mapping(session, "哑铃卧推")
    row.garmin_exercise_name = "MANUAL_DRAFT_NAME"
    session.commit()

    batch_svc.generate_all(session, refresh_drafts=False)
    session.refresh(row)
    assert row.garmin_exercise_name == "MANUAL_DRAFT_NAME"


def test_refresh_drafts_true_recomputes_draft(session):
    batch_svc.generate_all(session)
    # seed 的 16 条是 active，refresh_drafts 不会覆盖它们；用非 seed 的 draft 行验证
    row = _get_mapping(session, "海豹杠铃划船")
    row.garmin_exercise_name = "MANUAL_DRAFT_NAME"
    session.commit()

    expected = generate_candidates("海豹杠铃划船", limit=3)[0]
    batch_svc.generate_all(session, refresh_drafts=True)
    session.refresh(row)
    assert row.garmin_exercise_name == expected.garmin_exercise_name
    assert row.garmin_category == expected.garmin_category
    assert row.garmin_display_name == expected.garmin_display_name


# ---------- 统计（2）----------


def test_coverage_stats_shape_when_empty(session):
    stats = batch_svc.coverage_stats(session)
    assert stats["total"] == 1091
    assert stats["by_status"]["missing"] == 1091
    for key in ("draft", "active", "disabled", "not_applicable", "missing"):
        assert key in stats["by_status"]
    for key in ("high", "medium", "low", "none", "not_applicable"):
        assert key in stats["by_confidence"]
    for key in ("none", "catalog", "created", "displayed"):
        assert key in stats["by_verified_level"]
    cov = stats["coverage"]
    assert cov["with_candidate_pct"] == 0.0
    assert cov["high_pct"] == 0.0
    assert isinstance(cov["strength_with_candidate_pct"], float)


def test_coverage_stats_after_generate(session):
    batch_svc.generate_all(session)
    stats = batch_svc.coverage_stats(session)
    assert 120 <= stats["by_status"]["not_applicable"] <= 220
    assert stats["coverage"]["with_candidate"] >= 600
    assert stats["coverage"]["strength_with_candidate_pct"] > 60
    assert stats["by_status"]["missing"] == 0


# ---------- API（2）----------


def test_api_coverage_requires_auth(client):
    resp = client.get("/api/exercise-mappings/coverage")
    assert resp.status_code in (401, 403)


def test_api_generate_and_coverage(client, auth_headers):
    gen = client.post("/api/exercise-mappings/generate", headers=auth_headers)
    assert gen.status_code == 200
    body = gen.json()
    assert body["total"] == 1091
    assert body["seeded"] == 16
    assert body["inserted"] == 1091 - 16

    cov = client.get("/api/exercise-mappings/coverage", headers=auth_headers)
    assert cov.status_code == 200
    data = cov.json()
    assert data["total"] == 1091
    assert data["by_status"]["missing"] == 0
