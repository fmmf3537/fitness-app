"""V5-2 L2 每日记忆提炼 + tag 聚合 + 5 入口注入挂钩测试。"""
from __future__ import annotations

import json
from datetime import date, datetime
from unittest.mock import patch

import pytest

from app.adapters.llm import LLMError
from app.models import (
    AIReport,
    CoachChatMessage,
    CoachMemory,
    CoachPreference,
    JobRun,
    ReportChatMessage,
)
from app.services.memory_distill import (
    MAX_DAILY_INPUT_CHARS,
    _call_distill_llm,
    _format_messages_for_distill,
    _query_today_messages,
    build_query_tags,
    compose_memory_section_for,
    distill_daily_memory,
    distill_messages_to_memory,
)
from app.services.stats import classify_part


DAY = date(2026, 9, 4)


def _make_report(session, day=DAY):
    report = AIReport(
        type="session_review",
        period_start=day,
        period_end=day,
        content_md="# 点评\n内容",
        model="deepseek-chat",
    )
    session.add(report)
    session.commit()
    return report


def _add_report_msg(session, report_id, role, content, created_at):
    msg = ReportChatMessage(
        report_id=report_id,
        role=role,
        content=content,
        created_at=created_at,
    )
    session.add(msg)
    session.commit()
    return msg


def _add_coach_msg(session, role, content, created_at):
    msg = CoachChatMessage(
        role=role,
        content=content,
        created_at=created_at,
    )
    session.add(msg)
    session.commit()
    return msg


def _distill_chat_fn(items):
    """返回预置 JSON 摘要列表的 chat_fn。"""
    payload = json.dumps(items, ensure_ascii=False)

    def fake(messages):
        return {"content": payload, "prompt_tokens": 1, "completion_tokens": 1}

    return fake


# ---------- 1. _query_today_messages ----------


class TestQueryTodayMessages:
    def test_day_boundary_slice(self, session):
        report = _make_report(session)
        inside = datetime(2026, 9, 4, 10, 0, 0)
        before = datetime(2026, 9, 3, 23, 59, 59)
        after = datetime(2026, 9, 5, 0, 0, 0)
        _add_report_msg(session, report.id, "user", "今天内", inside)
        _add_report_msg(session, report.id, "assistant", "今天答", inside)
        _add_report_msg(session, report.id, "user", "昨天", before)
        _add_report_msg(session, report.id, "user", "明天", after)

        report_convs, coach_convs = _query_today_messages(session, DAY)
        assert coach_convs == []
        assert len(report_convs) == 1
        ref_id, msgs = report_convs[0]
        assert ref_id == report.id
        assert [(r, c) for r, c in msgs] == [
            ("user", "今天内"),
            ("assistant", "今天答"),
        ]

    def test_empty_returns_empty_lists(self, session):
        assert _query_today_messages(session, DAY) == ([], [])


# ---------- 2. _format_messages_for_distill ----------


class TestFormatMessages:
    def test_role_labels_zh(self):
        text = _format_messages_for_distill(
            [("user", "我膝盖疼"), ("assistant", "注意热身")]
        )
        assert "用户：我膝盖疼" in text
        assert "教练：注意热身" in text

    def test_truncates_to_8k(self):
        long_content = "啊" * (MAX_DAILY_INPUT_CHARS + 500)
        text = _format_messages_for_distill([("user", long_content)])
        assert len(text) == MAX_DAILY_INPUT_CHARS


# ---------- 3. _call_distill_llm ----------


class TestCallDistillLlm:
    def test_parses_injected_json(self):
        items = [
            {"summary": "膝盖旧伤需注意", "tags": "膝盖,伤病"},
            {"summary": "偏好晚间训练", "tags": "偏好,时间"},
        ]
        out = _call_distill_llm("对话", chat_fn=_distill_chat_fn(items))
        assert len(out) == 2
        assert out[0]["summary"] == "膝盖旧伤需注意"
        assert out[0]["tags"] == "膝盖,伤病"

    def test_invalid_json_raises_llm_error(self):
        def bad(_msgs):
            return {"content": "不是 JSON"}

        with pytest.raises(LLMError):
            _call_distill_llm("对话", chat_fn=bad)


# ---------- 4-5. distill_messages_to_memory ----------


class TestDistillMessagesToMemory:
    def test_success_inserts_rows_no_job_run(self, session):
        items = [
            {"summary": "摘要甲", "tags": "甲"},
            {"summary": "摘要乙", "tags": "乙"},
        ]
        n = distill_messages_to_memory(
            session,
            [("user", "我怕深蹲伤膝"), ("assistant", "减负并加强热身")],
            "report_chat",
            42,
            chat_fn=_distill_chat_fn(items),
        )
        assert n == 2
        rows = session.query(CoachMemory).filter_by(source="report_chat", ref_report_id=42).all()
        assert len(rows) == 2
        assert {r.summary for r in rows} == {"摘要甲", "摘要乙"}
        assert session.query(JobRun).filter_by(job_name="memory_distill").count() == 0

    def test_idempotent_skip_same_source_ref(self, session):
        items = [{"summary": "一次", "tags": "t"}]
        n1 = distill_messages_to_memory(
            session, [("user", "a")], "coach_chat", 7, chat_fn=_distill_chat_fn(items)
        )
        n2 = distill_messages_to_memory(
            session,
            [("user", "a"), ("assistant", "b")],
            "coach_chat",
            7,
            chat_fn=_distill_chat_fn(
                [{"summary": "二次", "tags": "t2"}, {"summary": "三次", "tags": "t3"}]
            ),
        )
        assert n1 == 1
        assert n2 == 0
        assert session.query(CoachMemory).filter_by(source="coach_chat", ref_chat_id=7).count() == 1


# ---------- 6-7. distill_daily_memory ----------


class TestDistillDailyMemory:
    def test_mixed_conversations_and_job_run(self, session):
        report = _make_report(session)
        ts = datetime(2026, 9, 4, 12, 0, 0)
        _add_report_msg(session, report.id, "user", "报告追问：右膝不适", ts)
        _add_report_msg(session, report.id, "assistant", "建议减负", ts)
        _add_coach_msg(session, "user", "独立聊：偏好晚练", ts)
        _add_coach_msg(session, "assistant", "好的，记下了", ts)

        call_count = {"n": 0}

        def chat_fn(messages):
            call_count["n"] += 1
            src = "报告" if call_count["n"] == 1 else "独立"
            return {
                "content": json.dumps(
                    [{"summary": f"{src}要点", "tags": src}],
                    ensure_ascii=False,
                )
            }

        result = distill_daily_memory(session, DAY, chat_fn=chat_fn)
        assert result["conversations_processed"] == 2
        assert result["memories_added"] == 2
        assert session.query(CoachMemory).filter_by(source="report_chat").count() == 1
        assert session.query(CoachMemory).filter_by(source="coach_chat").count() == 1
        run = session.query(JobRun).filter_by(job_name="memory_distill").one()
        assert run.status == "success"

    def test_llm_failure_writes_failed_job_run(self, session):
        report = _make_report(session)
        ts = datetime(2026, 9, 4, 15, 0, 0)
        _add_report_msg(session, report.id, "user", "会失败的对话", ts)

        def boom(_msgs):
            raise RuntimeError("llm down")

        result = distill_daily_memory(session, DAY, chat_fn=boom)
        assert result["memories_added"] == 0
        run = session.query(JobRun).filter_by(job_name="memory_distill").one()
        assert run.status == "failed"


# ---------- 8-9. build_query_tags ----------


class TestBuildQueryTags:
    def test_movements_and_tags_dedupe(self):
        workout = {
            "movements": [
                {"name": "卧推"},
                {"name": "卧推"},
                {"name": "深蹲"},
            ],
            "tags": "strength_training",
        }
        tags = build_query_tags(workout, "session_review")
        assert tags.count("卧推") == 1
        assert "深蹲" in tags
        assert "strength_training" in tags
        assert "session_review" in tags
        assert "胸" in tags
        assert "腿" in tags

    def test_empty_dict_weekly(self):
        assert build_query_tags({}, "weekly") == ["weekly"]
        assert build_query_tags(None, "monthly") == ["monthly"]

    def test_body_part_via_classify_part(self):
        # classify_part 实装：卧推→胸、深蹲→腿、硬拉→腿（关键词表归腿）、划船→背
        assert classify_part("卧推") == "胸"
        assert classify_part("深蹲") == "腿"
        assert classify_part("硬拉") == "腿"
        assert classify_part("划船") == "背"
        tags = build_query_tags(
            {
                "movements": [
                    {"name": "卧推"},
                    {"name": "深蹲"},
                    {"name": "硬拉"},
                    {"name": "划船"},
                ]
            },
            "session_review",
        )
        assert "胸" in tags
        assert "腿" in tags
        assert "背" in tags


# ---------- 10. compose_memory_section_for ----------


class TestComposeMemorySectionFor:
    def test_includes_l1_and_l2_hits(self, session):
        session.add(
            CoachPreference(content="须知：右膝旧伤", tags="膝盖", source="user", active=True)
        )
        session.add(
            CoachMemory(
                summary="历史：深蹲减负",
                tags="深蹲,膝盖",
                source="report_chat",
                ref_report_id=1,
                active=True,
            )
        )
        session.add(
            CoachMemory(
                summary="无关饮食",
                tags="饮食",
                source="coach_chat",
                ref_chat_id=1,
                active=True,
            )
        )
        session.commit()

        section = compose_memory_section_for(
            session,
            {"movements": [{"name": "深蹲"}], "tags": "strength_training"},
            "session_review",
        )
        assert "用户长期记忆" in section
        assert "须知：右膝旧伤" in section
        assert "历史：深蹲减负" in section

    def test_empty_returns_empty_string(self, session):
        assert compose_memory_section_for(session, {}, "weekly") == ""

    def test_with_l3_section(self, session):
        session.add(
            CoachPreference(content="须知：右膝旧伤", tags="膝盖", source="user", active=True)
        )
        session.add(
            CoachMemory(
                summary="历史：深蹲减负",
                tags="深蹲,膝盖",
                source="report_chat",
                ref_report_id=1,
                active=True,
            )
        )
        session.commit()
        l3 = {"训练频率": "3 次/周（36 个训练日，共 12 周）", "总容量": "12000 kg（100 次有效组）"}
        section = compose_memory_section_for(
            session,
            {"movements": [{"name": "深蹲"}], "tags": "strength_training"},
            "session_review",
            l3=l3,
        )
        assert "## 用户长期记忆（AI 参考）" in section
        assert "须知：" in section
        assert "历史对话要点：" in section
        assert "长期统计：" in section
        assert "训练频率：3 次/周（36 个训练日，共 12 周）" in section

    def test_l3_none_omits_section(self, session):
        session.add(
            CoachPreference(content="须知一条", tags="通用", source="user", active=True)
        )
        session.commit()
        section = compose_memory_section_for(session, {}, "chat", l3=None)
        assert "须知：" in section
        assert "长期统计：" not in section

    def test_l3_empty_dict_omits_section(self, session):
        session.add(
            CoachPreference(content="须知一条", tags="通用", source="user", active=True)
        )
        session.commit()
        section = compose_memory_section_for(session, {}, "chat", l3={})
        assert "须知：" in section
        assert "长期统计：" not in section


# ---------- 11. generate_session_review 注入 ----------


class TestGeneratorInjectsMemorySection:
    def test_generate_session_review_passes_memory_section(self, session):
        from app.services.ai import generate_session_review
        from app.services.fuse import fuse_workout
        from tests.conftest import make_garmin_activity, make_xunji_train

        day = date(2026, 8, 3)
        x = make_xunji_train(
            session,
            day,
            localid="mem1",
            title="胸",
            movements=[
                {
                    "name": "卧推",
                    "sets": [{"weight": "60", "unit": "kg", "reps": "8", "done": True}],
                }
            ],
        )
        g = make_garmin_activity(session, day, activity_id="g-mem1")
        w = fuse_workout(session, day, xunji=x, garmin=g, match_status="auto_matched")

        captured = {}

        def fake_chat(messages):
            captured["messages"] = messages
            return {
                "content": (
                    "## 完成质量\nok\n## 与历史对比\nok\n"
                    "## 恢复评估\nok\n## 注意事项\nok\n\n"
                    "```json\n"
                    '{"schema":"session_review_v1","score":80,'
                    '"subscores":{"completion":80,"intensity":80,"recovery_fit":80},'
                    '"one_liner":"不错"}\n```'
                ),
                "prompt_tokens": 1,
                "completion_tokens": 1,
            }

        mem = "## 用户长期记忆（AI 参考）\n须知：\n- 测记忆"
        with patch(
            "app.services.memory_distill.compose_memory_section_for",
            return_value=mem,
        ):
            generate_session_review(session, w.id, chat_fn=fake_chat)

        user = captured["messages"][1]["content"]
        assert mem in user
        assert user.endswith(mem)


# ---------- 12. daily_sync 挂钩 ----------


class TestDailySyncMemoryHook:
    def test_distill_failure_does_not_break_sync(self, session, monkeypatch):
        from app.services import sync as sync_mod

        day = date(2026, 8, 3)

        class FakeXunji:
            def fetch_trains(self, datestr, force_refresh=False):
                return []

        class FakeGarmin:
            def sync_activities(self, datestr):
                return []

            def sync_daily(self, datestr):
                return True

        monkeypatch.setattr(
            sync_mod, "match_day", lambda *_a, **_k: {"workouts": [], "candidates": []}
        )
        monkeypatch.setattr(sync_mod, "run_daily_reviews", lambda *_a, **_k: {"generated": 0})
        monkeypatch.setattr(
            sync_mod, "run_daily_next_advices", lambda *_a, **_k: {"generated": 0}
        )

        def boom(*_a, **_k):
            raise RuntimeError("distill boom")

        monkeypatch.setattr(
            "app.services.memory_distill.distill_daily_memory", boom
        )

        result = sync_mod.daily_sync(
            day,
            session=session,
            xunji=FakeXunji(),
            garmin=FakeGarmin(),
            sleep=lambda _: None,
        )
        assert result["status"] == "success"
        assert result["detail"].get("memory_distill_failed") is True
