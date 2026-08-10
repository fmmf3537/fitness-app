"""V1-3 AI 报告 API：按日期查询单次训练点评；V2-2 复盘生成/状态/导出。"""
import datetime
import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.models import AIReport, Workout
from app.services import ai as ai_service
from app.services import export as export_service

router = APIRouter(
    prefix="/api/ai-reports",
    tags=["ai-reports"],
    dependencies=[Depends(require_auth)],
)


def _serialize_report(session: Session, report: AIReport) -> dict:
    workout = session.get(Workout, report.workout_id) if report.workout_id else None
    return {
        "id": report.id,
        "type": report.type,
        "workout_id": report.workout_id,
        "date": report.period_start.isoformat() if report.period_start else None,
        "period_end": report.period_end.isoformat() if report.period_end else None,
        "workout_title": workout.title if workout else None,
        "model": report.model,
        "prompt_tokens": report.prompt_tokens,
        "completion_tokens": report.completion_tokens,
        "cost_estimate": report.cost_estimate,
        "content_md": report.content_md,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("")
def list_ai_reports(
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    type: str | None = Query(default=None, pattern=r"^(session_review|next_advice|weekly|monthly)$"),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict:
    """提供 date 时获取某日报告（V1-3 行为不变，type 缺省 session_review）；
    省略 date 时返回最近报告列表（created_at 倒序，limit 上限 100）。"""
    if date is not None:
        day = datetime.date.fromisoformat(date)
        report_type = type or "session_review"
        rows = (
            session.query(AIReport)
            .filter(AIReport.period_start == day, AIReport.type == report_type)
            .order_by(AIReport.created_at.desc())
            .all()
        )
        return {"date": date, "reports": [_serialize_report(session, r) for r in rows]}
    query = session.query(AIReport)
    if type:
        query = query.filter(AIReport.type == type)
    rows = (
        query.order_by(AIReport.created_at.desc(), AIReport.id.desc())
        .limit(limit)
        .all()
    )
    return {"reports": [_serialize_report(session, r) for r in rows]}


@router.get("/{report_id}")
def get_ai_report(
    report_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """获取单条 AI 报告详情。"""
    report = session.get(AIReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return _serialize_report(session, report)


# =====================================================================
# V2-2 周/月复盘：手动生成（后台线程）/ 状态轮询 / 导出
# =====================================================================


class ReviewGenerateManager:
    """复盘生成管理器：后台线程执行 + 运行状态跟踪（单用户单进程）。

    runners 可注入 {"weekly": fn, "monthly": fn}（fn 接受 day_str 参数），
    便于测试同步执行；默认 runner 自建 session 调 services.ai 编排函数。
    """

    def __init__(self, runners: dict | None = None):
        self._runners = runners or {}
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._errors: dict[str, str] = {}

    @staticmethod
    def _default_runner(rtype: str, day_str: str | None) -> None:
        from app.db import SessionLocal

        session = SessionLocal()
        try:
            if rtype == "weekly":
                ai_service.run_weekly_review(day_str, session=session)
            else:
                ai_service.run_monthly_review(day_str, session=session)
        finally:
            session.close()

    def start(self, rtype: str, day_str: str | None = None) -> bool:
        """启动后台生成；已在运行返回 False。"""
        with self._lock:
            if rtype in self._running:
                return False
            self._running.add(rtype)
            self._errors.pop(rtype, None)
        thread = threading.Thread(target=self._run, args=(rtype, day_str), daemon=True)
        thread.start()
        return True

    def _run(self, rtype: str, day_str: str | None) -> None:
        try:
            runner = self._runners.get(rtype)
            if runner is not None:
                runner(day_str)
            else:
                self._default_runner(rtype, day_str)
        except Exception as exc:  # 服务层已兜底，这里防御性记录
            self._errors[rtype] = str(exc)
        finally:
            with self._lock:
                self._running.discard(rtype)

    def is_running(self, rtype: str) -> bool:
        with self._lock:
            return rtype in self._running

    def last_error(self, rtype: str) -> str | None:
        return self._errors.get(rtype)


default_review_manager = ReviewGenerateManager()


def get_review_manager() -> ReviewGenerateManager:
    """依赖注入点：测试可 override 替换管理器。"""
    return default_review_manager


class GenerateRequest(BaseModel):
    type: Literal["weekly", "monthly"]
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/generate")
def generate_review(
    payload: GenerateRequest,
    session: Session = Depends(get_session),
    manager: ReviewGenerateManager = Depends(get_review_manager),
) -> dict:
    """手动触发周/月复盘生成（后台线程异步执行，前端轮询 /generate/status）。

    幂等：目标周期已存在报告时直接返回 exists，不重复生成。
    """
    day = datetime.date.fromisoformat(payload.date) if payload.date else datetime.date.today()
    range_fn = ai_service.week_range if payload.type == "weekly" else ai_service.month_range
    start, end = range_fn(day)
    existing = session.scalars(
        select(AIReport).where(
            AIReport.type == payload.type,
            AIReport.period_start == start,
        )
    ).first()
    if existing is not None:
        return {"status": "exists", "report": _serialize_report(session, existing)}
    if not manager.start(payload.type, payload.date):
        raise HTTPException(status_code=409, detail="该类型复盘正在生成中")
    return {
        "status": "started",
        "type": payload.type,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    }


@router.get("/generate/status")
def generate_status(
    type: str = Query(pattern=r"^(weekly|monthly)$"),
    session: Session = Depends(get_session),
    manager: ReviewGenerateManager = Depends(get_review_manager),
) -> dict:
    """轮询生成状态：running + 最新一条该类型报告 + 最近错误。"""
    report = (
        session.query(AIReport)
        .filter(AIReport.type == type)
        .order_by(AIReport.created_at.desc(), AIReport.id.desc())
        .first()
    )
    return {
        "type": type,
        "running": manager.is_running(type),
        "error": manager.last_error(type),
        "report": _serialize_report(session, report) if report else None,
    }


@router.get("/{report_id}/export")
def export_report(
    report_id: int,
    format: str = Query(pattern=r"^(md|pdf)$"),
    session: Session = Depends(get_session),
) -> Response:
    """导出报告为 Markdown 或 PDF（附件下载）。"""
    report = session.get(AIReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    filename = export_service.report_filename(report, format)
    if format == "md":
        return Response(
            content=export_service.render_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return Response(
        content=export_service.render_pdf(report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
