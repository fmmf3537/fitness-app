"""V1-1/V2-1 LLM 设置 API：GET/PUT /api/settings/llm。

PUT 时先调该厂商轻量接口验证 Key 有效再加密保存；无效 Key 拒绝入库。
V2-1：GET 返回各 provider 连续失败计数与建议备用模型（前端降级提示用）；
PUT 支持不带 api_key 仅切换默认模型（要求该 provider 已配置 Key）。
"""
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import llm
from app.api.auth import get_current_user_id
from app.config import get_settings
from app.db import get_session
from app.models import LLMCall

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LLMSettingsPut(BaseModel):
    provider: str
    api_key: str = ""  # V2-1：可为空，仅切换默认模型
    set_default: bool = False


@router.get("/llm")
def get_llm_settings(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    stored = llm.get_stored_keys(session, current_user_id)
    # 该用户可用 Key：已存 Key ∪ 环境变量全局 Key（仅用于「是否有可用 Key」判定）
    env_keys = {
        "deepseek": get_settings().deepseek_api_key,
        "minimax": get_settings().minimax_api_key,
        "kimi": get_settings().kimi_api_key,
    }
    usable = {name: bool(stored.get(name)) or bool(env_keys.get(name)) for name in llm.PROVIDERS}
    providers = [
        {
            "name": name,
            "base_url": cfg["base_url"],
            "default_model": cfg["default_model"],
            "implemented": cfg["implemented"],
            "has_key": bool(stored.get(name)),  # 设置页只展示「本用户已配置」Key
            "consecutive_failures": llm.get_consecutive_failures(session, name),
        }
        for name, cfg in llm.PROVIDERS.items()
    ]
    default = llm.get_default_provider(session, current_user_id)
    suggested_fallback = None
    if any(p["name"] == default and p["consecutive_failures"] >= 2 for p in providers):
        # 默认模型连续失败 ≥2 次：建议切到第一个其他「可用」的 provider（含环境变量 Key）
        suggested_fallback = next(
            (p["name"] for p in providers if p["name"] != default and p["implemented"] and usable.get(p["name"])),
            None,
        )
    return {
        "default_llm": default,
        "suggested_fallback": suggested_fallback,
        "providers": providers,
    }


@router.get("/llm/usage")
def get_llm_usage(
    month: str | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """LLM 调用月度用量统计（默认当月），按 (provider, model) 分组聚合。"""
    if month is None:
        today = date.today()
        year, mon = today.year, today.month
    else:
        m = re.fullmatch(r"(\d{4})-(\d{2})", month)
        if not m or not (1 <= int(m.group(2)) <= 12):
            raise HTTPException(status_code=422, detail="month 格式必须为 YYYY-MM")
        year, mon = int(m.group(1)), int(m.group(2))
    start = datetime(year, mon, 1)
    if mon == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, mon + 1, 1)

    rows = (
        session.query(LLMCall)
        .filter(LLMCall.created_at >= start, LLMCall.created_at < end,
                LLMCall.user_id == current_user_id)
        .all()
    )
    groups: dict[tuple, dict] = {}
    total_cost = 0.0
    for r in rows:
        key = (r.provider, r.model)
        g = groups.setdefault(key, {
            "provider": r.provider, "model": r.model,
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0,
        })
        g["calls"] += 1
        g["prompt_tokens"] += r.prompt_tokens or 0
        g["completion_tokens"] += r.completion_tokens or 0
        g["cost"] += r.cost_estimate or 0.0
        total_cost += r.cost_estimate or 0.0
    by_provider = sorted(groups.values(), key=lambda g: (g["provider"] or "", g["model"] or ""))
    for g in by_provider:
        g["cost"] = round(g["cost"], 4)
    return {
        "month": f"{year:04d}-{mon:02d}",
        "total_calls": len(rows),
        "total_cost": round(total_cost, 4),
        "by_provider": by_provider,
    }


@router.put("/llm")
def put_llm_settings(
    req: LLMSettingsPut,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    if req.provider not in llm.PROVIDERS:
        raise HTTPException(status_code=400, detail=f"未知 provider：{req.provider}")
    if not llm.PROVIDERS[req.provider]["implemented"]:
        raise HTTPException(status_code=400, detail=f"provider {req.provider} 尚未接入")
    if not req.api_key.strip():
        # V2-1：仅切换默认模型（要求该 provider 已配置 Key）
        if not req.set_default:
            raise HTTPException(status_code=400, detail="api_key 不能为空")
        if not llm.resolve_api_key(session, req.provider, user_id=current_user_id):
            raise HTTPException(status_code=400, detail=f"provider {req.provider} 未配置 Key，无法设为默认")
        llm.set_default_provider(session, req.provider, user_id=current_user_id)
        return {"ok": True, "provider": req.provider, "default_llm": llm.get_default_provider(session, current_user_id)}
    if not llm.verify_api_key(req.provider, req.api_key):
        raise HTTPException(status_code=400, detail="Key 验证失败（厂商接口返回非 200），未保存")
    llm.save_api_key(session, req.provider, req.api_key, user_id=current_user_id)
    if req.set_default:
        llm.set_default_provider(session, req.provider, user_id=current_user_id)
    return {"ok": True, "provider": req.provider, "default_llm": llm.get_default_provider(session, current_user_id)}
