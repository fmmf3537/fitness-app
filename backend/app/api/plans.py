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
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.models import AIReport, ExerciseMapping, ExerciseMappingCandidate
from app.services import ai as ai_service
from app.services import exercise_mapping as mapping_service
from app.services import garmin_plan_sync as garmin_sync_service
from app.services import garmin_reschedule as garmin_reschedule_service
from app.services import plans as plan_service
from app.services.garmin_workout_mapper import (
    WorkoutMappingError,
    map_plan_day,
    source_hash,
)

router = APIRouter(
    prefix="/api/plans",
    tags=["plans"],
    dependencies=[Depends(require_auth)],
)


@router.get("/garmin/reschedules")
def list_garmin_reschedules(session: Session = Depends(get_session)) -> dict:
    """列出顺延候选；只用本地数据，可恢复超时状态，零 Garmin 请求。"""
    from app.services.garmin_reschedule import list_reschedule_candidates

    items = list_reschedule_candidates(session)
    return {"count": len(items), "items": items}


def _record_for_plan_day(
    session: Session,
    plan_ref: str,
    training_date: date,
    records: dict | None = None,
):
    record = (
        records.get((plan_ref, training_date))
        if records is not None
        else garmin_sync_service.get_sync_record(
            session, plan_ref=plan_ref, training_date=training_date
        )
    )
    if record is None:
        record = garmin_sync_service.get_pending_reschedule_for_target(
            session, plan_ref=plan_ref, target_date=training_date
        )
    return record


@router.get("/upcoming")
def upcoming_plans(
    days: int = Query(default=30, ge=1, le=90),
    session: Session = Depends(get_session),
) -> dict:
    """未来 N 天计划与同步摘要；只用本地数据，可恢复超时状态。"""
    start = date.today()
    end = start + timedelta(days=days - 1)
    plan_days = plan_service.query_plan_days(
        session, start, days=days, include_source=True
    )
    records = garmin_sync_service.get_sync_records(session, start=start, end=end)
    for item in plan_days:
        source = item.pop("_garmin_source", None)
        if source is None:
            item["garmin_sync"] = None
            continue
        training_date = date.fromisoformat(source["date"])
        current_hash = source_hash(source)
        source_key = garmin_sync_service.source_key_for(
            source["plan_ref"], training_date
        )
        record = _record_for_plan_day(
            session, source["plan_ref"], training_date, records
        )
        item["garmin_sync"] = garmin_sync_service.sync_status_view(
            record, source_key=source_key, source_hash=current_hash
        )
    return {"from": start.isoformat(), "to": end.isoformat(), "days": plan_days}


def _require_plan_day(session: Session, day: date) -> dict:
    plan_day = plan_service.query_plan_day(session, day)
    if plan_day is None:
        raise HTTPException(404, plan_service.plan_day_skip_reason(session, day))
    return plan_day


def _pending_review_for_plan_day(session: Session, plan_day: dict) -> list[dict]:
    """本训练日中 status=draft 且有 rank-1 候选的动作，供 V6-6b 引导弹窗。"""
    names = [
        str(m.get("name") or "").strip()
        for m in (plan_day.get("movements") or [])
    ]
    names = [n for n in names if n]
    if not names:
        return []
    draft_rows = session.scalars(
        select(ExerciseMapping).where(
            ExerciseMapping.xunji_name.in_(names),
            ExerciseMapping.status == "draft",
        )
    ).all()
    if not draft_rows:
        return []
    result: list[dict] = []
    for row in draft_rows:
        candidate = session.scalars(
            select(ExerciseMappingCandidate)
            .where(ExerciseMappingCandidate.xunji_name == row.xunji_name)
            .order_by(
                ExerciseMappingCandidate.rank.asc(),
                ExerciseMappingCandidate.id.asc(),
            )
            .limit(1)
        ).first()
        if candidate is None:
            continue
        result.append(
            {
                "xunji_name": row.xunji_name,
                "suggested_category": candidate.garmin_category,
                "suggested_exercise": candidate.garmin_exercise_name,
            }
        )
    return result


def _preview_mappings(mappings: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """预览不阻断 draft（§7.3 能看）；写入路径仍用原始 load_all_mappings 拒绝。"""
    softened: dict[str, dict[str, Any]] = {}
    for name, item in mappings.items():
        if item.get("status") == "draft":
            softened[name] = {**item, "status": "active"}
        else:
            softened[name] = item
    return softened


def _current_sync_status(session: Session, plan_day: dict) -> dict:
    training_date = date.fromisoformat(plan_day["date"])
    current_hash = source_hash(plan_day)
    source_key = garmin_sync_service.source_key_for(
        plan_day["plan_ref"], training_date
    )
    record = _record_for_plan_day(session, plan_day["plan_ref"], training_date)
    return garmin_sync_service.sync_status_view(
        record, source_key=source_key, source_hash=current_hash
    )


class GarminRescheduleRequest(BaseModel):
    """顺延确认必须绑定目标日期和用户实际看到的目标来源哈希。"""

    to_date: date
    source_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


def _reschedule_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkoutMappingError):
        return HTTPException(
            status_code=422,
            detail={"code": "PLAN_MAPPING_UNSUPPORTED", "issues": exc.issues},
        )
    if isinstance(exc, garmin_sync_service.PlanSyncError):
        detail = {"code": exc.error_code, "message": exc.public_message}
        if exc.issues:
            detail["issues"] = exc.issues
        return HTTPException(status_code=exc.status_code, detail=detail)
    raise exc


@router.get("/{day}/garmin/reschedule")
def preview_garmin_reschedule(
    day: date,
    to_date: date = Query(...),
    session: Session = Depends(get_session),
) -> dict:
    """预览原 Workout 保留、内容更新和原日程改期；零 Garmin 请求。"""
    try:
        return garmin_reschedule_service.preview_reschedule(
            session, from_date=day, target_date=to_date
        )
    except (WorkoutMappingError, garmin_sync_service.PlanSyncError) as exc:
        raise _reschedule_http_error(exc) from exc


@router.post("/{day}/garmin/reschedule")
def confirm_garmin_reschedule(
    day: date,
    body: GarminRescheduleRequest,
    response: Response,
    session: Session = Depends(get_session),
    manager: garmin_reschedule_service.GarminRescheduleManager = Depends(
        garmin_reschedule_service.get_garmin_reschedule_manager
    ),
) -> dict:
    """确认原 Workout 更新和原日程改期；202 启动，成功重放 200。"""
    from app.config import get_settings

    try:
        result = manager.start(
            session,
            from_date=day,
            target_date=body.to_date,
            expected_source_hash=body.source_hash,
            enabled=get_settings().garmin_plan_sync_enabled,
        )
    except (WorkoutMappingError, garmin_sync_service.PlanSyncError) as exc:
        raise _reschedule_http_error(exc) from exc
    response.status_code = 202 if result["started"] else 200
    return result


@router.get("/{day}/garmin/preview")
def preview_garmin_plan(
    day: date,
    session: Session = Depends(get_session),
) -> dict:
    """生成完整本地 Workout 预览；不落同步记录，不访问 Garmin。"""
    plan_day = _require_plan_day(session, day)
    mappings = mapping_service.load_all_mappings(session)
    pending_review = _pending_review_for_plan_day(session, plan_day)
    try:
        preview = map_plan_day(plan_day, mappings=_preview_mappings(mappings))
    except WorkoutMappingError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "PLAN_MAPPING_UNSUPPORTED", "issues": exc.issues},
        ) from exc
    from app.config import get_settings

    return {
        **preview,
        "remote_write_eligible": get_settings().garmin_plan_sync_enabled,
        "sync": _current_sync_status(session, plan_day),
        "pending_review": pending_review,
    }


@router.get("/{day}/garmin/sync")
def get_garmin_plan_sync(
    day: date,
    session: Session = Depends(get_session),
) -> dict:
    """查询当前计划相对本地同步记录的状态，不触发任何远端操作。"""
    plan_day = _require_plan_day(session, day)
    return _current_sync_status(session, plan_day)


class GarminPlanSyncRequest(BaseModel):
    """确认必须携带用户实际看到的预览哈希，防止按计划变化前的旧预览覆盖。"""

    source_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


@router.post("/{day}/garmin/sync")
def confirm_garmin_plan_sync(
    day: date,
    body: GarminPlanSyncRequest,
    response: Response,
    session: Session = Depends(get_session),
    manager: garmin_sync_service.GarminPlanSyncManager = Depends(
        garmin_sync_service.get_garmin_plan_sync_manager
    ),
) -> dict:
    """确认创建/覆盖应用管理的训练；202 后台执行，已同步则 200 幂等返回。"""
    from app.config import get_settings

    plan_day = _require_plan_day(session, day)
    try:
        result = manager.start(
            session,
            plan_day,
            expected_source_hash=body.source_hash,
            enabled=get_settings().garmin_plan_sync_enabled,
        )
    except WorkoutMappingError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "PLAN_MAPPING_UNSUPPORTED", "issues": exc.issues},
        ) from exc
    except garmin_sync_service.PlanSyncError as exc:
        detail = {"code": exc.error_code, "message": exc.public_message}
        if exc.issues:
            detail["issues"] = exc.issues
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    response.status_code = 202 if result["started"] else 200
    return result


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
) -> dict:
    """手动触发计划缓存刷新（后台线程执行 sync_plan_cache，立即返回 202）。"""
    try:
        return manager.start()
    except PlanRefreshAlreadyRunningError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/refresh/status")
def refresh_status(
    manager: PlanRefreshManager = Depends(get_plan_refresh_manager),
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
    def _default_runner(date_str: str) -> None:
        from app.db import SessionLocal

        session = SessionLocal()
        try:
            ai_service.generate_plan_review(session, date_str)
        finally:
            session.close()

    def start(self, date_str: str) -> bool:
        """启动后台生成；该日期已在运行返回 False。"""
        with self._lock:
            if date_str in self._running:
                return False
            self._running.add(date_str)
            self._errors.pop(date_str, None)
        thread = threading.Thread(
            target=self._run, args=(date_str,), daemon=True, name=f"plan-review-{date_str}",
        )
        thread.start()
        return True

    def _run(self, date_str: str) -> None:
        try:
            runner = self._runner or self._default_runner
            runner(date_str)
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
) -> dict:
    """手动触发某日计划点评（后台线程异步执行；无计划日 404 并给可读原因）。"""
    if plan_service.query_plan_day(session, day) is None:
        raise HTTPException(404, plan_service.plan_day_skip_reason(session, day))
    if not manager.start(day.isoformat()):
        raise HTTPException(409, "该日期的计划点评正在生成中")
    return {"status": "started", "date": day.isoformat()}


@router.get("/review/{day}/status")
def plan_review_status(
    day: date,
    manager: PlanReviewManager = Depends(get_plan_review_manager),
) -> dict:
    """轮询某日计划点评生成状态。"""
    return manager.status(day.isoformat())


@router.get("/review/{day}")
def get_plan_review(
    day: date,
    session: Session = Depends(get_session),
) -> dict:
    """取某日最新一条 plan_review 报告，无则 404。"""
    report = (
        session.query(AIReport)
        .filter(AIReport.type == "plan_review", AIReport.period_start == day)
        .order_by(AIReport.created_at.desc(), AIReport.id.desc())
        .first()
    )
    if report is None:
        raise HTTPException(404, "该日期暂无计划点评")
    return _serialize_plan_review(report)
