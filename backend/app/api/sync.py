"""M5 手动触发同步 API。"""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.sync import daily_sync

router = APIRouter(prefix="/api", tags=["sync"])


def get_sync_fn():
    """依赖注入点：测试可 override 替换同步函数。"""
    return daily_sync


@router.post("/sync/{day}")
def trigger_sync(day: date, session: Session = Depends(get_session),
                 sync_fn=Depends(get_sync_fn)) -> dict:
    return sync_fn(day, session=session)
