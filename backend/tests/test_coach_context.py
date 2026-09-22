"""AI 教练实时训练、计划和动作纪录上下文。"""
import json
from datetime import date, datetime, timedelta

from app.models import Workout, XunjiPlan
from app.services.coach_context import (
    build_realtime_context,
    detect_context_intent,
    query_movement_records,
    query_recent_workouts,
    query_upcoming_plan_context,
)

DAY = date(2026, 9, 22)


def _workout(session, day, title, movements, **kwargs):
    row = Workout(
        date=day,
        title=title,
        movements_json=json.dumps(movements, ensure_ascii=False),
        match_status="auto_matched",
        **kwargs,
    )
    session.add(row)
    session.commit()
    return row


def test_recent_workouts_include_today_and_exclude_deleted(session):
    _workout(session, DAY, "胸", [{"name": "杠铃卧推", "sets": [{"weight": 80, "reps": 5}]}])
    deleted = _workout(
        session,
        DAY - timedelta(days=1),
        "已删除",
        [{"name": "深蹲", "sets": [{"weight": 100, "reps": 5}]}],
    )
    deleted.deleted_at = datetime.now()
    session.commit()

    rows = query_recent_workouts(session, DAY)

    assert [row["title"] for row in rows] == ["胸"]
    assert rows[0]["movements"][0]["sets"][0]["weight"] == 80


def test_upcoming_plan_uses_cache_and_reports_fetched_at(session):
    plan = XunjiPlan(
        plan_ref="p1",
        plan_json=json.dumps({
            "plan": {"name": "增肌计划"},
            "days": [{
                "datestr": (DAY + timedelta(days=1)).isoformat(),
                "workout": {"name": "背部", "movements": [{"name": "杠铃划船", "target_sets": []}]},
            }],
        }, ensure_ascii=False),
        date_from=DAY,
        date_to=DAY + timedelta(days=7),
        fetched_at=datetime(2026, 9, 22, 23, 3),
    )
    session.add(plan)
    session.commit()

    result = query_upcoming_plan_context(session, DAY)

    assert result["cache_available"] is True
    assert result["days"][0]["movements"][0]["name"] == "杠铃划船"
    assert result["fetched_at"].startswith("2026-09-22T23:03")


def test_movement_records_use_all_history_and_fall_back_after_delete(session):
    _workout(session, DAY - timedelta(days=60), "旧训练", [
        {"name": "杠铃卧推", "sets": [{"weight": 100, "reps": 2}]},
    ])
    deleted = _workout(session, DAY - timedelta(days=2), "错误纪录", [
        {"name": "杠铃卧推", "sets": [{"weight": 120, "reps": 1}]},
    ])
    deleted.deleted_at = datetime.now()
    _workout(session, DAY - timedelta(days=1), "最近训练", [
        {"name": "杠铃卧推", "sets": [{"weight": 90, "reps": 5}]},
    ])
    session.commit()

    rows = query_movement_records(session, DAY, names=["杠铃卧推"])

    assert rows[0]["pr_weight"] == 100
    assert rows[0]["pr_reps"] == 2
    assert rows[0]["pr_date"] == (DAY - timedelta(days=60)).isoformat()
    assert rows[0]["latest"]["best_weight"] == 90


def test_self_weight_record_does_not_claim_zero_kg(session):
    _workout(session, DAY, "背", [
        {"name": "引体向上", "sets": [{"weight": 0, "reps": 12}]},
    ])

    rows = query_movement_records(session, DAY, names=["引体向上"])

    assert rows[0]["pr_weight"] is None
    assert rows[0]["pr_reps"] == 12


def test_build_context_selects_plan_and_named_pr(session):
    _workout(session, DAY - timedelta(days=1), "胸", [
        {"name": "杠铃卧推", "sets": [{"weight": 90, "reps": 3}]},
        {"name": "深蹲", "sets": [{"weight": 120, "reps": 3}]},
    ])
    text, refs = build_realtime_context(
        session, "我的杠铃卧推 PR 是多少，下次计划是什么？", anchor=DAY
    )

    assert "杠铃卧推" in text
    assert "深蹲：历史最佳" not in text
    assert "计划缓存为空" in text
    assert refs["movement_records"] == ["杠铃卧推"]


def test_intent_detection():
    assert detect_context_intent("我明天练什么")["plan"] is True
    assert detect_context_intent("下周怎么练")["plan"] is True
    assert detect_context_intent("我的所有动作 PR")["all_pr"] is True
    assert detect_context_intent("最近睡眠恢复怎么样")["recovery"] is True


def test_short_movement_name_matches_known_full_name(session):
    _workout(session, DAY, "胸", [
        {"name": "杠铃卧推", "sets": [{"weight": 80, "reps": 5}]},
        {"name": "哑铃卧推", "sets": [{"weight": 30, "reps": 10}]},
    ])

    _, refs = build_realtime_context(session, "我的卧推 PR 是多少？", anchor=DAY)

    assert set(refs["movement_records"]) == {"杠铃卧推", "哑铃卧推"}
