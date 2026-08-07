"""V1-7 身体数据 API（PRD US-12）。

- POST /api/body-metrics：录入，按 (date, type) upsert；
- GET /api/body-metrics?type=&from=&to=：趋势查询；
- POST /api/body-metrics/{id}/sync-xunji：同步训记三段式
  （dry_run 预览取 res.summary → 用户确认 confirmed=True 执行 → 置 synced_to_xunji）；
  身高/血压/血糖仅本地，一律 400 拒绝。
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.xunji import XunjiAPIError
from app.adapters.xunji_body import XunjiBodyClient
from app.api.auth import require_auth
from app.db import get_session
from app.models import BodyMetric
from app.services import body_metrics as body_metrics_service
from app.services.body_metrics import BodyMetricValidationError, SYNCABLE_TYPES

router = APIRouter(
    prefix="/api/body-metrics",
    tags=["body-metrics"],
    dependencies=[Depends(require_auth)],
)


def get_body_client(session: Session = Depends(get_session)) -> XunjiBodyClient:
    """依赖注入点：测试可 override 替换训记身体数据客户端。"""
    return XunjiBodyClient(session)


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


def _parse_date(raw: str, field: str = "date") -> date:
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"{field} 日期格式非法: {raw!r}") from exc


@router.post("")
def create_body_metric(
    req: BodyMetricCreate,
    session: Session = Depends(get_session),
) -> dict:
    """录入身体数据：同日同类型覆盖旧值（upsert 幂等）。"""
    day = _parse_date(req.date)
    try:
        row = body_metrics_service.upsert_body_metric(
            session, day, req.type, req.value, unit=req.unit, note=req.note
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
) -> dict:
    """趋势查询：按类型/日期区间过滤，日期升序。"""
    from_date = _parse_date(from_, "from") if from_ else None
    to_date = _parse_date(to, "to") if to else None
    rows = body_metrics_service.query_body_metrics(session, type, from_date, to_date)
    return {"metrics": [body_metrics_service.to_dict(r) for r in rows]}


@router.post("/{metric_id}/sync-xunji")
def sync_body_metric_to_xunji(
    metric_id: int,
    req: SyncRequest,
    session: Session = Depends(get_session),
    client: XunjiBodyClient = Depends(get_body_client),
) -> dict:
    """同步到训记（仅 weight/bodyfat）。

    三段式：默认 dry_run=True 预览返回 res.summary；前端展示摘要后用户确认，
    带 confirmed=True 再调本接口执行真实写入，成功后置 synced_to_xunji=TRUE。
    """
    row = session.get(BodyMetric, metric_id)
    if row is None:
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
