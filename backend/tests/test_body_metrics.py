"""V1-7 身体数据模块测试（TDD）：录入 upsert 幂等、边界校验、趋势查询、AI prompt 体重趋势。

PRD US-12：身高/体重/血压(收缩/舒张)/血糖 + 体脂率，按 (date, type) upsert，
同日同类型重复录入覆盖旧值；身高/血压/血糖仅本地。
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import BodyMetric
from app.services.body_metrics import (
    BodyMetricValidationError,
    query_body_metrics,
    upsert_body_metric,
)


# ---------- service 层：upsert 与校验 ----------


class TestUpsertBodyMetric:
    def test_create_new_record(self, session):
        row = upsert_body_metric(session, date(2026, 8, 3), "weight", 72.4)
        assert row.id is not None
        assert row.date == date(2026, 8, 3)
        assert row.type == "weight"
        assert row.value == 72.4
        assert row.unit == "kg"
        assert row.synced_to_xunji is False

    def test_same_date_type_upsert_overrides(self, session):
        """同日同类型重复录入覆盖旧值，不产生重复行。"""
        r1 = upsert_body_metric(session, date(2026, 8, 3), "weight", 72.4, note="晨起")
        r2 = upsert_body_metric(session, date(2026, 8, 3), "weight", 73.1, note="睡前")
        assert r1.id == r2.id
        rows = session.query(BodyMetric).filter_by(date=date(2026, 8, 3), type="weight").all()
        assert len(rows) == 1
        assert rows[0].value == 73.1
        assert rows[0].note == "睡前"

    def test_same_date_different_type_kept(self, session):
        upsert_body_metric(session, date(2026, 8, 3), "bp_systolic", 120)
        upsert_body_metric(session, date(2026, 8, 3), "bp_diastolic", 80)
        assert session.query(BodyMetric).filter_by(date=date(2026, 8, 3)).count() == 2

    def test_default_units(self, session):
        """各类型默认单位符合 PRD：cm / kg / % / mmHg / mmol/L。"""
        expected = {
            "height": "cm",
            "weight": "kg",
            "bodyfat": "%",
            "bp_systolic": "mmHg",
            "bp_diastolic": "mmHg",
            "blood_glucose": "mmol/L",
        }
        for type_, unit in expected.items():
            row = upsert_body_metric(session, date(2026, 8, 3), type_, _valid_value(type_))
            assert row.unit == unit

    def test_unknown_type_rejected(self, session):
        with pytest.raises(BodyMetricValidationError):
            upsert_body_metric(session, date(2026, 8, 3), "body_temperature", 36.5)


def _valid_value(type_):
    return {
        "height": 175.0,
        "weight": 72.0,
        "bodyfat": 18.0,
        "bp_systolic": 120.0,
        "bp_diastolic": 80.0,
        "blood_glucose": 5.5,
    }[type_]


class TestMetricValidation:
    """四类指标边界值校验（PRD US-12 AC1 + 任务要求：血糖 0.5~40 mmol/L 合理区间）。"""

    @pytest.mark.parametrize(
        "type_,value",
        [
            ("height", 50.0), ("height", 250.0),
            ("weight", 10.0), ("weight", 400.0),
            ("bodyfat", 1.0), ("bodyfat", 70.0),
            ("bp_systolic", 40.0), ("bp_systolic", 300.0),
            ("bp_diastolic", 20.0), ("bp_diastolic", 200.0),
            ("blood_glucose", 0.5), ("blood_glucose", 40.0),
        ],
    )
    def test_boundary_values_accepted(self, session, type_, value):
        row = upsert_body_metric(session, date(2026, 8, 3), type_, value)
        assert row.value == value

    @pytest.mark.parametrize(
        "type_,value",
        [
            ("height", 49.9), ("height", 250.1),
            ("weight", 9.9), ("weight", 400.1),
            ("bodyfat", 0.9), ("bodyfat", 70.1),
            ("bp_systolic", 39.9), ("bp_systolic", 300.1),
            ("bp_diastolic", 19.9), ("bp_diastolic", 200.1),
            ("blood_glucose", 0.49), ("blood_glucose", 40.1),
            ("weight", -1), ("blood_glucose", 0),
        ],
    )
    def test_out_of_range_rejected(self, session, type_, value):
        with pytest.raises(BodyMetricValidationError):
            upsert_body_metric(session, date(2026, 8, 3), type_, value)


class TestQueryBodyMetrics:
    def test_filter_by_type_and_range(self, session):
        upsert_body_metric(session, date(2026, 7, 1), "weight", 73.0)
        upsert_body_metric(session, date(2026, 7, 15), "weight", 72.5)
        upsert_body_metric(session, date(2026, 8, 1), "weight", 72.0)
        upsert_body_metric(session, date(2026, 7, 15), "blood_glucose", 5.6)

        rows = query_body_metrics(session, type_="weight")
        assert [r.value for r in rows] == [73.0, 72.5, 72.0]  # 按日期升序

        rows = query_body_metrics(
            session, type_="weight", from_=date(2026, 7, 10), to=date(2026, 7, 31)
        )
        assert [r.value for r in rows] == [72.5]

    def test_no_filter_returns_all(self, session):
        upsert_body_metric(session, date(2026, 8, 3), "height", 175)
        upsert_body_metric(session, date(2026, 8, 3), "weight", 72.4)
        assert len(query_body_metrics(session)) == 2


# ---------- API 层 ----------


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings

    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth(client):
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


class TestCreateApi:
    def test_create_weight(self, client, auth, session):
        resp = client.post(
            "/api/body-metrics",
            json={"date": "2026-08-03", "type": "weight", "value": 72.4},
            headers=auth,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "weight"
        assert data["value"] == 72.4
        assert data["unit"] == "kg"
        assert data["synced_to_xunji"] is False
        assert session.query(BodyMetric).count() == 1

    def test_upsert_same_date_type_via_api(self, client, auth, session):
        for value in (72.4, 73.0):
            resp = client.post(
                "/api/body-metrics",
                json={"date": "2026-08-03", "type": "weight", "value": value},
                headers=auth,
            )
            assert resp.status_code == 200
        assert session.query(BodyMetric).count() == 1
        assert session.query(BodyMetric).one().value == 73.0

    def test_invalid_type_400(self, client, auth):
        resp = client.post(
            "/api/body-metrics",
            json={"date": "2026-08-03", "type": "temperature", "value": 36.5},
            headers=auth,
        )
        assert resp.status_code == 400

    def test_out_of_range_400(self, client, auth):
        resp = client.post(
            "/api/body-metrics",
            json={"date": "2026-08-03", "type": "blood_glucose", "value": 99.0},
            headers=auth,
        )
        assert resp.status_code == 400

    def test_invalid_date_400(self, client, auth):
        resp = client.post(
            "/api/body-metrics",
            json={"date": "2026-13-40", "type": "weight", "value": 72.0},
            headers=auth,
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client):
        resp = client.post(
            "/api/body-metrics",
            json={"date": "2026-08-03", "type": "weight", "value": 72.4},
        )
        assert resp.status_code == 401


class TestQueryApi:
    def test_list_with_filters(self, client, auth, session):
        upsert_body_metric(session, date(2026, 7, 1), "weight", 73.0)
        upsert_body_metric(session, date(2026, 8, 1), "weight", 72.0)
        upsert_body_metric(session, date(2026, 8, 1), "height", 175.0)

        resp = client.get("/api/body-metrics", headers=auth)
        assert resp.status_code == 200
        assert len(resp.json()["metrics"]) == 3

        resp = client.get(
            "/api/body-metrics?type=weight&from=2026-07-15&to=2026-08-03", headers=auth
        )
        data = resp.json()["metrics"]
        assert len(data) == 1
        assert data[0]["value"] == 72.0

    def test_bad_query_params_400(self, client, auth):
        resp = client.get("/api/body-metrics?from=not-a-date", headers=auth)
        assert resp.status_code == 400

    def test_requires_auth(self, client):
        assert client.get("/api/body-metrics").status_code == 401


# ---------- AI prompt：近 4 周体重趋势节（US-12 AC6） ----------


class TestSessionReviewPromptWeightTrend:
    def test_prompt_contains_weight_trend_section(self):
        from app.services.ai import build_session_review_prompt

        workout = {"date": "2026-08-03", "title": "胸", "movements": []}
        recovery = {
            "days_count": 0,
            "weight_trend": [
                {"date": "2026-07-20", "value": 73.0},
                {"date": "2026-08-02", "value": 72.4},
            ],
        }
        messages = build_session_review_prompt(workout, {}, recovery)
        user = messages[1]["content"]
        assert "近4周体重趋势" in user
        assert "2026-08-02" in user
        assert "72.4" in user

    def test_prompt_notes_missing_weight(self):
        from app.services.ai import build_session_review_prompt

        workout = {"date": "2026-08-03", "movements": []}
        messages = build_session_review_prompt(workout, {}, {"days_count": 0, "weight_trend": []})
        assert "近4周无体重记录" in messages[1]["content"]
