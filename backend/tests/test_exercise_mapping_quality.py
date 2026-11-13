"""V6-9f：候选质量回归（错配修复 / 覆盖率地板 / batch-reset / API）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ExerciseMapping, ExerciseMappingAudit
from app.services.exercise_mapping import (
    batch_reset_to_draft,
    build_seed_rows,
)
from app.services.exercise_mapping_candidates import (
    classify_applicability,
    generate_batch,
    generate_candidates,
)
from app.services.exercise_tokens import CARDIO_ONLY_CATEGORIES
from app.services.garmin_workout_mapper import EXERCISE_WHITELIST

DATA_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "xunji_movements.json"
)


def _all_names() -> list[str]:
    names = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert len(names) == 1091
    return names


def _top(name: str):
    cands = generate_candidates(name)
    assert cands, f"expected candidates for {name!r}"
    return cands[0]


# ---- 错配修复（10）----


def test_incline_not_lost():
    top = _top("上斜哑铃卧推")
    assert "INCLINE" in top.garmin_exercise_name


def test_decline_not_lost():
    top = _top("下斜杠铃卧推")
    assert "DECLINE" in top.garmin_exercise_name


def test_inline_barbell_bench():
    top = _top("上斜杠铃卧推")
    assert "INCLINE" in top.garmin_exercise_name


def test_wrist_curl_not_biceps():
    top = _top("正手杠铃手腕弯举")
    assert "WRIST" in top.garmin_exercise_name
    assert "BICEPS" not in top.garmin_exercise_name


def test_hip_abduction_not_shoulder():
    top = _top("弹力带-腿外展")
    name = top.garmin_exercise_name
    assert "LEG" in name or "HIP" in name
    assert "EXTERNAL_ROTATION" not in name


def test_machine_row_not_rowing_machine():
    top = _top("器械划船1")
    assert top.garmin_category != "INDOOR_ROW"
    assert top.garmin_exercise_name != "INDOOR_ROW"


def test_no_cardio_categories_anywhere():
    names = _all_names()
    strength = [n for n in names if classify_applicability(n)[0]]
    for n in strength:
        for c in generate_candidates(n):
            assert c.garmin_category not in CARDIO_ONLY_CATEGORIES, (
                f"{n!r} -> {c.garmin_category}"
            )
            assert c.garmin_exercise_name != "INDOOR_ROW", (
                f"{n!r} -> exercise INDOOR_ROW"
            )


def test_hamstring_curl_not_used_for_arm_curl():
    cands = generate_candidates("吊环弯举")
    assert cands
    assert all("HAMSTRING" not in c.garmin_exercise_name for c in cands)
    assert all("hamstring" not in c.garmin_display_name.lower() for c in cands)


def test_single_arm_matches_one_arm():
    top = _top("单手绳索臂屈伸")
    name = top.garmin_exercise_name
    assert "SINGLE" in name or "ONE_ARM" in name


def test_bent_over_row_prefers_bent_over():
    top = _top("俯身划船")
    name = top.garmin_exercise_name
    assert "BENT" in name or "BENT_OVER" in name


# ---- 回归保护（4）----


def test_seed_rows_still_active_and_unchanged():
    rows = build_seed_rows()
    assert len(rows) == 16
    assert all(r["status"] == "active" for r in rows)
    assert all(r["verified_level"] == "displayed" for r in rows)
    by_name = {r["xunji_name"]: r for r in rows}
    assert set(by_name) == set(EXERCISE_WHITELIST)
    for name, item in EXERCISE_WHITELIST.items():
        row = by_name[name]
        assert row["garmin_category"] == item["category"]
        assert row["garmin_exercise_name"] == item["exerciseName"]
        assert row["garmin_display_name"] == item["display_name"]


def test_high_confidence_not_collapsed():
    """high 档数量不得崩塌。

    V6-9f 收紧规则后 high 从 297 降到 **232**——这是**有意降级**：原先 66 条
    错配（手腕弯举→二头弯举、腿外展→肩外旋、器械划船→划船机、吊环弯举→腿弯举、
    上斜/下斜丢失等）本来就不该算 high，现在被扣分降到 medium/low 或退回无候选。
    宁可少而准，也不要多而错。阈值取实测 232 的约 78%（180）防进一步退化。
    """
    result = generate_batch(_all_names())
    high_count = sum(
        1 for cands in result.values() if any(c.confidence == "high" for c in cands)
    )
    assert high_count >= 180, f"high collapsed: {high_count}"


def test_strength_coverage_not_below_80pct():
    names = _all_names()
    result = generate_batch(names)
    strength = [n for n in names if classify_applicability(n)[0]]
    with_cands = sum(1 for n in strength if result[n])
    ratio = with_cands / len(strength) if strength else 0.0
    assert ratio >= 0.80, f"strength coverage {ratio:.1%} < 80%"


def test_not_applicable_and_blank_still_empty():
    assert generate_candidates("腿部拉伸") == []
    assert generate_candidates("") == []


# ---- batch-reset（4）----


def _add_active(
    session,
    *,
    name: str,
    source: str,
    mapping_version: int,
    exercise: str = "DUMBBELL_BENCH_PRESS",
    display: str = "Dumbbell Bench Press",
) -> ExerciseMapping:
    row = ExerciseMapping(
        xunji_name=name,
        garmin_category="BENCH_PRESS",
        garmin_exercise_name=exercise,
        garmin_display_name=display,
        weight_strategy="per_hand",
        status="active",
        confidence="high",
        source=source,
        verified_level="none",
        mapping_version=mapping_version,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_batch_reset_only_touches_auto_activated(session):
    seed = _add_active(session, name="reset-seed", source="seed", mapping_version=1)
    auto = _add_active(session, name="reset-auto-v2", source="auto", mapping_version=2)
    manual = _add_active(session, name="reset-auto-v1", source="auto", mapping_version=1)

    result = batch_reset_to_draft(session)
    session.refresh(seed)
    session.refresh(auto)
    session.refresh(manual)

    assert seed.status == "active"
    assert auto.status == "draft"
    assert manual.status == "active"
    assert result["reset"] == 1
    assert result["skipped"] == 2


def test_batch_reset_writes_audit(session):
    row = _add_active(session, name="reset-audit", source="algo", mapping_version=3)
    batch_reset_to_draft(session)
    audits = session.scalars(
        select(ExerciseMappingAudit).where(
            ExerciseMappingAudit.mapping_id == row.id,
            ExerciseMappingAudit.action == "reset",
        )
    ).all()
    assert len(audits) == 1
    assert audits[0].reason == "batch_reset"
    assert audits[0].action == "reset"


def test_batch_reset_does_not_change_mapping_values(session):
    row = _add_active(
        session,
        name="reset-keep-values",
        source="algo",
        mapping_version=2,
        exercise="BARBELL_BENCH_PRESS",
        display="Barbell Bench Press",
    )
    before = (
        row.garmin_category,
        row.garmin_exercise_name,
        row.garmin_display_name,
        row.mapping_version,
    )
    batch_reset_to_draft(session)
    session.refresh(row)
    assert row.status == "draft"
    assert (
        row.garmin_category,
        row.garmin_exercise_name,
        row.garmin_display_name,
        row.mapping_version,
    ) == before


def test_batch_reset_idempotent(session):
    _add_active(session, name="reset-idem", source="algo", mapping_version=2)
    first = batch_reset_to_draft(session)
    second = batch_reset_to_draft(session)
    assert first["reset"] == 1
    assert second["reset"] == 0


# ---- API（2）----


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


def test_api_batch_reset_requires_auth(client):
    resp = client.post("/api/exercise-mappings/batch-reset")
    assert resp.status_code in (401, 403)


def test_api_batch_reset_returns_counts(client, auth_headers, session):
    _add_active(session, name="api-reset-auto", source="algo", mapping_version=2)
    _add_active(session, name="api-reset-seed", source="seed", mapping_version=1)
    resp = client.post(
        "/api/exercise-mappings/batch-reset", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "reset" in body and "skipped" in body
    assert body["reset"] == 1
    assert body["skipped"] == 1
