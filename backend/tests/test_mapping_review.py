"""ADR-P2-2：AI 只读审核员（全部注入 chat_fn，不联网）。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from garminconnect import exercises as garmin_exercises
from sqlalchemy import func, select

from app.db import get_session
from app.main import app
from app.models import ExerciseMapping, ExerciseMappingReview
from app.services import exercise_mapping_review as review_svc
from app.services.exercise_mapping_review import (
    VERDICT_BETTER,
    VERDICT_CURRENT_OK,
    VERDICT_LIKELY_UNMAPPED,
    VERDICT_NEEDS_HUMAN,
    VERDICT_SUSPECTED_ERROR,
    list_reviews,
    parse_review_response,
    review_mappings,
    validate_suggestion,
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


# ---- parse / validate ----


def test_parse_valid_array():
    content = json.dumps(
        [
            {
                "name": "哑铃卧推",
                "verdict": VERDICT_CURRENT_OK,
                "suggested": None,
                "reason": "合理",
            },
            {
                "name": "杠铃深蹲",
                "verdict": VERDICT_LIKELY_UNMAPPED,
                "suggested": None,
                "reason": "目录无对应",
            },
        ],
        ensure_ascii=False,
    )
    parsed = parse_review_response(content)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "哑铃卧推"
    assert parsed[1]["verdict"] == VERDICT_LIKELY_UNMAPPED


def test_parse_strips_think_block():
    payload = [
        {
            "name": "引体向上",
            "verdict": VERDICT_CURRENT_OK,
            "suggested": None,
            "reason": "ok",
        }
    ]
    content = (
        "<think>内部推理应被剥离</think>\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    parsed = parse_review_response(content)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "引体向上"


def test_parse_invalid_json_returns_empty():
    assert parse_review_response("not-json at all") == []
    assert parse_review_response("") == []
    assert parse_review_response("[{broken") == []


def test_parse_drops_unknown_verdict():
    content = json.dumps(
        [
            {
                "name": "保留",
                "verdict": VERDICT_NEEDS_HUMAN,
                "suggested": None,
                "reason": "拿不准",
            },
            {
                "name": "丢弃",
                "verdict": "totally_invalid",
                "suggested": None,
                "reason": "坏",
            },
        ],
        ensure_ascii=False,
    )
    parsed = parse_review_response(content)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "保留"


def test_validate_suggestion_rejects_unknown_pair():
    assert validate_suggestion("NOT_A_REAL_CATEGORY", "ANYTHING") is False
    cat, _, _ = _real_pair()
    assert validate_suggestion(cat, "TOTALLY_FAKE_EXERCISE_NAME") is False


def test_validate_suggestion_rejects_empty_exercise():
    cat, _, _ = _real_pair()
    assert validate_suggestion(cat, "") is False
    assert validate_suggestion(cat, None) is False


# ---- review_mappings ----


def test_review_writes_rows(session):
    a = _add_mapping(session, "审核落库甲")
    b = _add_mapping(session, "审核落库乙")
    payload = [
        {
            "name": a.xunji_name,
            "verdict": VERDICT_CURRENT_OK,
            "suggested": None,
            "reason": "合理",
        },
        {
            "name": b.xunji_name,
            "verdict": VERDICT_SUSPECTED_ERROR,
            "suggested": None,
            "reason": "可疑",
        },
    ]
    stats = review_mappings(
        session, limit=10, max_batches=1, chat_fn=_fake_chat(payload)
    )
    assert stats["processed"] == 2
    count = session.scalar(select(func.count()).select_from(ExerciseMappingReview)) or 0
    assert count == 2


def test_review_never_modifies_mapping(session):
    row = _add_mapping(
        session,
        "审核不改映射",
        note="原始备注",
        verified_level="catalog",
        mapping_version=3,
        relation="exact",
    )
    before = {
        "status": row.status,
        "relation": row.relation,
        "verified_level": row.verified_level,
        "mapping_version": row.mapping_version,
        "note": row.note,
        "garmin_category": row.garmin_category,
        "garmin_exercise_name": row.garmin_exercise_name,
    }
    payload = [
        {
            "name": row.xunji_name,
            "verdict": VERDICT_SUSPECTED_ERROR,
            "suggested": None,
            "reason": "疑似错",
        }
    ]
    review_mappings(session, limit=5, max_batches=1, chat_fn=_fake_chat(payload))
    session.refresh(row)
    after = {
        "status": row.status,
        "relation": row.relation,
        "verified_level": row.verified_level,
        "mapping_version": row.mapping_version,
        "note": row.note,
        "garmin_category": row.garmin_category,
        "garmin_exercise_name": row.garmin_exercise_name,
    }
    assert after == before


def test_review_counts_by_verdict(session):
    names = [
        ("审核OK", VERDICT_CURRENT_OK),
        ("审核更好", VERDICT_BETTER),
        ("审核可疑", VERDICT_SUSPECTED_ERROR),
        ("审核无对应", VERDICT_LIKELY_UNMAPPED),
        ("审核人工", VERDICT_NEEDS_HUMAN),
    ]
    cat, ex, _ = _real_pair()
    for name, _verdict in names:
        _add_mapping(session, name)

    payload = []
    for name, verdict in names:
        suggested = None
        if verdict == VERDICT_BETTER:
            suggested = {"category": cat, "exerciseName": ex}
        payload.append(
            {
                "name": name,
                "verdict": verdict,
                "suggested": suggested,
                "reason": f"判{verdict}",
            }
        )

    stats = review_mappings(
        session, limit=20, max_batches=1, chat_fn=_fake_chat(payload)
    )
    assert stats["by_verdict"] == {
        VERDICT_CURRENT_OK: 1,
        VERDICT_BETTER: 1,
        VERDICT_SUSPECTED_ERROR: 1,
        VERDICT_LIKELY_UNMAPPED: 1,
        VERDICT_NEEDS_HUMAN: 1,
    }
    assert stats["rejected_suggestions"] == 0


def test_invalid_suggestion_downgraded(session):
    row = _add_mapping(session, "审核建议非法")
    payload = [
        {
            "name": row.xunji_name,
            "verdict": VERDICT_BETTER,
            "suggested": {
                "category": "NOT_IN_CATALOG",
                "exerciseName": "FAKE_EX",
            },
            "reason": "给了假建议",
        }
    ]
    stats = review_mappings(
        session, limit=5, max_batches=1, chat_fn=_fake_chat(payload)
    )
    assert stats["rejected_suggestions"] == 1
    assert stats["by_verdict"][VERDICT_NEEDS_HUMAN] == 1
    assert stats["by_verdict"][VERDICT_BETTER] == 0
    review = session.scalars(select(ExerciseMappingReview)).one()
    assert review.verdict == VERDICT_NEEDS_HUMAN
    assert review.suggested_category is None


def test_review_does_not_call_network_when_injected(session, monkeypatch):
    row = _add_mapping(session, "审核禁网")

    def boom(*args, **kwargs):
        raise AssertionError("llm.chat must not be called when chat_fn injected")

    monkeypatch.setattr(review_svc.llm, "chat", boom)
    payload = [
        {
            "name": row.xunji_name,
            "verdict": VERDICT_CURRENT_OK,
            "suggested": None,
            "reason": "ok",
        }
    ]
    stats = review_mappings(
        session, limit=5, max_batches=1, chat_fn=_fake_chat(payload)
    )
    assert stats["processed"] == 1


def test_batch_id_is_unique_per_run(session):
    row = _add_mapping(session, "审核批次号")
    payload = [
        {
            "name": row.xunji_name,
            "verdict": VERDICT_CURRENT_OK,
            "suggested": None,
            "reason": "ok",
        }
    ]
    s1 = review_mappings(
        session, limit=5, max_batches=1, chat_fn=_fake_chat(payload)
    )
    s2 = review_mappings(
        session, limit=5, max_batches=1, chat_fn=_fake_chat(payload)
    )
    assert s1["batch_id"] and s2["batch_id"]
    assert s1["batch_id"] != s2["batch_id"]
    only_first = list_reviews(session, batch_id=s1["batch_id"])
    assert len(only_first) == 1
    assert only_first[0]["batch_id"] == s1["batch_id"]


# ---- fault tolerance ----


def test_chat_failure_does_not_crash(session):
    _add_mapping(session, "审核失败甲")
    _add_mapping(session, "审核失败乙")

    def boom(messages):
        raise RuntimeError("LLM down")

    stats = review_mappings(session, limit=10, max_batches=2, chat_fn=boom)
    assert stats["requested"] == 2
    assert stats["processed"] == 0
    assert stats["batches"] == 0
    count = session.scalar(select(func.count()).select_from(ExerciseMappingReview)) or 0
    assert count == 0


def test_empty_targets_returns_zero_stats(session):
    calls = {"n": 0}

    def fake(messages):
        calls["n"] += 1
        return {"content": "[]", "prompt_tokens": 0, "completion_tokens": 0}

    stats = review_mappings(session, limit=10, max_batches=1, chat_fn=fake)
    assert calls["n"] == 0
    assert stats["requested"] == 0
    assert stats["processed"] == 0
    assert stats["batches"] == 0
    assert stats["rejected_suggestions"] == 0
    assert stats["by_verdict"] == {
        VERDICT_CURRENT_OK: 0,
        VERDICT_BETTER: 0,
        VERDICT_SUSPECTED_ERROR: 0,
        VERDICT_LIKELY_UNMAPPED: 0,
        VERDICT_NEEDS_HUMAN: 0,
    }
    assert isinstance(stats["batch_id"], str) and stats["batch_id"]


# ---- list_reviews ----


def test_list_reviews_orders_desc(session):
    older = ExerciseMappingReview(
        mapping_id=1,
        xunji_name="旧审核",
        verdict=VERDICT_CURRENT_OK,
        reason="old",
        batch_id="b1",
        resolved=False,
    )
    newer = ExerciseMappingReview(
        mapping_id=2,
        xunji_name="新审核",
        verdict=VERDICT_NEEDS_HUMAN,
        reason="new",
        batch_id="b1",
        resolved=False,
    )
    session.add(older)
    session.commit()
    session.add(newer)
    session.commit()
    items = list_reviews(session, limit=10)
    assert items[0]["xunji_name"] == "新审核"
    assert items[1]["xunji_name"] == "旧审核"


def test_list_reviews_filters_verdict(session):
    session.add(
        ExerciseMappingReview(
            mapping_id=1,
            xunji_name="滤A",
            verdict=VERDICT_CURRENT_OK,
            reason="a",
            batch_id="bf",
            resolved=False,
        )
    )
    session.add(
        ExerciseMappingReview(
            mapping_id=2,
            xunji_name="滤B",
            verdict=VERDICT_SUSPECTED_ERROR,
            reason="b",
            batch_id="bf",
            resolved=False,
        )
    )
    session.commit()
    items = list_reviews(session, verdict=VERDICT_SUSPECTED_ERROR)
    assert len(items) == 1
    assert items[0]["xunji_name"] == "滤B"


# ---- API ----


def test_review_endpoint_requires_auth(client):
    resp = client.post("/api/exercise-mappings/review")
    assert resp.status_code in (401, 403)


def test_reviews_endpoint_returns_items(client, auth_headers, session):
    session.add(
        ExerciseMappingReview(
            mapping_id=9,
            xunji_name="API审核项",
            verdict=VERDICT_CURRENT_OK,
            reason="api",
            batch_id="api-batch",
            resolved=False,
        )
    )
    session.commit()
    resp = client.get(
        "/api/exercise-mappings/reviews",
        headers=auth_headers,
        params={"batch_id": "api-batch"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert len(body["items"]) == 1
    assert body["items"][0]["xunji_name"] == "API审核项"
