"""M5 同步编排服务：daily_sync / health_check / sync_plan_cache。

纪律：
- 每步独立指数退避重试（RETRY_DELAYS = [1, 4, 16]，失败后最多重试 3 次，共 4 次尝试）；
- 任一步最终失败不向外抛异常，写 JobRun(status='failed') 并返回结果 dict；
- 每次运行写一行 JobRun 日志（job_run 表是日志，允许每次一行）；
- 幂等依赖各适配器 upsert 与 match_day 的跳过逻辑，本层不做额外去重；
- 健康检查是探针，不做重试。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.adapters.llm import LLMError
from app.db import SessionLocal
from app.models import JobRun
from app.services.ai import run_daily_next_advices, run_daily_reviews
from app.services.matcher import match_day

logger = logging.getLogger(__name__)

# 指数退避（秒）：失败后最多重试 3 次（共 4 次尝试）
RETRY_DELAYS = [1, 4, 16]


def _run_with_retry(fn: Callable[[], Any], *, sleep: Callable[[float], None] = time.sleep) -> tuple[Any, int]:
    """执行 fn，失败按 RETRY_DELAYS 退避重试；返回 (结果, 尝试次数)，最终失败抛异常。"""
    attempts = 0
    while True:
        attempts += 1
        try:
            return fn(), attempts
        except Exception as exc:
            if attempts > len(RETRY_DELAYS):
                raise
            logger.warning("同步步骤失败，%ds 后重试（第 %d 次）：%s",
                           RETRY_DELAYS[attempts - 1], attempts + 1, exc)
            sleep(RETRY_DELAYS[attempts - 1])


def _write_job_run(session: Session, job_name: str, started_at: datetime, result: dict) -> None:
    run = JobRun(
        job_name=job_name,
        started_at=started_at,
        finished_at=datetime.now(),
        status=result["status"],
        error=result["error"],
        detail_json=json.dumps(result["detail"], ensure_ascii=False, default=str),
    )
    session.add(run)
    session.commit()


def daily_sync(day, *, session: Session | None = None, xunji=None, garmin=None,
               sleep: Callable[[float], None] = time.sleep) -> dict:
    """每日同步编排：训记 → 佳明活动 → 佳明健康 → 融合匹配。"""
    day_date = date.fromisoformat(day) if isinstance(day, str) else day
    datestr = day_date.isoformat()
    own_session = session is None
    session = session or SessionLocal()
    started_at = datetime.now()
    try:
        if xunji is None:
            from app.adapters.xunji import XunjiClient
            xunji = XunjiClient(session)
        if garmin is None:
            from app.adapters.garmin_adapter import GarminClient
            garmin = GarminClient(session)

        # V2-7b 缺陷3：同步日期为今天时必须绕过同日缓存强刷，否则当天补录的
        # 组数拉不下来；历史日期保持缓存命中策略不变（SyncManager 手动同步亦走此处）。
        is_today = day_date == date.today()
        xunji_step = (
            (lambda: xunji.fetch_trains(datestr, force_refresh=True))  # noqa: E731
            if is_today else
            (lambda: xunji.fetch_trains(datestr))  # noqa: E731
        )
        steps = [
            ("xunji_trains", xunji_step),
            ("garmin_activities", lambda: garmin.sync_activities(datestr)),
            ("garmin_daily", lambda: garmin.sync_daily(datestr)),
            ("match", lambda: match_day(session, day_date)),
        ]
        detail: dict[str, Any] = {"date": datestr}
        attempts: dict[str, int] = {}
        failed_step = None
        error = None
        for name, fn in steps:
            try:
                out, n = _run_with_retry(fn, sleep=sleep)
            except Exception as exc:
                attempts[name] = len(RETRY_DELAYS) + 1
                failed_step = name
                error = str(exc)
                break
            attempts[name] = n
            if name == "xunji_trains":
                detail["xunji_trains"] = len(out)
            elif name == "garmin_activities":
                detail["garmin_activities"] = len(out)
            elif name == "garmin_daily":
                detail["garmin_daily"] = True
            else:
                detail["workouts"] = len(out["workouts"])
                detail["candidates"] = len(out["candidates"])

        detail["attempts"] = attempts
        if failed_step is not None:
            detail["failed_step"] = failed_step

        # AI 单次点评：同步成功后为当日 workout 异步生成；失败不影响同步主流程
        if failed_step is None:
            try:
                ai_summary = run_daily_reviews(session, day_date)
                detail["ai_reviews"] = ai_summary["generated"]
                # V1-4：单次点评生成后连锁触发下次训练建议
                advice_summary = run_daily_next_advices(session, day_date)
                detail["next_advices"] = advice_summary["generated"]
            except LLMError as exc:
                detail["ai_reviews_failed"] = True
                _write_job_run(
                    session,
                    "ai_review",
                    datetime.now(),
                    {
                        "date": datestr,
                        "status": "failed",
                        "error": str(exc),
                        "detail": {"date": datestr, "reason": "llm_error"},
                    },
                )
            except Exception as exc:
                detail["ai_reviews_failed"] = True
                _write_job_run(
                    session,
                    "ai_review",
                    datetime.now(),
                    {
                        "date": datestr,
                        "status": "failed",
                        "error": str(exc),
                        "detail": {"date": datestr, "reason": "unexpected"},
                    },
                )

        result = {
            "date": datestr,
            "status": "failed" if failed_step else "success",
            "error": error,
            "detail": detail,
        }
        _write_job_run(session, "daily_sync", started_at, result)
        return result
    finally:
        if own_session:
            session.close()


def health_check(*, session: Session | None = None, xunji=None, garmin=None,
                 alert_evaluator=None, alert_notifier=None) -> dict:
    """数据源健康探针（训记 + 佳明）。不做重试。

    V2-4：探针写完 job_run 后评估连续失败阈值，达标则推送告警
    （alert_evaluator / alert_notifier 可注入；告警失败不影响探针本身）。
    """
    today = date.today()
    datestr = today.isoformat()
    own_session = session is None
    session = session or SessionLocal()
    started_at = datetime.now()
    try:
        if xunji is None:
            from app.adapters.xunji import XunjiClient
            xunji = XunjiClient(session)
        if garmin is None:
            from app.adapters.garmin_adapter import GarminClient
            garmin = GarminClient(session)

        failures: list[str] = []
        try:
            xunji.fetch_trains(datestr)
        except Exception as exc:
            failures.append(f"xunji: {exc}")
        try:
            garmin.sync_daily(datestr)
        except Exception as exc:
            failures.append(f"garmin: {exc}")

        result = {
            "date": datestr,
            "status": "failed" if failures else "success",
            "error": "; ".join(failures) or None,
            "detail": {"date": datestr, "failed_sources": [f.split(":", 1)[0] for f in failures]},
        }
        _write_job_run(session, "health_check", started_at, result)

        # V2-4：连续失败 ≥3 次推送告警（30 分钟冷却去重）；告警故障不阻断探针
        try:
            from app.services.alerts import evaluate_health_alerts

            evaluator = alert_evaluator or evaluate_health_alerts
            if alert_evaluator is not None:
                alert_result = evaluator(session)
            else:
                alert_result = evaluator(session, notifier=alert_notifier)
            result["detail"]["alerts"] = alert_result.get("alerts", [])
        except Exception as exc:  # 告警通道故障不阻断健康检查
            result["detail"]["alert_error"] = str(exc)
        return result
    finally:
        if own_session:
            session.close()


def sync_plan_cache(*, session: Session | None = None, xunji=None, days_ahead: int = 30) -> dict:
    """刷新训记官方计划缓存（PRD §6.1 计划缓存任务）。"""
    today = date.today()
    own_session = session is None
    session = session or SessionLocal()
    started_at = datetime.now()
    try:
        if xunji is None:
            from app.adapters.xunji import XunjiClient
            xunji = XunjiClient(session)

        try:
            plans = xunji.fetch_plan_list()
            for plan in plans:
                xunji.fetch_plan(plan.plan_ref, today, today + timedelta(days=days_ahead))
            result = {
                "date": today.isoformat(),
                "status": "success",
                "error": None,
                "detail": {"plans": len(plans), "days_ahead": days_ahead},
            }
        except Exception as exc:
            result = {
                "date": today.isoformat(),
                "status": "failed",
                "error": str(exc),
                "detail": {"failed_step": "plan_cache"},
            }
        _write_job_run(session, "plan_cache", started_at, result)
        return result
    finally:
        if own_session:
            session.close()
