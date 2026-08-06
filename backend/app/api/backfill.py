"""V1-2 历史导入 API：POST /api/backfill/start 启动后台导入，GET /api/backfill/status 查进度。"""
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/backfill", tags=["backfill"])


def get_backfill_manager():
    """依赖注入点：测试可 override 替换管理器。"""
    from app.services.backfill import default_manager

    return default_manager


@router.post("/start")
def start_backfill(manager=Depends(get_backfill_manager)) -> dict:
    return manager.start()


@router.get("/status")
def backfill_status(manager=Depends(get_backfill_manager)) -> dict:
    return manager.status()
