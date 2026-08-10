"""M4 验收方独立边界测试（由需求方编写，非开发方测试）。"""
from datetime import date, datetime, timedelta, timezone

# 与 matcher.XUNJI_TZ 对齐：epoch 毫秒按固定 +08:00 编码/渲染，与本地时区无关
BJ = timezone(timedelta(hours=8))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import GarminActivity, MatchCandidate, Workout, XunjiTrain
from app.services.matcher import match_day

DAY = date(2026, 8, 3)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def add_xunji(s, start: datetime, minutes: int, title="力量训练"):
    t = XunjiTrain(
        datestr=DAY.isoformat(), localid=abs(hash((start, minutes))) % 10**12,
        title=title,
        start_ms=int(start.replace(tzinfo=BJ).timestamp() * 1000),
        end_ms=int((start + timedelta(minutes=minutes)).replace(tzinfo=BJ).timestamp() * 1000),
        note_json="{}", raw_json="{}",
    )
    s.add(t)
    s.commit()
    return t


def add_garmin(s, start: datetime, minutes: int, atype="strength_training"):
    g = GarminActivity(
        activity_id=abs(hash((start, minutes, atype))) % 10**12,
        activity_type=atype, name="活动",
        start_ts=start, end_ts=start + timedelta(minutes=minutes),
        duration_s=minutes * 60, calories=300, avg_hr=120, max_hr=150, raw_json="{}",
    )
    s.add(g)
    s.commit()
    return g


def statuses(s):
    return [w.match_status for w in s.query(Workout).all()]


def test_boundary_59pct_no_auto_but_pending(session):
    """重叠 58.3%（<60%）：不自动匹配，但起止差 25min ≤30 → 入待确认。"""
    add_xunji(session, datetime(2026, 8, 3, 10, 0), 60)
    add_garmin(session, datetime(2026, 8, 3, 10, 25), 60)  # overlap 35/60 = 58.3%
    r = match_day(session, DAY)
    assert statuses(session) == []  # 无 workout
    assert len(r["candidates"]) == 1 and r["candidates"][0].reason == "time_close"


def test_boundary_60pct_exact_auto(session):
    """重叠恰好 60%：自动匹配（>= 判定）。"""
    add_xunji(session, datetime(2026, 8, 3, 10, 0), 60)
    add_garmin(session, datetime(2026, 8, 3, 10, 24), 60)  # overlap 36/60 = 60.0%
    match_day(session, DAY)
    assert statuses(session) == ["auto_matched"]


def test_boundary_31min_diff_no_candidate(session):
    """起止差 31min（>30）且无重叠：两边都单边，不入待确认（佳明侧用非力量类型）。"""
    add_xunji(session, datetime(2026, 8, 3, 10, 0), 60)
    add_garmin(session, datetime(2026, 8, 3, 11, 31), 60, atype="running")
    r = match_day(session, DAY)
    assert sorted(statuses(session)) == ["garmin_only", "xunji_only"]
    assert r["candidates"] == []


def test_garmin_only_strength_creates_draft_candidate(session):
    """佳明单边且为力量类型：garmin_only + reason=garmin_only_strength 待确认（PRD §5.1）。"""
    add_garmin(session, datetime(2026, 8, 3, 11, 31), 60, atype="strength_training")
    r = match_day(session, DAY)
    assert statuses(session) == ["garmin_only"]
    assert len(r["candidates"]) == 1
    assert r["candidates"][0].reason == "garmin_only_strength"


def test_one_day_two_sessions_no_cross_talk(session):
    """早有氧（仅佳明）+ 晚力量（双侧）：各归各位，互不串扰。"""
    add_garmin(session, datetime(2026, 8, 3, 7, 0), 45, atype="running")
    add_xunji(session, datetime(2026, 8, 3, 18, 0), 60)
    add_garmin(session, datetime(2026, 8, 3, 18, 5), 65, atype="strength_training")
    match_day(session, DAY)
    assert sorted(statuses(session)) == ["auto_matched", "garmin_only"]


def test_real_20260803_timestamps_auto_match(session):
    """真实数据：训记 start=1785730647855/end=1785733522740 vs 佳明 12:18:51 起 ~48min。"""
    x = XunjiTrain(datestr="2026-08-03", localid=1785730645738, title="背·二头·2",
                   start_ms=1785730647855, end_ms=1785733522740, note_json="{}", raw_json="{}")
    session.add(x)
    g = GarminActivity(activity_id=999001, activity_type="strength_training", name="力量训练",
                       start_ts=datetime(2026, 8, 3, 12, 18, 51),
                       end_ts=datetime(2026, 8, 3, 13, 6, 51),
                       duration_s=2880, calories=186, avg_hr=110, max_hr=140, raw_json="{}")
    session.add(g)
    session.commit()
    match_day(session, DAY)
    assert statuses(session) == ["auto_matched"]


def test_rerun_three_times_idempotent(session):
    """连跑三次：workout 与 candidate 不增殖。"""
    add_xunji(session, datetime(2026, 8, 3, 10, 0), 60)
    add_garmin(session, datetime(2026, 8, 3, 10, 10), 60)
    add_xunji(session, datetime(2026, 8, 3, 20, 0), 45)
    add_garmin(session, datetime(2026, 8, 3, 20, 20), 45)  # 起止差20min且重叠<60% → pending
    for _ in range(3):
        match_day(session, DAY)
    assert session.query(Workout).count() == 1
    assert session.query(MatchCandidate).count() == 1
