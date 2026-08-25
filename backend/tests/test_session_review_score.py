"""V3-4 任务2：session_review 评分体系测试（解析/校验/重试/降级 + API + 迁移）。"""
import json
import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AIReport, Workout
from app.services import ai as ai_service
from app.services.ai import (
    SessionReviewParseError,
    build_session_review_prompt,
    generate_session_review,
    parse_session_review,
)

DAY = date(2026, 8, 3)

VALID_BLOCK = json.dumps(
    {
        "schema": "session_review_v1",
        "score": 85,
        "subscores": {"completion": 90, "intensity": 80, "recovery_fit": 85},
        "one_liner": "今天状态不错，卧推稳住了",
    },
    ensure_ascii=False,
)

GOOD_CONTENT = f"## 完成质量\n完成度高\n## 与历史对比\n持平\n\n```json\n{VALID_BLOCK}\n```\n"


def _make_workout(session) -> Workout:
    w = Workout(
        date=DAY,
        title="胸部训练",
        user_id=1,
        match_status="auto_matched",
        movements_json=json.dumps(
            [{"name": "卧推", "sets": [{"weight": 60, "unit": "kg", "reps": 8, "done": True}]}]
        ),
    )
    session.add(w)
    session.commit()
    return w


class TestPromptScoreRequirement:
    def test_system_prompt_requires_score_json_block(self):
        messages = build_session_review_prompt({"date": "2026-08-03", "movements": []}, {}, {})
        system = messages[0]["content"]
        assert "session_review_v1" in system
        assert "```json" in system
        assert "subscores" in system
        assert "one_liner" in system
        # 原有四节要求保留
        for s in ("完成质量", "与历史对比", "恢复评估", "注意事项"):
            assert s in system


class TestParseSessionReview:
    def test_parses_valid_content_and_strips_block(self):
        parsed = parse_session_review(GOOD_CONTENT)
        assert parsed["score"] == 85
        assert parsed["subscores"] == {"completion": 90, "intensity": 80, "recovery_fit": 85}
        assert parsed["one_liner"] == "今天状态不错，卧推稳住了"
        assert "```json" not in parsed["markdown"]
        assert "完成质量" in parsed["markdown"]

    def test_missing_json_block_raises(self):
        with pytest.raises(SessionReviewParseError):
            parse_session_review("## 完成质量\n只有正文")

    def test_wrong_schema_raises(self):
        content = '## 完成质量\nx\n```json\n{"schema":"other_v1","score":80}\n```'
        with pytest.raises(SessionReviewParseError):
            parse_session_review(content)

    def test_invalid_json_raises(self):
        content = "## 完成质量\nx\n```json\n{not json}\n```"
        with pytest.raises(SessionReviewParseError):
            parse_session_review(content)

    @pytest.mark.parametrize("bad_score", [-1, 101, 85.5, "85", True, None])
    def test_score_must_be_int_0_100(self, bad_score):
        block = json.dumps(
            {
                "schema": "session_review_v1",
                "score": bad_score,
                "subscores": {"completion": 1, "intensity": 1, "recovery_fit": 1},
                "one_liner": "ok",
            }
        )
        with pytest.raises(SessionReviewParseError):
            parse_session_review(f"正文\n```json\n{block}\n```")

    @pytest.mark.parametrize(
        "subscores",
        [
            {"completion": 90, "intensity": 80},  # 缺 recovery_fit
            {"completion": 90, "intensity": 80, "recovery_fit": 101},  # 超界
            {"completion": 90, "intensity": "80", "recovery_fit": 80},  # 非整数
            {"completion": True, "intensity": 80, "recovery_fit": 80},  # bool 非整数
        ],
    )
    def test_subscores_validated(self, subscores):
        block = json.dumps(
            {
                "schema": "session_review_v1",
                "score": 80,
                "subscores": subscores,
                "one_liner": "ok",
            }
        )
        with pytest.raises(SessionReviewParseError):
            parse_session_review(f"正文\n```json\n{block}\n```")

    def test_one_liner_over_40_chars_raises(self):
        block = json.dumps(
            {
                "schema": "session_review_v1",
                "score": 80,
                "subscores": {"completion": 1, "intensity": 1, "recovery_fit": 1},
                "one_liner": "字" * 41,
            },
            ensure_ascii=False,
        )
        with pytest.raises(SessionReviewParseError):
            parse_session_review(f"正文\n```json\n{block}\n```")

    def test_one_liner_at_40_chars_ok(self):
        block = json.dumps(
            {
                "schema": "session_review_v1",
                "score": 80,
                "subscores": {"completion": 1, "intensity": 1, "recovery_fit": 1},
                "one_liner": "字" * 40,
            },
            ensure_ascii=False,
        )
        parsed = parse_session_review(f"正文\n```json\n{block}\n```")
        assert len(parsed["one_liner"]) == 40


class TestGenerateSessionReviewScore:
    def test_valid_output_persists_score_fields(self, session):
        w = _make_workout(session)
        calls = []

        def fake_chat(messages):
            calls.append(messages)
            return {"content": GOOD_CONTENT, "prompt_tokens": 10, "completion_tokens": 5}

        report = generate_session_review(session, w.id, chat_fn=fake_chat)
        assert len(calls) == 1
        assert report.score == 85
        assert report.one_liner == "今天状态不错，卧推稳住了"
        assert json.loads(report.subscores_json) == {
            "completion": 90,
            "intensity": 80,
            "recovery_fit": 85,
        }
        assert "```json" not in report.content_md
        assert "完成质量" in report.content_md

    def test_retry_once_then_success(self, session):
        w = _make_workout(session)
        outputs = iter(
            [
                {"content": "## 完成质量\n没有 JSON 块", "prompt_tokens": 10, "completion_tokens": 5},
                {"content": GOOD_CONTENT, "prompt_tokens": 12, "completion_tokens": 6},
            ]
        )

        report = generate_session_review(session, w.id, chat_fn=lambda m: next(outputs))
        assert report.score == 85
        # token 累计两次调用
        assert report.prompt_tokens == 22
        assert report.completion_tokens == 11

    def test_degrade_after_retry_still_invalid(self, session):
        w = _make_workout(session)
        calls = []

        def bad_chat(messages):
            calls.append(messages)
            return {"content": "## 完成质量\n始终没有结构化块", "prompt_tokens": 7, "completion_tokens": 3}

        report = generate_session_review(session, w.id, chat_fn=bad_chat)
        assert len(calls) == 2  # 初次 + 重试 1 次
        assert report.score is None
        assert report.one_liner is None
        assert report.subscores_json is None
        assert "完成质量" in report.content_md  # 正文照常落库，不阻断


# =====================================================================
# API：序列化带出评分字段 + 重新生成端点
# =====================================================================


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
def auth(client, session):
    from app.services import users as _us
    try:
        _us.create_user(session, username="alice", password="test-pass", role="user")
    except ValueError:
        pass  # alice 已由 conftest session 预建（id=1）
    _b = client.post("/api/auth/login", json={"username": "alice", "password": "test-pass"}).json()
    return {"Authorization": f"Bearer {_b['token']}"}


class TestSerializeScore:
    def test_list_response_includes_score_fields(self, client, auth, session):
        w = _make_workout(session)
        session.add(
            AIReport(
                type="session_review",
                workout_id=w.id,
                user_id=1,
                period_start=DAY,
                period_end=DAY,
                model="deepseek-chat",
                content_md="## 完成质量\n不错",
                score=88,
                one_liner="稳",
                subscores_json='{"completion": 90, "intensity": 80, "recovery_fit": 85}',
            )
        )
        session.commit()
        resp = client.get("/api/ai-reports?date=2026-08-03", headers=auth)
        assert resp.status_code == 200
        r = resp.json()["reports"][0]
        assert r["score"] == 88
        assert r["one_liner"] == "稳"
        assert r["subscores"] == {"completion": 90, "intensity": 80, "recovery_fit": 85}

    def test_null_score_serializes_as_null(self, client, auth, session):
        w = _make_workout(session)
        session.add(
            AIReport(
                type="session_review",
                workout_id=w.id,
                user_id=1,
                period_start=DAY,
                period_end=DAY,
                model="deepseek-chat",
                content_md="旧报告",
            )
        )
        session.commit()
        resp = client.get("/api/ai-reports?date=2026-08-03", headers=auth)
        r = resp.json()["reports"][0]
        assert r["score"] is None
        assert r["one_liner"] is None
        assert r["subscores"] is None


class TestRegenerateService:
    """服务层 regenerate_session_reviews：删旧 + 重生成（复用 V2-7b 逻辑）。"""

    def test_deletes_old_and_regenerates_with_score(self, session):
        w = _make_workout(session)
        old = AIReport(
            type="session_review",
            workout_id=w.id,
            user_id=1,
            period_start=DAY,
            period_end=DAY,
            model="deepseek-chat",
            content_md="旧报告无评分",
        )
        session.add(old)
        session.commit()
        old_id = old.id

        def fake_chat(messages):
            return {"content": GOOD_CONTENT, "prompt_tokens": 10, "completion_tokens": 5}

        summary = ai_service.regenerate_session_reviews(session, DAY, chat_fn=fake_chat)
        assert summary["generated"] == 1
        session.expire_all()  # 清 identity map，确保读库验证（SQLite 可能复用 rowid）
        rows = (
            session.query(AIReport)
            .filter(AIReport.type == "session_review", AIReport.period_start == DAY)
            .all()
        )
        assert len(rows) == 1  # 旧报告被删除，仅剩重新生成的一条
        assert rows[0].content_md != "旧报告无评分"
        assert rows[0].score == 85

    def test_no_workout_still_deletes_stale_reports(self, session):
        # 当日无 workout 时：旧报告被清理且不生成新报告
        session.add(
            AIReport(
                type="session_review",
                workout_id=None,
                user_id=1,
                period_start=DAY,
                period_end=DAY,
                model="deepseek-chat",
                content_md="孤儿报告",
            )
        )
        session.commit()
        summary = ai_service.regenerate_session_reviews(session, DAY, chat_fn=lambda m: {})
        assert summary["generated"] == 0
        assert (
            session.query(AIReport)
            .filter(AIReport.type == "session_review", AIReport.period_start == DAY)
            .count()
            == 0
        )

    def test_other_types_untouched(self, session):
        w = _make_workout(session)
        advice = AIReport(
            type="next_advice",
            workout_id=w.id,
            user_id=1,
            period_start=DAY,
            period_end=DAY,
            model="deepseek-chat",
            content_md="建议",
        )
        session.add(advice)
        session.commit()
        ai_service.regenerate_session_reviews(
            session, DAY, chat_fn=lambda m: {"content": GOOD_CONTENT}
        )
        assert session.get(AIReport, advice.id) is not None


class TestRegenerateSessionReviewAPI:
    def test_requires_auth(self, client):
        resp = client.post("/api/ai-reports/session-review/regenerate", json={"date": "2026-08-03"})
        assert resp.status_code == 401

    def test_regenerate_flow_with_injected_manager(self, client, auth, session):
        from app.api import ai_reports as api_mod

        w = _make_workout(session)
        old = AIReport(
            type="session_review",
            workout_id=w.id,
            user_id=1,
            period_start=DAY,
            period_end=DAY,
            model="deepseek-chat",
            content_md="旧报告无评分",
        )
        session.add(old)
        session.commit()
        old_id = old.id

        def fake_chat(messages):
            return {"content": GOOD_CONTENT, "prompt_tokens": 10, "completion_tokens": 5}

        from app.db import make_engine, make_session_factory

        def _runner(day_str, user_id=None):
            eng = make_engine(os.environ["DATABASE_URL"])
            factory = make_session_factory(eng)
            s = factory()
            try:
                return ai_service.regenerate_session_reviews(
                    s, day_str, chat_fn=fake_chat
                )
            finally:
                s.close()
                eng.dispose()

        manager = api_mod.SessionReviewRegenManager(runner=_runner)
        app.dependency_overrides[api_mod.get_session_review_regen_manager] = lambda: manager
        try:
            resp = client.post(
                "/api/ai-reports/session-review/regenerate",
                json={"date": "2026-08-03"},
                headers=auth,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "started"

            import time

            st = {}
            for _ in range(100):
                st = client.get(
                    "/api/ai-reports/session-review/regenerate/status?date=2026-08-03",
                    headers=auth,
                ).json()
                if not st["running"]:
                    break
                time.sleep(0.02)
            assert st["running"] is False
            assert st["error"] is None

            session.expire_all()
            rows = (
                session.query(AIReport)
                .filter(AIReport.type == "session_review", AIReport.period_start == DAY)
                .all()
            )
            assert len(rows) == 1
            assert rows[0].content_md != "旧报告无评分"
            assert rows[0].score == 85
        finally:
            app.dependency_overrides.pop(api_mod.get_session_review_regen_manager, None)

    def test_conflict_when_already_running(self, client, auth, session):
        import threading

        from app.api import ai_reports as api_mod

        blocker = threading.Event()

        def slow_runner(day_str):
            blocker.wait(2)

        manager = api_mod.SessionReviewRegenManager(runner=slow_runner)
        app.dependency_overrides[api_mod.get_session_review_regen_manager] = lambda: manager
        try:
            r1 = client.post(
                "/api/ai-reports/session-review/regenerate",
                json={"date": "2026-08-03"},
                headers=auth,
            )
            assert r1.status_code == 200
            r2 = client.post(
                "/api/ai-reports/session-review/regenerate",
                json={"date": "2026-08-03"},
                headers=auth,
            )
            assert r2.status_code == 409
        finally:
            blocker.set()
            app.dependency_overrides.pop(api_mod.get_session_review_regen_manager, None)

    def test_invalid_date_returns_422(self, client, auth):
        resp = client.post(
            "/api/ai-reports/session-review/regenerate", json={"date": "2026-08"}, headers=auth
        )
        assert resp.status_code == 422

    def test_conflict_when_already_running(self, client, auth, session, monkeypatch):
        import threading

        from app.api import ai_reports as api_mod

        blocker = threading.Event()

        def slow_runner(day_str):
            blocker.wait(2)

        manager = api_mod.SessionReviewRegenManager(runner=slow_runner)
        app.dependency_overrides[api_mod.get_session_review_regen_manager] = lambda: manager
        try:
            r1 = client.post(
                "/api/ai-reports/session-review/regenerate",
                json={"date": "2026-08-03"},
                headers=auth,
            )
            assert r1.status_code == 200
            r2 = client.post(
                "/api/ai-reports/session-review/regenerate",
                json={"date": "2026-08-03"},
                headers=auth,
            )
            assert r2.status_code == 409
        finally:
            blocker.set()
            app.dependency_overrides.pop(api_mod.get_session_review_regen_manager, None)

    def test_invalid_date_returns_422(self, client, auth):
        resp = client.post(
            "/api/ai-reports/session-review/regenerate", json={"date": "2026-08"}, headers=auth
        )
        assert resp.status_code == 422
