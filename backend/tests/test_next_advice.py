"""V1-4 AI 下次训练建议（type='next_advice'）测试。

覆盖：
- 标准动作名表加载与校验；
- 结构化 JSON 建议的解析与校验（非法动作名/非法分类被拒）；
- 两类建议（auto_writable / manual）分类逻辑；
- 训记计划缓存查询下一次训练日（含真实 get 响应结构回归，V1-4-FIX）；
- prompt 组装注入动作名表；
- 生成落库 + 幂等 + 单次点评后连锁触发；
- API 按 type 查询。
"""
import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

FIXTURES = Path(__file__).resolve().parent / "fixtures"

import pytest
from tests.conftest import make_garmin_activity, make_xunji_train

from app.models import AIReport, XunjiPlan
from app.services.fuse import fuse_workout

DAY = date(2026, 8, 3)
NEXT_DAY = date(2026, 8, 5)

VALID_ADVICE_JSON = {
    "schema": "next_advice_v1",
    "next_plan_date": NEXT_DAY.isoformat(),
    "suggestions": [
        {
            "movement": "杠铃划船",
            "category": "manual",
            "original": {"weight": 60, "unit": "kg", "sets": 4, "reps": 10},
            "suggested": {"weight": 62.5, "unit": "kg", "sets": 4, "reps": 8},
            "reason": "上次 RPE 偏低，渐进超负荷",
        },
        {
            "movement": "宽距高位下拉",
            "category": "auto_writable",
            "original": {"rpe": None},
            "suggested": {"rpe": 8},
            "reason": "补录本次训练 RPE",
        },
    ],
}

VALID_CONTENT = (
    "## 计划对照\n本次背部训练完成度高，下次可加重。\n\n"
    "```json\n" + json.dumps(VALID_ADVICE_JSON, ensure_ascii=False) + "\n```\n"
)


def _make_plan(session, days, plan_ref="platform:155", plan_name="增肌计划"):
    row = XunjiPlan(
        plan_ref=plan_ref,
        plan_json=json.dumps(
            {"plan": {"plan_ref": plan_ref, "name": plan_name}, "days": days},
            ensure_ascii=False,
        ),
        date_from=DAY - timedelta(days=7),
        date_to=DAY + timedelta(days=30),
    )
    session.add(row)
    session.commit()
    return row


def _make_workout(session, title="背部训练"):
    x = make_xunji_train(
        session, DAY, localid="1", title=title,
        movements=[{"name": "杠铃划船",
                    "sets": [{"weight": "60", "unit": "kg", "reps": "10", "done": True}]}],
    )
    g = make_garmin_activity(session, DAY, activity_id="g1")
    return fuse_workout(session, DAY, xunji=x, garmin=g, match_status="auto_matched")


def _fake_chat(content=VALID_CONTENT):
    def chat(messages):
        return {"content": content, "prompt_tokens": 100, "completion_tokens": 50}
    return chat


# ---------- 标准动作名表 ----------


class TestMovementTable:
    def test_loads_standard_names(self):
        from app.movements import load_movement_names

        names = load_movement_names()
        assert len(names) >= 1000
        assert len(set(names)) == len(names)
        for expected in ("杠铃划船", "宽距高位下拉", "杠铃卧推", "跑步_有氧训练"):
            assert expected in names

    def test_is_standard_movement(self):
        from app.movements import is_standard_movement

        assert is_standard_movement("杠铃划船") is True
        assert is_standard_movement("深蹲大王") is False
        assert is_standard_movement("") is False


# ---------- JSON 解析与校验 ----------


class TestParseAdvice:
    def test_parses_valid_content(self):
        from app.services.ai import parse_next_advice

        data = parse_next_advice(VALID_CONTENT)
        assert data["schema"] == "next_advice_v1"
        assert data["next_plan_date"] == NEXT_DAY.isoformat()
        assert len(data["suggestions"]) == 2

    def test_missing_json_block_rejected(self):
        from app.services.ai import NextAdviceParseError, parse_next_advice

        with pytest.raises(NextAdviceParseError):
            parse_next_advice("## 只有 Markdown，没有 JSON 块")

    def test_invalid_json_rejected(self):
        from app.services.ai import NextAdviceParseError, parse_next_advice

        with pytest.raises(NextAdviceParseError):
            parse_next_advice("```json\n{not json}\n```")

    def test_wrong_schema_rejected(self):
        from app.services.ai import NextAdviceParseError, parse_next_advice

        bad = dict(VALID_ADVICE_JSON, schema="other_schema")
        content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
        with pytest.raises(NextAdviceParseError):
            parse_next_advice(content)

    def test_illegal_movement_name_rejected(self):
        from app.services.ai import NextAdviceParseError, parse_next_advice

        bad = json.loads(json.dumps(VALID_ADVICE_JSON))
        bad["suggestions"][0]["movement"] = "深蹲大王"
        content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
        with pytest.raises(NextAdviceParseError, match="深蹲大王"):
            parse_next_advice(content)

    def test_illegal_category_rejected(self):
        from app.services.ai import NextAdviceParseError, parse_next_advice

        bad = json.loads(json.dumps(VALID_ADVICE_JSON))
        bad["suggestions"][0]["category"] = "whatever"
        content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
        with pytest.raises(NextAdviceParseError):
            parse_next_advice(content)

    def test_missing_required_field_rejected(self):
        from app.services.ai import NextAdviceParseError, parse_next_advice

        bad = json.loads(json.dumps(VALID_ADVICE_JSON))
        del bad["suggestions"][0]["reason"]
        content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
        with pytest.raises(NextAdviceParseError):
            parse_next_advice(content)

    def test_empty_suggestions_allowed(self):
        from app.services.ai import parse_next_advice

        data = json.loads(json.dumps(VALID_ADVICE_JSON))
        data["suggestions"] = []
        content = "```json\n" + json.dumps(data, ensure_ascii=False) + "\n```"
        assert parse_next_advice(content)["suggestions"] == []


# ---------- 两类建议分类 ----------


class TestClassifySuggestions:
    def test_splits_two_categories(self):
        from app.services.ai import classify_suggestions, parse_next_advice

        data = parse_next_advice(VALID_CONTENT)
        grouped = classify_suggestions(data)
        assert [s["movement"] for s in grouped["auto_writable"]] == ["宽距高位下拉"]
        assert [s["movement"] for s in grouped["manual"]] == ["杠铃划船"]

    def test_empty(self):
        from app.services.ai import classify_suggestions

        grouped = classify_suggestions({"suggestions": []})
        assert grouped == {"auto_writable": [], "manual": []}


# ---------- 计划缓存查询 ----------


class TestQueryNextPlanDay:
    def test_finds_next_training_day(self, session):
        from app.services.ai import query_next_plan_day

        _make_plan(session, days=[
            {"date": DAY.isoformat(), "movements": [{"name": "杠铃划船"}]},  # 当天，应跳过
            {"date": (DAY + timedelta(days=1)).isoformat(), "movements": []},  # 休息日，应跳过
            {"date": NEXT_DAY.isoformat(),
             "movements": [{"name": "杠铃划船", "sets": [{"weight": 60, "reps": 10}]}]},
        ])

        plan_day = query_next_plan_day(session, DAY)
        assert plan_day is not None
        assert plan_day["date"] == NEXT_DAY.isoformat()
        assert plan_day["plan_name"] == "增肌计划"
        assert plan_day["movements"][0]["name"] == "杠铃划船"

    def test_returns_none_without_plan_cache(self, session):
        from app.services.ai import query_next_plan_day

        assert query_next_plan_day(session, DAY) is None

    def test_ignores_expired_plan(self, session):
        from app.services.ai import query_next_plan_day

        row = _make_plan(session, days=[
            {"date": NEXT_DAY.isoformat(), "movements": [{"name": "杠铃划船"}]},
        ])
        row.date_from = DAY - timedelta(days=60)
        row.date_to = DAY - timedelta(days=31)  # 缓存覆盖范围已过期
        session.commit()

        assert query_next_plan_day(session, DAY) is None

    def test_ignores_day_beyond_30_days(self, session):
        from app.services.ai import query_next_plan_day

        _make_plan(session, days=[
            {"date": (DAY + timedelta(days=31)).isoformat(),
             "movements": [{"name": "杠铃划船"}]},
        ])
        assert query_next_plan_day(session, DAY) is None

    def test_real_get_structure_datestr_and_workout_movements(self, session):
        """V1-4-FIX 回归：真实 get 响应用 datestr + workout.movements + target_sets。"""
        from app.services.ai import query_next_plan_day

        real = json.loads((FIXTURES / "plan_get_real.json").read_text(encoding="utf-8"))
        session.add(XunjiPlan(
            plan_ref="universal:1",
            plan_json=json.dumps(real, ensure_ascii=False),
            date_from=date(2026, 8, 7),
            date_to=date(2026, 9, 6),
        ))
        session.commit()

        plan_day = query_next_plan_day(session, date(2026, 8, 6))

        assert plan_day is not None
        assert plan_day["date"] == "2026-08-07"
        assert plan_day["movements"][0]["name"] == "杠铃卧推"
        # target_sets 已归一化为 sets，供 prompt 组装使用
        assert plan_day["movements"][0]["sets"][0]["weight"] == 32.5


# ---------- prompt 组装 ----------


class TestBuildNextAdvicePrompt:
    def test_injects_movement_table_and_plan(self):
        from app.movements import load_movement_names
        from app.services.ai import build_next_advice_prompt

        workout = {
            "date": DAY.isoformat(), "title": "背部训练", "tags": "strength_training",
            "duration_s": 3600, "calories": 400, "avg_hr": 118, "max_hr": 152,
            "movements": [{"name": "杠铃划船",
                           "sets": [{"weight": "60", "unit": "kg", "reps": "10",
                                     "done": True, "rpe": 7}]}],
        }
        plan_day = {
            "plan_ref": "platform:155", "plan_name": "增肌计划",
            "date": NEXT_DAY.isoformat(),
            "movements": [{"name": "杠铃划船",
                           "sets": [{"weight": 60, "reps": 10}, {"weight": 60, "reps": 10}]}],
        }
        recovery = {"days_count": 7, "avg_sleep_hours": 7.2, "hrv_status": "balanced"}

        messages = build_next_advice_prompt(workout, plan_day, recovery, load_movement_names())

        assert messages[0]["role"] == "system"
        system = messages[0]["content"]
        # 动作名表注入 system，且明确约束
        assert "杠铃划船" in system
        assert "跑步_有氧训练" in system
        assert "标准动作" in system
        assert "next_advice_v1" in system
        assert "auto_writable" in system and "manual" in system

        user = messages[1]["content"]
        assert "增肌计划" in user
        assert NEXT_DAY.isoformat() in user
        assert "背部训练" in user
        assert "balanced" in user


# ---------- 生成与落库 ----------


class TestGenerateNextAdvice:
    def test_generates_and_saves_report(self, session):
        from app.services.ai import generate_next_advice

        w = _make_workout(session)
        _make_plan(session, days=[
            {"date": NEXT_DAY.isoformat(),
             "movements": [{"name": "杠铃划船", "sets": [{"weight": 60, "reps": 10}]}]},
        ])

        report = generate_next_advice(session, w.id, chat_fn=_fake_chat())

        assert report is not None
        assert report.type == "next_advice"
        assert report.workout_id == w.id
        assert report.period_start == DAY
        assert report.prompt_tokens == 100
        assert report.completion_tokens == 50
        assert report.cost_estimate > 0
        assert "next_advice_v1" in report.content_md

    def test_returns_none_without_plan(self, session):
        from app.services.ai import generate_next_advice

        w = _make_workout(session)
        called = []

        def chat(messages):
            called.append(messages)
            return {"content": VALID_CONTENT, "prompt_tokens": 1, "completion_tokens": 1}

        assert generate_next_advice(session, w.id, chat_fn=chat) is None
        assert called == []  # 无计划缓存时不调用模型
        assert session.query(AIReport).count() == 0

    def test_invalid_output_raises_and_not_saved(self, session):
        from app.services.ai import NextAdviceParseError, generate_next_advice

        w = _make_workout(session)
        _make_plan(session, days=[
            {"date": NEXT_DAY.isoformat(), "movements": [{"name": "杠铃划船"}]},
        ])
        bad = json.loads(json.dumps(VALID_ADVICE_JSON))
        bad["suggestions"][0]["movement"] = "不存在的动作"
        content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"

        with pytest.raises(NextAdviceParseError):
            generate_next_advice(session, w.id, chat_fn=_fake_chat(content))
        assert session.query(AIReport).count() == 0


# ---------- 连锁触发与幂等 ----------


class TestRunDailyNextAdvices:
    def test_generates_and_skips_idempotently(self, session):
        from app.services.ai import run_daily_next_advices

        w = _make_workout(session)
        _make_plan(session, days=[
            {"date": NEXT_DAY.isoformat(), "movements": [{"name": "杠铃划船"}]},
        ])

        summary = run_daily_next_advices(session, DAY, chat_fn=_fake_chat())
        assert summary["generated"] == 1
        assert summary["reports"]

        summary2 = run_daily_next_advices(session, DAY, chat_fn=_fake_chat())
        assert summary2["generated"] == 0
        assert summary2["skipped"] == 1
        assert session.query(AIReport).filter_by(type="next_advice").count() == 1

    def test_counts_no_plan(self, session):
        from app.services.ai import run_daily_next_advices

        _make_workout(session)
        summary = run_daily_next_advices(session, DAY, chat_fn=_fake_chat())
        assert summary["generated"] == 0
        assert summary["no_plan"] == 1

    def test_no_plan_note_when_plan_ended(self, session):
        """V1-4-FIX：缓存计划 status=ended 且无未来训练日时优雅跳过并在摘要中说明。"""
        from app.services.ai import run_daily_next_advices

        _make_workout(session)
        row = _make_plan(session, days=[
            {"date": (DAY - timedelta(days=1)).isoformat(),
             "movements": [{"name": "杠铃划船"}]},  # 只有过去的训练日
        ])
        data = json.loads(row.plan_json)
        data["plan"]["status"] = "ended"  # 真实缓存结构：计划已结束
        row.plan_json = json.dumps(data, ensure_ascii=False)
        session.commit()

        summary = run_daily_next_advices(session, DAY, chat_fn=_fake_chat())

        assert summary["generated"] == 0
        assert summary["no_plan"] == 1
        assert "ended" in summary["note"]
        # 不调用模型、不落库、不报错
        assert session.query(AIReport).filter_by(type="next_advice").count() == 0


class TestSyncChain:
    def _mocks(self):
        xunji = Mock()
        xunji.fetch_trains.return_value = []
        garmin = Mock()
        garmin.sync_activities.return_value = []
        garmin.sync_daily.return_value = Mock()
        return xunji, garmin

    def test_daily_sync_chains_next_advice_after_review(self, session, monkeypatch):
        from app.services import sync as sync_mod

        _make_workout(session)
        calls = []

        def fake_reviews(session, day, chat_fn=None):
            calls.append("review")
            return {"date": day.isoformat(), "generated": 1, "skipped": 0, "reports": [1]}

        def fake_advices(session, day, chat_fn=None):
            calls.append("advice")
            return {"date": day.isoformat(), "generated": 1, "skipped": 0,
                    "no_plan": 0, "reports": [2]}

        monkeypatch.setattr(sync_mod, "run_daily_reviews", fake_reviews)
        monkeypatch.setattr(sync_mod, "run_daily_next_advices", fake_advices)
        xunji, garmin = self._mocks()

        result = sync_mod.daily_sync(DAY, session=session, xunji=xunji, garmin=garmin,
                                     sleep=lambda _: None)

        assert result["status"] == "success"
        assert calls == ["review", "advice"]  # 点评先，建议连锁其后
        assert result["detail"]["next_advices"] == 1

    def test_advice_failure_does_not_fail_sync(self, session, monkeypatch):
        from app.services import sync as sync_mod

        _make_workout(session)

        def fake_reviews(session, day, chat_fn=None):
            return {"date": day.isoformat(), "generated": 1, "skipped": 0, "reports": [1]}

        def fake_advices(*args, **kwargs):
            raise ValueError("建议解析失败")

        monkeypatch.setattr(sync_mod, "run_daily_reviews", fake_reviews)
        monkeypatch.setattr(sync_mod, "run_daily_next_advices", fake_advices)
        xunji, garmin = self._mocks()

        result = sync_mod.daily_sync(DAY, session=session, xunji=xunji, garmin=garmin,
                                     sleep=lambda _: None)
        assert result["status"] == "success"
        assert result["detail"].get("ai_reviews_failed") is True


# ---------- API 按类型查询 ----------


class TestNextAdviceAPI:
    @pytest.fixture
    def client(self, session, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.db import get_session
        from app.main import app

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
    def auth(self, client):
        token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_list_filters_by_type(self, client, auth, session):
        from app.models import Workout

        w = Workout(date=DAY, title="背", match_status="auto_matched")
        session.add(w)
        session.commit()
        session.add(AIReport(type="session_review", workout_id=w.id,
                             period_start=DAY, period_end=DAY, content_md="点评"))
        session.add(AIReport(type="next_advice", workout_id=w.id,
                             period_start=DAY, period_end=DAY, content_md=VALID_CONTENT))
        session.commit()

        resp = client.get(f"/api/ai-reports?date={DAY.isoformat()}&type=next_advice",
                          headers=auth)
        assert resp.status_code == 200
        reports = resp.json()["reports"]
        assert len(reports) == 1
        assert reports[0]["type"] == "next_advice"

        # 不传 type 保持原行为（仅 session_review）
        resp2 = client.get(f"/api/ai-reports?date={DAY.isoformat()}", headers=auth)
        types = [r["type"] for r in resp2.json()["reports"]]
        assert types == ["session_review"]
