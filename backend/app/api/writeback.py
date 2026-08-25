"""V1-5 训记写回确认流 API：preview 生成 diff（只读），confirm 执行真实写回。"""
from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.xunji import XunjiAPIError
from app.api.auth import get_current_user_id
from app.db import get_session
from app.services.writeback import (
    WritebackNotFoundError,
    WritebackService,
    WritebackValidationError,
)

router = APIRouter(
    prefix="/api/writeback", tags=["writeback"],
)


class WritebackRequest(BaseModel):
    """写回请求：目标训练 + 变更集（title / movements，服务端合并保留元数据）。"""

    datestr: str
    localid: Union[int, str]
    changes: dict[str, Any]


def get_writeback_service(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> WritebackService:
    """依赖注入点：测试可 override 替换写回服务。"""
    return WritebackService(session, user_id=current_user_id)


def _handle_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, WritebackValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, WritebackNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, XunjiAPIError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=f"写回失败: {exc}")


@router.post("/preview")
def writeback_preview(
    req: WritebackRequest,
    service: WritebackService = Depends(get_writeback_service),
) -> dict:
    """生成「原值 → 新值」diff（只读原训练，绝不调用写回接口）。"""
    try:
        return service.preview(req.datestr, req.localid, req.changes)
    except Exception as exc:
        raise _handle_errors(exc) from exc


@router.post("/confirm")
def writeback_confirm(
    req: WritebackRequest,
    service: WritebackService = Depends(get_writeback_service),
) -> dict:
    """用户确认后执行真实写回（45s 限频排队），成功覆盖缓存并重跑当日融合。"""
    try:
        return service.confirm(req.datestr, req.localid, req.changes)
    except Exception as exc:
        raise _handle_errors(exc) from exc
