"""V2-4 佳明 FIT/TCX 手动导入 API（接口失效降级通道，PRD §6.2 /import/fit）。

V3-7 扩展 GPX/KML：上传 .fit/.tcx/.gpx/.kml 文件 → 解析落库 garmin_activity → 触发当日重匹配 → 返回融合结果。
"""
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.garmin_adapter import FitImportError, import_fit_file
from app.api.auth import get_current_user_id
from app.db import get_session
from app.models import Workout

router = APIRouter(
    prefix="/api/import", tags=["import"],
)

ALLOWED_SUFFIXES = {".fit", ".tcx", ".gpx", ".kml"}
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50MB


@router.post("/fit")
async def import_fit(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=422,
                            detail=f"不支持的文件类型：{suffix or '(无后缀)'}（仅支持 .fit / .tcx / .gpx / .kml）")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="文件内容为空")
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=422, detail="文件超过 50MB")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        result = import_fit_file(session, tmp_path, user_id=current_user_id)
    except FitImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    activity = result["activity"]
    # 跨用户隔离：仅当导入的活动属于当前用户时才关联其 workout
    workout = session.scalars(
        select(Workout).where(
            Workout.garmin_activity_id == activity.id,
            Workout.user_id == current_user_id,
            Workout.deleted_at.is_(None),
        )
    ).first()
    return {
        "ok": True,
        "activity_id": activity.activity_id,
        "date": activity.start_ts.date().isoformat(),
        "activity_type": activity.activity_type,
        "match_status": workout.match_status if workout else None,
        "workout_id": workout.id if workout else None,
    }
