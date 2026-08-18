"""V3-9 体脂秤"身体测量报告"图片导入测试（TDD）。

- build_prompt：body_scale_v1 schema + 指标名→type 映射表；
- normalize_extraction：字符串数值化、无年份日期默认当前年；
- validate_extraction：date 合法、metrics 每条 type 在 METRIC_TYPES、value 数值；
- 越界仅警告不拦截（新类型软区间）；
- extract_from_image：校验失败带 feedback 重试 1 次（vision_extract mock）；
- confirm_import：按 (date,type) 幂等 upsert、selected=false 跳过、sync_xunji 走训记三段式（mock）；
- API：401/413/422、extract 不落库、confirm 幂等。
"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import BodyMetric
from app.services import body_image as svc
from app.services.body_image import (
    build_prompt,
    confirm_import,
    extract_from_image,
    normalize_extraction,
    validate_extraction,
)
from app.services.body_metrics import METRIC_TYPES, upsert_body_metric
from app.services.screenshot import ExtractionError

VALID_DATA = {
    "schema": "body_scale_v1",
    "date": "2026-08-18",
    "metrics": [
        {"type": "weight", "value": 86.7},
        {"type": "bodyfat", "value": 25.5},
        {"type": "visceral_fat", "value": 13},
        {"type": "bmr", "value": 1764},
        {"type": "muscle_ability", "value": 3.0},
        {"type": "muscle_rate", "value": 70.8},
        {"type": "water_rate", "value": 51.9},
        {"type": "protein_rate", "value": 18.9},
        {"type": "bone_mass", "value": 3.2},
        {"type": "bmi", "value": 29.3},
        {"type": "body_age", "value": 44},
        {"type": "body_score", "value": 72},
    ],
}


def _valid(**overrides):
    data = json.loads(json.dumps(VALID_DATA, ensure_ascii=False))
    data.update(overrides)
    return data


# ---------- 新指标类型定义（METRIC_TYPES 扩展） ----------


class TestNewMetricTypes:
    EXPECTED_UNITS = {
        "visceral_fat": "级",
        "bmr": "kcal",
        "muscle_rate": "%",
        "water_rate": "%",
        "protein_rate": "%",
        "bone_mass": "kg",
        "muscle_ability": "级",
        "bmi": "kg/m²",
        "body_age": "岁",
        "body_score": "分",
    }

    def test_all_new_types_registered(self):
        for type_ in self.EXPECTED_UNITS:
            assert type_ in METRIC_TYPES, f"缺少指标类型 {type_}"

    def test_default_units(self, session):
        for type_, unit in self.EXPECTED_UNITS.items():
            row = upsert_body_metric(session, date(2026, 8, 18), type_, 5.0)
            assert row.unit == unit

    def test_new_types_are_soft_range(self, session):
        """新类型越界仅警告不拒绝（软区间），upsert 不抛错。"""
        row = upsert_body_metric(session, date(2026, 8, 18), "bmi", 99.9)
        assert row.value == 99.9

    def test_syncable_types_unchanged(self):
        from app.services.body_metrics import SYNCABLE_TYPES

        assert SYNCABLE_TYPES == frozenset({"weight", "bodyfat"})


# ---------- prompt 构造 ----------


class TestBuildPrompt:
    def test_contains_schema(self):
        prompt = build_prompt()
        assert "body_scale_v1" in prompt
        assert '"date"' in prompt
        assert '"metrics"' in prompt

    def test_contains_mapping_table(self):
        prompt = build_prompt()
        for pair in (
            ("体重", "weight"),
            ("脂肪率", "bodyfat"),
            ("内脏脂肪指数", "visceral_fat"),
            ("基础代谢率", "bmr"),
            ("肌肉率", "muscle_rate"),
            ("水分", "water_rate"),
            ("蛋白质", "protein_rate"),
            ("骨量", "bone_mass"),
            ("储肌能力等级", "muscle_ability"),
            ("BMI", "bmi"),
            ("身体年龄", "body_age"),
            ("body_score",),
        ):
            for token in pair:
                assert token in prompt, f"prompt 缺少映射项 {token}"

    def test_no_year_defaults_current_year_rule(self):
        assert "当前年" in build_prompt()

    def test_text_metrics_excluded(self):
        """身体类型等文本类指标不入 metrics。"""
        assert "身体类型" in build_prompt()

    def test_feedback_appended(self):
        assert "缺少 date" in build_prompt(feedback="缺少 date")


# ---------- 规范化（数值化 + 无年份日期） ----------


class TestNormalizeExtraction:
    def test_string_values_coerced(self):
        data = _valid(metrics=[{"type": "weight", "value": "86.7"}])
        out = normalize_extraction(data)
        assert out["metrics"][0]["value"] == 86.7

    def test_yearless_date_defaults_current_year(self):
        for raw in ("08-18", "8月18日", "8/18"):
            data = _valid(date=raw)
            out = normalize_extraction(data, today=date(2026, 8, 18))
            assert out["date"] == "2026-08-18", raw

    def test_full_date_untouched(self):
        out = normalize_extraction(_valid(date="2025-01-02"), today=date(2026, 8, 18))
        assert out["date"] == "2025-01-02"

    def test_unknown_type_entries_dropped(self):
        """文本类/未知指标在规范化时剔除（身体类型等）。"""
        data = _valid(
            metrics=[
                {"type": "weight", "value": 86.7},
                {"type": "body_type", "value": "偏胖型"},
            ]
        )
        out = normalize_extraction(data)
        assert [m["type"] for m in out["metrics"]] == ["weight"]


# ---------- Schema 校验 ----------


class TestValidateExtraction:
    def test_valid_passes(self):
        assert validate_extraction(_valid()) == []

    def test_missing_date(self):
        data = _valid()
        del data["date"]
        assert any("date" in e for e in validate_extraction(data))

    def test_bad_date(self):
        assert validate_extraction(_valid(date="2026-13-40"))
        assert validate_extraction(_valid(date=""))

    def test_metrics_required(self):
        data = _valid()
        del data["metrics"]
        assert validate_extraction(data)
        assert validate_extraction(_valid(metrics=[]))
        assert validate_extraction(_valid(metrics="x"))

    def test_unknown_type_rejected(self):
        assert validate_extraction(_valid(metrics=[{"type": "heart_rate", "value": 60}]))

    def test_non_numeric_value_rejected(self):
        bad = _valid(metrics=[{"type": "weight", "value": "偏胖"}])
        assert validate_extraction(bad)

    def test_out_of_range_soft_type_is_warning_not_error(self):
        """新类型越界不拦截：validate 通过。"""
        data = _valid(metrics=[{"type": "body_age", "value": 150}])
        assert validate_extraction(data) == []


# ---------- 识别编排（feedback 重试 1 次） ----------


class TestExtractFromImage:
    def _fake_vision(self, monkeypatch, contents):
        calls = []

        def fake(image_bytes, prompt, **kwargs):
            calls.append(prompt)
            return {
                "content": contents[len(calls) - 1],
                "prompt_tokens": 1,
                "completion_tokens": 1,
            }

        monkeypatch.setattr(svc, "vision_extract", fake)
        return calls

    def test_success_first_try(self, session, monkeypatch):
        calls = self._fake_vision(monkeypatch, [json.dumps(VALID_DATA, ensure_ascii=False)])
        data = extract_from_image(b"img", session=session, mime="image/jpeg")
        assert data["date"] == "2026-08-18"
        assert len(data["metrics"]) == 12
        assert len(calls) == 1

    def test_retry_once_with_feedback(self, session, monkeypatch):
        calls = self._fake_vision(
            monkeypatch, ["不是 JSON", json.dumps(VALID_DATA, ensure_ascii=False)]
        )
        data = extract_from_image(b"img", session=session)
        assert data["date"] == "2026-08-18"
        assert len(calls) == 2
        assert "上次" in calls[1]

    def test_schema_invalid_then_fixed(self, session, monkeypatch):
        bad = _valid(metrics=[])
        calls = self._fake_vision(
            monkeypatch,
            [json.dumps(bad, ensure_ascii=False), json.dumps(VALID_DATA, ensure_ascii=False)],
        )
        data = extract_from_image(b"img", session=session)
        assert len(calls) == 2
        assert "metrics" in calls[1]

    def test_invalid_twice_raises(self, session, monkeypatch):
        self._fake_vision(monkeypatch, ["垃圾", "还是垃圾"])
        with pytest.raises(ExtractionError):
            extract_from_image(b"img", session=session)

    def test_llm_error_propagates(self, session, monkeypatch):
        from app.adapters.llm import LLMError

        def fake(image_bytes, prompt, **kwargs):
            raise LLMError("boom")

        monkeypatch.setattr(svc, "vision_extract", fake)
        with pytest.raises(LLMError):
            extract_from_image(b"img", session=session)

    def test_result_includes_range_warnings(self, session, monkeypatch):
        """越界值保留并附 warning（警告不拦截）。"""
        data = _valid(metrics=[{"type": "body_age", "value": 150}])
        self._fake_vision(monkeypatch, [json.dumps(data, ensure_ascii=False)])
        out = extract_from_image(b"img", session=session)
        assert out["metrics"][0]["value"] == 150
        assert out["metrics"][0].get("warning")


# ---------- 确认入库 ----------


class FakeBodyClient:
    def __init__(self):
        self.calls: list[dict] = []

    def upsert_body_metrics(self, records, dry_run=True, confirmed=False):
        self.calls.append({"records": records, "dry_run": dry_run, "confirmed": confirmed})
        if dry_run:
            return {"res": {"summary": "将更新 2 条"}}
        return {"res": {"summary": "已更新 2 条"}}


def _confirm_metrics(**overrides):
    metrics = [
        {"type": "weight", "value": 86.7, "selected": True},
        {"type": "bodyfat", "value": 25.5, "selected": True},
        {"type": "bmi", "value": 29.3, "selected": True},
    ]
    for m in metrics:
        m.update(overrides.get(m["type"], {}))
    return metrics


class TestConfirmImport:
    def test_imports_selected_metrics(self, session):
        result = confirm_import(session, date(2026, 8, 18), _confirm_metrics())
        assert session.query(BodyMetric).count() == 3
        assert len(result["imported"]) == 3
        row = session.query(BodyMetric).filter_by(type="bmi").one()
        assert row.value == 29.3
        assert row.unit == "kg/m²"

    def test_selected_false_skipped(self, session):
        metrics = _confirm_metrics(bmi={"selected": False})
        result = confirm_import(session, date(2026, 8, 18), metrics)
        assert session.query(BodyMetric).count() == 2
        assert session.query(BodyMetric).filter_by(type="bmi").count() == 0
        assert len(result["imported"]) == 2

    def test_idempotent_upsert_same_date_type(self, session):
        """同日同类型重复导入覆盖不重复建行。"""
        confirm_import(session, date(2026, 8, 18), _confirm_metrics())
        confirm_import(
            session,
            date(2026, 8, 18),
            [{"type": "weight", "value": 85.0, "selected": True}],
        )
        rows = session.query(BodyMetric).filter_by(date=date(2026, 8, 18), type="weight").all()
        assert len(rows) == 1
        assert rows[0].value == 85.0
        assert session.query(BodyMetric).count() == 3

    def test_out_of_range_value_imported_with_warning(self, session):
        result = confirm_import(
            session,
            date(2026, 8, 18),
            [{"type": "body_score", "value": 120, "selected": True}],
        )
        assert session.query(BodyMetric).count() == 1
        assert result["warnings"]

    def test_unknown_type_rejected_no_rows(self, session):
        from app.services.body_metrics import BodyMetricValidationError

        with pytest.raises(BodyMetricValidationError):
            confirm_import(
                session,
                date(2026, 8, 18),
                [{"type": "heart_rate", "value": 60, "selected": True}],
            )
        assert session.query(BodyMetric).count() == 0

    def test_sync_xunji_three_step(self, session):
        """勾选同步：weight/bodyfat 走 dry_run → confirmed 三段式并置标记。"""
        client = FakeBodyClient()
        result = confirm_import(
            session, date(2026, 8, 18), _confirm_metrics(),
            sync_xunji=True, body_client=client,
        )
        assert [c["dry_run"] for c in client.calls] == [True, False]
        assert client.calls[0]["confirmed"] is not True
        assert client.calls[1]["confirmed"] is True
        # 仅 weight/bodyfat 同步，bmi 不发
        assert {r["type"] for r in client.calls[0]["records"]} == {"weight", "bodyfat"}
        for type_ in ("weight", "bodyfat"):
            assert session.query(BodyMetric).filter_by(type=type_).one().synced_to_xunji is True
        assert session.query(BodyMetric).filter_by(type="bmi").one().synced_to_xunji is False
        assert result["sync"]["status"] == "synced"

    def test_sync_xunji_without_syncable_selected(self, session):
        client = FakeBodyClient()
        result = confirm_import(
            session,
            date(2026, 8, 18),
            [{"type": "bmi", "value": 29.3, "selected": True}],
            sync_xunji=True,
            body_client=client,
        )
        assert client.calls == []
        assert result["sync"] is None

    def test_no_sync_by_default(self, session):
        client = FakeBodyClient()
        result = confirm_import(
            session, date(2026, 8, 18), _confirm_metrics(), body_client=client
        )
        assert client.calls == []
        assert result["sync"] is None


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


class TestExtractImageApi:
    def test_extract_ok_not_persisted(self, client, auth, session, monkeypatch):
        def fake(image_bytes, *, session=None, mime="image/jpeg"):
            return json.loads(json.dumps(VALID_DATA, ensure_ascii=False))

        monkeypatch.setattr("app.api.body_metrics.extract_body_image", fake)
        resp = client.post(
            "/api/body-metrics/extract-image",
            files=[("file", ("report.jpg", b"jpg-bytes", "image/jpeg"))],
            headers=auth,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "2026-08-18"
        assert len(data["metrics"]) == 12
        # extract 不落库
        assert session.query(BodyMetric).count() == 0

    def test_requires_auth(self, client):
        resp = client.post(
            "/api/body-metrics/extract-image",
            files=[("file", ("report.jpg", b"x", "image/jpeg"))],
        )
        assert resp.status_code == 401

    def test_non_image_422(self, client, auth):
        resp = client.post(
            "/api/body-metrics/extract-image",
            files=[("file", ("a.txt", b"hello", "text/plain"))],
            headers=auth,
        )
        assert resp.status_code == 422

    def test_oversize_413(self, client, auth):
        big = b"x" * (10 * 1024 * 1024 + 1)
        resp = client.post(
            "/api/body-metrics/extract-image",
            files=[("file", ("big.jpg", big, "image/jpeg"))],
            headers=auth,
        )
        assert resp.status_code == 413

    def test_extraction_failure_422(self, client, auth, monkeypatch):
        def fake(image_bytes, *, session=None, mime="image/jpeg"):
            raise ExtractionError("两次校验均不合法")

        monkeypatch.setattr("app.api.body_metrics.extract_body_image", fake)
        resp = client.post(
            "/api/body-metrics/extract-image",
            files=[("file", ("report.jpg", b"x", "image/jpeg"))],
            headers=auth,
        )
        assert resp.status_code == 422


class TestConfirmImportApi:
    def _payload(self, **kw):
        payload = {
            "date": "2026-08-18",
            "metrics": [
                {"type": "weight", "value": 86.7, "selected": True},
                {"type": "bodyfat", "value": 25.5, "selected": True},
            ],
            "sync_xunji": False,
        }
        payload.update(kw)
        return payload

    def test_confirm_upsert_idempotent(self, client, auth, session):
        for value in (86.7, 85.0):
            resp = client.post(
                "/api/body-metrics/confirm-import",
                json=self._payload(
                    metrics=[{"type": "weight", "value": value, "selected": True}]
                ),
                headers=auth,
            )
            assert resp.status_code == 200
        rows = session.query(BodyMetric).filter_by(date=date(2026, 8, 18), type="weight").all()
        assert len(rows) == 1
        assert rows[0].value == 85.0

    def test_confirm_selected_false_not_imported(self, client, auth, session):
        resp = client.post(
            "/api/body-metrics/confirm-import",
            json=self._payload(
                metrics=[
                    {"type": "weight", "value": 86.7, "selected": True},
                    {"type": "bodyfat", "value": 25.5, "selected": False},
                ]
            ),
            headers=auth,
        )
        assert resp.status_code == 200
        assert session.query(BodyMetric).count() == 1
        assert session.query(BodyMetric).one().type == "weight"

    def test_confirm_sync_xunji_calls_client(self, client, auth, session, monkeypatch):
        from app.api.body_metrics import get_body_client_lazy

        fake = FakeBodyClient()
        app.dependency_overrides[get_body_client_lazy] = lambda: fake
        try:
            resp = client.post(
                "/api/body-metrics/confirm-import",
                json=self._payload(sync_xunji=True),
                headers=auth,
            )
        finally:
            del app.dependency_overrides[get_body_client_lazy]
        assert resp.status_code == 200
        assert resp.json()["sync"]["status"] == "synced"
        assert [c["dry_run"] for c in fake.calls] == [True, False]

    def test_confirm_unknown_type_400(self, client, auth, session):
        resp = client.post(
            "/api/body-metrics/confirm-import",
            json=self._payload(
                metrics=[{"type": "heart_rate", "value": 60, "selected": True}]
            ),
            headers=auth,
        )
        assert resp.status_code == 400
        assert session.query(BodyMetric).count() == 0

    def test_confirm_requires_auth(self, client):
        resp = client.post("/api/body-metrics/confirm-import", json=self._payload())
        assert resp.status_code == 401
