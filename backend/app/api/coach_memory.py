"""V5-1 AI 教练长期记忆 API：偏好 CRUD + 草稿采纳/拒绝。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.services import coach_memory as svc

# 提示词中的 router / router2；main 通过合并后的 router 一次注册
preferences_router = APIRouter(
    prefix="/api/coach/preferences",
    tags=["coach"],
    dependencies=[Depends(require_auth)],
)
drafts_router = APIRouter(
    prefix="/api/coach/drafts",
    tags=["coach"],
    dependencies=[Depends(require_auth)],
)
# 兼容提示词命名
router2 = drafts_router


class PreferenceCreate(BaseModel):
    content: str
    tags: str | None = None


class PreferenceUpdate(BaseModel):
    content: str | None = None
    tags: str | None = None


@preferences_router.get("")
def list_preferences(session: Session = Depends(get_session)) -> dict:
    rows = svc.list_preferences(session, active_only=True)
    return {"preferences": [svc.to_dict(r) for r in rows]}


@preferences_router.post("")
def create_preference(
    req: PreferenceCreate,
    session: Session = Depends(get_session),
) -> dict:
    try:
        row = svc.create_preference(
            session, content=req.content, category="manual", tags=req.tags, source="user"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return svc.to_dict(row)


@preferences_router.put("/{pref_id}")
def update_preference(
    pref_id: int,
    req: PreferenceUpdate,
    session: Session = Depends(get_session),
) -> dict:
    try:
        row = svc.update_preference(
            session, pref_id, content=req.content, tags=req.tags
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return svc.to_dict(row)


@preferences_router.delete("/{pref_id}")
def delete_preference(
    pref_id: int,
    session: Session = Depends(get_session),
) -> dict:
    try:
        svc.deactivate_preference(session, pref_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@drafts_router.get("")
def list_drafts(session: Session = Depends(get_session)) -> dict:
    rows = svc.list_drafts(session)
    return {"drafts": [svc.draft_to_dict(r) for r in rows]}


@drafts_router.post("/{draft_id}/accept")
def accept_draft(
    draft_id: int,
    session: Session = Depends(get_session),
) -> dict:
    try:
        pref = svc.accept_draft(session, draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"preference": svc.to_dict(pref)}


@drafts_router.post("/{draft_id}/reject")
def reject_draft(
    draft_id: int,
    session: Session = Depends(get_session),
) -> dict:
    try:
        svc.reject_draft(session, draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


# 合并供 main.py 单次 include（保持 import + include_router 两行）
router = APIRouter()
router.include_router(preferences_router)
router.include_router(drafts_router)
