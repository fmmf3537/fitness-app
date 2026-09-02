"""V4-3 皮脂钳体脂率 API（PRD F5）。

- GET /api/skinfold/methods：返回 4 方案元数据 + 当前 profile（前端判断是否要先填设置）；
- POST /api/skinfold/records：录入一次测量，自动算体脂率并落 bodyfat body_metric；
- GET /api/skinfold/records?method=&date=：查询历史（日期倒序）。
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.services import body_metrics as body_metrics_service
from app.services.skinfold import (
    METHODS,
    SITE_NAME_ZH,
    SkinfoldValidationError,
    get_profile,
    query_skinfold_records,
    to_dict,
    upsert_skinfold_record,
)

router = APIRouter(
    prefix="/api/skinfold",
    tags=["skinfold"],
    dependencies=[Depends(require_auth)],
)


def _parse_date(raw: str | None, field: str = "date") -> date | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"{field} 日期格式非法: {raw!r}") from exc


def _methods_with_zh() -> list[dict]:
    out = []
    for key, meta in METHODS.items():
        out.append({
            "key": key,
            "name_zh": meta["name_zh"],
            "sites": [
                {"key": s, "name_zh": SITE_NAME_ZH.get(s, s)} for s in meta["sites"]
            ],
            "sex": meta["sex"],
            "self_test": meta["self_test"],
        })
    return out


@router.get("/methods")
def get_methods(session: Session = Depends(get_session)) -> dict:
    """返回 4 方案元数据 + 当前设置里的性别 / 出生日期（前端判断是否先填设置）。"""
    return {
        "methods": _methods_with_zh(),
        "profile": get_profile(session),
    }


class SkinfoldRecordCreate(BaseModel):
    """录入请求：日期 + 方案 + 各部位 mm 值 + 可选备注。"""

    date: str
    method: str
    sites: dict[str, float] = Field(default_factory=dict)
    note: str | None = None


@router.post("/records")
def create_record(
    req: SkinfoldRecordCreate,
    session: Session = Depends(get_session),
) -> dict:
    """录入一次皮脂钳测量：自动算体脂率，幂等 upsert 到 skinfold_record + body_metric。"""
    day = _parse_date(req.date, "date")
    try:
        record, body_row = upsert_skinfold_record(
            session, day, req.method, req.sites, req.note
        )
    except SkinfoldValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "record": to_dict(record),
        "body_metric": body_metrics_service.to_dict(body_row),
    }


@router.get("/records")
def list_records(
    method: str | None = Query(default=None),
    date_: str | None = Query(default=None, alias="date"),
    session: Session = Depends(get_session),
) -> dict:
    """查询皮脂钳测量记录（日期倒序），按 method / date 过滤。"""
    if method is not None and method not in METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"未知方案: {method!r}（支持: {', '.join(METHODS)}）",
        )
    day = _parse_date(date_, "date")
    rows = query_skinfold_records(session, method=method, day=day)
    return {"records": [to_dict(r) for r in rows]}