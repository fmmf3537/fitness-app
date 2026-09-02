"""V1-1/V2-1 LLM 设置 API：GET/PUT /api/settings/llm。

PUT 时先调该厂商轻量接口验证 Key 有效再加密保存；无效 Key 拒绝入库。
V2-1：GET 返回各 provider 连续失败计数与建议备用模型（前端降级提示用）；
PUT 支持不带 api_key 仅切换默认模型（要求该 provider 已配置 Key）。

V4-3：新增 GET/PUT /api/settings/profile，管理性别 / 出生日期（皮脂钳公式所需）。
"""
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import llm
from app.api.auth import require_auth
from app.db import get_session
from app.models import LLMCall, Setting
from app.services.skinfold import get_profile

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LLMSettingsPut(BaseModel):
    provider: str
    api_key: str = ""  # V2-1：可为空，仅切换默认模型
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
            "consecutive_failures": llm.get_consecutive_failures(session, name),
        }
        for name, cfg in llm.PROVIDERS.items()
    ]
    default = llm.get_default_provider(session)
    suggested_fallback = None
    if any(p["name"] == default and p["consecutive_failures"] >= 2 for p in providers):
        # 默认模型连续失败 ≥2 次：建议切到第一个其他已配置 Key 的 provider
        suggested_fallback = next(
            (p["name"] for p in providers if p["name"] != default and p["implemented"] and p["has_key"]),
            None,
        )
    return {
        "default_llm": default,
        "suggested_fallback": suggested_fallback,
        "providers": providers,
    }


@router.get("/llm/usage", dependencies=[Depends(require_auth)])
def get_llm_usage(
    month: str | None = Query(default=None),
    session: Session = Depends(get_session),
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
        .filter(LLMCall.created_at >= start, LLMCall.created_at < end)
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


@router.put("/llm", dependencies=[Depends(require_auth)])
def put_llm_settings(req: LLMSettingsPut, session: Session = Depends(get_session)) -> dict:
    if req.provider not in llm.PROVIDERS:
        raise HTTPException(status_code=400, detail=f"未知 provider：{req.provider}")
    if not llm.PROVIDERS[req.provider]["implemented"]:
        raise HTTPException(status_code=400, detail=f"provider {req.provider} 尚未接入")
    if not req.api_key.strip():
        # V2-1：仅切换默认模型（要求该 provider 已配置 Key）
        if not req.set_default:
            raise HTTPException(status_code=400, detail="api_key 不能为空")
        if not llm.resolve_api_key(session, req.provider):
            raise HTTPException(status_code=400, detail=f"provider {req.provider} 未配置 Key，无法设为默认")
        llm.set_default_provider(session, req.provider)
        return {"ok": True, "provider": req.provider, "default_llm": llm.get_default_provider(session)}
    if not llm.verify_api_key(req.provider, req.api_key):
        raise HTTPException(status_code=400, detail="Key 验证失败（厂商接口返回非 200），未保存")
    llm.save_api_key(session, req.provider, req.api_key)
    if req.set_default:
        llm.set_default_provider(session, req.provider)
    return {"ok": True, "provider": req.provider, "default_llm": llm.get_default_provider(session)}


# ---------- V4-3 用户画像（性别 / 出生日期，皮脂钳公式所需） ----------


_ALLOWED_GENDER = {"male", "female"}
_AGE_MIN = 10
_AGE_MAX = 120


class ProfilePut(BaseModel):
    """PUT /api/settings/profile 请求体：PATCH 语义，只更新传入字段。"""

    gender: str | None = None
    birth_date: str | None = None  # ISO 日期字符串


def _calc_age(birth: date, today: date | None = None) -> int:
    today = today or date.today()
    return today.year - birth.year - (
        (today.month, today.day) < (birth.month, birth.day)
    )


@router.get("/profile", dependencies=[Depends(require_auth)])
def get_profile_api(session: Session = Depends(get_session)) -> dict:
    """读取当前性别 / 出生日期；未设置返回 null。"""
    return get_profile(session)


@router.put("/profile", dependencies=[Depends(require_auth)])
def put_profile(req: ProfilePut, session: Session = Depends(get_session)) -> dict:
    """写入性别 / 出生日期（PATCH 语义：只更新传入字段）；不存在则创建 settings 单行。

    - gender ∈ {male, female}；非允许值 → 400；
    - birth_date 为合法 ISO 日期，且推算年龄 ∈ [10, 120]；否则 → 400。
    """
    if req.gender is None and req.birth_date is None:
        raise HTTPException(status_code=400, detail="gender 与 birth_date 至少传一个")

    new_birth: date | None = None
    if req.birth_date is not None:
        try:
            new_birth = date.fromisoformat(req.birth_date)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"birth_date 日期格式非法: {req.birth_date!r}"
            ) from exc
        age = _calc_age(new_birth)
        if age < _AGE_MIN or age > _AGE_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"根据出生日期推算年龄 {age} 超出合理区间 [{_AGE_MIN}, {_AGE_MAX}]",
            )

    if req.gender is not None and req.gender not in _ALLOWED_GENDER:
        raise HTTPException(
            status_code=400,
            detail=f"gender 非法: {req.gender!r}（仅支持 male / female）",
        )

    row = session.query(Setting).first()
    if row is None:
        row = Setting()
        session.add(row)
    if req.gender is not None:
        row.gender = req.gender
    if new_birth is not None:
        row.birth_date = new_birth
    session.commit()
    return {
        "gender": row.gender,
        "birth_date": row.birth_date.isoformat() if row.birth_date else None,
    }
