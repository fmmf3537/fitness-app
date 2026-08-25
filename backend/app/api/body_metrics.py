"""V1-7 身体数据 API（PRD US-12）。

- POST /api/body-metrics：录入，按 (date, type) upsert；
- GET /api/body-metrics?type=&from=&to=：趋势查询；
- POST /api/body-metrics/{id}/sync-xunji：同步训记三段式
  （dry_run 预览取 res.summary → 用户确认 confirmed=True 执行 → 置 synced_to_xunji）；
  身高/血压/血糖仅本地，一律 400 拒绝。
- V3-9：POST /api/body-metrics/extract-image 体脂秤报告图片识别（不落库）；
  POST /api/body-metrics/confirm-import 用户确认后批量入库（幂等 upsert，可勾选同步训记）。
"""
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.llm import LLMError
from app.adapters.xunji import XunjiAPIError
from app.adapters.xunji_body import XunjiBodyClient
from app.api.auth import get_current_user, get_current_user_id, resolve_viewer
from app.db import get_session
from app.models import BodyMetric, User
from app.services import body_metrics as body_metrics_service
from app.services.body_image import confirm_import as confirm_body_image_import
from app.services.body_image import extract_from_image as extract_body_image
from app.services.body_metrics import BodyMetricValidationError, SYNCABLE_TYPES
from app.services.screenshot import ExtractionError

router = APIRouter(
    prefix="/api/body-metrics",
    tags=["body-metrics"],
)


def get_body_client(session: Session = Depends(get_session)) -> XunjiBodyClient:
    """依赖注入点：测试可 override 替换训记身体数据客户端。"""
    return XunjiBodyClient(session)


def get_body_client_lazy(session: Session = Depends(get_session)) -> XunjiBodyClient | None:
    """V3-9 图片导入用：未配置 XUNJI_BODY_API_KEY 时返回 None（仅勾选同步时才需要）。"""
    try:
        return XunjiBodyClient(session)
    except RuntimeError:
        return None


class BodyMetricCreate(BaseModel):
    """录入请求：date + type + value，unit/note 可选。"""

    date: str
    type: str
    value: float
    unit: str | None = None
    note: str | None = None


class SyncRequest(BaseModel):
    """同步请求：缺省为 dry_run 预览；confirmed=True 才真实写入。"""

    confirmed: bool = False


# ---- V3-9 体脂秤图片导入 ----

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png"}


class ImportMetricItem(BaseModel):
    """确认入库的单条指标：selected=false 跳过。"""

    type: str
    value: Any
    selected: bool = True


class ConfirmImportRequest(BaseModel):
    """图片识别结果确认入库请求（用户可编辑日期/数值、逐条勾选）。"""

    date: str
    metrics: list[ImportMetricItem]
    sync_xunji: bool = False


def _parse_date(raw: str, field: str = "date") -> date:
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"{field} 日期格式非法: {raw!r}") from exc


@router.post("")
def create_body_metric(
    req: BodyMetricCreate,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """录入身体数据：同日同类型覆盖旧值（upsert 幂等）。"""
    day = _parse_date(req.date)
    try:
        row = body_metrics_service.upsert_body_metric(
            session, day, req.type, req.value, unit=req.unit, note=req.note,
            user_id=current_user_id,
        )
    except BodyMetricValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return body_metrics_service.to_dict(row)


@router.get("")
def list_body_metrics(
    type: str | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    session: Session = Depends(get_session),
    principal: User = Depends(get_current_user),
    override_user_id: int | None = Query(default=None, alias="user_id"),
) -> dict:
    """趋势查询：按类型/日期区间过滤，日期升序（当前用户）。"""
    from_date = _parse_date(from_, "from") if from_ else None
    to_date = _parse_date(to, "to") if to else None
    rows = body_metrics_service.query_body_metrics(
        session, type, from_date, to_date, user_id=resolve_viewer(principal, override_user_id)
    )
    return {"metrics": [body_metrics_service.to_dict(r) for r in rows]}


@router.post("/{metric_id}/sync-xunji")
def sync_body_metric_to_xunji(
    metric_id: int,
    req: SyncRequest,
    session: Session = Depends(get_session),
    client: XunjiBodyClient = Depends(get_body_client),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """同步到训记（仅 weight/bodyfat）。

    三段式：默认 dry_run=True 预览返回 res.summary；前端展示摘要后用户确认，
    带 confirmed=True 再调本接口执行真实写入，成功后置 synced_to_xunji=TRUE。
    """
    row = session.get(BodyMetric, metric_id)
    if row is None or row.user_id != current_user_id:
        raise HTTPException(status_code=404, detail=f"记录 {metric_id} 不存在")
    if row.type not in SYNCABLE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"{row.type} 类型训记 API 不支持，仅本地保存（可同步：weight/bodyfat）",
        )

    records = [
        {"datestr": row.date.isoformat(), "type": row.type, "value": row.value}
    ]
    try:
        if not req.confirmed:
            data = client.upsert_body_metrics(records, dry_run=True)
            return {
                "status": "preview",
                "summary": (data.get("res") or {}).get("summary") or "",
                "metric": body_metrics_service.to_dict(row),
            }
        data = client.upsert_body_metrics(records, dry_run=False, confirmed=True)
    except XunjiAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    row.synced_to_xunji = True
    session.commit()
    return {
        "status": "synced",
        "summary": (data.get("res") or {}).get("summary") or "",
        "metric": body_metrics_service.to_dict(row),
    }


# ---------- V3-9 体脂秤"身体测量报告"图片导入 ----------


@router.post("/extract-image")
async def extract_body_scale_image(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """体脂秤报告图片识别：调视觉模型 + Schema 校验（失败自动重试 1 次），结果不落库。"""
    if (file.content_type or "") not in ALLOWED_IMAGE_MIME:
        raise HTTPException(
            status_code=422, detail=f"不支持的文件类型：{file.filename}（仅 jpg/png）"
        )
    content = await file.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片超过 10MB")
    try:
        return extract_body_image(content, session=session, mime=file.content_type)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=422, detail=f"模型调用失败：{exc}") from exc


@router.post("/confirm-import")
def confirm_body_image_import_api(
    req: ConfirmImportRequest,
    session: Session = Depends(get_session),
    client: XunjiBodyClient | None = Depends(get_body_client_lazy),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """用户确认后批量入库：selected 指标按 (date,type) 幂等 upsert；

    sync_xunji=True 时 weight/bodyfat 走训记三段式同步（dry_run → confirmed）。
    """
    day = _parse_date(req.date)
    if req.sync_xunji and client is None:
        raise HTTPException(status_code=503, detail="XUNJI_BODY_API_KEY 未配置，无法同步训记")
    try:
        return confirm_body_image_import(
            session,
            day,
            [m.model_dump() for m in req.metrics],
            sync_xunji=req.sync_xunji,
            body_client=client,
            user_id=current_user_id,
        )
    except BodyMetricValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except XunjiAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
