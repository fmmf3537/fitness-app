"""APScheduler 任务注册（M5；V2-2 增加周/月复盘；V2-4 增加每日数据库备份；M4-1 多用户串行同步）。

- 返回未 start 的 BackgroundScheduler，由调用方（main.py startup）启动；
- jobstores 固定内存存储（单用户自托管，无需持久化）；
- 任务函数通过参数注入，便于测试替换。
- M4-1：22:47 / 22:52 改调 sync_all_users（按绑定用户串行 daily_sync）。
"""
from datetime import date, timedelta
from functools import partial

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


def _job_sync_today(sync_fn) -> None:
    sync_fn(date.today())


def _job_sync_prev_day(sync_fn) -> None:
    sync_fn(date.today() - timedelta(days=1))


def _job_monthly_review(monthly_fn) -> None:
    # 每月 1 日 09:23 触发时复盘上个月（传入前一天日期）
    monthly_fn(date.today() - timedelta(days=1))


def create_scheduler(*, sync_fn=None, all_users_sync_fn=None, health_fn=None, plan_fn=None,
                     weekly_fn=None, monthly_fn=None, backup_fn=None) -> BackgroundScheduler:
    if (
        all_users_sync_fn is None
        or sync_fn is None
        or health_fn is None
        or plan_fn is None
    ):
        from app.services import sync as sync_mod  # 延迟 import，避免循环依赖
        all_users_sync_fn = (
            all_users_sync_fn if all_users_sync_fn is not None else sync_mod.sync_all_users
        )
        sync_fn = sync_fn if sync_fn is not None else sync_mod.daily_sync
        health_fn = health_fn if health_fn is not None else sync_mod.health_check
        plan_fn = plan_fn if plan_fn is not None else sync_mod.sync_plan_cache
    if weekly_fn is None or monthly_fn is None:
        from app.services import ai as ai_mod
        weekly_fn = weekly_fn if weekly_fn is not None else ai_mod.run_weekly_review
        monthly_fn = monthly_fn if monthly_fn is not None else ai_mod.run_monthly_review
    if backup_fn is None:
        from app.services import backup as backup_mod
        backup_fn = backup_mod.backup_database

    scheduler = BackgroundScheduler(jobstores={"default": MemoryJobStore()})
    # M4-1：daily 任务改用 all_users_sync_fn；sync_fn 仍注入以向后兼容，但不挂到这两个 job
    scheduler.add_job(partial(_job_sync_today, all_users_sync_fn),
                      CronTrigger(hour=22, minute=47), id="daily_sync_today")
    scheduler.add_job(partial(_job_sync_prev_day, all_users_sync_fn),
                      CronTrigger(hour=22, minute=52), id="daily_sync_prev_day")
    scheduler.add_job(health_fn, CronTrigger(minute=11), id="health_check_hourly")
    scheduler.add_job(plan_fn, CronTrigger(hour=23, minute=3), id="plan_cache_daily")
    # V2-2：每周日 21:13 周复盘；每月 1 日 09:23 月复盘（复盘上个月）
    scheduler.add_job(weekly_fn,
                      CronTrigger(day_of_week="sun", hour=21, minute=13),
                      id="weekly_review")
    scheduler.add_job(partial(_job_monthly_review, monthly_fn),
                      CronTrigger(day=1, hour=9, minute=23), id="monthly_review")
    # V2-4：每日 03:17 数据库备份（低峰时段，保留 30 天滚动清理）
    scheduler.add_job(backup_fn, CronTrigger(hour=3, minute=17), id="db_backup_daily")
    return scheduler
