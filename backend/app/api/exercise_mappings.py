"""动作映射批处理、覆盖率看板与复核/纠错 API（V6-7 / V6-4 / V6-8）。

固定路径（/coverage /generate /catalog /stale-syncs /batch-activate /batch-reset
/llm-suggest /probe /backfill-relations /migrate-existing）必须注册在 /{mapping_id} 之前，避免被路径参数吞掉。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.services import exercise_mapping as mapping_svc
from app.services import exercise_mapping_batch as batch_svc
from app.services import exercise_mapping_llm as llm_svc
from app.services import exercise_mapping_relation as relation_svc
from app.services.exercise_mapping import MappingValueError

router = APIRouter(
    prefix="/api/exercise-mappings",
    tags=["exercise-mappings"],
    dependencies=[Depends(require_auth)],
)


class MappingPatchBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    garmin_category: str | None = None
    garmin_exercise_name: str | None = None
    garmin_display_name: str | None = None
    weight_strategy: str | None = None
    status: str | None = None
    reason: str | None = None


class ReasonBody(BaseModel):
    reason: str | None = None


class AcceptCandidateBody(BaseModel):
    weight_strategy: str | None = None
    reason: str | None = None


class BatchActivateBody(BaseModel):
    confidence: str = "high"
    only_confirmed_catalog: bool = True


class ProbeRequest(BaseModel):
    pairs: list[dict] = []  # [{"category": str, "exercise_name": str}]
    keep: bool = False
    apply: bool = True  # 是否把结果写回映射表


def _http_from_mapping_error(exc: MappingValueError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": exc.code, "message": str(exc)},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "MAPPING_NOT_FOUND"},
    )


# ---------- 固定路径（必须在 /{mapping_id} 之前） ----------


@router.get("/coverage")
def get_coverage(session: Session = Depends(get_session)) -> dict:
    """覆盖率看板：按 status / confidence / verified_level 分组统计。"""
    return batch_svc.coverage_stats(session)


@router.post("/generate")
def post_generate(
    refresh_drafts: bool = Query(default=False),
    force_refresh: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> dict:
    """触发全量批处理。

    `refresh_drafts=True` 时重算 draft，但**默认跳过被人工修改
    （mapping_version > 1）或由 LLM 填充（source='llm'）的行**；
    传 `force_refresh=True` 才会连这些一起覆盖。
    """
    return batch_svc.generate_all(
        session, refresh_drafts=refresh_drafts, force_refresh=force_refresh
    )


@router.get("/catalog")
def get_catalog(
    q: str = Query(default=""),
    category: str | None = Query(default=None),
    limit: int = Query(default=30),
) -> list[dict]:
    """Garmin 离线目录搜索，供前端换候选。"""
    return mapping_svc.search_catalog(q=q, category=category, limit=limit)


@router.get("/stale-syncs")
def get_stale_syncs(
    limit: int = Query(default=50),
    session: Session = Depends(get_session),
) -> list[dict]:
    """已同步但映射已变更的记录。"""
    return mapping_svc.list_stale_syncs(session, limit=limit)


@router.post("/batch-activate")
def post_batch_activate(
    body: BatchActivateBody | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """批量把符合 ADR §5.1 条件的 draft 转 active。

    透传 service 返回：activated / skipped / skipped_reasons / relation_breakdown。
    """
    payload = body or BatchActivateBody()
    return mapping_svc.batch_activate(
        session,
        confidence=payload.confidence,
        only_confirmed_catalog=payload.only_confirmed_catalog,
    )


@router.post("/batch-reset")
def post_batch_reset(session: Session = Depends(get_session)) -> dict:
    """把算法批量激活的映射退回 draft（seed 与人工行不受影响）。"""
    return mapping_svc.batch_reset_to_draft(session)


@router.post("/llm-suggest")
def post_llm_suggest(
    limit: int = Query(default=200, ge=1, le=400),
    max_batches: int = Query(default=10, ge=1, le=30),
    only_without_candidate: bool = Query(default=True),
    session: Session = Depends(get_session),
) -> dict:
    """用 LLM 为无候选的动作补候选（只写 candidate 表，绝不自动激活）。"""
    return llm_svc.suggest_candidates_with_llm(
        session,
        limit=limit,
        max_batches=max_batches,
        only_without_candidate=only_without_candidate,
    )


@router.post("/probe")
def post_probe(body: ProbeRequest, session: Session = Depends(get_session)) -> dict:
    """L2 探针：真实创建并删除 Garmin Workout，验证目录组合是否被原样接受。
    **会写 Garmin**，仅在 GARMIN_PLAN_SYNC_ENABLED=1 时允许。"""
    from app.config import get_settings
    from app.services.exercise_catalog_probe import (
        ProbeResult,
        apply_probe_results,
        probe_batch,
    )

    settings = get_settings()
    if not settings.garmin_plan_sync_enabled:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "GARMIN_WRITE_DISABLED",
                "message": "Garmin 写入未启用（GARMIN_PLAN_SYNC_ENABLED）",
            },
        )
    if not body.pairs:
        raise HTTPException(
            status_code=422,
            detail={"code": "EMPTY_PAIRS"},
        )

    # 延迟导入，避免模块导入期就要求 garminconnect 依赖
    from app.adapters.garmin_workout_adapter import GarminWorkoutAdapter

    adapter = GarminWorkoutAdapter.from_settings(settings)
    pairs = [
        (str(item.get("category") or ""), str(item.get("exercise_name") or ""))
        for item in body.pairs
    ]
    result = probe_batch(adapter, pairs, keep=body.keep)
    applied = None
    if body.apply:
        probe_results = [ProbeResult(**row) for row in result["results"]]
        applied = apply_probe_results(session, probe_results)
    return {**result, "applied": applied}


@router.post("/backfill-relations")
def post_backfill_relations(session: Session = Depends(get_session)) -> dict:
    """按 ADR §10.1 回填 relation/match_basis/unmapped_reason（幂等，只处理空值）。"""
    return relation_svc.backfill_relations(session)


@router.post("/migrate-existing")
def post_migrate_existing(session: Session = Depends(get_session)) -> dict:
    """ADR §10：把 B 策略应用到存量 active 映射并输出迁移报告（幂等）。"""
    return relation_svc.migrate_existing_active(session)


@router.get("")
def list_mappings(
    status: str | None = Query(default=None),
    confidence: str | None = Query(default=None),
    verified_level: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> dict:
    """映射分页列表。"""
    return mapping_svc.list_mappings(
        session,
        status=status,
        confidence=confidence,
        verified_level=verified_level,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


# ---------- 动态路径 ----------


@router.get("/{mapping_id}")
def get_mapping_detail(
    mapping_id: int,
    session: Session = Depends(get_session),
) -> dict:
    detail = mapping_svc.get_mapping_detail(session, mapping_id)
    if detail is None:
        raise _not_found()
    return detail


@router.patch("/{mapping_id}")
def patch_mapping(
    mapping_id: int,
    body: MappingPatchBody,
    session: Session = Depends(get_session),
) -> dict:
    data = body.model_dump(exclude_unset=True)
    reason = data.pop("reason", None)
    kwargs: dict[str, Any] = {
        field: data[field]
        for field in (
            "garmin_category",
            "garmin_exercise_name",
            "garmin_display_name",
            "weight_strategy",
            "status",
        )
        if field in data
    }
    try:
        item = mapping_svc.update_mapping(
            session,
            mapping_id,
            reason=reason,
            **kwargs,
        )
    except MappingValueError as exc:
        raise _http_from_mapping_error(exc) from exc
    if item is None:
        raise _not_found()
    return item


@router.post("/{mapping_id}/activate")
def post_activate(
    mapping_id: int,
    body: ReasonBody | None = None,
    session: Session = Depends(get_session),
) -> dict:
    payload = body or ReasonBody()
    try:
        item = mapping_svc.activate_mapping(
            session, mapping_id, reason=payload.reason
        )
    except MappingValueError as exc:
        raise _http_from_mapping_error(exc) from exc
    if item is None:
        raise _not_found()
    return item


@router.post("/{mapping_id}/disable")
def post_disable(
    mapping_id: int,
    body: ReasonBody | None = None,
    session: Session = Depends(get_session),
) -> dict:
    payload = body or ReasonBody()
    item = mapping_svc.disable_mapping(
        session, mapping_id, reason=payload.reason
    )
    if item is None:
        raise _not_found()
    return item


@router.post("/{mapping_id}/candidates/{candidate_id}/accept")
def post_accept_candidate(
    mapping_id: int,
    candidate_id: int,
    body: AcceptCandidateBody | None = None,
    session: Session = Depends(get_session),
) -> dict:
    payload = body or AcceptCandidateBody()
    try:
        item = mapping_svc.accept_candidate(
            session,
            mapping_id,
            candidate_id,
            weight_strategy=payload.weight_strategy,
            reason=payload.reason,
        )
    except MappingValueError as exc:
        raise _http_from_mapping_error(exc) from exc
    if item is None:
        raise _not_found()
    return item
