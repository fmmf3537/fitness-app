"""V1-3 AI 单次训练点评服务测试。"""
import json
from datetime import date, datetime, timedelta
from unittest.mock import Mock

import pytest
from tests.conftest import make_garmin_activity, make_xunji_train

from app.adapters.llm import LLMError
from app.models import AIReport, BodyMetric, GarminDaily, JobRun, Workout
from app.services import ai as ai_mod
from app.services.ai import (
    PROMPT_SECTIONS,
    build_session_review_prompt,
    generate_session_review,
    query_activity_history,
    query_movement_history,
    query_recovery_summary,
    run_daily_reviews,
)
from app.services.fuse import fuse_workout
from app.services.sync import daily_sync

DAY = date(2026, 8, 3)


def _workout_dict(**overrides):
    base = {
        "date": "2026-08-03",
        "title": "背部训练",
        "tags": "strength_training",
        "duration_s": 3600,
        "calories": 456,
        "avg_hr": 118,
        "max_hr": 152,
        "movements": [
            {
                "name": "引体向上",
                "sets": [
                    {"weight": "0", "unit": "kg", "reps": "8", "done": True},
                    {"weight": "0", "unit": "kg", "reps": "7", "done": True},
                ],
            },
            {
                "name": "杠铃划船",
                "sets": [{"weight": 60, "unit": "kg", "reps": 10, "done": True, "rpe": 8}],
            },
        ],
    }
    base.update(overrides)
    return base


def _history_dict():
    return {
        "引体向上": {
            "count": 3,
            "pr_weight": 5.0,
            "recent": [
                {"date": "2026-07-28", "best_weight": 0.0, "best_reps": 10,
                 "total_volume": 0.0, "sets_count": 3},
                {"date": "2026-07-21", "best_weight": 0.0, "best_reps": 9,
                 "total_volume": 0.0, "sets_count": 3},
            ],
        }
    }


def _recovery_dict():
    return {
        "days_count": 7,
        "avg_sleep_hours": 7.2,
        "avg_deep_ratio": 0.18,
        "hrv_status": "balanced",
        "body_battery_high": 95,
        "body_battery_low": 15,
        "resting_hr": 58,
        "stress_avg": 35,
        "weight_trend": [{"date": "2026-08-02", "value": 72.4}],
        "training_readiness": None,
    }


class TestBuildPrompt:
    def test_returns_system_and_user_messages(self):
        messages = build_session_review_prompt(_workout_dict(), _history_dict(), _recovery_dict())
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_prompt_contains_required_sections(self):
        messages = build_session_review_prompt(_workout_dict(), _history_dict(), _recovery_dict())
        user = messages[1]["content"]
        assert "本次训练（2026-08-03）" in user
        assert "背部训练" in user
        assert "引体向上" in user
        assert "杠铃划船" in user
        assert "近4周同动作历史" in user
        assert "个人纪录（PR）重量：5.0 kg" in user
        assert "近7天恢复数据" in user
        assert "平均睡眠时长：7.2 小时" in user
        assert "HRV 状态：balanced" in user
        assert "训练准备度：当前未接入" in user
        for section in PROMPT_SECTIONS:
            assert section in messages[0]["content"]

    def test_prompt_handles_no_movements(self):
        messages = build_session_review_prompt(_workout_dict(movements=[]), {}, _recovery_dict())
        assert "无动作数据" in messages[1]["content"]


class TestQueryMovementHistory:
    def test_finds_recent_records_and_pr(self, session):
        day = DAY
        dates = [
            (day - timedelta(days=7), "70"),    # 2026-07-27, PR
            (day - timedelta(days=14), "60"),   # 2026-07-20
            (day - timedelta(days=35), "80"),   # 2026-06-29, 超出4周应忽略
        ]
        for d, weight in dates:
            x = make_xunji_train(
                session, d, localid=f"x{d.day}", title="背",
                movements=[{"name": "杠铃划船",
                            "sets": [{"weight": weight, "unit": "kg",
                                      "reps": "10", "done": True}]}],
            )
            g = make_garmin_activity(session, d, activity_id=f"g{d.day}")
            fuse_workout(session, d, xunji=x, garmin=g, match_status="auto_matched")

        hist = query_movement_history(session, "杠铃划船", day)

        assert hist["count"] == 2
        assert hist["pr_weight"] == 70.0
        assert len(hist["recent"]) == 2
        assert hist["recent"][0]["date"] == "2026-07-27"
        assert hist["recent"][0]["best_weight"] == 70.0

    def test_ignores_other_movements(self, session):
        day = DAY
        past = day - timedelta(days=5)
        x = make_xunji_train(
            session, past, localid="x1", title="胸",
            movements=[{"name": "卧推", "sets": [{"weight": "80", "unit": "kg", "reps": "5", "done": True}]}],
        )
        g = make_garmin_activity(session, past, activity_id="g1")
        fuse_workout(session, past, xunji=x, garmin=g, match_status="auto_matched")

        hist = query_movement_history(session, "深蹲", day)
        assert hist["count"] == 0
        assert hist["recent"] == []


class TestQueryRecoverySummary:
    def test_extracts_sleep_and_hrv(self, session):
        sleep_data = {
            "dailySleepDTO": {
                "sleepTimeInSeconds": 28800,
                "deepSleepSeconds": 5760,
            }
        }
        for i in range(7):
            d = DAY - timedelta(days=i)
            row = GarminDaily(
                date=d,
                sleep_json=json.dumps(sleep_data, ensure_ascii=False),
                hrv_status="balanced" if i == 0 else "unbalanced",
                resting_hr=58,
                stress_avg=35,
                body_battery_high=95,
                body_battery_low=15,
            )
            session.add(row)
        session.commit()

        recovery = query_recovery_summary(session, DAY)

        assert recovery["days_count"] == 7
        assert recovery["avg_sleep_hours"] == 8.0
        assert recovery["avg_deep_ratio"] == 0.2
        assert recovery["hrv_status"] == "balanced"
        assert recovery["resting_hr"] == 58
        assert recovery["stress_avg"] == 35
        assert recovery["training_readiness"] is None

    def test_weight_trend_included(self, session):
        for i, value in enumerate([73.0, 72.8, 72.4]):
            session.add(BodyMetric(date=DAY - timedelta(days=i), type="weight", value=value, unit="kg"))
        session.commit()

        recovery = query_recovery_summary(session, DAY)
        assert len(recovery["weight_trend"]) == 3
        assert recovery["weight_trend"][0]["value"] == 73.0


class TestGenerateSessionReview:
    def test_saves_ai_report_with_tokens_and_cost(self, session):
        x = make_xunji_train(session, DAY, localid="1", title="背二头", movements=[
            {"name": "引体向上", "sets": [{"weight": "0", "unit": "kg", "reps": "8", "done": True}]}
        ])
        g = make_garmin_activity(session, DAY, activity_id="g1", duration_s=3600, calories=400,
                                 avg_hr=118, max_hr=152)
        w = fuse_workout(session, DAY, xunji=x, garmin=g, match_status="auto_matched")

        # V3-4：合法输出须附 session_review_v1 评分块，否则触发重试/降级
        def fake_chat(messages):
            return {"content": (
                        "## 完成质量\n不错\n## 与历史对比\n持平\n"
                        '```json\n{"schema":"session_review_v1","score":82,'
                        '"subscores":{"completion":85,"intensity":80,"recovery_fit":82},'
                        '"one_liner":"稳定发挥"}\n```'
                    ),
                    "prompt_tokens": 100, "completion_tokens": 20}

        report = generate_session_review(session, w.id, chat_fn=fake_chat)

        assert report.type == "session_review"
        assert report.workout_id == w.id
        assert report.period_start == DAY
        assert report.model is not None
        assert report.prompt_tokens == 100
        assert report.completion_tokens == 20
        assert report.cost_estimate > 0
        assert "完成质量" in report.content_md
        assert report.score == 82

        persisted = session.get(AIReport, report.id)
        assert persisted is not None

    def test_raises_value_error_for_missing_workout(self, session):
        with pytest.raises(ValueError, match="workout 999 不存在"):
            generate_session_review(session, 999, chat_fn=lambda m: {"content": "x"})


class TestRunDailyReviews:
    def test_generates_for_all_workouts(self, session):
        for i in range(2):
            x = make_xunji_train(session, DAY, localid=str(i), title=f"训练{i}")
            g = make_garmin_activity(session, DAY, activity_id=f"g{i}")
            fuse_workout(session, DAY, xunji=x, garmin=g, match_status="auto_matched")

        def fake_chat(messages):
            return {"content": "点评", "prompt_tokens": 10, "completion_tokens": 5}

        summary = run_daily_reviews(session, DAY, chat_fn=fake_chat)

        assert summary["generated"] == 2
        assert session.query(AIReport).count() == 2

    def test_skips_existing_report(self, session):
        x = make_xunji_train(session, DAY, localid="1", title="胸")
        g = make_garmin_activity(session, DAY, activity_id="g1")
        w = fuse_workout(session, DAY, xunji=x, garmin=g, match_status="auto_matched")
        session.add(AIReport(type="session_review", workout_id=w.id,
                            period_start=DAY, period_end=DAY, content_md="已有"))
        session.commit()

        def fake_chat(messages):
            return {"content": "新点评", "prompt_tokens": 10, "completion_tokens": 5}

        summary = run_daily_reviews(session, DAY, chat_fn=fake_chat)

        assert summary["skipped"] == 1
        assert summary["generated"] == 0
        assert session.query(AIReport).count() == 1


class TestSyncIntegration:
    def test_daily_sync_triggers_ai_review(self, session, monkeypatch):
        x = make_xunji_train(session, DAY, localid="1", title="腿")
        g = make_garmin_activity(session, DAY, activity_id="g1")
        fuse_workout(session, DAY, xunji=x, garmin=g, match_status="auto_matched")
        session.commit()

        called = []

        def fake_run(session, day, chat_fn=None):
            called.append(day)
            return {"date": day.isoformat(), "generated": 1, "skipped": 0, "reports": [1]}

        monkeypatch.setattr(ai_mod, "run_daily_reviews", fake_run)
        from app.services import sync as sync_mod
        monkeypatch.setattr(sync_mod, "run_daily_reviews", fake_run)

        xunji = Mock()
        xunji.fetch_trains.return_value = []
        garmin = Mock()
        garmin.sync_activities.return_value = []
        garmin.sync_daily.return_value = Mock()

        result = daily_sync(DAY, session=session, xunji=xunji, garmin=garmin, sleep=lambda _: None)

        assert result["status"] == "success"
        assert called == [DAY]
        assert result["detail"].get("ai_reviews") == 1

    def test_daily_sync_ai_failure_does_not_fail_sync(self, session, monkeypatch):
        x = make_xunji_train(session, DAY, localid="1", title="肩")
        g = make_garmin_activity(session, DAY, activity_id="g1")
        fuse_workout(session, DAY, xunji=x, garmin=g, match_status="auto_matched")
        session.commit()

        def fake_run(*args, **kwargs):
            raise LLMError("模型超时")

        from app.services import sync as sync_mod
        monkeypatch.setattr(sync_mod, "run_daily_reviews", fake_run)

        xunji = Mock()
        xunji.fetch_trains.return_value = []
        garmin = Mock()
        garmin.sync_activities.return_value = []
        garmin.sync_daily.return_value = Mock()

        result = daily_sync(DAY, session=session, xunji=xunji, garmin=garmin, sleep=lambda _: None)

        assert result["status"] == "success"
        assert result["detail"].get("ai_reviews_failed") is True

        runs = session.query(JobRun).filter(JobRun.job_name == "ai_review").all()
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert "模型超时" in runs[0].error


# =====================================================================
# V4-1 F1：同类活动历史（garmin_only 但 tags 非空）
# =====================================================================


class TestActivityTypeZh:
    """activity_type_zh 映射函数三分支：命中/未命中/None"""

    def test_hit_returns_chinese(self):
        assert ai_mod.activity_type_zh("badminton") == "羽毛球"
        assert ai_mod.activity_type_zh("running") == "跑步"
        assert ai_mod.activity_type_zh("strength_training") == "力量训练"
        assert ai_mod.activity_type_zh("treadmill_running") == "跑步机跑步"

    def test_miss_returns_original(self):
        assert ai_mod.activity_type_zh("unknown_xyz") == "unknown_xyz"
        assert ai_mod.activity_type_zh("zumba") == "zumba"

    def test_none_or_empty_returns_unknown(self):
        assert ai_mod.activity_type_zh(None) == "未知类型"
        assert ai_mod.activity_type_zh("") == "未知类型"
        assert ai_mod.activity_type_zh("   ") == "未知类型"


class TestQueryActivityHistory:
    """query_activity_history：按 Workout.tags 精确匹配 + 4 周窗口 + 软删过滤"""

    def test_filters_by_tags_and_window(self, session):
        day = DAY
        in_window_dates = [
            day - timedelta(days=3),    # 2026-07-31
            day - timedelta(days=10),   # 2026-07-24
            day - timedelta(days=20),   # 2026-07-14
        ]
        in_window_specs = [
            {"duration_s": 1800, "avg_hr": 110, "max_hr": 150, "calories": 200},
            {"duration_s": 1900, "avg_hr": 115, "max_hr": 155, "calories": 250},
            {"duration_s": 2000, "avg_hr": 120, "max_hr": 160, "calories": 300},
        ]
        for d, spec in zip(in_window_dates, in_window_specs):
            session.add(Workout(date=d, tags="badminton", **spec))
        # 窗口外（35 天前）：应忽略
        session.add(Workout(date=day - timedelta(days=35), tags="badminton",
                            duration_s=2000, calories=300, avg_hr=120, max_hr=160))
        # 其他类型：应忽略
        session.add(Workout(date=day - timedelta(days=5), tags="running",
                            duration_s=1800, calories=250, avg_hr=130, max_hr=170))
        # 软删：应忽略
        session.add(Workout(date=day - timedelta(days=7), tags="badminton",
                            duration_s=2400, calories=400, avg_hr=140, max_hr=180,
                            deleted_at=datetime(2026, 8, 1, 12, 0, 0)))
        session.commit()

        result = query_activity_history(session, "badminton", day)

        assert result["count"] == 3
        assert len(result["recent"]) == 3
        # recent 按日期倒序（最近→最远）
        assert result["recent"][0]["date"] == "2026-07-31"
        assert result["recent"][1]["date"] == "2026-07-24"
        assert result["recent"][2]["date"] == "2026-07-14"
        # 仅羽毛球明细字段
        assert result["recent"][0]["duration_s"] == 1800
        assert result["recent"][0]["avg_hr"] == 110
        # 均值（int 取整）
        expected_avg_dur = int((1800 + 1900 + 2000) / 3)  # 1900
        expected_avg_hr = int((110 + 115 + 120) / 3)      # 115
        assert result["avg_duration_s"] == expected_avg_dur
        assert result["avg_hr"] == expected_avg_hr

    def test_returns_empty_when_no_match(self, session):
        result = query_activity_history(session, "badminton", DAY)
        assert result["count"] == 0
        assert result["avg_duration_s"] is None
        assert result["avg_hr"] is None
        assert result["recent"] == []

    def test_ignores_records_with_missing_metrics(self, session):
        # duration_s / avg_hr 全部为 None 时，均值字段为 None，recent 仍有序
        for i in range(2):
            session.add(Workout(
                date=DAY - timedelta(days=3 + i), tags="tennis",
                duration_s=None, avg_hr=None, max_hr=None, calories=None,
            ))
        session.commit()
        result = query_activity_history(session, "tennis", DAY)
        assert result["count"] == 2
        assert result["avg_duration_s"] is None
        assert result["avg_hr"] is None
        assert len(result["recent"]) == 2


class TestBuildPromptActivityHistory:
    """build_session_review_prompt：garmin_only 注入同类活动历史段的契约"""

    def _garmin_only_workout(self):
        return {
            "date": "2026-08-03",
            "title": "午休羽毛球",
            "tags": "badminton",
            "duration_s": 1800,
            "calories": 230,
            "avg_hr": 120,
            "max_hr": 150,
            "movements": [],
        }

    def _activity_history(self, count=3):
        return {
            "count": count,
            "avg_duration_s": 1900,
            "avg_hr": 115,
            "recent": [
                {"date": "2026-07-31", "duration_s": 1800, "avg_hr": 110,
                 "max_hr": 150, "calories": 200},
                {"date": "2026-07-24", "duration_s": 1900, "avg_hr": 115,
                 "max_hr": 155, "calories": 250},
            ][:count] if count > 0 else [],
        }

    def test_garmin_only_injects_activity_history_section(self):
        w = self._garmin_only_workout()
        ah = self._activity_history(count=3)
        messages = build_session_review_prompt(
            w, {}, _recovery_dict(), activity_history=ah
        )
        user = messages[1]["content"]
        # 新段标题：含中文映射名
        assert "近4周同类活动（羽毛球）历史" in user
        assert "出现次数：3" in user
        # 平均时长走 _format_duration：1900/60=31 → "31 分钟"
        assert "平均时长：31 分钟" in user
        assert "平均心率：115 bpm" in user
        # 旧段必须被替换掉（不能同时存在两段）
        assert "近4周同动作历史" not in user
        # 活动类型也走中文映射（不是 typeKey）
        assert "活动类型：羽毛球" in user
        assert "活动类型：badminton" not in user
        # 明细：单项为 None 的片段省略
        assert "2026-07-31：时长 30 分钟" in user
        assert "平均心率 110 bpm" in user
        assert "最大心率 150 bpm" in user
        assert "热量 200 千卡" in user
        # recovery 段保持不变（验证分支不影响后续节）
        assert "近7天恢复数据" in user
        assert "平均睡眠时长：7.2 小时" in user

    def test_count_zero_renders_no_records_message(self):
        w = self._garmin_only_workout()
        ah = self._activity_history(count=0)
        messages = build_session_review_prompt(
            w, {}, _recovery_dict(), activity_history=ah
        )
        user = messages[1]["content"]
        assert "近4周同类活动（羽毛球）历史" in user
        assert "近4周无同类活动记录" in user
        # 不应出现次数/明细行
        assert "出现次数：0" not in user
        assert "平均时长：" not in user
        assert "最近记录：" not in user

    def test_no_movements_without_activity_history_falls_back(self):
        """无 movements 且 activity_history 未传入：沿用旧逻辑（向后兼容）。"""
        w = _workout_dict(movements=[], tags="badminton")
        messages = build_session_review_prompt(w, {}, _recovery_dict())
        user = messages[1]["content"]
        assert "近4周同动作历史" in user
        assert "近4周无同动作历史数据" in user
        assert "近4周同类活动" not in user

    def test_movements_present_unchanged_prompt_structure(self):
        """回归红线：有 movements 时 prompt 逐字节保持除 tags 行外一致。"""
        w = _workout_dict()
        messages = build_session_review_prompt(
            w, _history_dict(), _recovery_dict()
        )
        user = messages[1]["content"]
        # tags 行走中文映射
        assert "活动类型：力量训练" in user
        assert "活动类型：strength_training" not in user
        # 旧历史段原样保留
        assert "近4周同动作历史" in user
        assert "个人纪录（PR）重量：5.0 kg" in user
        # 不应注入同类活动段
        assert "近4周同类活动" not in user

    def test_recent_omits_none_fields(self):
        """明细行：duration_s/avg_hr/max_hr/calories 任一为 None 时省略该片段。"""
        w = self._garmin_only_workout()
        ah = {
            "count": 1,
            "avg_duration_s": 1800,
            "avg_hr": 120,
            "recent": [
                {"date": "2026-07-31", "duration_s": 1800, "avg_hr": None,
                 "max_hr": None, "calories": 250},
            ],
        }
        messages = build_session_review_prompt(
            w, {}, _recovery_dict(), activity_history=ah
        )
        user = messages[1]["content"]
        line = next(
            (ln for ln in user.splitlines() if ln.startswith("  - 2026-07-31")),
            None,
        )
        assert line is not None
        assert "时长 30 分钟" in line
        assert "热量 250 千卡" in line
        assert "平均心率" not in line
        assert "最大心率" not in line
