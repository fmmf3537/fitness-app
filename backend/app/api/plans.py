"""V2-8 训练计划 API：未来计划查询 / 计划缓存手动刷新 / 计划级 AI 点评。

纪律：
- 全部端点挂 require_auth；
- 刷新与点评均为后台线程执行（立即 202 + 运行中 409），状态可轮询；
- 计划数据只读 xunji_plan 本地缓存；点评 runner 自建 DB 会话，不复用请求会话；
- 训记官方计划接口只读，本模块不提供任何修改计划的入口。
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, get_current_user_id, resolve_viewer
from app.db import get_session
from app.models import AIReport, User
from app.services import ai as ai_service
from app.services import plans as plan_service

router = APIRouter(
    prefix="/api/plans",
    tags=["plans"],
)


@router.get("/upcoming")
def upcoming_plans(
    days: int = Query(default=30, ge=1, le=90),
    session: Session = Depends(get_session),
    principal: User = Depends(get_current_user),
    override_user_id: int | None = Query(default=None, alias="user_id"),
) -> dict:
    """未来 N 天计划日程（含休息日标记），只读本地计划缓存（当前用户）。"""
    start = date.today()
    return {
        "from": start.isoformat(),
        "to": (start + timedelta(days=days - 1)).isoformat(),
        "days": plan_service.query_plan_days(session, start, days=days, user_id=resolve_viewer(principal, override_user_id)),
    }


# =====================================================================
# 计划缓存手动刷新（后台线程 + 409 防重）
# =====================================================================


class PlanRefreshAlreadyRunningError(Exception):
    """已有计划刷新在跑，对应 HTTP 409。"""


class PlanRefreshManager:
    """后台线程执行 sync_plan_cache，内存保存当前/最近一次状态。"""

    def __init__(self, refresh_fn: Callable[[], dict] | None = None) -> None:
        self._refresh_fn = refresh_fn
        self._lock = threading.Lock()
        self._running = False
        self._status: str | None = None  # success / failed / None(从未运行)
        self._error: str | None = None
        self._started_at: datetime | None = None
        self._finished_at: datetime | None = None

    @staticmethod
    def _default_refresh() -> dict:
        from app.db import SessionLocal
        from app.services.sync import sync_plan_cache

        session = SessionLocal()
        try:
            return sync_plan_cache(session=session)
        finally:
            session.close()

    def start(self) -> dict:
        with self._lock:
            if self._running:
                raise PlanRefreshAlreadyRunningError("计划缓存刷新正在进行中")
            self._running = True
            self._status = None
            self._error = None
            self._started_at = datetime.now()
            self._finished_at = None
            thread = threading.Thread(
                target=self._run_safe, daemon=True, name="plan-refresh",
            )
            thread.start()
        return {"status": "started", "job": "plan_refresh"}

    def _run_safe(self) -> None:
        try:
            fn = self._refresh_fn or self._default_refresh
            result = fn() or {}
            with self._lock:
                self._status = result.get("status", "success")
                self._error = result.get("error")
        except Exception as exc:  # noqa: BLE001 - 后台线程异常只落状态
            with self._lock:
                self._status = "failed"
                self._error = f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                self._running = False
                self._finished_at = datetime.now()

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "status": self._status,
                "error": self._error,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "finished_at": self._finished_at.isoformat() if self._finished_at else None,
            }


default_plan_refresh_manager = PlanRefreshManager()


def get_plan_refresh_manager() -> PlanRefreshManager:
    """依赖注入点：测试可 override 替换管理器。"""
    return default_plan_refresh_manager


@router.post("/refresh", status_code=202)
def refresh_plans(
    manager: PlanRefreshManager = Depends(get_plan_refresh_manager),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """手动触发计划缓存刷新（后台线程执行 sync_plan_cache，立即返回 202）。"""
    try:
        return manager.start()
    except PlanRefreshAlreadyRunningError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/refresh/status")
def refresh_status(
    manager: PlanRefreshManager = Depends(get_plan_refresh_manager),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """当前/最近一次计划缓存刷新状态。"""
    return manager.status()


# =====================================================================
# 计划级 AI 点评（后台线程 + 409 防重；只手动触发，不进 scheduler）
# =====================================================================


class PlanReviewManager:
    """按日期键控的计划点评后台生成管理器（runner 可注入，便于测试同步执行）。"""

    def __init__(self, runner: Callable[[str], None] | None = None) -> None:
        self._runner = runner
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._errors: dict[str, str] = {}

    @staticmethod
    def _default_runner(date_str: str, user_id: int | None = None) -> None:
        from app.db import SessionLocal

        session = SessionLocal()
        try:
            ai_service.generate_plan_review(session, date_str, user_id=user_id)
        finally:
            session.close()

    def start(self, date_str: str, user_id: int | None = None) -> bool:
        """启动后台生成；该日期已在运行返回 False。"""
        with self._lock:
            if date_str in self._running:
                return False
            self._running.add(date_str)
            self._errors.pop(date_str, None)
        thread = threading.Thread(
            target=self._run, args=(date_str, user_id), daemon=True, name=f"plan-review-{date_str}",
        )
        thread.start()
        return True

    def _run(self, date_str: str, user_id: int | None = None) -> None:
        try:
            runner = self._runner or self._default_runner
            runner(date_str, user_id)
        except Exception as exc:  # noqa: BLE001 - 后台线程异常只落状态
            with self._lock:
                self._errors[date_str] = f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                self._running.discard(date_str)

    def status(self, date_str: str) -> dict:
        with self._lock:
            return {
                "date": date_str,
                "running": date_str in self._running,
                "error": self._errors.get(date_str),
            }


default_plan_review_manager = PlanReviewManager()


def get_plan_review_manager() -> PlanReviewManager:
    """依赖注入点：测试可 override 替换管理器。"""
    return default_plan_review_manager


def _serialize_plan_review(report: AIReport) -> dict:
    return {
        "id": report.id,
        "type": report.type,
        "date": report.period_start.isoformat() if report.period_start else None,
        "model": report.model,
        "prompt_tokens": report.prompt_tokens,
        "completion_tokens": report.completion_tokens,
        "cost_estimate": report.cost_estimate,
        "content_md": report.content_md,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.post("/review/{day}", status_code=202)
def start_plan_review(
    day: date,
    session: Session = Depends(get_session),
    manager: PlanReviewManager = Depends(get_plan_review_manager),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """手动触发某日计划点评（后台线程异步执行；无计划日 404 并给可读原因）。"""
    if plan_service.query_plan_day(session, day, user_id=current_user_id) is None:
        raise HTTPException(404, plan_service.plan_day_skip_reason(session, day))
    if not manager.start(day.isoformat(), user_id=current_user_id):
        raise HTTPException(409, "该日期的计划点评正在生成中")
    return {"status": "started", "date": day.isoformat()}


@router.get("/review/{day}/status")
def plan_review_status(
    day: date,
    manager: PlanReviewManager = Depends(get_plan_review_manager),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """轮询某日计划点评生成状态。"""
    return manager.status(day.isoformat())


@router.get("/review/{day}")
def get_plan_review(
    day: date,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """取某日最新一条 plan_review 报告，无则 404（当前用户）。"""
    report = (
        session.query(AIReport)
        .filter(AIReport.type == "plan_review", AIReport.period_start == day,
                AIReport.user_id == current_user_id)
        .order_by(AIReport.created_at.desc(), AIReport.id.desc())
        .first()
    )
    if report is None:
        raise HTTPException(404, "该日期暂无计划点评")
    return _serialize_plan_review(report)
