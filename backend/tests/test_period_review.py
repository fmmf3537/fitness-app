"""V2-2 周期复盘：周复盘（weekly）/ 月复盘（monthly）服务测试。"""
import json
from datetime import date
from unittest.mock import Mock

import pytest

from app.adapters.llm import LLMError
from app.models import AIReport, BodyMetric, JobRun, Workout, XunjiPlan
from app.services import ai as ai_service


def make_workout(session, day, title="训练", movements=None,
                 duration_s=3600, calories=300):
    w = Workout(
        date=day, title=title, match_status="auto_matched",
        duration_s=duration_s, calories=calories,
        movements_json=json.dumps(movements or [], ensure_ascii=False),
    )
    session.add(w)
    session.commit()
    return w


def make_plan(session, days, plan_ref="platform:1",
              date_from=date(2026, 8, 1), date_to=date(2026, 8, 31)):
    row = XunjiPlan(
        plan_ref=plan_ref,
        plan_json=json.dumps({"plan": {"name": "增肌计划"}, "days": days},
                             ensure_ascii=False),
        date_from=date_from, date_to=date_to,
    )
    session.add(row)
    session.commit()
    return row


def make_weekly_report(session, period_start, period_end, content="复盘内容"):
    r = AIReport(
        type="weekly", period_start=period_start, period_end=period_end,
        model="deepseek-chat", content_md=content,
    )
    session.add(r)
    session.commit()
    return r


CHAT_RESULT = {"content": "## 本周概览\n表现不错", "prompt_tokens": 10,
               "completion_tokens": 5, "model": "deepseek-chat"}


# ---------- 周期区间 ----------

class TestPeriodRange:
    def test_week_range_monday_to_sunday(self):
        # 2026-08-03 是周一，2026-08-09 是周日
        assert ai_service.week_range(date(2026, 8, 9)) == (
            date(2026, 8, 3), date(2026, 8, 9))
        assert ai_service.week_range(date(2026, 8, 3)) == (
            date(2026, 8, 3), date(2026, 8, 9))
        assert ai_service.week_range(date(2026, 8, 5)) == (
            date(2026, 8, 3), date(2026, 8, 9))

    def test_month_range_full_month(self):
        assert ai_service.month_range(date(2026, 8, 15)) == (
            date(2026, 8, 1), date(2026, 8, 31))
        assert ai_service.month_range(date(2026, 2, 10)) == (
            date(2026, 2, 1), date(2026, 2, 28))


# ---------- 周期训练汇总 ----------

class TestPeriodTrainingSummary:
    def test_summary_counts_volume_parts(self, session):
        make_workout(session, date(2026, 8, 4), "胸", movements=[
            {"name": "杠铃卧推", "sets": [
                {"weight": 60, "unit": "kg", "reps": 10},
                {"weight": 60, "unit": "kg", "reps": 8}]},
        ])
        make_workout(session, date(2026, 8, 6), "腿", movements=[
            {"name": "杠铃深蹲", "sets": [{"weight": 80, "unit": "kg", "reps": 5}]},
        ])
        s = ai_service.query_period_training_summary(
            session, date(2026, 8, 3), date(2026, 8, 9))
        assert s["start"] == "2026-08-03"
        assert s["end"] == "2026-08-09"
        assert s["workout_count"] == 2
        assert s["training_days"] == 2
        assert s["total_volume_kg"] == 60 * 10 + 60 * 8 + 80 * 5
        assert s["total_calories"] == 600
        assert s["total_duration_s"] == 7200
        parts = {p["part"]: p for p in s["part_distribution"]}
        assert parts["胸"]["sets"] == 2
        assert parts["腿"]["sets"] == 1
        assert [w["date"] for w in s["workouts"]] == ["2026-08-04", "2026-08-06"]

    def test_summary_empty_period(self, session):
        s = ai_service.query_period_training_summary(
            session, date(2026, 8, 3), date(2026, 8, 9))
        assert s["workout_count"] == 0
        assert s["training_days"] == 0
        assert s["total_volume_kg"] == 0
        assert s["part_distribution"] == []

    def test_summary_undone_sets_not_counted(self, session):
        make_workout(session, date(2026, 8, 4), "胸", movements=[
            {"name": "杠铃卧推", "sets": [
                {"weight": 60, "unit": "kg", "reps": 10, "done": False},
                {"weight": 60, "unit": "kg", "reps": 8}]},
        ])
        s = ai_service.query_period_training_summary(
            session, date(2026, 8, 3), date(2026, 8, 9))
        assert s["total_volume_kg"] == 60 * 8


# ---------- PR 事件 ----------

class TestPrEvents:
    def test_detects_new_pr(self, session):
        make_workout(session, date(2026, 7, 20), "胸", movements=[
            {"name": "杠铃卧推", "sets": [{"weight": 60, "reps": 8}]},
        ])
        make_workout(session, date(2026, 8, 4), "胸", movements=[
            {"name": "杠铃卧推", "sets": [{"weight": 62.5, "reps": 5}]},
        ])
        events = ai_service.query_pr_events(
            session, date(2026, 8, 3), date(2026, 8, 9))
        assert len(events) == 1
        assert events[0]["movement"] == "杠铃卧推"
        assert events[0]["weight"] == 62.5
        assert events[0]["prev_best"] == 60.0
        assert events[0]["date"] == "2026-08-04"

    def test_no_history_no_event(self, session):
        make_workout(session, date(2026, 8, 4), "胸", movements=[
            {"name": "杠铃卧推", "sets": [{"weight": 62.5, "reps": 5}]},
        ])
        assert ai_service.query_pr_events(
            session, date(2026, 8, 3), date(2026, 8, 9)) == []

    def test_not_exceeded_no_event(self, session):
        make_workout(session, date(2026, 7, 20), "胸", movements=[
            {"name": "杠铃卧推", "sets": [{"weight": 65, "reps": 5}]},
        ])
        make_workout(session, date(2026, 8, 4), "胸", movements=[
            {"name": "杠铃卧推", "sets": [{"weight": 62.5, "reps": 5}]},
        ])
        assert ai_service.query_pr_events(
            session, date(2026, 8, 3), date(2026, 8, 9)) == []


# ---------- 计划完成率 ----------

class TestPlanCompletion:
    def test_completion_rate(self, session):
        make_plan(session, days=[
            {"datestr": "2026-08-04", "workout": {"movements": [{"name": "杠铃卧推"}]}},
            {"datestr": "2026-08-06", "workout": {"movements": [{"name": "杠铃深蹲"}]}},
            {"datestr": "2026-08-08", "workout": {"movements": []}},  # 休息日不计
        ])
        make_workout(session, date(2026, 8, 4), "胸", movements=[
            {"name": "杠铃卧推", "sets": [{"weight": 60, "reps": 10}]},
        ])
        r = ai_service.query_plan_completion(
            session, date(2026, 8, 1), date(2026, 8, 31))
        assert r["planned_days"] == 2
        assert r["completed_days"] == 1
        assert r["rate"] == 0.5
        assert r["missed_dates"] == ["2026-08-06"]
        assert r["plan_name"] == "增肌计划"

    def test_no_plan_cache(self, session):
        r = ai_service.query_plan_completion(
            session, date(2026, 8, 1), date(2026, 8, 31))
        assert r["planned_days"] == 0
        assert r["completed_days"] == 0
        assert r["rate"] is None
        assert r["missed_dates"] == []


# ---------- 体成分变化 ----------

class TestBodyComposition:
    def test_weight_and_bodyfat_delta(self, session):
        session.add_all([
            BodyMetric(date=date(2026, 8, 1), type="weight", value=72.5, unit="kg"),
            BodyMetric(date=date(2026, 8, 30), type="weight", value=71.8, unit="kg"),
            BodyMetric(date=date(2026, 8, 1), type="bodyfat", value=18.0, unit="%"),
            BodyMetric(date=date(2026, 8, 30), type="bodyfat", value=17.2, unit="%"),
        ])
        session.commit()
        r = ai_service.query_body_composition(
            session, date(2026, 8, 1), date(2026, 8, 31))
        assert r["weight"]["first"] == 72.5
        assert r["weight"]["last"] == 71.8
        assert r["weight"]["delta"] == -0.7
        assert r["weight"]["count"] == 2
        assert r["bodyfat"]["delta"] == -0.8

    def test_no_data(self, session):
        r = ai_service.query_body_composition(
            session, date(2026, 8, 1), date(2026, 8, 31))
        assert r["weight"] is None
        assert r["bodyfat"] is None


# ---------- 上周复盘回读 ----------

class TestPreviousReview:
    def test_returns_latest_before_period(self, session):
        make_weekly_report(session, date(2026, 7, 20), date(2026, 7, 26), "更早的复盘")
        make_weekly_report(session, date(2026, 7, 27), date(2026, 8, 2),
                           "## 下周建议\n卧推加到 62.5kg")
        prev = ai_service.query_previous_review(session, "weekly", date(2026, 8, 3))
        assert prev is not None
        assert prev["period_start"] == "2026-07-27"
        assert "卧推加到 62.5kg" in prev["content_md"]

    def test_ignores_same_period_and_later(self, session):
        make_weekly_report(session, date(2026, 8, 3), date(2026, 8, 9), "本周")
        assert ai_service.query_previous_review(
            session, "weekly", date(2026, 8, 3)) is None

    def test_no_previous(self, session):
        assert ai_service.query_previous_review(
            session, "weekly", date(2026, 8, 3)) is None


# ---------- prompt 组装 ----------

def _summary():
    return {
        "start": "2026-08-03", "end": "2026-08-09",
        "workout_count": 3, "training_days": 3,
        "total_volume_kg": 4520.0, "total_duration_s": 10800,
        "total_calories": 900,
        "part_distribution": [
            {"part": "胸", "sets": 6, "volume_kg": 2160.0},
            {"part": "腿", "sets": 5, "volume_kg": 2360.0},
        ],
        "workouts": [
            {"date": "2026-08-04", "title": "胸", "volume_kg": 2160.0,
             "duration_s": 3600, "calories": 300},
        ],
    }


def _recovery():
    return {
        "days_count": 7, "avg_sleep_hours": 7.2, "avg_deep_ratio": 0.21,
        "hrv_status": "BALANCED", "hrv_status_list": ["BALANCED"],
        "body_battery_high": 90, "body_battery_low": 30,
        "resting_hr": 52, "stress_avg": 28,
        "weight_trend": [], "training_readiness": None,
    }


class TestBuildWeeklyPrompt:
    def test_includes_stats_sections_and_echarts_requirement(self):
        pr_events = [{"movement": "杠铃卧推", "date": "2026-08-04",
                      "weight": 62.5, "prev_best": 60.0}]
        msgs = ai_service.build_weekly_prompt(
            _summary(), _recovery(), pr_events, None)
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        system = msgs[0]["content"]
        for s in ai_service.WEEKLY_SECTIONS:
            assert f"## {s}" in system
        assert "```echarts" in system  # 要求输出 ECharts 可渲染数据块
        user = msgs[1]["content"]
        assert "2026-08-03" in user and "2026-08-09" in user
        assert "4520" in user
        assert "胸" in user and "腿" in user
        assert "杠铃卧推" in user and "62.5" in user  # PR 事件
        assert "BALANCED" in user

    def test_includes_previous_review_advice(self):
        prev = {"period_start": "2026-07-27", "period_end": "2026-08-02",
                "content_md": "## 下周建议\n卧推加到 62.5kg"}
        msgs = ai_service.build_weekly_prompt(_summary(), _recovery(), [], prev)
        user = msgs[1]["content"]
        assert "上周复盘" in user
        assert "卧推加到 62.5kg" in user

    def test_without_previous_review_marks_absent(self):
        msgs = ai_service.build_weekly_prompt(_summary(), _recovery(), [], None)
        assert "上周无复盘报告" in msgs[1]["content"]


class TestBuildMonthlyPrompt:
    def test_includes_plan_completion_and_body_composition(self):
        plan = {"planned_days": 12, "completed_days": 10, "rate": 0.833,
                "missed_dates": ["2026-08-06", "2026-08-20"],
                "plan_name": "增肌计划"}
        body = {"weight": {"first": 72.5, "last": 71.8, "delta": -0.7,
                           "count": 8, "unit": "kg"},
                "bodyfat": None}
        summary = _summary()
        summary["start"], summary["end"] = "2026-08-01", "2026-08-31"
        msgs = ai_service.build_monthly_prompt(summary, plan, body, _recovery())
        system = msgs[0]["content"]
        for s in ai_service.MONTHLY_SECTIONS:
            assert f"## {s}" in system
        assert "```echarts" in system
        user = msgs[1]["content"]
        assert "2026-08-01" in user and "2026-08-31" in user
        assert "增肌计划" in user
        assert "83.3%" in user  # 计划完成率
        assert "2026-08-06" in user  # 错过日期
        assert "72.5" in user and "71.8" in user  # 体成分变化

    def test_no_plan_and_no_body_data(self):
        plan = {"planned_days": 0, "completed_days": 0, "rate": None,
                "missed_dates": [], "plan_name": None}
        body = {"weight": None, "bodyfat": None}
        summary = _summary()
        summary["start"], summary["end"] = "2026-08-01", "2026-08-31"
        msgs = ai_service.build_monthly_prompt(summary, plan, body, _recovery())
        user = msgs[1]["content"]
        assert "无计划缓存" in user or "无训记计划" in user
        assert "无体重记录" in user


# ---------- 生成与落库 ----------

class TestGenerateWeeklyReview:
    def test_generates_and_stores_report(self, session):
        make_workout(session, date(2026, 8, 4), "胸", movements=[
            {"name": "杠铃卧推", "sets": [{"weight": 60, "reps": 10}]},
        ])
        chat_fn = Mock(return_value=dict(CHAT_RESULT))
        report = ai_service.generate_weekly_review(
            session, date(2026, 8, 3), chat_fn=chat_fn)
        assert report.type == "weekly"
        assert report.workout_id is None
        assert report.period_start == date(2026, 8, 3)
        assert report.period_end == date(2026, 8, 9)
        assert report.content_md == CHAT_RESULT["content"]
        assert report.prompt_tokens == 10
        chat_fn.assert_called_once()
        messages = chat_fn.call_args[0][0]
        assert messages[0]["role"] == "system"


class TestGenerateMonthlyReview:
    def test_generates_and_stores_report(self, session):
        chat_fn = Mock(return_value=dict(CHAT_RESULT))
        report = ai_service.generate_monthly_review(
            session, date(2026, 8, 1), chat_fn=chat_fn)
        assert report.type == "monthly"
        assert report.workout_id is None
        assert report.period_start == date(2026, 8, 1)
        assert report.period_end == date(2026, 8, 31)


# ---------- 编排（幂等 + JobRun） ----------

class TestRunWeeklyReview:
    def test_writes_jobrun_and_idempotent(self, session):
        chat_fn = Mock(return_value=dict(CHAT_RESULT))
        r1 = ai_service.run_weekly_review(
            date(2026, 8, 9), session=session, chat_fn=chat_fn)
        assert r1["status"] == "success"
        assert r1["generated"] is True
        assert r1["period_start"] == "2026-08-03"

        r2 = ai_service.run_weekly_review(
            date(2026, 8, 9), session=session, chat_fn=chat_fn)
        assert r2["status"] == "success"
        assert r2["skipped"] is True
        assert chat_fn.call_count == 1  # 第二次未再调用模型

        jobs = session.query(JobRun).filter_by(job_name="weekly_review").all()
        assert len(jobs) == 2
        assert all(j.status == "success" for j in jobs)

    def test_llm_failure_writes_failed_jobrun(self, session):
        chat_fn = Mock(side_effect=LLMError("boom"))
        r = ai_service.run_weekly_review(
            date(2026, 8, 9), session=session, chat_fn=chat_fn)
        assert r["status"] == "failed"
        assert "boom" in r["error"]
        job = session.query(JobRun).filter_by(job_name="weekly_review").one()
        assert job.status == "failed"


class TestRunMonthlyReview:
    def test_reviews_month_of_given_day(self, session):
        chat_fn = Mock(return_value=dict(CHAT_RESULT))
        r = ai_service.run_monthly_review(
            date(2026, 7, 31), session=session, chat_fn=chat_fn)
        assert r["status"] == "success"
        assert r["period_start"] == "2026-07-01"
        assert r["period_end"] == "2026-07-31"
        report = session.query(AIReport).filter_by(type="monthly").one()
        assert report.period_start == date(2026, 7, 1)

    def test_llm_failure_writes_failed_jobrun(self, session):
        chat_fn = Mock(side_effect=LLMError("boom"))
        r = ai_service.run_monthly_review(
            date(2026, 7, 31), session=session, chat_fn=chat_fn)
        assert r["status"] == "failed"
        job = session.query(JobRun).filter_by(job_name="monthly_review").one()
        assert job.status == "failed"
