"""V1-2 历史数据导入 backfill 服务测试（TDD）。

- 适配器全部用 Fake 桩替代，禁止真实外呼；
- 时钟/睡眠注入假实现，验证 15s 限频计时而不真实等待；
- 覆盖：3 年稀疏数据、断点续传、空日跳过、单日容错、完成后自动融合、进度计算。
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import pytest

from app.models import BackfillProgress, GarminActivity, GarminDaily, Workout, XunjiTrain
from app.services.backfill import (
    GARMIN_PAGE_SIZE,
    XUNJI_DAY_INTERVAL_S,
    BackfillRunner,
    BackfillState,
    compute_status,
)

TODAY = date(2026, 8, 6)
START = date(2023, 2, 1)


class SleepRecorder:
    """注入用假睡眠：记录每次睡眠秒数，不真实等待。"""

    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class FakeXunji:
    """训记适配器桩：train_days 有训练，fail_days 抛错，其余返回空。"""

    def __init__(self, session, train_days: set[str] | None = None, fail_days: set[str] | None = None):
        self._session = session
        self.train_days = train_days or set()
        self.fail_days = fail_days or set()
        self.calls: list[str] = []

    def fetch_trains(self, datestr, include_full_data=False, *, force_refresh=False):
        self.calls.append(datestr)
        if datestr in self.fail_days:
            raise RuntimeError("network boom")
        if datestr in self.train_days:
            day = date.fromisoformat(datestr)
            start_ms = int(datetime.combine(day, time(10, 0)).timestamp() * 1000)
            end_ms = int(datetime.combine(day, time(11, 0)).timestamp() * 1000)
            row = XunjiTrain(
                datestr=datestr, localid="1", title="力量训练",
                start_ms=start_ms, end_ms=end_ms,
                raw_json=json.dumps({"localid": "1", "title": "力量训练",
                                     "start": start_ms, "end": end_ms}),
            )
            self._session.add(row)
            self._session.commit()
            return [row]
        return []


class FakeGarmin:
    """佳明适配器桩：activities 全量列表分页返回；daily 按日落库。"""

    def __init__(self, session, activities: list[dict] | None = None,
                 fail_days: set[str] | None = None, activities_error: Exception | None = None):
        self._session = session
        self.activities = activities or []
        self.fail_days = fail_days or set()
        self.activities_error = activities_error
        self.sync_all_calls: list[dict] = []
        self.daily_calls: list[str] = []

    def sync_all_activities(self, *, page_size, start_offset=0, skip_ids=None, on_page=None):
        self.sync_all_calls.append({
            "page_size": page_size, "start_offset": start_offset, "skip_ids": set(skip_ids or []),
        })
        if self.activities_error:
            raise self.activities_error
        skip_ids = skip_ids or set()
        start = start_offset
        total = 0
        while start < len(self.activities) or start == start_offset:
            page = self.activities[start:start + page_size]
            for act in page:
                activity_id = str(act["activityId"])
                if activity_id in skip_ids:
                    continue
                row = GarminActivity(
                    activity_id=activity_id,
                    activity_type=act.get("activityType", {}).get("typeKey"),
                    name=act.get("activityName"),
                    start_ts=datetime.fromisoformat(act["startTimeLocal"]),
                    end_ts=datetime.fromisoformat(act["startTimeLocal"]) + timedelta(seconds=act.get("duration", 3600)),
                    duration_s=int(act.get("duration", 3600)),
                )
                self._session.add(row)
                total += 1
            self._session.commit()
            if on_page:
                on_page(start, len(page))
            if len(page) < page_size:
                break
            start += page_size
        return total

    def sync_daily(self, datestr):
        self.daily_calls.append(datestr)
        if datestr in self.fail_days:
            raise RuntimeError("garmin boom")
        day = date.fromisoformat(datestr)
        row = self._session.query(GarminDaily).filter_by(date=day).first()
        if row is None:
            row = GarminDaily(date=day)
            self._session.add(row)
        row.steps = 1000
        self._session.commit()
        return row


def make_activity(activity_id: int, day: date, start: time = time(10, 0)) -> dict:
    return {
        "activityId": activity_id,
        "activityName": "力量训练",
        "activityType": {"typeKey": "strength_training"},
        "startTimeLocal": datetime.combine(day, start).strftime("%Y-%m-%d %H:%M:%S"),
        "duration": 3600.0,
    }


def progress_rows(session, source) -> dict[str, str]:
    rows = session.query(BackfillProgress).filter_by(source=source).all()
    return {r.date: r.status for r in rows}


def make_runner(session, xunji, garmin, *, start=START, today=TODAY, sleep=None, state=None):
    return BackfillRunner(
        session, xunji, garmin,
        start_date=start, today=today,
        sleep=sleep or SleepRecorder(),
        state=state or BackfillState(),
    )


# ---------- 训记逐日回溯 ----------

def test_xunji_backfill_three_years_sparse_data(session):
    """3 年稀疏数据：空日记 empty、训练日记 done，全部进 backfill_progress。"""
    train_days = {(START + timedelta(days=30 * i)).isoformat() for i in range(0, 42)}
    xunji = FakeXunji(session, train_days=train_days)
    garmin = FakeGarmin(session)
    runner = make_runner(session, xunji, garmin)
    runner.run()

    rows = progress_rows(session, "xunji")
    total_days = (TODAY - START).days + 1
    assert len(rows) == total_days
    for ds, status in rows.items():
        assert status == ("done" if ds in train_days else "empty")
    assert session.query(XunjiTrain).count() == len(train_days)
    # 每天都只拉一次
    assert len(xunji.calls) == total_days


def test_xunji_empty_days_skipped_on_rerun(session):
    """断点续传：已完成（含空日）的日期重启后不再重拉。"""
    xunji = FakeXunji(session)
    garmin = FakeGarmin(session)
    make_runner(session, xunji, garmin, start=date(2026, 8, 1)).run()
    first_calls = list(xunji.calls)
    assert len(first_calls) == 6  # 2026-08-01 ~ 2026-08-06

    # 模拟重启：新 runner 同一数据库
    xunji2 = FakeXunji(session)
    make_runner(session, xunji2, FakeGarmin(session), start=date(2026, 8, 1)).run()
    assert xunji2.calls == []  # 全部跳过，零请求


def test_xunji_pacing_15s_between_requests(session):
    """限频计时：同一 run 内相邻两次训记请求之间恰好睡 15s，首次请求前不睡。"""
    sleep = SleepRecorder()
    xunji = FakeXunji(session)
    make_runner(session, xunji, FakeGarmin(session),
                start=date(2026, 8, 1), today=date(2026, 8, 4), sleep=sleep).run()
    assert sleep.calls == [XUNJI_DAY_INTERVAL_S] * 3  # 4 天 4 次请求，3 次间隔
    assert XUNJI_DAY_INTERVAL_S == 15.0


def test_single_day_failure_recorded_and_run_continues(session):
    """单日失败：记录 failed 后继续后续日期，不得终止整个导入。"""
    fail_day = "2026-08-02"
    xunji = FakeXunji(session, fail_days={fail_day})
    state = BackfillState()
    runner = make_runner(session, xunji, FakeGarmin(session),
                         start=date(2026, 8, 1), today=date(2026, 8, 4), state=state)
    result = runner.run()

    rows = progress_rows(session, "xunji")
    assert rows[fail_day] == "failed"
    assert rows["2026-08-01"] == "empty"
    assert rows["2026-08-04"] == "empty"  # 失败日之后的日期仍被处理
    assert "2026-08-03" in xunji.calls
    assert state.phase == "done"


def test_failed_day_retried_on_next_run(session):
    """failed 不算完成：下次运行会重试该日。"""
    xunji = FakeXunji(session, fail_days={"2026-08-02"})
    make_runner(session, xunji, FakeGarmin(session),
                start=date(2026, 8, 1), today=date(2026, 8, 2)).run()
    xunji2 = FakeXunji(session)  # 故障恢复
    make_runner(session, xunji2, FakeGarmin(session),
                start=date(2026, 8, 1), today=date(2026, 8, 2)).run()
    assert xunji2.calls == ["2026-08-02"]  # 只重拉失败日
    assert progress_rows(session, "xunji")["2026-08-02"] == "empty"


# ---------- 佳明活动全量分页 ----------

def test_garmin_activities_paged_with_progress(session):
    """活动列表：每页 100 条分页，页进度落 backfill_progress，活动落库。"""
    activities = [make_activity(1000 + i, date(2020, 1, 1) + timedelta(days=i)) for i in range(250)]
    garmin = FakeGarmin(session, activities=activities)
    make_runner(session, FakeXunji(session), garmin, start=TODAY).run()

    call = garmin.sync_all_calls[0]
    assert call["page_size"] == GARMIN_PAGE_SIZE == 100
    assert call["start_offset"] == 0
    rows = progress_rows(session, "garmin_activity")
    assert rows == {"page:0": "done", "page:100": "done", "page:200": "done", "all": "done"}
    assert session.query(GarminActivity).count() == 250


def test_garmin_activities_resume_skips_done_pages(session):
    """活动断点：已完成页不重拉，从最后未完成页继续，已入库活动跳过详情。"""
    activities = [make_activity(1000 + i, date(2020, 1, 1) + timedelta(days=i)) for i in range(250)]
    garmin = FakeGarmin(session, activities=activities)
    make_runner(session, FakeXunji(session), garmin, start=TODAY).run()
    assert len(garmin.sync_all_calls) == 1

    # 模拟中断后重启：新 garmin 实例，已有 page:0/page:100/page:200 进度
    garmin2 = FakeGarmin(session, activities=activities)
    make_runner(session, FakeXunji(session), garmin2, start=TODAY).run()
    call = garmin2.sync_all_calls[0]
    assert call["start_offset"] == 300  # 3 页已完成 → 从 offset 300 继续
    assert call["skip_ids"] == {str(1000 + i) for i in range(250)}


def test_garmin_activities_phase_failure_does_not_abort_run(session):
    """活动阶段整体失败（如登录 429）：记录错误，继续每日健康与融合阶段。"""
    garmin = FakeGarmin(session, activities_error=RuntimeError("429 storm"))
    state = BackfillState()
    runner = make_runner(session, FakeXunji(session), garmin,
                         start=date(2026, 8, 5), state=state)
    runner.run()
    assert state.phase == "done"
    assert state.errors  # 记录了阶段错误
    assert garmin.daily_calls  # 每日健康阶段仍执行
    assert progress_rows(session, "fusion") == {"all": "done"}


# ---------- 佳明每日健康 ----------

def test_garmin_daily_backfill_and_skip(session):
    """每日健康仅从 BACKFILL_START_DATE 起；已完成日期跳过。"""
    garmin = FakeGarmin(session)
    make_runner(session, FakeXunji(session), garmin,
                start=date(2026, 8, 1), today=date(2026, 8, 3)).run()
    assert garmin.daily_calls == ["2026-08-01", "2026-08-02", "2026-08-03"]
    assert session.query(GarminDaily).count() == 3

    garmin2 = FakeGarmin(session)
    make_runner(session, FakeXunji(session), garmin2,
                start=date(2026, 8, 1), today=date(2026, 8, 3)).run()
    assert garmin2.daily_calls == []  # 断点全部跳过


def test_garmin_daily_single_day_failure_continues(session):
    """每日健康单日失败记录 failed 并继续。"""
    garmin = FakeGarmin(session, fail_days={"2026-08-02"})
    make_runner(session, FakeXunji(session), garmin,
                start=date(2026, 8, 1), today=date(2026, 8, 3)).run()
    rows = progress_rows(session, "garmin_daily")
    assert rows == {"2026-08-01": "done", "2026-08-02": "failed", "2026-08-03": "done"}


# ---------- 完成后自动融合 ----------

def test_fusion_runs_automatically_after_backfill(session):
    """导入完成后自动跑 matcher+fuse：重叠 ≥60% 的记录产出 auto_matched workout。"""
    day = date(2026, 8, 5)
    xunji = FakeXunji(session, train_days={day.isoformat()})
    garmin = FakeGarmin(session, activities=[make_activity(9001, day)])
    state = BackfillState()
    make_runner(session, xunji, garmin, start=day, today=day, state=state).run()

    workouts = session.query(Workout).all()
    assert len(workouts) == 1
    assert workouts[0].match_status == "auto_matched"
    assert progress_rows(session, "fusion") == {"all": "done"}
    assert state.phase == "done"


def test_runner_writes_job_run_log(session):
    """导入结束写 job_run 日志。"""
    from app.models import JobRun

    make_runner(session, FakeXunji(session), FakeGarmin(session),
                start=TODAY, today=TODAY).run()
    run = session.query(JobRun).filter_by(job_name="backfill").one()
    assert run.status == "success"
    assert run.finished_at is not None


# ---------- 进度与 ETA 计算 ----------

def test_compute_status_percent_and_eta(session):
    """进度百分比与预计剩余时间：按训记 70% / 活动 10% / 健康 15% / 融合 5% 加权。"""
    start = date(2026, 8, 1)
    today = date(2026, 8, 4)  # 共 4 天
    for i, ds in enumerate(["2026-08-01", "2026-08-02"]):
        session.add(BackfillProgress(source="xunji", date=ds, status="done",
                                     finished_at=datetime.now()))
    session.add(BackfillProgress(source="garmin_daily", date="2026-08-01",
                                 status="done", finished_at=datetime.now()))
    session.commit()

    state = BackfillState()
    state.running = True
    state.phase = "xunji"
    status = compute_status(session, state, start_date=start, today=today)

    # xunji 2/4 → 0.35；activities 0；daily 1/4 → 0.0375；fusion 0
    assert status["percent"] == pytest.approx(38.8, abs=0.1)
    # ETA：剩 2 天训记 ×15s + 剩 3 天健康 ×3s
    assert status["eta_seconds"] == 2 * 15 + 3 * 3
    assert status["running"] is True
    assert status["phase"] == "xunji"
    assert status["details"]["xunji"] == {"done": 2, "total": 4}


def test_compute_status_done_is_100_percent(session):
    start = today = date(2026, 8, 6)
    for source, ds in [("xunji", "2026-08-06"), ("garmin_daily", "2026-08-06"),
                       ("garmin_activity", "all"), ("fusion", "all")]:
        session.add(BackfillProgress(source=source, date=ds, status="done",
                                     finished_at=datetime.now()))
    session.commit()
    state = BackfillState()
    state.phase = "done"
    status = compute_status(session, state, start_date=start, today=today)
    assert status["percent"] == 100.0
    assert status["eta_seconds"] == 0



# ---------- BackfillManager：后台线程生命周期 ----------


def _manager_env(monkeypatch, start: date):
    """把回溯起点锚到指定日期，让 manager 测试在 1-2 天内跑完。"""
    from app.config import get_settings

    monkeypatch.setenv("BACKFILL_START_DATE", start.isoformat())
    get_settings.cache_clear()


def _wait_finish(manager, timeout: float = 15.0) -> None:
    import time as _time

    deadline = _time.time() + timeout
    while manager._state.running and _time.time() < deadline:
        _time.sleep(0.05)
    assert not manager._state.running, "backfill 线程未在超时内结束"


def _fresh_factory():
    import os

    from app.db import make_engine, make_session_factory
    from app.models import Base

    engine = make_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def test_manager_start_runs_thread_and_completes(session, monkeypatch):
    from app.services.backfill import BackfillManager

    # 使用当前真实日期，避免硬编码 TODAY 随系统日期漂移后失败
    _manager_env(monkeypatch, date.today())
    manager = BackfillManager(
        session_factory=_fresh_factory(),
        xunji_factory=lambda s: FakeXunji(s),
        garmin_factory=lambda s: FakeGarmin(s),
        sleep=lambda s: None,
    )
    assert manager.start()["started"] is True
    _wait_finish(manager)
    assert manager._state.phase == "done"
    status = manager.status()
    assert status["percent"] == 100.0
    assert status["running"] is False
    assert status["details"]["xunji"] == {"done": 1, "total": 1}


def test_manager_double_start_guard(session, monkeypatch):
    """运行中重复 start 不重复启动线程。"""
    import threading

    from app.services.backfill import BackfillManager

    _manager_env(monkeypatch, TODAY - timedelta(days=1))
    gate = threading.Event()

    class SlowXunji(FakeXunji):
        def fetch_trains(self, datestr, **kwargs):
            gate.wait(timeout=10)
            return super().fetch_trains(datestr, **kwargs)

    manager = BackfillManager(
        session_factory=_fresh_factory(),
        xunji_factory=lambda s: SlowXunji(s),
        garmin_factory=lambda s: FakeGarmin(s),
        sleep=lambda s: None,
    )
    assert manager.start()["started"] is True
    try:
        assert manager.start()["started"] is False  # 运行中：拒绝重复启动
    finally:
        gate.set()
    _wait_finish(manager)


def test_manager_fatal_error_recorded_not_raised(session, monkeypatch):
    """线程内致命异常只落状态（phase=error），不炸掉服务。"""
    from app.services.backfill import BackfillManager

    _manager_env(monkeypatch, TODAY)

    def bad_factory(s):
        raise RuntimeError("no api key")

    manager = BackfillManager(
        session_factory=_fresh_factory(),
        xunji_factory=bad_factory,
        garmin_factory=lambda s: FakeGarmin(s),
        sleep=lambda s: None,
    )
    manager.start()
    _wait_finish(manager)
    assert manager._state.phase == "error"
    assert "no api key" in (manager._state.error or "")
    status = manager.status()
    assert status["running"] is False


def test_get_backfill_manager_returns_default_singleton():
    from app.api.backfill import get_backfill_manager
    from app.services.backfill import default_manager

    assert get_backfill_manager() is default_manager
