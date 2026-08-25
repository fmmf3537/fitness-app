"""V2-3 截图识别补录 API：extract 只识别不落库；confirm 校验后入库并重跑当日匹配。"""
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.llm import LLMError
from app.api.auth import get_current_user_id
from app.db import get_session
from app.services.screenshot import ExtractionError, confirm_import, extract_from_image

router = APIRouter(
    prefix="/api/screenshot", tags=["screenshot"],
)

MAX_IMAGES = 9
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}


class ConfirmRequest(BaseModel):
    """确认入库请求：用户编辑修正后的识别结果。"""

    datestr: str
    title: str
    movements: list[dict[str, Any]]
    start_time: str | None = None
    end_time: str | None = None
    duration_s: float | None = None
    calories: float | None = None


@router.post("/extract")
async def screenshot_extract(
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """多图识别：逐张调视觉模型 + Schema 校验（失败自动重试 1 次），结果不落库。"""
    if not files:
        raise HTTPException(status_code=422, detail="未上传文件")
    if len(files) > MAX_IMAGES:
        raise HTTPException(status_code=422, detail=f"单次最多 {MAX_IMAGES} 张")
    for f in files:
        if (f.content_type or "") not in ALLOWED_MIME:
            raise HTTPException(status_code=422, detail=f"不支持的文件类型：{f.filename}")

    results = []
    for f in files:
        content = await f.read()
        if len(content) > MAX_IMAGE_BYTES:
            results.append({"filename": f.filename, "ok": False, "error": "图片超过 10MB"})
            continue
        try:
            data = extract_from_image(content, session=session, mime=f.content_type)
            results.append({"filename": f.filename, "ok": True, "data": data})
        except ExtractionError as exc:
            results.append({"filename": f.filename, "ok": False, "error": str(exc)})
        except LLMError as exc:
            results.append({"filename": f.filename, "ok": False, "error": f"模型调用失败：{exc}"})
    return {"results": results}


@router.post("/confirm")
def screenshot_confirm(
    req: ConfirmRequest,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """用户确认入库：写 xunji_train 并重跑当日匹配（match_status 按现有规则）。"""
    try:
        return confirm_import(session, req.model_dump(exclude_none=True), user_id=current_user_id)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
