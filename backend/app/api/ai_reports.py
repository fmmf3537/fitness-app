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
    date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: Session = Depends(get_session),
) -> dict:
    """获取某日全部 AI 报告。"""
    day = datetime.date.fromisoformat(date)
    rows = (
        session.query(AIReport)
        .filter(AIReport.period_start == day, AIReport.type == "session_review")
        .order_by(AIReport.created_at.desc())
        .all()
    )
    return {"date": date, "reports": [_serialize_report(session, r) for r in rows]}


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
