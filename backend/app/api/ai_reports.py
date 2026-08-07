"""V1-3 AI 报告 API：按日期查询单次训练点评。"""
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.models import AIReport, Workout

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
