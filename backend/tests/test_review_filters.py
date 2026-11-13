"""ADR-P2-5：审核端点筛选参数（status / xunji_name / offset）。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from garminconnect import exercises as garmin_exercises

from app.db import get_session
from app.main import app
from app.models import ExerciseMapping
from app.services import exercise_mapping_review as review_svc
from app.services.exercise_mapping_review import (
    VERDICT_CURRENT_OK,
    _select_targets,
    review_mappings,
)


def _real_pair() -> tuple[str, str, str]:
    for entry in garmin_exercises.EXERCISES:
        cat = entry.get("category") or ""
        ex = entry.get("exercise") or ""
        if cat and ex:
            return cat, ex, entry.get("name") or ""
    raise RuntimeError("Garmin catalog empty")


def _add_mapping(
    session,
    name: str,
    *,
    status: str = "active",
    category: str | None = None,
    exercise_name: str | None = None,
    display_name: str | None = None,
    relation: str | None = "exact",
    note: str | None = None,
    verified_level: str | None = "catalog",
    mapping_version: int = 1,
) -> ExerciseMapping:
    cat, ex, disp = _real_pair()
    row = ExerciseMapping(
        xunji_name=name,
        garmin_category=category if category is not None else cat,
        garmin_exercise_name=exercise_name if exercise_name is not None else ex,
        garmin_display_name=display_name if display_name is not None else disp,
        status=status,
        confidence="high",
        source="test",
        verified_level=verified_level,
        mapping_version=mapping_version,
        relation=relation,
        note=note,
        decision_source="rule",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _fake_chat(payload: list[dict], *, model: str = "fake-model"):
    def fake(messages):
        return {
            "content": json.dumps(payload, ensure_ascii=False),
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "model": model,
        }

    return fake


def _ok_payload(names: list[str]) -> list[dict]:
    return [
        {
            "name": name,
            "verdict": VERDICT_CURRENT_OK,
            "suggested": None,
            "reason": "ok",
        }
        for name in names
    ]


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


# ---- service layer ----


def test_default_still_active_only(session):
    a = _add_mapping(session, "滤默认甲", status="active")
    _add_mapping(session, "滤默认乙", status="draft")
    _add_mapping(session, "滤默认丙", status="disabled")
    targets = _select_targets(session, limit=10, only_active=True)
    assert [r.id for r in targets] == [a.id]
    assert all(r.status == "active" for r in targets)


def test_status_overrides_only_active(session):
    _add_mapping(session, "滤覆盖甲", status="active")
    d1 = _add_mapping(session, "滤覆盖乙", status="draft")
    d2 = _add_mapping(session, "滤覆盖丙", status="draft")
    targets = _select_targets(
        session, limit=10, only_active=True, status="draft"
    )
    assert {r.id for r in targets} == {d1.id, d2.id}
    assert all(r.status == "draft" for r in targets)


def test_status_disabled(session):
    _add_mapping(session, "滤禁用甲", status="active")
    disabled = _add_mapping(session, "滤禁用乙", status="disabled")
    _add_mapping(session, "滤禁用丙", status="draft")
    targets = _select_targets(
        session, limit=10, only_active=False, status="disabled"
    )
    assert [r.id for r in targets] == [disabled.id]
    assert targets[0].status == "disabled"


def test_xunji_name_selects_single_row(session):
    _add_mapping(session, "滤指名甲", status="active")
    target = _add_mapping(session, "滤指名乙", status="active")
    _add_mapping(session, "滤指名丙", status="active")
    stats = review_mappings(
        session,
        limit=10,
        max_batches=1,
        chat_fn=_fake_chat(_ok_payload([target.xunji_name])),
        xunji_name=target.xunji_name,
    )
    assert stats["requested"] == 1
    assert stats["processed"] == 1


def test_xunji_name_not_found_zero_targets(session):
    _add_mapping(session, "滤无名甲", status="active")

    def boom(messages):
        raise AssertionError("chat_fn must not be called when no targets")

    stats = review_mappings(
        session,
        limit=10,
        max_batches=1,
        chat_fn=boom,
        xunji_name="绝对不存在的动作名_P25",
    )
    assert stats["requested"] == 0
    assert stats["processed"] == 0
    assert stats["batches"] == 0


def test_offset_skips_rows(session):
    rows = [
        _add_mapping(session, f"滤偏移{i}", status="active") for i in range(5)
    ]
    first = _select_targets(session, limit=2, only_active=True, offset=0)
    second = _select_targets(session, limit=2, only_active=True, offset=2)
    assert [r.id for r in first] == [rows[0].id, rows[1].id]
    assert [r.id for r in second] == [rows[2].id, rows[3].id]
    assert {r.id for r in first}.isdisjoint({r.id for r in second})


def test_offset_beyond_end_returns_empty(session):
    _add_mapping(session, "滤越界甲", status="active")
    _add_mapping(session, "滤越界乙", status="active")

    def boom(messages):
        raise AssertionError("chat_fn must not be called when offset beyond end")

    stats = review_mappings(
        session,
        limit=10,
        max_batches=1,
        chat_fn=boom,
        offset=100,
    )
    assert stats["requested"] == 0
    assert stats["processed"] == 0
    assert stats["batches"] == 0


def test_filters_combine(session):
    _add_mapping(session, "滤组合甲", status="draft")
    d2 = _add_mapping(session, "滤组合乙", status="draft")
    _add_mapping(session, "滤组合丙", status="draft")
    _add_mapping(session, "滤组合丁", status="active")
    targets = _select_targets(
        session,
        limit=1,
        only_active=True,
        status="draft",
        offset=1,
    )
    assert len(targets) == 1
    assert targets[0].id == d2.id
    assert targets[0].status == "draft"


# ---- API ----


def test_review_endpoint_accepts_status_filter(
    client, auth_headers, session, monkeypatch
):
    row = _add_mapping(session, "API滤状态", status="draft")
    inner = _fake_chat(_ok_payload([row.xunji_name]))

    def fake_llm(messages, *args, **kwargs):
        return inner(messages)

    monkeypatch.setattr(review_svc.llm, "chat", fake_llm)
    resp = client.post(
        "/api/exercise-mappings/review",
        headers=auth_headers,
        params={"status": "draft", "limit": 5, "max_batches": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "requested" in body
    assert body["requested"] == 1
    assert "batch_id" in body


def test_review_endpoint_rejects_invalid_status(client, auth_headers):
    resp = client.post(
        "/api/exercise-mappings/review",
        headers=auth_headers,
        params={"status": "bogus"},
    )
    assert resp.status_code == 422


def test_review_endpoint_accepts_xunji_name(
    client, auth_headers, session, monkeypatch
):
    row = _add_mapping(session, "API滤指名", status="active")
    inner = _fake_chat(_ok_payload([row.xunji_name]))

    def fake_llm(messages, *args, **kwargs):
        return inner(messages)

    monkeypatch.setattr(review_svc.llm, "chat", fake_llm)
    resp = client.post(
        "/api/exercise-mappings/review",
        headers=auth_headers,
        params={"xunji_name": row.xunji_name, "limit": 5, "max_batches": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requested"] == 1


def test_review_endpoint_rejects_negative_offset(client, auth_headers):
    resp = client.post(
        "/api/exercise-mappings/review",
        headers=auth_headers,
        params={"offset": -1},
    )
    assert resp.status_code == 422
