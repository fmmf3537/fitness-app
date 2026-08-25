"""V1-1/V2-1 LLM 设置 API：GET/PUT /api/settings/llm。

PUT 时先调该厂商轻量接口验证 Key 有效再加密保存；无效 Key 拒绝入库。
V2-1：GET 返回各 provider 连续失败计数与建议备用模型（前端降级提示用）；
PUT 支持不带 api_key 仅切换默认模型（要求该 provider 已配置 Key）。

M3-4：绑定状态管理 API（GET/POST/DELETE /api/settings/bindings*）。
"""
import json
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import garmin_adapter, llm
from app.adapters.xunji import XunjiAPIError, XunjiClient
from app.api.auth import get_current_user_id
from app.config import encrypt_value, get_settings
from app.db import get_session
from app.models import LLMCall, Setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LLMSettingsPut(BaseModel):
    provider: str
    api_key: str = ""  # V2-1：可为空，仅切换默认模型
    set_default: bool = False


# ---------- M3-4 绑定请求体 ----------

class GarminBindRequest(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)
    domain: str = "garmin.cn"


class XunjiBindRequest(BaseModel):
    api_key: str = Field(min_length=1)
    body_api_key: str | None = None


class LLMBindRequest(BaseModel):
    provider: str = Field(min_length=1)
    api_key: str = Field(min_length=1)


def _get_or_create_setting(session: Session, user_id: int) -> Setting:
    """按 user_id 取 settings 行；不存在则新建（UNIQUE(user_id)）。"""
    row = session.scalars(select(Setting).where(Setting.user_id == user_id)).first()
    if row is None:
        row = Setting(user_id=user_id)
        session.add(row)
        session.flush()
    return row


def _mask_email(email: str) -> str:
    """邮箱脱敏：首字符 + *** + @域名，永不回传明文。"""
    if "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


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


# ---------- M3-4 绑定状态管理 ----------

@router.get("/bindings")
def get_bindings(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """返回当前用户绑定状态（仅布尔/元数据，不回传明文凭据）。"""
    row = session.scalars(
        select(Setting).where(Setting.user_id == current_user_id)
    ).first()
    domain = get_settings().garmin_domain or "garmin.cn"
    if row is None:
        return {
            "garmin": {"bound": False, "has_token": False, "domain": domain},
            "xunji": {"bound": False, "body_bound": False},
            "llm": {
                "bound": False,
                "default_provider": llm.get_default_provider(session, current_user_id),
                "providers": [],
            },
        }
    stored = llm.get_stored_keys(session, current_user_id)
    providers = sorted(stored.keys())
    return {
        "garmin": {
            "bound": bool(row.garmin_email_enc and row.garmin_password_enc),
            "has_token": bool(row.garmin_token_store_enc),
            "domain": domain,
        },
        "xunji": {
            "bound": bool(row.xunji_api_key_enc),
            "body_bound": bool(row.xunji_body_api_key_enc),
        },
        "llm": {
            "bound": bool(providers),
            "default_provider": llm.get_default_provider(session, current_user_id),
            "providers": providers,
        },
    }


@router.post("/bindings/garmin")
def bind_garmin(
    req: GarminBindRequest,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """绑定佳明：凭据登录验证 → 加密存 email/password（token 由 adapter 自管）。"""
    email = req.email.strip()
    password = req.password
    domain = (req.domain or "garmin.cn").strip() or "garmin.cn"
    try:
        client = garmin_adapter.GarminClient(
            session,
            user_id=current_user_id,
            email=email,
            password=password,
            domain=domain,
        )
        # 强制凭据重登（不走 token 恢复），失败视为凭据错误
        client._relogin()
    except garmin_adapter.GarminKeyNotConfiguredError as exc:
        raise HTTPException(status_code=422, detail="佳明凭据不完整") from exc
    except garmin_adapter.GarminAdapterError as exc:
        raise HTTPException(status_code=401, detail="佳明凭据验证失败") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="佳明服务暂不可用") from exc

    row = _get_or_create_setting(session, current_user_id)
    row.garmin_email_enc = encrypt_value(email)
    row.garmin_password_enc = encrypt_value(password)
    session.commit()
    return {"ok": True, "email_masked": _mask_email(email)}


@router.post("/bindings/xunji")
def bind_xunji(
    req: XunjiBindRequest,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """绑定训记：拉一次 plan_list 验证 Key → 加密存储。"""
    api_key = req.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=422, detail="api_key 不能为空")
    try:
        client = XunjiClient(session, api_key=api_key, user_id=current_user_id)
        client.fetch_plan_list()
    except XunjiAPIError as exc:
        raise HTTPException(status_code=401, detail="训记 Key 验证失败") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="训记 Key 验证失败") from exc

    row = _get_or_create_setting(session, current_user_id)
    row.xunji_api_key_enc = encrypt_value(api_key)
    if req.body_api_key is not None and req.body_api_key.strip():
        row.xunji_body_api_key_enc = encrypt_value(req.body_api_key.strip())
    session.commit()
    return {"ok": True}


@router.post("/bindings/llm")
def bind_llm(
    req: LLMBindRequest,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """绑定 LLM Key：verify_api_key → 合并写入 llm_keys_json_enc（保留其它 provider）。"""
    provider = req.provider.strip()
    api_key = req.api_key.strip()
    if provider not in llm.PROVIDERS:
        raise HTTPException(status_code=400, detail=f"未知 provider：{provider}")
    if not api_key:
        raise HTTPException(status_code=422, detail="api_key 不能为空")
    if not llm.verify_api_key(provider, api_key):
        raise HTTPException(status_code=401, detail="Key 验证失败")
    # save_api_key 内部按 user_id 读-改-写，保留其它 provider
    llm.save_api_key(session, provider, api_key, user_id=current_user_id)
    return {"ok": True, "provider": provider}


@router.delete("/bindings/{binding_type}")
def unbind(
    binding_type: str,
    provider: str | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
) -> dict:
    """解绑：按类型清除当前用户 settings 中对应凭据字段。

    llm 解绑可带 ?provider= 只删该厂商 Key；不带则清空全部 LLM Key。
    """
    if binding_type not in ("garmin", "xunji", "llm"):
        raise HTTPException(status_code=400, detail=f"未知绑定类型：{binding_type}")

    row = session.scalars(
        select(Setting).where(Setting.user_id == current_user_id)
    ).first()
    if row is None:
        return {"ok": True, "unbound": binding_type}

    if binding_type == "garmin":
        row.garmin_email_enc = None
        row.garmin_password_enc = None
        row.garmin_token_store_enc = None
    elif binding_type == "xunji":
        row.xunji_api_key_enc = None
        row.xunji_body_api_key_enc = None
    else:  # llm
        if provider:
            keys = llm.get_stored_keys(session, current_user_id)
            keys.pop(provider, None)
            if keys:
                row.llm_keys_json_enc = encrypt_value(
                    json.dumps(keys, ensure_ascii=False)
                )
            else:
                row.llm_keys_json_enc = None
        else:
            row.llm_keys_json_enc = None
    session.commit()
    return {"ok": True, "unbound": binding_type}
