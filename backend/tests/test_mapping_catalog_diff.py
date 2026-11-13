"""ADR-P1-1：训记动作全集 diff / 疑似改名 / 人工判定应用。"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ExerciseMapping, ExerciseMappingAudit
from app.services import exercise_mapping_catalog as catalog_svc


def _add_mapping(
    session,
    name: str,
    *,
    status: str = "draft",
    verified_level: str | None = None,
    verified_at: datetime | None = None,
    relation: str | None = None,
    confidence: str | None = None,
    mapping_version: int = 1,
    source: str | None = "auto",
    note: str | None = None,
) -> ExerciseMapping:
    row = ExerciseMapping(
        xunji_name=name,
        status=status,
        verified_level=verified_level,
        verified_at=verified_at,
        relation=relation,
        confidence=confidence,
        mapping_version=mapping_version,
        source=source,
        note=note,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---------- diff（7） ----------


def test_no_diff_when_identical(session):
    names = ["动作A", "动作B", "动作C"]
    for n in names:
        _add_mapping(session, n)
    result = catalog_svc.catalog_diff(session, names=names)
    assert result["added"] == []
    assert result["removed"] == []
    assert result["needs_confirmation"] is False


def test_added_detected(session):
    _add_mapping(session, "旧动作")
    result = catalog_svc.catalog_diff(session, names=["旧动作", "新动作"])
    assert result["added"] == ["新动作"]
    assert result["needs_confirmation"] is True


def test_removed_detected(session):
    _add_mapping(session, "旧动作")
    _add_mapping(session, "保留")
    result = catalog_svc.catalog_diff(session, names=["保留"])
    assert result["removed"] == ["旧动作"]
    assert result["needs_confirmation"] is True


def test_unchanged_count(session):
    for n in ("共有1", "共有2", "仅DB"):
        _add_mapping(session, n)
    names = ["共有1", "共有2", "仅JSON"]
    result = catalog_svc.catalog_diff(session, names=names)
    assert result["unchanged"] == 2


def test_rename_candidate_by_movement_token(session):
    _add_mapping(session, "哑铃卧推")
    result = catalog_svc.catalog_diff(session, names=["哑铃平板卧推"])
    assert len(result["rename_candidates"]) == 1
    cand = result["rename_candidates"][0]
    assert cand["from"] == "哑铃卧推"
    assert cand["to"] == "哑铃平板卧推"
    assert "same_movement_token" in cand["reasons"]


def test_rename_candidate_by_similarity(session):
    # 无共同器械/动作词根，但字面相似度高
    old, new = "自定义甲乙丙丁动作", "自定义甲乙丙戊动作"
    score = __import__("difflib").SequenceMatcher(None, old, new).ratio()
    assert score >= 0.5
    _add_mapping(session, old)
    result = catalog_svc.catalog_diff(session, names=[new])
    assert len(result["rename_candidates"]) == 1
    cand = result["rename_candidates"][0]
    assert cand["from"] == old
    assert cand["to"] == new
    assert cand["score"] >= 0.5
    assert cand["reasons"] == []


def test_unrelated_names_not_paired(session):
    _add_mapping(session, "完全无关甲")
    result = catalog_svc.catalog_diff(session, names=["截然不同乙"])
    assert result["rename_candidates"] == []


# ---------- apply rename（3） ----------


def test_rename_keeps_id_and_updates_name(session):
    row = _add_mapping(session, "旧名动作", status="active", relation="EXACT")
    mid = row.id
    out = catalog_svc.apply_catalog_change(
        session, action="rename", old_name="旧名动作", new_name="新名动作"
    )
    assert out["changed"] is True
    assert out["mapping_id"] == mid
    refreshed = session.get(ExerciseMapping, mid)
    assert refreshed is not None
    assert refreshed.xunji_name == "新名动作"
    assert refreshed.id == mid


def test_rename_does_not_reset_verified_level(session):
    ts = datetime(2026, 1, 15, 12, 0, 0)
    row = _add_mapping(
        session,
        "已验证旧名",
        status="active",
        verified_level="displayed",
        verified_at=ts,
        relation="EXACT",
        confidence="high",
        mapping_version=3,
    )
    mid = row.id
    catalog_svc.apply_catalog_change(
        session, action="rename", old_name="已验证旧名", new_name="已验证新名"
    )
    refreshed = session.get(ExerciseMapping, mid)
    assert refreshed is not None
    assert refreshed.verified_level == "displayed"
    assert refreshed.verified_at == ts
    assert refreshed.relation == "EXACT"
    assert refreshed.confidence == "high"
    assert refreshed.status == "active"
    assert refreshed.mapping_version == 4


def test_rename_writes_audit_with_old_name(session):
    row = _add_mapping(session, "审计旧名")
    catalog_svc.apply_catalog_change(
        session, action="rename", old_name="审计旧名", new_name="审计新名"
    )
    audit = session.scalars(
        select(ExerciseMappingAudit)
        .where(ExerciseMappingAudit.mapping_id == row.id)
        .order_by(ExerciseMappingAudit.id.desc())
    ).first()
    assert audit is not None
    assert audit.action == "rename"
    assert audit.reason == "catalog_change"
    blob = (audit.before_json or "") + (audit.after_json or "")
    assert "审计旧名" in blob


# ---------- apply new / delete（2） ----------


def test_new_creates_draft_row(session):
    out = catalog_svc.apply_catalog_change(
        session, action="new", new_name="全新动作"
    )
    assert out["changed"] is True
    row = session.get(ExerciseMapping, out["mapping_id"])
    assert row is not None
    assert row.status == "draft"
    assert row.relation is None
    assert row.confidence is None
    assert row.mapping_version == 1
    assert row.source == "auto"
    assert row.match_basis is None
    assert row.unmapped_reason is None
    assert row.verified_level is None


def test_delete_disables_without_removing(session):
    row = _add_mapping(session, "待删动作", status="active", note="原备注")
    mid = row.id
    out = catalog_svc.apply_catalog_change(
        session, action="delete", old_name="待删动作"
    )
    assert out["changed"] is True
    refreshed = session.get(ExerciseMapping, mid)
    assert refreshed is not None
    assert refreshed.status == "disabled"
    assert "训记已移除" in (refreshed.note or "")
    audit = session.scalars(
        select(ExerciseMappingAudit).where(
            ExerciseMappingAudit.mapping_id == mid,
            ExerciseMappingAudit.action == "delete",
        )
    ).first()
    assert audit is not None
    assert audit.reason == "catalog_change"


# ---------- 错误与幂等（3+） ----------


def test_rename_rejects_missing_old(session):
    with pytest.raises(ValueError):
        catalog_svc.apply_catalog_change(
            session, action="rename", old_name="不存在", new_name="目标名"
        )


def test_rename_rejects_existing_new(session):
    _add_mapping(session, "源动作")
    _add_mapping(session, "已被占用")
    with pytest.raises(ValueError):
        catalog_svc.apply_catalog_change(
            session, action="rename", old_name="源动作", new_name="已被占用"
        )


def test_apply_is_idempotent(session):
    _add_mapping(session, "幂等旧", status="active", verified_level="catalog")
    first = catalog_svc.apply_catalog_change(
        session, action="rename", old_name="幂等旧", new_name="幂等新"
    )
    second = catalog_svc.apply_catalog_change(
        session, action="rename", old_name="幂等旧", new_name="幂等新"
    )
    assert first["changed"] is True
    assert second["changed"] is False

    n1 = catalog_svc.apply_catalog_change(session, action="new", new_name="幂等新建")
    n2 = catalog_svc.apply_catalog_change(session, action="new", new_name="幂等新建")
    assert n1["changed"] is True
    assert n2["changed"] is False

    _add_mapping(session, "幂等删")
    d1 = catalog_svc.apply_catalog_change(session, action="delete", old_name="幂等删")
    d2 = catalog_svc.apply_catalog_change(session, action="delete", old_name="幂等删")
    assert d1["changed"] is True
    assert d2["changed"] is False

    audits = session.scalars(
        select(ExerciseMappingAudit).where(
            ExerciseMappingAudit.action == "rename",
            ExerciseMappingAudit.mapping_id == first["mapping_id"],
        )
    ).all()
    assert len(audits) == 1


def test_invalid_action_raises(session):
    with pytest.raises(ValueError):
        catalog_svc.apply_catalog_change(session, action="bogus")


# ---------- API（2） ----------


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


def test_catalog_diff_endpoint(client, auth_headers, session):
    _add_mapping(session, "端点动作")
    resp = client.get("/api/exercise-mappings/catalog-diff", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "added" in body
    assert "removed" in body
    assert "rename_candidates" in body


def test_catalog_apply_endpoint_returns_422_on_bad_input(
    client, auth_headers, session
):
    resp = client.post(
        "/api/exercise-mappings/catalog-apply",
        headers=auth_headers,
        json={"action": "bogus"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_CATALOG_CHANGE"
