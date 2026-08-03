"""PRD §4 全部表的插入/查询测试 + 全部 UNIQUE 约束触发 IntegrityError 用例。"""
from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    AIReport,
    BodyMetric,
    GarminActivity,
    GarminDaily,
    JobRun,
    LLMCall,
    MatchCandidate,
    Setting,
    Workout,
    XunjiPlan,
    XunjiTrain,
)


def _xunji_train(**kw):
    defaults = dict(
        datestr="2026-08-03",
        localid="abc123",
        title="胸推日",
        start_ms=1754208000000,
        end_ms=1754211600000,
        note_json="{}",
        raw_json="{}",
    )
    defaults.update(kw)
    return XunjiTrain(**defaults)


def _garmin_activity(**kw):
    defaults = dict(
        activity_id="1001",
        activity_type="strength_training",
        name="力量训练",
        start_ts=datetime(2026, 8, 3, 8, 0),
        end_ts=datetime(2026, 8, 3, 9, 0),
        duration_s=3600,
        calories=320,
        avg_hr=120,
        max_hr=155,
        raw_json="{}",
    )
    defaults.update(kw)
    return GarminActivity(**defaults)


def test_settings_insert_query(session):
    row = Setting(garmin_token_store="tok", xunji_api_key_enc="enc",
                  default_llm="kimi", llm_keys_json_enc="{}")
    session.add(row)
    session.commit()
    got = session.query(Setting).one()
    assert got.default_llm == "kimi"
    assert got.created_at is not None


def test_xunji_train_insert_query(session):
    session.add(_xunji_train())
    session.commit()
    got = session.query(XunjiTrain).filter_by(datestr="2026-08-03").one()
    assert got.localid == "abc123"
    assert got.fetched_at is not None


def test_xunji_train_unique_datestr_localid(session):
    session.add(_xunji_train())
    session.commit()
    session.add(_xunji_train(title="重复记录"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_garmin_activity_insert_query(session):
    session.add(_garmin_activity())
    session.commit()
    got = session.query(GarminActivity).one()
    assert got.avg_hr == 120


def test_garmin_activity_unique_activity_id(session):
    session.add(_garmin_activity())
    session.commit()
    session.add(_garmin_activity(name="重复活动"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_garmin_daily_insert_query(session):
    session.add(GarminDaily(date=date(2026, 8, 3), steps=8000, resting_hr=55,
                            stress_avg=30, body_battery_high=90, body_battery_low=20,
                            hrv_status="balanced", sleep_json="{}", raw_json="{}"))
    session.commit()
    got = session.query(GarminDaily).one()
    assert got.resting_hr == 55


def test_garmin_daily_unique_date(session):
    session.add(GarminDaily(date=date(2026, 8, 3)))
    session.commit()
    session.add(GarminDaily(date=date(2026, 8, 3), steps=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_body_metric_insert_query(session):
    session.add(BodyMetric(date=date(2026, 8, 3), type="weight", value=72.4,
                           unit="kg", synced_to_xunji=False, note="晨起空腹"))
    session.commit()
    got = session.query(BodyMetric).one()
    assert got.value == 72.4
    assert got.synced_to_xunji is False
    assert got.updated_at is not None


def test_body_metric_unique_date_type(session):
    session.add(BodyMetric(date=date(2026, 8, 3), type="weight", value=72.4, unit="kg"))
    session.commit()
    session.add(BodyMetric(date=date(2026, 8, 3), type="weight", value=73.0, unit="kg"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_body_metric_same_date_different_type_ok(session):
    session.add(BodyMetric(date=date(2026, 8, 3), type="weight", value=72.4, unit="kg"))
    session.add(BodyMetric(date=date(2026, 8, 3), type="blood_glucose", value=5.2, unit="mmol/L"))
    session.commit()
    assert session.query(BodyMetric).count() == 2


def test_workout_insert_with_fks(session):
    x = _xunji_train()
    g = _garmin_activity()
    session.add_all([x, g])
    session.commit()
    w = Workout(date=date(2026, 8, 3), title="胸推日",
                xunji_train_id=x.id, garmin_activity_id=g.id,
                match_status="auto_matched", duration_s=3600, calories=320,
                avg_hr=120, max_hr=155, movements_json="[]")
    session.add(w)
    session.commit()
    got = session.query(Workout).one()
    assert got.xunji_train_id == x.id
    assert got.garmin_activity_id == g.id
    assert got.match_status == "auto_matched"


def test_workout_allows_single_side_null(session):
    w = Workout(date=date(2026, 8, 3), title="仅训记", match_status="xunji_only")
    session.add(w)
    session.commit()
    assert session.query(Workout).one().garmin_activity_id is None


def test_match_candidate_insert_query(session):
    x = _xunji_train()
    g = _garmin_activity()
    session.add_all([x, g])
    session.commit()
    mc = MatchCandidate(xunji_train_id=x.id, garmin_activity_id=g.id,
                        reason="time_close", status="pending")
    session.add(mc)
    session.commit()
    got = session.query(MatchCandidate).one()
    assert got.reason == "time_close"
    assert got.resolved_at is None


def test_xunji_plan_insert_query(session):
    session.add(XunjiPlan(plan_ref="platform:155", plan_json="{}",
                          date_from=date(2026, 8, 1), date_to=date(2026, 8, 31)))
    session.commit()
    got = session.query(XunjiPlan).one()
    assert got.plan_ref == "platform:155"


def test_ai_report_insert_with_workout_fk(session):
    w = Workout(date=date(2026, 8, 3), title="胸推日", match_status="xunji_only")
    session.add(w)
    session.commit()
    session.add(AIReport(type="session_review", workout_id=w.id,
                         period_start=date(2026, 8, 3), period_end=date(2026, 8, 3),
                         model="kimi-k2-0905-preview", prompt_tokens=1000,
                         completion_tokens=300, cost_estimate=0.012,
                         content_md="# 点评"))
    session.commit()
    got = session.query(AIReport).one()
    assert got.workout_id == w.id
    assert got.type == "session_review"


def test_ai_report_workout_fk_nullable(session):
    session.add(AIReport(type="weekly", model="kimi", content_md="# 周复盘"))
    session.commit()
    assert session.query(AIReport).one().workout_id is None


def test_llm_call_insert_query(session):
    session.add(LLMCall(provider="kimi", model="kimi-k2-0905-preview",
                        purpose="session_review", prompt_tokens=1000,
                        completion_tokens=300, cost_estimate=0.012, status="ok"))
    session.commit()
    got = session.query(LLMCall).one()
    assert got.provider == "kimi"


def test_job_run_insert_query(session):
    session.add(JobRun(job_name="daily_sync", started_at=datetime(2026, 8, 3, 22, 47),
                       finished_at=datetime(2026, 8, 3, 22, 48), status="ok",
                       error=None, detail_json="{}"))
    session.commit()
    got = session.query(JobRun).one()
    assert got.job_name == "daily_sync"
