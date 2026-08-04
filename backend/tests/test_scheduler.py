"""M5 调度器注册测试（不 start，只校验任务与触发器）。"""
from datetime import date, timedelta
from unittest.mock import Mock

from apscheduler.jobstores.memory import MemoryJobStore

from app.scheduler import create_scheduler


def _make():
    sync_fn, health_fn, plan_fn = Mock(name="sync"), Mock(name="health"), Mock(name="plan")
    sched = create_scheduler(sync_fn=sync_fn, health_fn=health_fn, plan_fn=plan_fn)
    return sched, sync_fn, health_fn, plan_fn


def _field(job, name):
    return str(next(f for f in job.trigger.fields if f.name == name))


def test_registers_four_jobs_with_cron_triggers():
    sched, *_ = _make()
    assert not sched.running  # 返回未 start 的 scheduler
    assert isinstance(sched._jobstores["default"], MemoryJobStore)

    jobs = {j.id: j for j in sched.get_jobs()}
    assert set(jobs) == {"daily_sync_today", "daily_sync_prev_day",
                         "health_check_hourly", "plan_cache_daily"}

    assert _field(jobs["daily_sync_today"], "hour") == "22"
    assert _field(jobs["daily_sync_today"], "minute") == "47"

    assert _field(jobs["daily_sync_prev_day"], "hour") == "22"
    assert _field(jobs["daily_sync_prev_day"], "minute") == "52"

    assert _field(jobs["health_check_hourly"], "minute") == "11"

    assert _field(jobs["plan_cache_daily"], "hour") == "23"
    assert _field(jobs["plan_cache_daily"], "minute") == "3"


def test_jobs_invoke_injected_functions():
    sched, sync_fn, health_fn, plan_fn = _make()
    jobs = {j.id: j for j in sched.get_jobs()}

    jobs["daily_sync_today"].func()
    sync_fn.assert_called_once_with(date.today())

    sync_fn.reset_mock()
    jobs["daily_sync_prev_day"].func()
    sync_fn.assert_called_once_with(date.today() - timedelta(days=1))

    jobs["health_check_hourly"].func()
    health_fn.assert_called_once_with()

    jobs["plan_cache_daily"].func()
    plan_fn.assert_called_once_with()


def test_default_functions_are_sync_service():
    from app.services import sync as sync_mod

    sched = create_scheduler()
    jobs = {j.id: j for j in sched.get_jobs()}
    assert jobs["health_check_hourly"].func is sync_mod.health_check
    assert jobs["plan_cache_daily"].func is sync_mod.sync_plan_cache
