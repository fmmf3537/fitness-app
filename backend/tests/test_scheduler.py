"""M5 调度器注册测试（不 start，只校验任务与触发器）。

M4-1：daily 任务改调 all_users_sync_fn。
M5-1：新增 23:30 precompute_leaderboards（job 数 7→8）。
"""
from datetime import date, timedelta
from unittest.mock import Mock

from apscheduler.jobstores.memory import MemoryJobStore

from app.scheduler import create_scheduler


def _make():
    sync_fn, health_fn, plan_fn = Mock(name="sync"), Mock(name="health"), Mock(name="plan")
    weekly_fn, monthly_fn = Mock(name="weekly"), Mock(name="monthly")
    backup_fn = Mock(name="backup")
    all_users_sync_fn = Mock(name="all_users_sync")
    leaderboard_fn = Mock(name="leaderboard")
    sched = create_scheduler(
        sync_fn=sync_fn,
        health_fn=health_fn,
        plan_fn=plan_fn,
        weekly_fn=weekly_fn,
        monthly_fn=monthly_fn,
        backup_fn=backup_fn,
        all_users_sync_fn=all_users_sync_fn,
        leaderboard_fn=leaderboard_fn,
    )
    return (
        sched, sync_fn, health_fn, plan_fn, weekly_fn, monthly_fn,
        backup_fn, all_users_sync_fn, leaderboard_fn,
    )


def _field(job, name):
    return str(next(f for f in job.trigger.fields if f.name == name))


def test_registers_eight_jobs_with_cron_triggers():
    sched, *_ = _make()
    assert not sched.running  # 返回未 start 的 scheduler
    assert isinstance(sched._jobstores["default"], MemoryJobStore)

    jobs = {j.id: j for j in sched.get_jobs()}
    assert set(jobs) == {
        "daily_sync_today", "daily_sync_prev_day",
        "health_check_hourly", "plan_cache_daily",
        "weekly_review", "monthly_review", "db_backup_daily",
        "precompute_leaderboards",
    }

    assert _field(jobs["daily_sync_today"], "hour") == "22"
    assert _field(jobs["daily_sync_today"], "minute") == "47"

    assert _field(jobs["daily_sync_prev_day"], "hour") == "22"
    assert _field(jobs["daily_sync_prev_day"], "minute") == "52"

    assert _field(jobs["health_check_hourly"], "minute") == "11"

    assert _field(jobs["plan_cache_daily"], "hour") == "23"
    assert _field(jobs["plan_cache_daily"], "minute") == "3"

    # V2-2：每周日 21:13 周复盘；每月 1 日 09:23 月复盘
    assert _field(jobs["weekly_review"], "day_of_week") == "sun"
    assert _field(jobs["weekly_review"], "hour") == "21"
    assert _field(jobs["weekly_review"], "minute") == "13"

    assert _field(jobs["monthly_review"], "day") == "1"
    assert _field(jobs["monthly_review"], "hour") == "9"
    assert _field(jobs["monthly_review"], "minute") == "23"

    # V2-4：每日 03:17 数据库备份（低峰时段）
    assert _field(jobs["db_backup_daily"], "hour") == "3"
    assert _field(jobs["db_backup_daily"], "minute") == "17"

    # M5-1：每日 23:30 排行榜预计算
    assert _field(jobs["precompute_leaderboards"], "hour") == "23"
    assert _field(jobs["precompute_leaderboards"], "minute") == "30"


def test_jobs_invoke_injected_functions():
    (
        sched, sync_fn, health_fn, plan_fn, weekly_fn, monthly_fn,
        backup_fn, all_users_sync_fn, leaderboard_fn,
    ) = _make()
    jobs = {j.id: j for j in sched.get_jobs()}

    # M4-1：daily 任务调 all_users_sync_fn，不再调 sync_fn
    jobs["daily_sync_today"].func()
    all_users_sync_fn.assert_called_once_with(date.today())
    sync_fn.assert_not_called()

    all_users_sync_fn.reset_mock()
    jobs["daily_sync_prev_day"].func()
    all_users_sync_fn.assert_called_once_with(date.today() - timedelta(days=1))
    sync_fn.assert_not_called()

    jobs["health_check_hourly"].func()
    health_fn.assert_called_once_with()

    jobs["plan_cache_daily"].func()
    plan_fn.assert_called_once_with()

    jobs["weekly_review"].func()
    weekly_fn.assert_called_once_with()

    # 每月 1 日触发时复盘上个月（传入前一天日期）
    jobs["monthly_review"].func()
    monthly_fn.assert_called_once_with(date.today() - timedelta(days=1))

    jobs["db_backup_daily"].func()
    backup_fn.assert_called_once_with()

    jobs["precompute_leaderboards"].func()
    leaderboard_fn.assert_called_once_with()


def test_default_functions_are_sync_service():
    from app.services import ai as ai_mod
    from app.services import backup as backup_mod
    from app.services import leaderboard as lb_mod
    from app.services import sync as sync_mod

    sched = create_scheduler()
    jobs = {j.id: j for j in sched.get_jobs()}
    # M4-1：daily 任务默认调 sync_mod.sync_all_users（经 partial 绑定，不直接暴露）
    assert jobs["health_check_hourly"].func is sync_mod.health_check
    assert jobs["plan_cache_daily"].func is sync_mod.sync_plan_cache
    assert jobs["weekly_review"].func is ai_mod.run_weekly_review
    assert jobs["db_backup_daily"].func is backup_mod.backup_database
    assert jobs["precompute_leaderboards"].func is lb_mod.precompute_leaderboards
