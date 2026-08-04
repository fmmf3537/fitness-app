"""APScheduler 任务注册（M5）。

- 返回未 start 的 BackgroundScheduler，由调用方（main.py startup）启动；
- jobstores 固定内存存储（单用户自托管，无需持久化）；
- 任务函数通过参数注入，便于测试替换。
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


def create_scheduler(*, sync_fn=None, health_fn=None, plan_fn=None) -> BackgroundScheduler:
    if sync_fn is None or health_fn is None or plan_fn is None:
        from app.services import sync as sync_mod  # 延迟 import，避免循环依赖
        sync_fn = sync_fn if sync_fn is not None else sync_mod.daily_sync
        health_fn = health_fn if health_fn is not None else sync_mod.health_check
        plan_fn = plan_fn if plan_fn is not None else sync_mod.sync_plan_cache

    scheduler = BackgroundScheduler(jobstores={"default": MemoryJobStore()})
    scheduler.add_job(partial(_job_sync_today, sync_fn),
                      CronTrigger(hour=22, minute=47), id="daily_sync_today")
    scheduler.add_job(partial(_job_sync_prev_day, sync_fn),
                      CronTrigger(hour=22, minute=52), id="daily_sync_prev_day")
    scheduler.add_job(health_fn, CronTrigger(minute=11), id="health_check_hourly")
    scheduler.add_job(plan_fn, CronTrigger(hour=23, minute=3), id="plan_cache_daily")
    return scheduler
