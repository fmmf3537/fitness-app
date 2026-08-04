"""M4 匹配引擎测试（严格按 PRD §5.1 伪代码语义）。

覆盖：完全重叠、59%/60%/61% 边界、起止差 29/31 分钟边界、一日两练、
单边记录两种、佳明力量单边入待确认、多次运行幂等。
"""
from datetime import date, datetime, time, timedelta

from tests.conftest import make_garmin_activity, make_xunji_train

from app.models import GarminActivity, MatchCandidate, Workout, XunjiTrain
from app.services.matcher import match_day, overlap_ratio

DAY = date(2026, 8, 3)


def dt(h, m=0, s=0):
    return datetime.combine(DAY, time(h, m, s))


# ---------- overlap_ratio 纯函数 ----------


def test_overlap_ratio_identical_intervals():
    assert overlap_ratio(dt(10), dt(11), dt(10), dt(11)) == 1.0


def test_overlap_ratio_disjoint():
    assert overlap_ratio(dt(9), dt(10), dt(10), dt(11)) == 0.0


def test_overlap_ratio_uses_shorter_interval():
    # a: 09:00-11:00（120min），b: 10:00-11:00（60min），重叠 60min / 较短 60min = 1.0
    assert overlap_ratio(dt(9), dt(11), dt(10), dt(11)) == 1.0


def test_overlap_ratio_partial():
    # 重叠 30min / 较短 60min = 0.5
    assert overlap_ratio(dt(9), dt(11), dt(10, 30), dt(11, 30)) == 0.5


def test_overlap_ratio_zero_duration():
    assert overlap_ratio(dt(10), dt(10), dt(10), dt(11)) == 0.0


# ---------- 第一轮：重叠率 ≥ 0.6 自动匹配 ----------


def test_full_overlap_auto_matched(session):
    x = make_xunji_train(session, DAY, localid="1", title="背二头2")
    g = make_garmin_activity(session, DAY, activity_id="g1")

    result = match_day(session, DAY)

    workouts = session.query(Workout).all()
    assert len(workouts) == 1
    w = workouts[0]
    assert w.match_status == "auto_matched"
    assert w.xunji_train_id == x.id
    assert w.garmin_activity_id == g.id
    assert session.query(MatchCandidate).count() == 0
    assert w in result["workouts"]


def test_overlap_61_percent_auto_matched(session):
    # x: 09:00-10:36:36，g: 10:00-11:00 → 重叠 2196s / 3600s = 0.61 ≥ 0.6
    make_xunji_train(session, DAY, localid="1", start=time(9, 0), end=time(10, 36, 36))
    make_garmin_activity(session, DAY, activity_id="g1")

    match_day(session, DAY)

    w = session.query(Workout).one()
    assert w.match_status == "auto_matched"
    assert session.query(MatchCandidate).count() == 0


def test_overlap_exactly_60_percent_auto_matched(session):
    # 边界：恰好 0.6（2160s / 3600s）→ ≥ 0.6 自动匹配
    make_xunji_train(session, DAY, localid="1", start=time(9, 0), end=time(10, 36))
    make_garmin_activity(session, DAY, activity_id="g1")

    match_day(session, DAY)

    assert session.query(Workout).one().match_status == "auto_matched"


def test_overlap_59_percent_not_auto_matched(session):
    # x: 09:00-10:35:24，g: 10:00-11:00 → 重叠 2124s / 3600s = 0.59 < 0.6
    # 起止差：end 差 24.6min ≤ 30 → 第二轮入待确认队列
    x = make_xunji_train(session, DAY, localid="1", start=time(9, 0), end=time(10, 35, 24))
    g = make_garmin_activity(session, DAY, activity_id="g1")

    match_day(session, DAY)

    assert session.query(Workout).filter_by(match_status="auto_matched").count() == 0
    c = session.query(MatchCandidate).one()
    assert c.status == "pending"
    assert c.reason == "time_close"
    assert c.xunji_train_id == x.id
    assert c.garmin_activity_id == g.id


# ---------- 第二轮：起止差 ≤ 30min 入待确认 ----------


def test_start_diff_29min_goes_pending(session):
    # x: 10:00-11:00，g: 10:29-12:00 → 重叠 31min/60min = 0.517 < 0.6；起差 29min ≤ 30
    x = make_xunji_train(session, DAY, localid="1")
    g = make_garmin_activity(session, DAY, activity_id="g1",
                             start=time(10, 29), end=time(12, 0))

    match_day(session, DAY)

    c = session.query(MatchCandidate).one()
    assert c.reason == "time_close"
    assert c.status == "pending"
    # 两侧记录从待配池移除：不产出 xunji_only / garmin_only workout
    assert session.query(Workout).count() == 0


def test_start_diff_31min_stays_unmatched(session):
    # x: 10:00-11:00，g: 10:31-11:31 → 重叠 29min/60min = 0.483 < 0.6；起差/止差均 31min > 30
    x = make_xunji_train(session, DAY, localid="1")
    g = make_garmin_activity(session, DAY, activity_id="g1", activity_type="running",
                             start=time(10, 31), end=time(11, 31))

    match_day(session, DAY)

    assert session.query(MatchCandidate).count() == 0
    w_x = session.query(Workout).filter_by(match_status="xunji_only").one()
    w_g = session.query(Workout).filter_by(match_status="garmin_only").one()
    assert w_x.xunji_train_id == x.id and w_x.garmin_activity_id is None
    assert w_g.garmin_activity_id == g.id and w_g.xunji_train_id is None


# ---------- 一日两练互不串扰 ----------


def test_two_sessions_same_day_matched_independently(session):
    # 早晨有氧：x1 07:00-08:00 ↔ g1 07:05-08:00（重叠 55min/55min = 1.0）
    x1 = make_xunji_train(session, DAY, localid="1", title="晨跑",
                          start=time(7, 0), end=time(8, 0))
    g1 = make_garmin_activity(session, DAY, activity_id="g1", activity_type="running",
                              name="晨跑", start=time(7, 5), end=time(8, 0))
    # 晚间力量：x2 19:00-20:00 ↔ g2 19:00-20:00（完全重叠）
    x2 = make_xunji_train(session, DAY, localid="2", title="背二头2",
                          start=time(19, 0), end=time(20, 0))
    g2 = make_garmin_activity(session, DAY, activity_id="g2", activity_type="strength_training",
                              name="力量训练", start=time(19, 0), end=time(20, 0))

    match_day(session, DAY)

    workouts = session.query(Workout).filter_by(match_status="auto_matched").all()
    assert len(workouts) == 2
    by_xunji = {w.xunji_train_id: w for w in workouts}
    assert by_xunji[x1.id].garmin_activity_id == g1.id
    assert by_xunji[x2.id].garmin_activity_id == g2.id
    assert session.query(MatchCandidate).count() == 0


# ---------- 单边记录 ----------


def test_xunji_only(session):
    x = make_xunji_train(session, DAY, localid="1", title="背二头2")

    match_day(session, DAY)

    w = session.query(Workout).one()
    assert w.match_status == "xunji_only"
    assert w.xunji_train_id == x.id
    assert w.garmin_activity_id is None
    assert session.query(MatchCandidate).count() == 0


def test_garmin_only_non_strength_no_candidate(session):
    g = make_garmin_activity(session, DAY, activity_id="g1", activity_type="running")

    match_day(session, DAY)

    w = session.query(Workout).one()
    assert w.match_status == "garmin_only"
    assert w.garmin_activity_id == g.id
    # 非力量类型不入待确认队列
    assert session.query(MatchCandidate).count() == 0


def test_garmin_only_strength_creates_draft_candidate(session):
    g = make_garmin_activity(session, DAY, activity_id="g1", activity_type="strength_training")

    match_day(session, DAY)

    w = session.query(Workout).one()
    assert w.match_status == "garmin_only"
    c = session.query(MatchCandidate).one()
    assert c.reason == "garmin_only_strength"
    assert c.status == "pending"
    assert c.garmin_activity_id == g.id
    assert c.workout_id == w.id
    assert c.xunji_train_id is None


# ---------- 幂等 ----------


def test_rerun_is_idempotent(session):
    make_xunji_train(session, DAY, localid="1", title="背二头2",
                     start=time(19, 0), end=time(20, 0))
    make_garmin_activity(session, DAY, activity_id="g1",
                         start=time(19, 0), end=time(20, 0))
    make_xunji_train(session, DAY, localid="2", title="有氧",
                     start=time(7, 0), end=time(8, 0))
    make_garmin_activity(session, DAY, activity_id="g2", activity_type="strength_training",
                         start=time(12, 0), end=time(13, 0))

    match_day(session, DAY)
    w1 = session.query(Workout).count()
    c1 = session.query(MatchCandidate).count()

    match_day(session, DAY)
    match_day(session, DAY)

    assert session.query(Workout).count() == w1 == 3
    assert session.query(MatchCandidate).count() == c1 == 1


def test_empty_day_no_workouts(session):
    result = match_day(session, DAY)
    assert result["workouts"] == []
    assert result["candidates"] == []
    assert session.query(Workout).count() == 0


def test_other_day_records_not_touched(session):
    other = date(2026, 8, 2)
    make_xunji_train(session, other, localid="9", title="昨日训练")

    match_day(session, DAY)

    assert session.query(Workout).count() == 0


# ---------- 缺时间字段的退化记录 ----------


def test_train_without_interval_goes_xunji_only(session):
    """训记记录缺 start/end：不参与两轮匹配，直接 xunji_only 入库。"""
    x = make_xunji_train(session, DAY, localid="1", title="无时间训练")
    x.start_ms = None
    x.end_ms = None
    session.commit()
    make_garmin_activity(session, DAY, activity_id="g1")

    match_day(session, DAY)

    w_x = session.query(Workout).filter_by(match_status="xunji_only").one()
    assert w_x.xunji_train_id == x.id
    # 佳明活动不受影响，正常 garmin_only
    assert session.query(Workout).filter_by(match_status="garmin_only").count() == 1
    assert session.query(MatchCandidate).count() == 1  # strength_training 单边候选


def test_activity_without_interval_goes_garmin_only(session):
    """佳明活动缺 end（无法构成时间区间）：不参与两轮匹配，直接 garmin_only 入库。"""
    g = make_garmin_activity(session, DAY, activity_id="g1", activity_type="running")
    g.end_ts = None
    session.commit()
    x = make_xunji_train(session, DAY, localid="1", title="背二头2")

    match_day(session, DAY)

    w_g = session.query(Workout).filter_by(match_status="garmin_only").one()
    assert w_g.garmin_activity_id == g.id
    assert session.query(Workout).filter_by(match_status="xunji_only").one().xunji_train_id == x.id
    assert session.query(MatchCandidate).count() == 0  # running 非力量，不入队
