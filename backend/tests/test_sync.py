"""M5 同步编排服务测试：daily_sync / health_check / sync_plan_cache。"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx

from app.models import GarminActivity, JobRun, Workout, XunjiPlan, XunjiTrain
from app.services import sync as sync_mod
from app.services.sync import RETRY_DELAYS, daily_sync, health_check, sync_plan_cache

DAY = date(2026, 8, 3)


def _recorder_sleep(records):
    def fake_sleep(seconds):
        records.append(seconds)
    return fake_sleep


def _no_sleep(_seconds):
    return None


def _mock_adapters():
    """返回配置好默认返回值的 (xunji, garmin) Mock。"""
    xunji = Mock()
    xunji.fetch_trains.return_value = []
    garmin = Mock()
    garmin.sync_activities.return_value = []
    garmin.sync_daily.return_value = Mock()
    return xunji, garmin


def _stub_match(workouts=(), candidates=()):
    def fake_match(session, day):
        return {"workouts": list(workouts), "candidates": list(candidates)}
    return fake_match


# ---------- daily_sync 编排 ----------

def test_daily_sync_orchestration_order(session, monkeypatch):
    order = []
    xunji = Mock()
    xunji.fetch_trains.side_effect = lambda datestr: order.append("fetch_trains") or []
    garmin = Mock()
    garmin.sync_activities.side_effect = lambda datestr: order.append("sync_activities") or []
    garmin.sync_daily.side_effect = lambda datestr: order.append("sync_daily") or Mock()

    def fake_match(sess, day):
        order.append("match_day")
        return {"workouts": [], "candidates": []}
    monkeypatch.setattr(sync_mod, "match_day", fake_match)

    result = daily_sync(DAY, session=session, xunji=xunji, garmin=garmin, sleep=_no_sleep)

    assert order == ["fetch_trains", "sync_activities", "sync_daily", "match_day"]
    assert result["status"] == "success"
    assert result["error"] is None
    assert result["date"] == "2026-08-03"
    xunji.fetch_trains.assert_called_once_with("2026-08-03")
    garmin.sync_activities.assert_called_once_with("2026-08-03")
    garmin.sync_daily.assert_called_once_with("2026-08-03")


def test_daily_sync_accepts_str_day(session, monkeypatch):
    monkeypatch.setattr(sync_mod, "match_day", _stub_match())
    xunji, garmin = _mock_adapters()
    result = daily_sync("2026-08-03", session=session, xunji=xunji, garmin=garmin, sleep=_no_sleep)
    assert result["status"] == "success"
    assert result["date"] == "2026-08-03"


def test_daily_sync_creates_session_when_none(session, monkeypatch):
    """session=None 时应通过 SessionLocal 自建会话。"""
    created = []

    class FakeFactory:
        def __call__(self):
            created.append(True)
            return session

    monkeypatch.setattr(sync_mod, "SessionLocal", FakeFactory())
    monkeypatch.setattr(sync_mod, "match_day", _stub_match())
    xunji, garmin = _mock_adapters()
    result = daily_sync(DAY, xunji=xunji, garmin=garmin, sleep=_no_sleep)
    assert created, "应通过 SessionLocal 自建会话"
    assert result["status"] == "success"


# ---------- 重试与退避 ----------

def test_retry_backoff_then_success(session, monkeypatch):
    monkeypatch.setattr(sync_mod, "match_day", _stub_match())
    xunji = Mock()
    xunji.fetch_trains.side_effect = [RuntimeError("boom1"), RuntimeError("boom2"), ["t"]]
    garmin = Mock()
    garmin.sync_activities.return_value = []
    sleeps = []

    result = daily_sync(DAY, session=session, xunji=xunji, garmin=garmin,
                        sleep=_recorder_sleep(sleeps))

    assert xunji.fetch_trains.call_count == 3
    assert sleeps == RETRY_DELAYS[:2] == [1, 4]
    assert result["status"] == "success"
    assert result["detail"]["attempts"]["xunji_trains"] == 3


def test_persistent_failure_records_failed_job_run(session, monkeypatch):
    match_called = []
    monkeypatch.setattr(sync_mod, "match_day",
                        lambda s, d: match_called.append(d) or {"workouts": [], "candidates": []})
    xunji = Mock()
    xunji.fetch_trains.side_effect = RuntimeError("always down")
    garmin = Mock()
    sleeps = []

    result = daily_sync(DAY, session=session, xunji=xunji, garmin=garmin,
                        sleep=_recorder_sleep(sleeps))

    assert xunji.fetch_trains.call_count == len(RETRY_DELAYS) + 1 == 4
    assert sleeps == RETRY_DELAYS == [1, 4, 16]
    assert result["status"] == "failed"
    assert "always down" in result["error"]
    # 后续步骤不应执行
    garmin.sync_activities.assert_not_called()
    assert match_called == []

    runs = session.query(JobRun).filter(JobRun.job_name == "daily_sync").all()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "always down" in runs[0].error
    detail = json.loads(runs[0].detail_json)
    assert detail["failed_step"] == "xunji_trains"
    assert detail["attempts"]["xunji_trains"] == 4


# ---------- JobRun 正确性 ----------

def test_job_run_success_fields(session, monkeypatch):
    monkeypatch.setattr(sync_mod, "match_day", _stub_match(workouts=[Mock(), Mock()], candidates=[Mock()]))
    xunji = Mock()
    xunji.fetch_trains.return_value = ["t1"]
    garmin = Mock()
    garmin.sync_activities.return_value = ["a1", "a2"]
    garmin.sync_daily.return_value = Mock()

    result = daily_sync(DAY, session=session, xunji=xunji, garmin=garmin, sleep=_no_sleep)

    run = session.query(JobRun).filter(JobRun.job_name == "daily_sync").one()
    assert run.started_at is not None
    assert run.finished_at is not None
    assert run.finished_at >= run.started_at
    assert run.status == "success"
    assert run.error is None
    detail = json.loads(run.detail_json)
    assert detail["date"] == "2026-08-03"
    assert detail["xunji_trains"] == 1
    assert detail["garmin_activities"] == 2
    assert detail["garmin_daily"] is True
    assert detail["workouts"] == 2
    assert detail["candidates"] == 1
    assert detail["attempts"] == {"xunji_trains": 1, "garmin_activities": 1,
                                 "garmin_daily": 1, "match": 1}
    assert result["detail"] == detail


# ---------- 幂等（真 session + 假适配器 upsert 固定数据 + 真 match_day） ----------

class _FakeXunji:
    def __init__(self, session):
        self._s = session

    def fetch_trains(self, datestr):
        row = (self._s.query(XunjiTrain)
               .filter_by(datestr=datestr, localid="t1").one_or_none())
        if row is None:
            row = XunjiTrain(
                datestr=datestr, localid="t1", title="晨训",
                start_ms=int(datetime(2026, 8, 3, 10, 0).timestamp() * 1000),
                end_ms=int(datetime(2026, 8, 3, 11, 0).timestamp() * 1000),
            )
            self._s.add(row)
            self._s.commit()
        return [row]


class _FakeGarmin:
    def __init__(self, session):
        self._s = session

    def sync_activities(self, datestr):
        row = (self._s.query(GarminActivity)
               .filter_by(activity_id="g1").one_or_none())
        if row is None:
            row = GarminActivity(
                activity_id="g1", activity_type="strength_training", name="力量",
                start_ts=datetime(2026, 8, 3, 10, 0), end_ts=datetime(2026, 8, 3, 11, 0),
                duration_s=3600,
            )
            self._s.add(row)
            self._s.commit()
        return [row]

    def sync_daily(self, datestr):
        return object()


def test_daily_sync_idempotent(session):
    xunji = _FakeXunji(session)
    garmin = _FakeGarmin(session)

    r1 = daily_sync(DAY, session=session, xunji=xunji, garmin=garmin, sleep=_no_sleep)
    r2 = daily_sync(DAY, session=session, xunji=xunji, garmin=garmin, sleep=_no_sleep)

    assert r1["status"] == "success" and r2["status"] == "success"
    assert r1["detail"]["workouts"] == 1  # 10:00-11:00 完全重叠 → auto_matched 1 条
    assert r2["detail"]["workouts"] == 0  # 第二次不产生新 workout
    assert session.query(Workout).count() == 1
    # job_run 每次一行属正常日志
    assert session.query(JobRun).filter(JobRun.job_name == "daily_sync").count() == 2


# ---------- health_check ----------

def test_health_check_all_success(session):
    xunji = Mock()
    garmin = Mock()
    result = health_check(session=session, xunji=xunji, garmin=garmin)
    assert result["status"] == "success"
    assert result["error"] is None
    xunji.fetch_trains.assert_called_once_with(date.today().isoformat())
    garmin.sync_daily.assert_called_once_with(date.today().isoformat())
    run = session.query(JobRun).filter(JobRun.job_name == "health_check").one()
    assert run.status == "success"


def test_health_check_partial_failure(session):
    xunji = Mock()
    xunji.fetch_trains.side_effect = RuntimeError("xunji down")
    garmin = Mock()

    result = health_check(session=session, xunji=xunji, garmin=garmin)

    assert result["status"] == "failed"
    assert "xunji" in result["error"]
    # 健康检查不重试
    assert xunji.fetch_trains.call_count == 1
    run = session.query(JobRun).filter(JobRun.job_name == "health_check").one()
    assert run.status == "failed"
    assert "xunji" in run.error


# ---------- sync_plan_cache ----------

def test_sync_plan_cache_success(session):
    xunji = Mock()
    xunji.fetch_plan_list.return_value = [Mock(plan_ref="p1"), Mock(plan_ref="p2")]
    xunji.fetch_plan.side_effect = lambda ref, start, end: Mock(plan_ref=ref)

    result = sync_plan_cache(session=session, xunji=xunji, days_ahead=30)

    assert result["status"] == "success"
    assert xunji.fetch_plan.call_count == 2
    today = date.today()
    for call in xunji.fetch_plan.call_args_list:
        ref, start, end = call.args
        assert ref in ("p1", "p2")
        assert start == today
        assert end == today + timedelta(days=30)
    run = session.query(JobRun).filter(JobRun.job_name == "plan_cache").one()
    assert run.status == "success"
    assert json.loads(run.detail_json)["plans"] == 2


def test_sync_plan_cache_failure(session):
    xunji = Mock()
    xunji.fetch_plan_list.side_effect = RuntimeError("plan list down")

    result = sync_plan_cache(session=session, xunji=xunji)

    assert result["status"] == "failed"
    assert "plan list down" in result["error"]
    run = session.query(JobRun).filter(JobRun.job_name == "plan_cache").one()
    assert run.status == "failed"


# ---------- V1-4-FIX 真实链路回归 ----------

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PLAN_URL = "https://api.xunjiapp.cn/open/plan/query_gzip"


@respx.mock
def test_sync_plan_cache_real_chain_with_date_objects(session):
    """回归：sync_plan_cache 经真实 XunjiClient（respx 拦 HTTP）全链路落库。

    修复前 sync_plan_cache 把 date 对象直接交给 fetch_plan 拼请求体，
    httpx 序列化报 Object of type date is not JSON serializable。
    list/get 响应均使用真实 API 抓取的结构（非纯字符串 mock）。
    """
    from app.adapters.xunji import XunjiClient

    list_gzip = (FIXTURES / "plan_list_real_gzip.bin").read_bytes()
    real_get = json.loads((FIXTURES / "plan_get_real.json").read_text(encoding="utf-8"))
    responses = iter([
        httpx.Response(200, content=list_gzip),
        httpx.Response(200, json={"schema_version": "plan_open_api_v1", "res": real_get}),
    ])
    respx.post(PLAN_URL).mock(side_effect=lambda request: next(responses))
    client = XunjiClient(session, api_key="test-key", sleep=_no_sleep)

    result = sync_plan_cache(session=session, xunji=client)

    assert result["status"] == "success", result["error"]
    rows = session.query(XunjiPlan).all()
    assert len(rows) == 1
    assert rows[0].plan_ref == "universal:1"
    assert rows[0].date_from is not None
    assert rows[0].date_to is not None
    assert json.loads(rows[0].plan_json)["days"]
