"""ADR-P0-2：预览端点 excluded 通道 + load_all_mappings opt-in 契约。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.main  # noqa: F401
from app.models import ExerciseMapping, XunjiPlan
from app.services.exercise_mapping import load_all_mappings

PLAN_DATE = date(2026, 11, 12)
PLAN_REF = "platform:155"
STRENGTH_NAME = "海豹杠铃划船"
STRETCH_NAME = "腿部拉伸"
DRAFT_NAME = "待复核划船"
UNKNOWN_NAME = "完全未知动作XYZ"


def _make_set(weight=20, reps=10):
    return {
        "set_type": "working",
        "weight": weight,
        "left_weight": weight,
        "unit": "kg",
        "reps": reps,
        "duration_seconds": 60,
        "rest_seconds": 60,
        "rounds": None,
    }


def _add_mapping(
    session,
    *,
    name: str,
    status: str = "active",
    category: str | None = "ROW",
    exercise: str | None = "BARBELL_ROW",
    display: str | None = "Barbell Row",
) -> ExerciseMapping:
    row = ExerciseMapping(
        xunji_name=name,
        garmin_category=category,
        garmin_exercise_name=exercise,
        garmin_display_name=display,
        weight_strategy="total",
        status=status,
        confidence="high",
        source="test",
        verified_level="catalog",
        mapping_version=1,
        not_applicable_reason="stretch" if status == "not_applicable" else None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _set_plan_cache(session, movements: list[dict]) -> XunjiPlan:
    session.query(XunjiPlan).delete()
    row = XunjiPlan(
        plan_ref=PLAN_REF,
        plan_json=json.dumps(
            {
                "plan": {"plan_ref": PLAN_REF, "name": "增肌计划"},
                "days": [
                    {
                        "datestr": PLAN_DATE.isoformat(),
                        "workout": {
                            "name": "预览 excluded 测试",
                            "movements": [
                                {
                                    "name": m["name"],
                                    "rest_seconds": m.get("rest_seconds", 60),
                                    "target_sets": m.get("sets")
                                    or m.get("target_sets")
                                    or [_make_set()],
                                }
                                for m in movements
                            ],
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        date_from=PLAN_DATE - timedelta(days=1),
        date_to=PLAN_DATE + timedelta(days=60),
        fetched_at=datetime.now(),
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings
    from app.db import get_session
    from app.main import app

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


def test_preview_returns_excluded(client, auth_headers, session):
    _add_mapping(session, name=STRENGTH_NAME, status="active")
    _add_mapping(
        session,
        name=STRETCH_NAME,
        status="not_applicable",
        category=None,
        exercise=None,
        display=None,
    )
    _set_plan_cache(
        session,
        [
            {"name": STRENGTH_NAME, "sets": [_make_set()]},
            {"name": STRETCH_NAME, "sets": [_make_set(weight=0, reps=1)]},
        ],
    )

    resp = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/preview",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["excluded"] == [
        {"name": STRETCH_NAME, "reason": "not_applicable"}
    ]
    names = [m["name"] for m in body["movements"]]
    assert STRENGTH_NAME in names
    assert STRETCH_NAME not in names


def test_preview_still_422_on_unmapped(client, auth_headers, session):
    _add_mapping(session, name=STRENGTH_NAME, status="active")
    _add_mapping(
        session,
        name=STRETCH_NAME,
        status="not_applicable",
        category=None,
        exercise=None,
        display=None,
    )
    _set_plan_cache(
        session,
        [
            {"name": STRENGTH_NAME, "sets": [_make_set()]},
            {"name": STRETCH_NAME, "sets": [_make_set(weight=0, reps=1)]},
            {"name": UNKNOWN_NAME, "sets": [_make_set()]},
        ],
    )

    resp = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/preview",
        headers=auth_headers,
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "PLAN_MAPPING_UNSUPPORTED"
    assert "issues" in detail
    assert "excluded" in detail
    codes = {issue["code"] for issue in detail["issues"]}
    assert "UNKNOWN_EXERCISE" in codes
    assert detail["excluded"] == [
        {"name": STRETCH_NAME, "reason": "not_applicable"}
    ]


def test_preview_draft_softened_not_excluded(client, auth_headers, session):
    _add_mapping(
        session,
        name=DRAFT_NAME,
        status="draft",
        category="ROW",
        exercise="BARBELL_ROW",
        display="Barbell Row",
    )
    _set_plan_cache(session, [{"name": DRAFT_NAME, "sets": [_make_set()]}])

    resp = client.get(
        f"/api/plans/{PLAN_DATE.isoformat()}/garmin/preview",
        headers=auth_headers,
    )
    # _preview_mappings 把 draft 软化为 active → 预览 200，不进 excluded
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("excluded") == []
    assert any(m["name"] == DRAFT_NAME for m in body["movements"])


def test_load_all_mappings_default_excludes_not_applicable(session):
    _add_mapping(session, name=STRENGTH_NAME, status="active")
    _add_mapping(
        session,
        name=STRETCH_NAME,
        status="not_applicable",
        category=None,
        exercise=None,
        display=None,
    )
    mappings = load_all_mappings(session)
    assert STRENGTH_NAME in mappings
    assert STRETCH_NAME not in mappings


def test_load_all_mappings_include_excluded(session):
    _add_mapping(session, name=STRENGTH_NAME, status="active")
    _add_mapping(
        session,
        name=STRETCH_NAME,
        status="not_applicable",
        category=None,
        exercise=None,
        display=None,
    )
    mappings = load_all_mappings(session, include_excluded=True)
    assert STRENGTH_NAME in mappings
    assert STRETCH_NAME in mappings
    assert mappings[STRETCH_NAME]["status"] == "not_applicable"
