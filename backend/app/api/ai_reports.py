"""V1-3 AI 报告 API：按日期查询单次训练点评；V2-2 复盘生成/状态/导出；
V3-4 评分字段透出 + session_review 重新生成；V3-8 报告追问对话。"""
import datetime
import json
import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, get_current_user_id, resolve_viewer
from app.db import get_session
from app.models import AIReport, User, Workout
from app.services import ai as ai_service
from app.services import export as export_service
from app.services import report_chat as report_chat_service

router = APIRouter(
    prefix="/api/ai-reports",
    tags=["ai-reports"],
)


def _serialize_report(session: Session, report: AIReport) -> dict:
    workout = session.get(Workout, report.workout_id) if report.workout_id else None
    if workout is not None and workout.deleted_at is not None:
        workout = None  # V3-11：已删除训练不随报告展示
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
        "score": report.score,
        "one_liner": report.one_liner,
        "subscores": _parse_subscores(report.subscores_json),
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


def _parse_subscores(subscores_json: str | None) -> dict | None:
    if not subscores_json:
        return None
    try:
        data = json.loads(subscores_json)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


@router.get("")
def list_ai_reports(
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    type: str | None = Query(default=None, pattern=r"^(session_review|next_advice|weekly|monthly)$"),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    principal: User = Depends(get_current_user),
    override_user_id: int | None = Query(default=None, alias="user_id"),
) -> dict:
    """提供 date 时获取某日报告（V1-3 行为不变，type 缺省 session_review）；
    省略 date 时返回最近报告列表（created_at 倒序，limit 上限 100）。"""
    if date is not None:
        day = datetime.date.fromisoformat(date)
        report_type = type or "session_review"
        rows = (
            session.query(AIReport)
            .filter(            AIReport.period_start == day, AIReport.type == report_type,
                    AIReport.user_id == resolve_viewer(principal, override_user_id))
            .order_by(AIReport.created_at.desc())
            .all()
        )
        return {"date": date, "reports": [_serialize_report(session, r) for r in rows]}
    query = session.query(AIReport).filter(AIReport.user_id == resolve_viewer(principal, override_user_id))
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
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """获取单条 AI 报告详情。"""
    report = session.get(AIReport, report_id)
    if report is None or report.user_id != current_user_id:
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
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """手动触发周/月复盘生成（后台线程异步执行，前端轮询 /generate/status）。

    幂等：目标周期已存在报告时直接返回 exists，不重复生成（按当前用户隔离）。
    """
    day = datetime.date.fromisoformat(payload.date) if payload.date else datetime.date.today()
    range_fn = ai_service.week_range if payload.type == "weekly" else ai_service.month_range
    start, end = range_fn(day)
    existing = session.scalars(
        select(AIReport).where(
            AIReport.type == payload.type,
            AIReport.period_start == start,
            AIReport.user_id == current_user_id,
        )
    ).first()
    if existing is not None:
        return {"status": "exists", "report": _serialize_report(session, existing)}
    if not manager.start(payload.type, payload.date, user_id=current_user_id):
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
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """轮询生成状态：running + 最新一条该类型报告（当前用户）+ 最近错误。"""
    report = (
        session.query(AIReport)
        .filter(AIReport.type == type, AIReport.user_id == current_user_id)
        .order_by(AIReport.created_at.desc(), AIReport.id.desc())
        .first()
    )
    return {
        "type": type,
        "running": manager.is_running(type),
        "error": manager.last_error(type),
        "report": _serialize_report(session, report) if report else None,
    }


# =====================================================================
# V3-4 session_review 重新生成（存量无评分报告）：删旧 + run_daily_reviews
# =====================================================================


class SessionReviewRegenManager:
    """session_review 重新生成管理器：后台线程执行 + 按日期防重（单用户单进程）。

    runner 可注入（接受 day_str 参数），便于测试同步执行；
    默认 runner 自建 session：删当日旧 session_review 后调 run_daily_reviews。
    """

    def __init__(self, runner=None):
        self._runner = runner
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._errors: dict[str, str] = {}

    @staticmethod
    def _default_runner(day_str: str) -> None:
        from app.db import SessionLocal

        session = SessionLocal()
        try:
            ai_service.regenerate_session_reviews(session, day_str)
        finally:
            session.close()

    def start(self, day_str: str) -> bool:
        """启动后台重新生成；该日期已在运行返回 False。"""
        with self._lock:
            if day_str in self._running:
                return False
            self._running.add(day_str)
            self._errors.pop(day_str, None)
        thread = threading.Thread(target=self._run, args=(day_str,), daemon=True)
        thread.start()
        return True

    def _run(self, day_str: str) -> None:
        try:
            runner = self._runner or self._default_runner
            runner(day_str)
        except Exception as exc:  # 服务层已兜底，这里防御性记录
            self._errors[day_str] = str(exc)
        finally:
            with self._lock:
                self._running.discard(day_str)

    def is_running(self, day_str: str) -> bool:
        with self._lock:
            return day_str in self._running

    def last_error(self, day_str: str) -> str | None:
        return self._errors.get(day_str)


default_session_review_regen_manager = SessionReviewRegenManager()


def get_session_review_regen_manager() -> SessionReviewRegenManager:
    """依赖注入点：测试可 override 替换管理器。"""
    return default_session_review_regen_manager


class RegenerateRequest(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/session-review/regenerate")
def regenerate_session_review(
    payload: RegenerateRequest,
    manager: SessionReviewRegenManager = Depends(get_session_review_regen_manager),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """重新生成某日单次点评（后台线程异步执行，前端轮询 status）。

    删除当日旧 session_review 后调 run_daily_reviews；并发冲突返回 409。
    """
    datetime.date.fromisoformat(payload.date)  # 防御性校验日期合法性
    if not manager.start(payload.date):
        raise HTTPException(status_code=409, detail="该日期点评正在重新生成中")
    return {"status": "started", "date": payload.date}


@router.get("/session-review/regenerate/status")
def regenerate_session_review_status(
    date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    manager: SessionReviewRegenManager = Depends(get_session_review_regen_manager),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """轮询重新生成状态：running + 最近错误。"""
    return {
        "date": date,
        "running": manager.is_running(date),
        "error": manager.last_error(date),
    }


# =====================================================================
# V3-8 报告追问对话：GET 历史 / POST 发送（同步返回两条消息）
# =====================================================================


class ChatMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=report_chat_service.MAX_CONTENT_LENGTH)
    client_request_id: str = Field(min_length=1, max_length=64)


def _serialize_message(msg) -> dict:
    return {
        "id": msg.id,
        "report_id": msg.report_id,
        "role": msg.role,
        "content": msg.content,
        "model": msg.model,
        "prompt_tokens": msg.prompt_tokens,
        "completion_tokens": msg.completion_tokens,
        "cost_estimate": msg.cost_estimate,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.get("/{report_id}/messages")
def list_report_messages(
    report_id: int,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """该报告的追问对话历史（按时间正序）。"""
    report = session.get(AIReport, report_id)
    if report is None or report.user_id != current_user_id:
        raise HTTPException(status_code=404, detail="报告不存在") from None
    try:
        messages = report_chat_service.list_messages(session, report_id)
    except report_chat_service.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="报告不存在") from None
    return {"messages": [_serialize_message(m) for m in messages]}


@router.post("/{report_id}/messages")
def post_report_message(
    report_id: int,
    payload: ChatMessageRequest,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """发送追问消息：落用户消息 → 调 LLM → 落 assistant 回复，同步返回两条。

    幂等：client_request_id 重放时直接返回已落库消息对，不重复调 LLM。
    """
    report = session.get(AIReport, report_id)
    if report is None or report.user_id != current_user_id:
        raise HTTPException(status_code=404, detail="报告不存在") from None
    if not payload.content.strip():
        raise HTTPException(status_code=422, detail="消息内容不能为空")
    try:
        user_msg, assistant_msg = report_chat_service.post_message(
            session, report_id, payload.content, payload.client_request_id
        )
    except report_chat_service.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="报告不存在") from None
    except report_chat_service.ChatMessageLimitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {
        "user_message": _serialize_message(user_msg),
        "assistant_message": _serialize_message(assistant_msg),
    }


@router.get("/{report_id}/export")
def export_report(
    report_id: int,
    format: str = Query(pattern=r"^(md|pdf)$"),
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> Response:
    """导出报告为 Markdown 或 PDF（附件下载）。"""
    report = session.get(AIReport, report_id)
    if report is None or report.user_id != current_user_id:
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
