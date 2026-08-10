"""M5 手动触发同步 API；V2-7 加认证 + 异步化（后台线程 + 状态查询）。"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_auth
from app.services.sync_manager import SyncAlreadyRunningError

router = APIRouter(
    prefix="/api/sync", tags=["sync"],
    dependencies=[Depends(require_auth)],
)


def get_sync_manager():
    """依赖注入点：测试可 override 替换管理器。"""
    from app.services.sync_manager import default_manager

    return default_manager


@router.post("/{day}")
def trigger_sync(day: date, manager=Depends(get_sync_manager)) -> dict:
    """后台启动当日同步，立即返回 {"status": "started"}；运行中重复触发 409。"""
    try:
        return manager.start(day)
    except SyncAlreadyRunningError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/status")
def sync_status(manager=Depends(get_sync_manager)) -> dict:
    """当前/最近一次同步状态：running / success / failed + 结果摘要 + 错误。"""
    return manager.status()
