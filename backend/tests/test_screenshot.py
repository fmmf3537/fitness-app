"""V2-3 截图识别补录：Schema 校验 / 自动修正重试 / 确认入库重匹配 / API 层。"""
import json
from datetime import date, time

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import Workout, XunjiTrain
from app.services import screenshot as svc
from app.services.screenshot import (
    ExtractionError,
    build_prompt,
    confirm_import,
    extract_from_image,
    parse_json_content,
    validate_extraction,
)
from tests.conftest import make_garmin_activity

VALID_DATA = {
    "datestr": "2026-08-03",
    "title": "背·二头·2",
    "duration_s": 2820,
    "calories": 186,
    "movements": [
        {
            "name": "宽距高位下拉",
            "sets": [
                {"weight": 40, "unit": "kg", "reps": 10},
                {"weight": 40, "unit": "kg", "reps": 10},
            ],
        }
    ],
}


def _valid(**overrides):
    data = json.loads(json.dumps(VALID_DATA, ensure_ascii=False))
    data.update(overrides)
    return data


# ---------- Schema 校验 ----------


class TestValidateExtraction:
    def test_valid_data_passes(self):
        assert validate_extraction(_valid()) == []

    def test_optional_fields_absent_passes(self):
        data = _valid()
        del data["duration_s"]
        del data["calories"]
        assert validate_extraction(data) == []

    def test_missing_datestr(self):
        data = _valid()
        del data["datestr"]
        assert any("datestr" in e for e in validate_extraction(data))

    def test_bad_datestr_format(self):
        assert validate_extraction(_valid(datestr="2026/08/03"))
        assert validate_extraction(_valid(datestr="2026-13-01"))

    def test_empty_title(self):
        assert validate_extraction(_valid(title=""))
        assert validate_extraction(_valid(title=123))

    def test_movements_required_and_nonempty(self):
        data = _valid()
        del data["movements"]
        assert validate_extraction(data)
        assert validate_extraction(_valid(movements=[]))
        assert validate_extraction(_valid(movements="x"))

    def test_movement_name_required(self):
        data = _valid(movements=[{"sets": [{"weight": 40, "reps": 10}]}])
        assert validate_extraction(data)
        data = _valid(movements=[{"name": "  ", "sets": [{"weight": 40, "reps": 10}]}])
        assert validate_extraction(data)

    def test_sets_required_and_nonempty(self):
        assert validate_extraction(_valid(movements=[{"name": "划船"}]))
        assert validate_extraction(_valid(movements=[{"name": "划船", "sets": []}]))

    def test_set_weight_required_and_nonnegative(self):
        bad = _valid(movements=[{"name": "划船", "sets": [{"reps": 10}]}])
        assert validate_extraction(bad)
        neg = _valid(movements=[{"name": "划船", "sets": [{"weight": -1, "reps": 10}]}])
        assert validate_extraction(neg)

    def test_set_needs_reps_or_time(self):
        none_ = _valid(movements=[{"name": "划船", "sets": [{"weight": 40}]}])
        assert validate_extraction(none_)
        time_only = _valid(movements=[{"name": "平板支撑", "sets": [{"weight": 0, "time": 60}]}])
        assert validate_extraction(time_only) == []
        zero_reps = _valid(movements=[{"name": "划船", "sets": [{"weight": 40, "reps": 0}]}])
        assert validate_extraction(zero_reps)

    def test_optional_field_type_checks(self):
        assert validate_extraction(_valid(duration_s=-5))
        assert validate_extraction(_valid(duration_s="47m"))
        assert validate_extraction(_valid(calories=-1))
        assert validate_extraction(_valid(start_time="25:00"))
        assert validate_extraction(_valid(start_time="10:00", end_time="11:00")) == []


# ---------- 模型输出 JSON 解析 ----------


class TestParseJsonContent:
    def test_plain_json(self):
        assert parse_json_content('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        content = '```json\n{"a": 1}\n```'
        assert parse_json_content(content) == {"a": 1}

    def test_fenced_with_surrounding_text(self):
        content = '识别结果：\n```\n{"a": 1}\n```\n以上。'
        assert parse_json_content(content) == {"a": 1}

    def test_garbage_raises(self):
        with pytest.raises(ExtractionError):
            parse_json_content("这不是 JSON")

    def test_non_object_raises(self):
        with pytest.raises(ExtractionError):
            parse_json_content("[1, 2]")


# ---------- 识别编排（含自动修正重试） ----------


class TestExtractFromImage:
    def _fake_vision(self, monkeypatch, contents):
        calls = []

        def fake(image_bytes, prompt, **kwargs):
            calls.append(prompt)
            return {"content": contents[len(calls) - 1], "prompt_tokens": 1, "completion_tokens": 1}

        monkeypatch.setattr(svc, "vision_extract", fake)
        return calls

    def test_success_first_try(self, session, monkeypatch):
        calls = self._fake_vision(monkeypatch, [json.dumps(VALID_DATA, ensure_ascii=False)])
        data = extract_from_image(b"img", session=session)
        assert data["datestr"] == "2026-08-03"
        assert len(calls) == 1

    def test_retry_once_with_feedback_then_success(self, session, monkeypatch):
        calls = self._fake_vision(
            monkeypatch,
            ["这不是 JSON", json.dumps(VALID_DATA, ensure_ascii=False)],
        )
        data = extract_from_image(b"img", session=session)
        assert data["title"] == "背·二头·2"
        assert len(calls) == 2
        assert "上次" in calls[1]  # 第二次 prompt 附错误反馈

    def test_schema_invalid_then_fixed(self, session, monkeypatch):
        bad = _valid()
        del bad["datestr"]
        calls = self._fake_vision(
            monkeypatch,
            [json.dumps(bad, ensure_ascii=False), json.dumps(VALID_DATA, ensure_ascii=False)],
        )
        data = extract_from_image(b"img", session=session)
        assert data["datestr"] == "2026-08-03"
        assert len(calls) == 2
        assert "datestr" in calls[1]

    def test_invalid_twice_raises(self, session, monkeypatch):
        self._fake_vision(monkeypatch, ["垃圾", "还是垃圾"])
        with pytest.raises(ExtractionError):
            extract_from_image(b"img", session=session)

    def test_schema_invalid_twice_raises(self, session, monkeypatch):
        bad = json.dumps(_valid(movements=[]), ensure_ascii=False)
        self._fake_vision(monkeypatch, [bad, bad])
        with pytest.raises(ExtractionError):
            extract_from_image(b"img", session=session)

    def test_llm_error_propagates(self, session, monkeypatch):
        from app.adapters.llm import LLMError

        def fake(image_bytes, prompt, **kwargs):
            raise LLMError("boom")

        monkeypatch.setattr(svc, "vision_extract", fake)
        with pytest.raises(LLMError):
            extract_from_image(b"img", session=session)


# ---------- 确认入库 + 重跑匹配 ----------


class TestConfirmImport:
    def test_creates_train_and_workout_xunji_only(self, session):
        result = confirm_import(session, _valid())
        train = session.query(XunjiTrain).one()
        assert train.datestr == "2026-08-03"
        assert train.localid.startswith("shot-")
        raw = json.loads(train.raw_json)
        assert raw["movements"][0]["name"] == "宽距高位下拉"
        assert raw["source"] == "screenshot"

        workout = session.query(Workout).one()
        assert workout.xunji_train_id == train.id
        assert workout.match_status == "xunji_only"
        assert workout.title == "背·二头·2"
        movements = json.loads(workout.movements_json)
        assert movements[0]["sets"][0]["unit"] == "kg"  # 规范化补默认单位
        assert movements[0]["sets"][0]["done"] is True
        assert result["workout_id"] == workout.id
        assert result["match_status"] == "xunji_only"

    def test_auto_match_with_garmin_when_time_overlap(self, session):
        make_garmin_activity(session, date(2026, 8, 3), activity_id="g1",
                             start=time(10, 0), end=time(11, 0))
        data = _valid(start_time="10:05", end_time="10:50")
        result = confirm_import(session, data)
        workout = session.query(Workout).one()
        assert workout.match_status == "auto_matched"
        assert workout.garmin_activity_id is not None
        assert workout.duration_s == 3600  # 时长以佳明为准（PRD §5.2）
        assert result["match_status"] == "auto_matched"

    def test_time_close_goes_pending(self, session):
        # 重叠 35/60 < 60%，但起止差 ≤30min → 入待确认队列（第二轮）
        make_garmin_activity(session, date(2026, 8, 3), activity_id="g1",
                             start=time(12, 0), end=time(13, 0))
        data = _valid(start_time="12:25", end_time="13:55")
        result = confirm_import(session, data)
        assert result["match_status"] == "pending"
        assert session.query(Workout).count() == 0  # 双方入候选队列，不产 workout

    def test_invalid_data_rejected_no_rows(self, session):
        with pytest.raises(ExtractionError):
            confirm_import(session, _valid(movements=[]))
        assert session.query(XunjiTrain).count() == 0
        assert session.query(Workout).count() == 0


# ---------- prompt 构造 ----------


class TestBuildPrompt:
    def test_contains_schema_keys(self):
        prompt = build_prompt()
        for key in ("datestr", "title", "movements", "sets", "weight", "reps", "duration", "calories"):
            assert key in prompt

    def test_feedback_appended(self):
        assert "缺少 datestr" in build_prompt(feedback="缺少 datestr")


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


class TestExtractApi:
    def test_extract_ok(self, client, auth, monkeypatch):
        def fake(image_bytes, *, session=None, mime="image/png"):
            return _valid()

        monkeypatch.setattr("app.api.screenshot.extract_from_image", fake)
        resp = client.post(
            "/api/screenshot/extract",
            files=[("files", ("a.png", b"png-bytes", "image/png"))],
            headers=auth,
        )
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert result["ok"] is True
        assert result["filename"] == "a.png"
        assert result["data"]["title"] == "背·二头·2"

    def test_extract_failure_returns_per_file_error(self, client, auth, monkeypatch):
        def fake(image_bytes, *, session=None, mime="image/png"):
            raise ExtractionError("模型两次输出均不合法")

        monkeypatch.setattr("app.api.screenshot.extract_from_image", fake)
        resp = client.post(
            "/api/screenshot/extract",
            files=[("files", ("a.png", b"x", "image/png"))],
            headers=auth,
        )
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert result["ok"] is False
        assert "不合法" in result["error"]

    def test_extract_rejects_non_image(self, client, auth):
        resp = client.post(
            "/api/screenshot/extract",
            files=[("files", ("a.txt", b"hello", "text/plain"))],
            headers=auth,
        )
        assert resp.status_code == 422

    def test_extract_requires_auth(self, client):
        resp = client.post(
            "/api/screenshot/extract",
            files=[("files", ("a.png", b"x", "image/png"))],
        )
        assert resp.status_code == 401


class TestConfirmApi:
    def test_confirm_ok(self, client, auth, session):
        resp = client.post("/api/screenshot/confirm", json=_valid(), headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["match_status"] == "xunji_only"
        assert session.query(XunjiTrain).count() == 1
        assert session.query(Workout).count() == 1

    def test_confirm_invalid_422(self, client, auth, session):
        resp = client.post(
            "/api/screenshot/confirm", json=_valid(movements=[]), headers=auth
        )
        assert resp.status_code == 422
        assert session.query(XunjiTrain).count() == 0

    def test_confirm_requires_auth(self, client):
        resp = client.post("/api/screenshot/confirm", json=_valid())
        assert resp.status_code == 401
