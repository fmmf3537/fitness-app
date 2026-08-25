"""V1-2 历史导入 API：POST /api/backfill/start 启动后台导入，GET /api/backfill/status 查进度。"""
from fastapi import APIRouter, Depends

from app.api.auth import get_current_user_id

router = APIRouter(
    prefix="/api/backfill", tags=["backfill"],
)


def get_backfill_manager():
    """依赖注入点：测试可 override 替换管理器。"""
    from app.services.backfill import default_manager

    return default_manager


@router.post("/start")
def start_backfill(
    manager=Depends(get_backfill_manager),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    return manager.start(user_id=current_user_id)


@router.get("/status")
def backfill_status(
    manager=Depends(get_backfill_manager),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    return manager.status()
