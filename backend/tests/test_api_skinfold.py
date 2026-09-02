"""V4-3 皮脂钳体脂率 API 测试（TestClient）。

- /api/settings/profile：GET/PUT + 校验；
- /api/skinfold/methods：返回 4 方案元数据；
- /api/skinfold/records POST/GET：幂等 upsert、缺设置提示、mm 越界。
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import BodyMetric, Setting, SkinfoldRecord


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
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
def auth(client):
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_profile(session, gender="male", birth_year=1990):
    session.add(Setting(gender=gender, birth_date=date(birth_year, 6, 15)))
    session.commit()


# ---------- /api/settings/profile ----------


class TestProfileAPI:
    def test_requires_auth(self, client):
        assert client.get("/api/settings/profile").status_code == 401
        assert client.put("/api/settings/profile", json={"gender": "male"}).status_code == 401

    def test_get_returns_null_when_empty(self, client, auth):
        resp = client.get("/api/settings/profile", headers=auth)
        assert resp.status_code == 200
        assert resp.json() == {"gender": None, "birth_date": None}

    def test_put_then_get_roundtrip(self, client, auth):
        resp = client.put(
            "/api/settings/profile",
            headers=auth,
            json={"gender": "male", "birth_date": "1990-06-15"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["gender"] == "male"
        assert body["birth_date"] == "1990-06-15"

        resp2 = client.get("/api/settings/profile", headers=auth)
        assert resp2.json() == {"gender": "male", "birth_date": "1990-06-15"}

    def test_put_invalid_gender_returns_400(self, client, auth):
        resp = client.put(
            "/api/settings/profile",
            headers=auth,
            json={"gender": "x"},
        )
        assert resp.status_code == 400
        assert "gender" in resp.json()["detail"]

    def test_put_invalid_birth_date_returns_400(self, client, auth):
        resp = client.put(
            "/api/settings/profile",
            headers=auth,
            json={"gender": "male", "birth_date": "not-a-date"},
        )
        assert resp.status_code == 400
        assert "birth_date" in resp.json()["detail"]

    def test_put_age_out_of_range_returns_400(self, client, auth):
        # 推算年龄 = 0（当年出生）
        resp = client.put(
            "/api/settings/profile",
            headers=auth,
            json={"gender": "male", "birth_date": "2024-01-01"},
        )
        assert resp.status_code == 400
        assert "年龄" in resp.json()["detail"]

    def test_put_patch_semantic_only_updates_provided(self, client, auth):
        """先写 gender + birth_date；再 PUT 只传 gender，birth_date 不变。"""
        client.put(
            "/api/settings/profile", headers=auth,
            json={"gender": "male", "birth_date": "1990-06-15"},
        )
        resp = client.put(
            "/api/settings/profile", headers=auth,
            json={"gender": "female"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["gender"] == "female"
        assert body["birth_date"] == "1990-06-15"

    def test_put_empty_body_returns_400(self, client, auth):
        resp = client.put("/api/settings/profile", headers=auth, json={})
        assert resp.status_code == 400


# ---------- /api/skinfold/methods ----------


class TestMethodsAPI:
    def test_requires_auth(self, client):
        assert client.get("/api/skinfold/methods").status_code == 401

    def test_returns_four_methods(self, client, auth):
        resp = client.get("/api/skinfold/methods", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        keys = {m["key"] for m in data["methods"]}
        assert keys == {"jp3_male", "jp3_female", "dw4", "jp7"}
        # 部位带中文名
        for m in data["methods"]:
            assert all("name_zh" in s for s in m["sites"])
            assert {"key", "name_zh", "sex", "self_test"} <= set(m.keys())

    def test_profile_section_reflects_settings(self, client, auth, session):
        _seed_profile(session, gender="female", birth_year=1992)
        resp = client.get("/api/skinfold/methods", headers=auth)
        assert resp.json()["profile"] == {
            "gender": "female",
            "birth_date": "1992-06-15",
        }


# ---------- /api/skinfold/records ----------


class TestSkinfoldRecordsAPI:
    def test_requires_auth(self, client):
        assert client.get("/api/skinfold/records").status_code == 401
        assert client.post("/api/skinfold/records", json={}).status_code == 401

    def test_post_without_settings_returns_400_with_chinese_hint(self, client, auth):
        resp = client.post(
            "/api/skinfold/records", headers=auth,
            json={
                "date": "2026-08-10",
                "method": "jp3_male",
                "sites": {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
            },
        )
        assert resp.status_code == 400
        assert "设置页" in resp.json()["detail"]

    def test_post_normal_flow_returns_record_and_body_metric(self, client, auth, session):
        _seed_profile(session)
        resp = client.post(
            "/api/skinfold/records", headers=auth,
            json={
                "date": "2026-08-10",
                "method": "jp3_male",
                "sites": {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["record"]["date"] == "2026-08-10"
        assert data["record"]["method"] == "jp3_male"
        assert "Jackson-Pollock 3 点（男）" in data["record"]["method_zh"]
        assert data["record"]["bodyfat_result"] > 0
        assert data["body_metric"]["type"] == "bodyfat"
        assert data["body_metric"]["date"] == "2026-08-10"
        assert data["body_metric"]["value"] == data["record"]["bodyfat_result"]

    def test_post_idempotent_same_day_same_method(self, client, auth, session):
        _seed_profile(session)
        payload = {
            "date": "2026-08-10",
            "method": "jp3_male",
            "sites": {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
        }
        r1 = client.post("/api/skinfold/records", headers=auth, json=payload)
        assert r1.status_code == 200

        payload2 = dict(payload)
        payload2["sites"] = {"chest": 12.0, "abdomen": 22.0, "thigh": 16.0}
        r2 = client.post("/api/skinfold/records", headers=auth, json=payload2)
        assert r2.status_code == 200
        # 两次 record.id 一致 → 幂等 upsert
        assert r1.json()["record"]["id"] == r2.json()["record"]["id"]

        # GET 仅 1 条
        resp = client.get(
            "/api/skinfold/records", headers=auth,
            params={"method": "jp3_male", "date": "2026-08-10"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["records"]) == 1
        # 体脂率随之覆盖
        assert resp.json()["records"][0]["bodyfat_result"] == r2.json()["record"]["bodyfat_result"]

    def test_post_mm_out_of_range_returns_400(self, client, auth, session):
        _seed_profile(session)
        resp = client.post(
            "/api/skinfold/records", headers=auth,
            json={
                "date": "2026-08-10",
                "method": "jp3_male",
                "sites": {"chest": 1.0, "abdomen": 20.0, "thigh": 15.0},
            },
        )
        assert resp.status_code == 400
        assert "超出合理区间" in resp.json()["detail"]

    def test_post_invalid_method_returns_400(self, client, auth, session):
        _seed_profile(session)
        resp = client.post(
            "/api/skinfold/records", headers=auth,
            json={
                "date": "2026-08-10",
                "method": "jp99",
                "sites": {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
            },
        )
        assert resp.status_code == 400
        assert "未知方案" in resp.json()["detail"]

    def test_post_invalid_date_returns_400(self, client, auth, session):
        _seed_profile(session)
        resp = client.post(
            "/api/skinfold/records", headers=auth,
            json={
                "date": "2026-08-99",
                "method": "jp3_male",
                "sites": {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
            },
        )
        assert resp.status_code == 400

    def test_get_records_filter_and_order(self, client, auth, session):
        _seed_profile(session)
        client.post(
            "/api/skinfold/records", headers=auth,
            json={
                "date": "2026-08-10", "method": "jp3_male",
                "sites": {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
            },
        )
        client.post(
            "/api/skinfold/records", headers=auth,
            json={
                "date": "2026-08-12", "method": "dw4",
                "sites": {
                    "biceps": 10.0, "triceps": 12.0,
                    "subscapular": 15.0, "suprailiac": 14.0,
                },
            },
        )
        resp = client.get("/api/skinfold/records", headers=auth)
        assert resp.status_code == 200
        dates = [r["date"] for r in resp.json()["records"]]
        assert dates == ["2026-08-12", "2026-08-10"]  # 日期倒序

        only_dw4 = client.get(
            "/api/skinfold/records", headers=auth, params={"method": "dw4"},
        )
        assert len(only_dw4.json()["records"]) == 1
        assert only_dw4.json()["records"][0]["method"] == "dw4"

        only_day = client.get(
            "/api/skinfold/records", headers=auth, params={"date": "2026-08-10"},
        )
        assert len(only_day.json()["records"]) == 1
        assert only_day.json()["records"][0]["date"] == "2026-08-10"

    def test_get_records_invalid_method_returns_400(self, client, auth):
        resp = client.get(
            "/api/skinfold/records", headers=auth, params={"method": "jp99"},
        )
        assert resp.status_code == 400