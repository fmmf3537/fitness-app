"""M4 匹配引擎测试（严格按 PRD §5.1 伪代码语义）。

覆盖：完全重叠、59%/60%/61% 边界、起止差 29/31 分钟边界、一日两练、
单边记录两种、佳明力量单边入待确认、多次运行幂等。
"""
import json
from datetime import date, datetime, time, timedelta

from tests.conftest import make_garmin_activity, make_xunji_train

from app.models import AIReport, GarminActivity, MatchCandidate, Workout, XunjiPlan, XunjiTrain
from app.services.matcher import _xunji_interval, match_day, overlap_ratio

DAY = date(2026, 8, 3)


def test_xunji_interval_timezone_independent():
    """训记 start_ms 是 epoch 毫秒，佳明侧存 startTimeLocal（北京墙钟）；
    匹配引擎必须按固定 +08:00 渲染训记时间，与服务器本地时区无关
    （CI 2026-08-10 踩坑：UTC  runner 上 fromtimestamp 渲染偏移 8h 导致匹配全乱）。"""
    ms = 1785730647855  # 真实数据：2026-08-03 12:17:27 北京时间
    train = XunjiTrain(datestr="2026-08-03", localid="t0", title="t",
                       start_ms=ms, end_ms=ms + 3600_000)
    start, end = _xunji_interval(train)
    expected = datetime(2026, 8, 3, 12, 17, 27, 855000)  # utcfromtimestamp + 8h
    assert start == expected
    assert end - start == timedelta(hours=1)


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

    result = match_day(session, DAY, user_id=1)

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

    match_day(session, DAY, user_id=1)

    w = session.query(Workout).one()
    assert w.match_status == "auto_matched"
    assert session.query(MatchCandidate).count() == 0


def test_overlap_exactly_60_percent_auto_matched(session):
    # 边界：恰好 0.6（2160s / 3600s）→ ≥ 0.6 自动匹配
    make_xunji_train(session, DAY, localid="1", start=time(9, 0), end=time(10, 36))
    make_garmin_activity(session, DAY, activity_id="g1")

    match_day(session, DAY, user_id=1)

    assert session.query(Workout).one().match_status == "auto_matched"


def test_overlap_59_percent_not_auto_matched(session):
    # x: 09:00-10:35:24，g: 10:00-11:00 → 重叠 2124s / 3600s = 0.59 < 0.6
    # 起止差：end 差 24.6min ≤ 30 → 第二轮入待确认队列
    x = make_xunji_train(session, DAY, localid="1", start=time(9, 0), end=time(10, 35, 24))
    g = make_garmin_activity(session, DAY, activity_id="g1")

    match_day(session, DAY, user_id=1)

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

    match_day(session, DAY, user_id=1)

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

    match_day(session, DAY, user_id=1)

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

    match_day(session, DAY, user_id=1)

    workouts = session.query(Workout).filter_by(match_status="auto_matched").all()
    assert len(workouts) == 2
    by_xunji = {w.xunji_train_id: w for w in workouts}
    assert by_xunji[x1.id].garmin_activity_id == g1.id
    assert by_xunji[x2.id].garmin_activity_id == g2.id
    assert session.query(MatchCandidate).count() == 0


# ---------- 单边记录 ----------


def test_xunji_only(session):
    x = make_xunji_train(session, DAY, localid="1", title="背二头2")

    match_day(session, DAY, user_id=1)

    w = session.query(Workout).one()
    assert w.match_status == "xunji_only"
    assert w.xunji_train_id == x.id
    assert w.garmin_activity_id is None
    assert session.query(MatchCandidate).count() == 0


def test_garmin_only_non_strength_no_candidate(session):
    g = make_garmin_activity(session, DAY, activity_id="g1", activity_type="running")

    match_day(session, DAY, user_id=1)

    w = session.query(Workout).one()
    assert w.match_status == "garmin_only"
    assert w.garmin_activity_id == g.id
    # 非力量类型不入待确认队列
    assert session.query(MatchCandidate).count() == 0


def test_garmin_only_strength_creates_draft_candidate(session):
    g = make_garmin_activity(session, DAY, activity_id="g1", activity_type="strength_training")

    match_day(session, DAY, user_id=1)

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

    match_day(session, DAY, user_id=1)
    w1 = session.query(Workout).count()
    c1 = session.query(MatchCandidate).count()

    match_day(session, DAY, user_id=1)
    match_day(session, DAY, user_id=1)

    assert session.query(Workout).count() == w1 == 3
    assert session.query(MatchCandidate).count() == c1 == 1


def test_empty_day_no_workouts(session):
    result = match_day(session, DAY, user_id=1)
    assert result["workouts"] == []
    assert result["candidates"] == []
    assert session.query(Workout).count() == 0


def test_other_day_records_not_touched(session):
    other = date(2026, 8, 2)
    make_xunji_train(session, other, localid="9", title="昨日训练")

    match_day(session, DAY, user_id=1)

    assert session.query(Workout).count() == 0


# ---------- 缺时间字段的退化记录 ----------


def test_train_without_interval_goes_xunji_only(session):
    """训记记录缺 start/end：不参与两轮匹配，直接 xunji_only 入库。"""
    x = make_xunji_train(session, DAY, localid="1", title="无时间训练")
    x.start_ms = None
    x.end_ms = None
    session.commit()
    make_garmin_activity(session, DAY, activity_id="g1")

    match_day(session, DAY, user_id=1)

    w_x = session.query(Workout).filter_by(match_status="xunji_only").one()
    assert w_x.xunji_train_id == x.id
    # 佳明活动不受影响，正常 garmin_only
    assert session.query(Workout).filter_by(match_status="garmin_only").count() == 1
    assert session.query(MatchCandidate).count() == 1  # strength_training 单边候选


# ---------- V2-7b 重融合就地更新（缺陷3） ----------

ADVICE_DAY = DAY + timedelta(days=2)

_REGEN_CONTENT = (
    "## 新点评\n基于最新融合数据。\n\n```json\n"
    + json.dumps({
        "schema": "next_advice_v1",
        "next_plan_date": ADVICE_DAY.isoformat(),
        "suggestions": [{"movement": "杠铃划船", "category": "manual",
                         "original": {"weight": 60}, "suggested": {"weight": 62.5},
                         "reason": "渐进超负荷"}],
    }, ensure_ascii=False) + "\n```\n"
)


def _make_plan_for_advice(session):
    row = XunjiPlan(
        plan_ref="platform:155",
        plan_json=json.dumps(
            {"plan": {"plan_ref": "platform:155", "name": "增肌计划"},
             "days": [{"date": ADVICE_DAY.isoformat(),
                       "movements": [{"name": "杠铃划船"}]}]},
            ensure_ascii=False,
        ),
        date_from=DAY - timedelta(days=7),
        date_to=DAY + timedelta(days=30),
    )
    session.add(row)
    session.commit()
    return row


def _regen_chat(messages):
    return {"content": _REGEN_CONTENT, "prompt_tokens": 10, "completion_tokens": 5}


def test_stale_train_inplace_refuse_and_ai_regen(session):
    """缺陷3：force_refresh 补齐组数后重跑 match_day，须就地刷新 movements_json
    （不新建 workout 行、不动匹配关系），并删除当日旧 AI 报告后重生成。"""
    movements_v1 = [{"name": "杠铃划船",
                     "sets": [{"weight": 60, "unit": "kg", "reps": 10, "done": True}]}]
    x = make_xunji_train(session, DAY, localid="1", title="背部训练", movements=movements_v1)
    make_garmin_activity(session, DAY, activity_id="g1")
    match_day(session, DAY, user_id=1)
    w = session.query(Workout).one()
    wid = w.id

    # 当日已有 AI 报告（基于旧数据）
    session.add_all([
        AIReport(type="session_review", workout_id=wid, period_start=DAY, period_end=DAY,
                 model="m", content_md="旧点评"),
        AIReport(type="next_advice", workout_id=wid, period_start=DAY, period_end=ADVICE_DAY,
                 model="m", content_md="旧建议"),
    ])
    session.commit()

    # 训记原始记录补录一组，fetched_at 晚于 workout.updated_at
    movements_v2 = [{"name": "杠铃划船", "sets": [
        {"weight": 60, "unit": "kg", "reps": 10, "done": True},
        {"weight": 60, "unit": "kg", "reps": 8, "done": True}]}]
    raw = json.loads(x.raw_json)
    raw["movements"] = movements_v2
    x.raw_json = json.dumps(raw, ensure_ascii=False)
    # 训记重新拉取时间明显晚于 workout.updated_at（onupdate 会在提交时把
    # updated_at 刷成当前时刻，故 fetched_at 需充分靠后以保证 > updated_at）
    x.fetched_at = datetime.now() + timedelta(days=1)
    w.updated_at = datetime.now() - timedelta(hours=1)
    session.commit()
    _make_plan_for_advice(session)

    result = match_day(session, DAY, user_id=1, chat_fn=_regen_chat)

    # 不新建行、匹配关系不变、movements_json 刷新
    assert session.query(Workout).count() == 1
    w2 = session.query(Workout).one()
    assert w2.id == wid
    assert w2.match_status == "auto_matched"
    assert w2.xunji_train_id == x.id
    assert w2.garmin_activity_id is not None
    assert json.loads(w2.movements_json) == movements_v2
    assert result["refreshed"] == [wid]

    # 旧报告删除、新报告落库
    reviews = session.query(AIReport).filter_by(workout_id=wid, type="session_review").all()
    assert len(reviews) == 1
    assert reviews[0].content_md != "旧点评"
    advices = session.query(AIReport).filter_by(workout_id=wid, type="next_advice").all()
    assert len(advices) == 1
    assert advices[0].content_md != "旧建议"


def test_fresh_train_no_refuse_no_ai_regen(session):
    """训记记录不比 workout 新（fetched_at <= updated_at）时不触发重融合，
    旧报告保留，且不调用模型。"""
    movements = [{"name": "杠铃划船",
                  "sets": [{"weight": 60, "unit": "kg", "reps": 10, "done": True}]}]
    make_xunji_train(session, DAY, localid="1", title="背部训练", movements=movements)
    make_garmin_activity(session, DAY, activity_id="g1")
    match_day(session, DAY, user_id=1)
    w = session.query(Workout).one()
    old_movements = w.movements_json
    session.add(AIReport(type="session_review", workout_id=w.id, period_start=DAY,
                         period_end=DAY, model="m", content_md="旧点评"))
    session.commit()

    def forbidden_chat(messages):
        raise AssertionError("数据未变新，不应调用模型")

    result = match_day(session, DAY, chat_fn=forbidden_chat)

    assert result["refreshed"] == []
    assert session.query(Workout).one().movements_json == old_movements
    assert session.query(AIReport).one().content_md == "旧点评"


def test_activity_without_interval_goes_garmin_only(session):
    """佳明活动缺 end（无法构成时间区间）：不参与两轮匹配，直接 garmin_only 入库。"""
    g = make_garmin_activity(session, DAY, activity_id="g1", activity_type="running")
    g.end_ts = None
    session.commit()
    x = make_xunji_train(session, DAY, localid="1", title="背二头2")

    match_day(session, DAY, user_id=1)

    w_g = session.query(Workout).filter_by(match_status="garmin_only").one()
    assert w_g.garmin_activity_id == g.id
    assert session.query(Workout).filter_by(match_status="xunji_only").one().xunji_train_id == x.id
    assert session.query(MatchCandidate).count() == 0  # running 非力量，不入队
