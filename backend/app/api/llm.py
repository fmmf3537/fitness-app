"""V2-1 LLM 通用 API：GET /api/llm/monthly-usage（按 provider 分组的月度成本汇总）。

与 /api/settings/llm/usage 的区别：该路由按 provider 粒度聚合（同 provider 多模型合并），
供月度成本汇总与对账使用。
"""
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.models import LLMCall

router = APIRouter(prefix="/api/llm", tags=["llm"])


def _month_range(month: str | None) -> tuple[int, int, datetime, datetime]:
    if month is None:
        today = date.today()
        year, mon = today.year, today.month
    else:
        m = re.fullmatch(r"(\d{4})-(\d{2})", month)
        if not m or not (1 <= int(m.group(2)) <= 12):
            raise HTTPException(status_code=422, detail="month 格式必须为 YYYY-MM")
        year, mon = int(m.group(1)), int(m.group(2))
    start = datetime(year, mon, 1)
    end = datetime(year + 1, 1, 1) if mon == 12 else datetime(year, mon + 1, 1)
    return year, mon, start, end


@router.get("/monthly-usage", dependencies=[Depends(require_auth)])
def get_monthly_usage(
    month: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict:
    """月度成本汇总：按 provider 分组返回 token 与估算成本（默认当月）。"""
    year, mon, start, end = _month_range(month)
    rows = (
        session.query(LLMCall)
        .filter(LLMCall.created_at >= start, LLMCall.created_at < end)
        .all()
    )
    groups: dict[str, dict] = {}
    total_cost = 0.0
    for r in rows:
        g = groups.setdefault(r.provider, {
            "provider": r.provider,
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0,
        })
        g["calls"] += 1
        g["prompt_tokens"] += r.prompt_tokens or 0
        g["completion_tokens"] += r.completion_tokens or 0
        g["cost"] += r.cost_estimate or 0.0
        total_cost += r.cost_estimate or 0.0
    by_provider = sorted(groups.values(), key=lambda g: g["provider"] or "")
    for g in by_provider:
        g["cost"] = round(g["cost"], 4)
    return {
        "month": f"{year:04d}-{mon:02d}",
        "total_calls": len(rows),
        "total_cost": round(total_cost, 4),
        "by_provider": by_provider,
    }
