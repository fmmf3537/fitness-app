"""V6-9b：批处理刷新保护（不覆盖手改与 LLM 结果）。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ExerciseMapping
from app.services import exercise_mapping_batch as batch_svc
from app.services import exercise_mapping_llm as llm_svc
from app.services.exercise_mapping_candidates import generate_candidates
from app.services.exercise_mapping_llm import suggest_candidates_with_llm

# 非 seed 名单：控制耗时，且不会被 seed_mappings 建成 active
_SMALL_NAMES = ["海豹杠铃划船", "哑铃飞鸟", "坐姿划船"]

_STATS_KEYS = {
    "total",
    "inserted",
    "refreshed",
    "skipped_active",
    "skipped_protected",
    "not_applicable",
    "with_candidate",
    "no_candidate",
    "candidates",
    "seeded",
}


@pytest.fixture
def small_names(monkeypatch):
    monkeypatch.setattr(batch_svc, "_load_movement_names", lambda: list(_SMALL_NAMES))
    return list(_SMALL_NAMES)


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


def _get_mapping(session, name: str) -> ExerciseMapping:
    return session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.xunji_name == name)
    ).one()


def _real_pair() -> tuple[str, str, str]:
    from garminconnect import exercises as garmin_exercises

    for entry in garmin_exercises.EXERCISES:
        cat = entry.get("category") or ""
        ex = entry.get("exercise") or ""
        if cat and ex:
            return cat, ex, entry.get("name") or ""
    raise RuntimeError("Garmin catalog empty")


def _fake_chat_for(name: str, category: str, exercise_name: str, reason: str = "match"):
    payload = [
        {
            "xunji_name": name,
            "category": category,
            "exercise_name": exercise_name,
            "reason": reason,
        }
    ]

    def fake(messages):
        return {
            "content": json.dumps(payload, ensure_ascii=False),
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }

    return fake


# ---------- batch refresh guard ----------


def test_new_rows_are_inserted(session, small_names):
    stats = batch_svc.generate_all(session)
    assert stats["inserted"] == 3
    assert stats["total"] == 3


def test_second_run_is_idempotent(session, small_names):
    batch_svc.generate_all(session)
    second = batch_svc.generate_all(session)
    assert second["inserted"] == 0
    assert second["refreshed"] == 0


def test_refresh_recomputes_untouched_draft(session, small_names):
    batch_svc.generate_all(session)
    name = small_names[0]
    row = _get_mapping(session, name)
    assert row.status == "draft"
    assert row.mapping_version == 1
    row.garmin_exercise_name = "MANUAL_UNTOUCHED_MARKER"
    session.commit()

    expected = generate_candidates(name, limit=3)[0]
    stats = batch_svc.generate_all(session, refresh_drafts=True)
    session.refresh(row)
    assert row.garmin_exercise_name == expected.garmin_exercise_name
    assert row.garmin_category == expected.garmin_category
    assert stats["skipped_protected"] == 0
    assert stats["refreshed"] >= 1


def test_refresh_skips_user_edited_row(session, small_names):
    batch_svc.generate_all(session)
    name = small_names[0]
    row = _get_mapping(session, name)
    row.garmin_exercise_name = "USER_EDITED_NAME"
    row.mapping_version = 2
    session.commit()

    stats = batch_svc.generate_all(session, refresh_drafts=True)
    session.refresh(row)
    assert row.garmin_exercise_name == "USER_EDITED_NAME"
    assert stats["skipped_protected"] >= 1


def test_refresh_skips_llm_row(session, small_names):
    batch_svc.generate_all(session)
    name = small_names[0]
    row = _get_mapping(session, name)
    row.source = "llm"
    row.garmin_exercise_name = "LLM_FILLED_NAME"
    row.mapping_version = 1
    row.status = "draft"
    session.commit()

    stats = batch_svc.generate_all(session, refresh_drafts=True)
    session.refresh(row)
    assert row.garmin_exercise_name == "LLM_FILLED_NAME"
    assert row.source == "llm"
    assert stats["skipped_protected"] >= 1


def test_force_refresh_overwrites_user_edited_row(session, small_names):
    batch_svc.generate_all(session)
    name = small_names[0]
    row = _get_mapping(session, name)
    row.garmin_exercise_name = "USER_EDITED_NAME"
    row.mapping_version = 2
    session.commit()

    expected = generate_candidates(name, limit=3)[0]
    stats = batch_svc.generate_all(
        session, refresh_drafts=True, force_refresh=True
    )
    session.refresh(row)
    assert row.garmin_exercise_name == expected.garmin_exercise_name
    assert stats["skipped_protected"] == 0
    assert stats["refreshed"] >= 1


def test_force_refresh_overwrites_llm_row(session, small_names):
    batch_svc.generate_all(session)
    name = small_names[0]
    row = _get_mapping(session, name)
    row.source = "llm"
    row.garmin_exercise_name = "LLM_FILLED_NAME"
    row.mapping_version = 1
    row.status = "draft"
    session.commit()

    expected = generate_candidates(name, limit=3)[0]
    stats = batch_svc.generate_all(
        session, refresh_drafts=True, force_refresh=True
    )
    session.refresh(row)
    assert row.garmin_exercise_name == expected.garmin_exercise_name
    assert stats["skipped_protected"] == 0
    assert stats["refreshed"] >= 1


def test_skip_active_still_counted_separately(session, small_names):
    batch_svc.generate_all(session)
    name = small_names[0]
    row = _get_mapping(session, name)
    row.status = "active"
    row.garmin_exercise_name = "ACTIVE_MARKER"
    # 即便带上手改/LLM 信号，active 仍只走 skipped_active
    row.mapping_version = 2
    row.source = "llm"
    session.commit()

    stats = batch_svc.generate_all(session, refresh_drafts=True)
    session.refresh(row)
    assert row.status == "active"
    assert row.garmin_exercise_name == "ACTIVE_MARKER"
    assert stats["skipped_active"] >= 1
    assert stats["skipped_protected"] == 0


def test_no_protected_count_when_refresh_disabled(session, small_names):
    batch_svc.generate_all(session)
    name = small_names[0]
    row = _get_mapping(session, name)
    row.garmin_exercise_name = "USER_EDITED_NAME"
    row.mapping_version = 2
    session.commit()

    stats = batch_svc.generate_all(session, refresh_drafts=False)
    session.refresh(row)
    assert row.garmin_exercise_name == "USER_EDITED_NAME"
    assert stats["skipped_protected"] == 0


def test_stats_keys_all_present(session, small_names):
    stats = batch_svc.generate_all(session)
    assert set(stats.keys()) == _STATS_KEYS
    stats2 = batch_svc.generate_all(session, refresh_drafts=True)
    assert set(stats2.keys()) == _STATS_KEYS


# ---------- LLM source marking ----------


def test_llm_fill_marks_source_llm(session, monkeypatch):
    name = "LLM填充来源标记"
    cat, ex, _ = _real_pair()
    row = ExerciseMapping(
        xunji_name=name,
        status="draft",
        source="auto",
        verified_level="none",
        mapping_version=1,
    )
    session.add(row)
    session.commit()
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [name])

    stats = suggest_candidates_with_llm(
        session,
        limit=10,
        max_batches=1,
        chat_fn=_fake_chat_for(name, cat, ex, "相似"),
    )
    assert stats["accepted"] == 1
    session.refresh(row)
    assert row.source == "llm"
    assert row.status == "draft"
    assert row.mapping_version == 1


def test_llm_fill_does_not_change_seed_source(session, monkeypatch):
    """手工造 seed/active 行；即便被强制选中填充，source 仍保持 seed。"""
    name = "SEED保护测试"
    cat, ex, _ = _real_pair()
    row = ExerciseMapping(
        xunji_name=name,
        status="active",
        source="seed",
        # 无候选 → 默认 only_without_candidate 也会选中，用以触发防御分支
        garmin_category=None,
        garmin_exercise_name=None,
        garmin_display_name=None,
        confidence=None,
        verified_level="created",
        mapping_version=1,
    )
    session.add(row)
    session.commit()
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [name])
    stats = suggest_candidates_with_llm(
        session,
        limit=10,
        max_batches=1,
        chat_fn=_fake_chat_for(name, cat, ex),
    )
    assert stats["accepted"] == 1
    session.refresh(row)
    assert row.source == "seed"
    assert row.status == "active"
    assert row.mapping_version == 1


def test_llm_fill_does_not_bump_mapping_version(session, monkeypatch):
    name = "LLM不涨版本"
    cat, ex, _ = _real_pair()
    row = ExerciseMapping(
        xunji_name=name,
        status="draft",
        source="auto",
        verified_level="none",
        mapping_version=1,
    )
    session.add(row)
    session.commit()
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [name])

    suggest_candidates_with_llm(
        session,
        limit=10,
        max_batches=1,
        chat_fn=_fake_chat_for(name, cat, ex),
    )
    session.refresh(row)
    assert row.mapping_version == 1
    assert row.source == "llm"


# ---------- API ----------


def test_api_generate_accepts_force_refresh(
    session, client, auth_headers, monkeypatch
):
    monkeypatch.setattr(batch_svc, "_load_movement_names", lambda: list(_SMALL_NAMES))
    resp = client.post(
        "/api/exercise-mappings/generate"
        "?refresh_drafts=true&force_refresh=true",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "skipped_protected" in body
    assert set(body.keys()) >= _STATS_KEYS
