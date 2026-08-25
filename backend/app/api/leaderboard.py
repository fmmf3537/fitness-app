"""M5-2 排行榜 API：GET /api/leaderboard?metric=&window=。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db import get_session
from app.models import User
from app.services import leaderboard as lb

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("")
def list_leaderboard(
    metric: str = Query(..., pattern="^(frequency|volume|calories|streak)$"),
    window: str = Query(..., pattern="^(7d|30d)$"),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
) -> dict:
    """返回 metric × window 排行榜（优先 cache；未命中则实时计算，不写 cache）。"""
    if metric not in lb.METRICS:
        raise HTTPException(status_code=400, detail=f"非法 metric：{metric}")
    if window not in lb.WINDOWS:
        raise HTTPException(status_code=400, detail=f"非法 window：{window}")

    cached_row = lb.get_cached_row(session, metric, window)
    if cached_row is not None:
        entries = lb.get_cached(session, metric, window) or []
        return {
            "metric": metric,
            "window": window,
            "computed_at": cached_row.computed_at.isoformat() if cached_row.computed_at else None,
            "entries": entries,
            "from_cache": True,
        }

    days = lb.WINDOW_DAYS[window]
    entries = lb.compute_metric(session, metric, days)
    return {
        "metric": metric,
        "window": window,
        "computed_at": None,
        "entries": entries,
        "from_cache": False,
    }
