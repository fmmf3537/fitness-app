"""V3-6 海报数据装配端点。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.models import AIReport
from app.services.poster import build_poster_data

router = APIRouter(
    prefix="/api/posters",
    tags=["posters"],
    dependencies=[Depends(require_auth)],
)


@router.get("/data")
def poster_data(report_id: int, session: Session = Depends(get_session)) -> dict:
    """一次装配分享海报全部数据（report + workout 摘要 + PR 明细 + 本周计数）。"""
    report = session.get(AIReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return build_poster_data(session, report)
