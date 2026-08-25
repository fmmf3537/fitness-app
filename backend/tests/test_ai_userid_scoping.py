"""M2-5-b：ai.py prompt 组装类查询的 user_id 收敛（防御纵深）。

验证：传入 user_id 时仅返回该用户数据；不传（None）时保留 legacy 全量语义。
覆盖表：workout / garmin_daily / body_metric / xunji_plan / ai_report。
"""
import json
from datetime import date, timedelta

import pytest

from app.models import AIReport, BodyMetric, GarminDaily, User, Workout, XunjiPlan
from app.services import ai as ai_mod

DAY = date(2026, 8, 10)
START = date(2026, 8, 1)
END = date(2026, 8, 31)


@pytest.fixture(autouse=True)
def _ensure_bob(session):
    """conftest 已预建 alice(id=1)；此处补一个 bob(id=2) 供跨用户隔离测试。"""
    if session.get(User, 2) is None:
        session.add(User(id=2, username="bob", password_hash="x", role="user"))
        session.commit()


def _workout(session, uid, d, *, name="深蹲", weight=100, reps=5):
    w = Workout(
        date=d,
        user_id=uid,
        title="训练",
        movements_json=json.dumps(
            [{"name": name, "sets": [{"weight": weight, "unit": "kg", "reps": str(reps), "done": True}]}]
        ),
        deleted_at=None,
    )
    session.add(w)
    session.commit()
    return w


def _garmin_daily(session, uid, d):
    row = GarminDaily(
        date=d,
        user_id=uid,
        resting_hr=58,
        stress_avg=35,
        body_battery_high=95,
        body_battery_low=15,
        hrv_status="balanced",
        sleep_json=json.dumps({"dailySleepDTO": {"sleepTimeInSeconds": 28800}}),
    )
    session.add(row)
    session.commit()
    return row


def _body_metric(session, uid, d, mtype="weight", value=72.0):
    row = BodyMetric(date=d, user_id=uid, type=mtype, value=value, unit="kg")
    session.add(row)
    session.commit()
    return row


def _xunji_plan(session, uid, day_str="2026-08-20"):
    row = XunjiPlan(
        user_id=uid,
        plan_ref=f"plan{uid}",
        plan_json=json.dumps({
            "plan": {"name": f"P{uid}"},
            "days": [{"date": day_str, "movements": [{"name": "深蹲", "sets": [{"weight": 100, "unit": "kg", "reps": 5}]}]}],
        }),
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
    )
    session.add(row)
    session.commit()
    return row


def _ai_report(session, uid, period_start):
    row = AIReport(
        type="weekly",
        user_id=uid,
        period_start=period_start,
        period_end=period_start,
        content_md="old review",
    )
    session.add(row)
    session.commit()
    return row


class TestPeriodTrainingSummaryScoping:
    def test_scopes_by_user_id(self, session):
        _workout(session, 1, date(2026, 8, 5))
        _workout(session, 2, date(2026, 8, 6))

        a = ai_mod.query_period_training_summary(session, START, END, user_id=1)
        b = ai_mod.query_period_training_summary(session, START, END, user_id=2)
        both = ai_mod.query_period_training_summary(session, START, END)

        assert a["workout_count"] == 1
        assert b["workout_count"] == 1
        assert both["workout_count"] == 2

    def test_null_user_id_matches_legacy(self, session):
        _workout(session, 1, date(2026, 8, 5))
        _workout(session, None, date(2026, 8, 6))

        both = ai_mod.query_period_training_summary(session, START, END, user_id=None)
        assert both["workout_count"] == 2


class TestMovementHistoryScoping:
    def test_scopes_by_user_id(self, session):
        _workout(session, 1, date(2026, 8, 5), name="深蹲", weight=100)
        _workout(session, 2, date(2026, 8, 6), name="深蹲", weight=120)

        a = ai_mod.query_movement_history(session, "深蹲", DAY, user_id=1)
        b = ai_mod.query_movement_history(session, "深蹲", DAY, user_id=2)

        assert a["count"] == 1
        assert a["pr_weight"] == 100.0
        assert b["count"] == 1
        assert b["pr_weight"] == 120.0


class TestRecoverySummaryScoping:
    def test_scopes_garmin_and_weight(self, session):
        _garmin_daily(session, 1, DAY)
        _garmin_daily(session, 2, DAY)
        _body_metric(session, 1, DAY, value=72.0)
        _body_metric(session, 2, DAY, value=80.0)

        a = ai_mod.query_recovery_summary(session, DAY, user_id=1)
        b = ai_mod.query_recovery_summary(session, DAY, user_id=2)

        assert a["days_count"] == 1
        assert b["days_count"] == 1
        assert a["weight_trend"][0]["value"] == 72.0
        assert b["weight_trend"][0]["value"] == 80.0


class TestBodyCompositionScoping:
    def test_scopes_by_user_id(self, session):
        _body_metric(session, 1, date(2026, 8, 1), value=70.0)
        _body_metric(session, 1, date(2026, 8, 31), value=68.0)
        _body_metric(session, 2, date(2026, 8, 1), value=90.0)
        _body_metric(session, 2, date(2026, 8, 31), value=88.0)

        a = ai_mod.query_body_composition(session, START, END, user_id=1)
        b = ai_mod.query_body_composition(session, START, END, user_id=2)

        assert a["weight"]["first"] == 70.0 and a["weight"]["last"] == 68.0
        assert b["weight"]["first"] == 90.0 and b["weight"]["last"] == 88.0


class TestPrEventsScoping:
    def test_scopes_by_user_id(self, session):
        # 历史最佳（周期前）与周期内突破，分属不同用户
        _workout(session, 1, date(2026, 7, 20), name="硬拉", weight=150)
        _workout(session, 1, date(2026, 8, 5), name="硬拉", weight=160)
        _workout(session, 2, date(2026, 7, 20), name="硬拉", weight=200)
        _workout(session, 2, date(2026, 8, 6), name="硬拉", weight=210)

        a = ai_mod.query_pr_events(session, START, END, user_id=1)
        b = ai_mod.query_pr_events(session, START, END, user_id=2)

        assert [e["movement"] for e in a] == ["硬拉"]
        assert a[0]["weight"] == 160.0 and a[0]["prev_best"] == 150.0
        assert b[0]["weight"] == 210.0 and b[0]["prev_best"] == 200.0


class TestNextPlanDayScoping:
    def test_scopes_by_user_id(self, session):
        _xunji_plan(session, 1, day_str="2026-08-20")
        _xunji_plan(session, 2, day_str="2026-08-21")

        a = ai_mod.query_next_plan_day(session, DAY, user_id=1)
        b = ai_mod.query_next_plan_day(session, DAY, user_id=2)

        assert a is not None and a["plan_ref"] == "plan1"
        assert b is not None and b["plan_ref"] == "plan2"


class TestPlanCompletionScoping:
    def test_scopes_by_user_id(self, session):
        _xunji_plan(session, 1, day_str="2026-08-05")
        _workout(session, 1, date(2026, 8, 5))  # 实际完成 user1 的计划日
        _workout(session, 2, date(2026, 8, 6))

        a = ai_mod.query_plan_completion(session, START, END, user_id=1)
        b = ai_mod.query_plan_completion(session, START, END, user_id=2)

        assert a["planned_days"] == 1 and a["completed_days"] == 1
        assert b["planned_days"] == 0  # 计划缓存按 user_id 过滤，user2 无计划


class TestPreviousReviewScoping:
    def test_scopes_by_user_id(self, session):
        _ai_report(session, 1, date(2026, 8, 3))
        _ai_report(session, 2, date(2026, 8, 3))

        a = ai_mod.query_previous_review(session, "weekly", DAY, user_id=1)
        b = ai_mod.query_previous_review(session, "weekly", DAY, user_id=2)

        assert a is not None and a["content_md"] == "old review"
        assert b is not None and b["content_md"] == "old review"
        assert a["period_start"] == "2026-08-03" and b["period_start"] == "2026-08-03"
