"""V6-4：映射复核 / 纠错 API 层。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ExerciseMapping
from app.services import exercise_mapping_llm as llm_svc
from app.services.exercise_mapping import seed_mappings


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


def _get_by_name(session, name: str) -> ExerciseMapping:
    return session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.xunji_name == name)
    ).one()


def test_list_requires_auth(client):
    resp = client.get("/api/exercise-mappings")
    assert resp.status_code in (401, 403)


def test_list_returns_pagination_shape(client, auth_headers, session):
    seed_mappings(session)
    resp = client.get(
        "/api/exercise-mappings",
        params={"page": 1, "page_size": 5},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"items", "total", "page", "page_size", "pages"}
    assert body["page"] == 1
    assert body["page_size"] == 5
    assert len(body["items"]) == 5
    assert body["total"] == 16
    assert body["pages"] == 4


def test_detail_404_for_unknown_id(client, auth_headers, session):
    seed_mappings(session)
    resp = client.get("/api/exercise-mappings/999999", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "MAPPING_NOT_FOUND"


def test_patch_updates_and_returns_item(client, auth_headers, session):
    seed_mappings(session)
    row = _get_by_name(session, "哑铃卧推")
    before_version = row.mapping_version
    resp = client.patch(
        f"/api/exercise-mappings/{row.id}",
        headers=auth_headers,
        json={"garmin_display_name": "API Edited Name", "reason": "api patch"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["garmin_display_name"] == "API Edited Name"
    assert body["mapping_version"] == before_version + 1
    assert body["xunji_name"] == "哑铃卧推"


def test_patch_invalid_category_returns_422_with_code(
    client, auth_headers, session
):
    seed_mappings(session)
    row = _get_by_name(session, "哑铃卧推")
    resp = client.patch(
        f"/api/exercise-mappings/{row.id}",
        headers=auth_headers,
        json={"garmin_category": "NOT_A_CATEGORY"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_CATEGORY"
    assert "message" in detail


def test_activate_endpoint(client, auth_headers, session):
    seed_mappings(session)
    row = ExerciseMapping(
        xunji_name="API待采纳",
        garmin_category="BENCH_PRESS",
        garmin_exercise_name="DUMBBELL_BENCH_PRESS",
        garmin_display_name="Dumbbell Bench Press",
        weight_strategy="per_hand",
        status="draft",
        confidence="high",
        source="test",
        verified_level="none",
        mapping_version=1,
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    resp = client.post(
        f"/api/exercise-mappings/{row.id}/activate",
        headers=auth_headers,
        json={"reason": "api activate"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_catalog_search_endpoint(client, auth_headers):
    resp = client.get(
        "/api/exercise-mappings/catalog",
        params={"q": "bench", "limit": 10},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) <= 10
    assert all("category" in r and "exercise" in r and "name" in r for r in rows)
    assert all("bench" in (r["name"] or "").lower() for r in rows)


def test_batch_activate_endpoint(client, auth_headers, session):
    seed_mappings(session)
    row = ExerciseMapping(
        xunji_name="API批量高置信",
        garmin_category="BENCH_PRESS",
        garmin_exercise_name="BENCH_PRESS",
        garmin_display_name="Bench Press",
        weight_strategy="total",
        status="draft",
        confidence="high",
        source="test",
        # ADR §5.1：批量自动确认要求 relation=EXACT 且目标已验证（至少 catalog）
        relation="EXACT",
        verified_level="catalog",
        mapping_version=1,
    )
    session.add(row)
    session.commit()

    resp = client.post(
        "/api/exercise-mappings/batch-activate",
        headers=auth_headers,
        json={"confidence": "high", "only_confirmed_catalog": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "activated" in body and "skipped" in body
    assert body["activated"] >= 1
    session.refresh(row)
    assert row.status == "active"


def test_llm_suggest_endpoint_requires_auth(client):
    resp = client.post("/api/exercise-mappings/llm-suggest")
    assert resp.status_code in (401, 403)


def test_llm_suggest_endpoint_returns_stats(client, auth_headers, monkeypatch):
    def fake_chat(messages, **kwargs):
        return {
            "content": "[]",
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }

    monkeypatch.setattr(llm_svc.llm, "chat", fake_chat)
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: ["API-LLM占位"])
    resp = client.post(
        "/api/exercise-mappings/llm-suggest",
        params={"limit": 1, "max_batches": 1},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "requested",
        "processed",
        "batches",
        "accepted",
        "rejected",
        "skipped_no_candidate_list",
        "prompt_tokens",
        "completion_tokens",
    ):
        assert key in body
