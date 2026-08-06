"""V1-1 LLM 设置 API：GET/PUT /api/settings/llm。

PUT 时先调该厂商轻量接口验证 Key 有效再加密保存；无效 Key 拒绝入库。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import llm
from app.api.auth import require_auth
from app.db import get_session

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LLMSettingsPut(BaseModel):
    provider: str
    api_key: str
    set_default: bool = False


@router.get("/llm", dependencies=[Depends(require_auth)])
def get_llm_settings(session: Session = Depends(get_session)) -> dict:
    stored = llm.get_stored_keys(session)
    providers = [
        {
            "name": name,
            "base_url": cfg["base_url"],
            "default_model": cfg["default_model"],
            "implemented": cfg["implemented"],
            "has_key": bool(stored.get(name) or llm.resolve_api_key(None, name)),
        }
        for name, cfg in llm.PROVIDERS.items()
    ]
    return {"default_llm": llm.get_default_provider(session), "providers": providers}


@router.put("/llm", dependencies=[Depends(require_auth)])
def put_llm_settings(req: LLMSettingsPut, session: Session = Depends(get_session)) -> dict:
    if req.provider not in llm.PROVIDERS:
        raise HTTPException(status_code=400, detail=f"未知 provider：{req.provider}")
    if not llm.PROVIDERS[req.provider]["implemented"]:
        raise HTTPException(status_code=400, detail=f"provider {req.provider} 尚未接入")
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="api_key 不能为空")
    if not llm.verify_api_key(req.provider, req.api_key):
        raise HTTPException(status_code=400, detail="Key 验证失败（厂商接口返回非 200），未保存")
    llm.save_api_key(session, req.provider, req.api_key)
    if req.set_default:
        llm.set_default_provider(session, req.provider)
    return {"ok": True, "provider": req.provider, "default_llm": llm.get_default_provider(session)}
