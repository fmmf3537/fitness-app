"""动作映射批处理与覆盖率看板 API（V6-7）。

列表/编辑/采纳属 V6-4，本模块仅提供 coverage + generate。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.services import exercise_mapping_batch as batch_svc

router = APIRouter(
    prefix="/api/exercise-mappings",
    tags=["exercise-mappings"],
    dependencies=[Depends(require_auth)],
)


@router.get("/coverage")
def get_coverage(session: Session = Depends(get_session)) -> dict:
    """覆盖率看板：按 status / confidence / verified_level 分组统计。"""
    return batch_svc.coverage_stats(session)


@router.post("/generate")
def post_generate(
    refresh_drafts: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> dict:
    """触发全量批处理。幂等；refresh_drafts=True 时重算 draft 与 not_applicable。"""
    return batch_svc.generate_all(session, refresh_drafts=refresh_drafts)
