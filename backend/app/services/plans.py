"""V2-8 训记官方计划缓存的查询与解析（只读本地缓存，零网络请求）。

纪律：
- 只读 xunji_plan 表缓存（由 sync_plan_cache 每日刷新），本模块不发起任何网络请求；
- 兼容两种缓存结构：get 行（plan.status + days[].datestr + workout.movements + target_sets）
  与 list 行（顶层 status + days[].date + movements）；
- parse_json / normalize_plan_movement 是与 services/ai.py 共享的解析原语
  （ai.py 从这里 import，禁止复制粘贴）；
- status=ended 的计划不再产出训练日（其日期一律按休息日呈现）。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import XunjiPlan

PLAN_ENDED = "ended"


def parse_json(text: str | None) -> Any:
    """容忍非法/空输入的 JSON 解析，失败返回 None。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def normalize_plan_movement(mv: dict) -> dict:
    """计划动作归一化：真实响应的 target_sets 映射为 sets（供 prompt 组装统一读取）。"""
    if not isinstance(mv, dict):
        return {"name": str(mv), "sets": []}
    if mv.get("sets") is None and mv.get("target_sets") is not None:
        return {**mv, "sets": mv.get("target_sets") or []}
    return mv


def plan_status(data: Any) -> str | None:
    """计划状态：兼容 list 行顶层 status 与 get 行 plan.status。"""
    if not isinstance(data, dict):
        return None
    status = data.get("status") or (data.get("plan") or {}).get("status")
    return str(status) if status else None


def plan_name_of(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    plan = data.get("plan") or {}
    return plan.get("name") or plan.get("title") or data.get("name") or data.get("title")


def extract_plan_days(data: Any) -> list[dict]:
    """从一行 plan_json 提取训练日：[{date, title, movements(已归一化 sets)}]。

    休息日（movements 为空）与非法日期不产出。
    """
    days: list[dict] = []
    if not isinstance(data, dict):
        return days
    for day in data.get("days") or []:
        if not isinstance(day, dict):
            continue
        # 真实 get 响应用 datestr + workout.movements；旧结构用 date + movements
        day_str = day.get("date") or day.get("datestr")
        movements = day.get("movements") or (day.get("workout") or {}).get("movements") or []
        if not day_str or not movements:
            continue
        try:
            day_date = date.fromisoformat(day_str)
        except (ValueError, TypeError):
            continue
        title = day.get("title") or (day.get("workout") or {}).get("name")
        days.append({
            "date": day_date,
            "title": title,
            "movements": [normalize_plan_movement(mv) for mv in movements],
        })
    return days


def _candidate_rows(session: Session, start: date, end: date,
                     user_id: int | None = None) -> list[XunjiPlan]:
    filters = [
        XunjiPlan.plan_json.isnot(None),
        XunjiPlan.date_from.isnot(None),
        XunjiPlan.date_to.isnot(None),
        XunjiPlan.date_from <= end,
        XunjiPlan.date_to >= start,
    ]
    if user_id is not None:
        filters.append(XunjiPlan.user_id == user_id)
    return (
        session.query(XunjiPlan)
        .filter(*filters)
        .all()
    )


def query_plan_days(
    session: Session,
    start: date,
    *,
    days: int = 30,
    user_id: int | None = None,
) -> list[dict]:
    """从 start 起逐日计划视图（API 输出形态）：训练日带动作清单，无计划日 is_rest=True。

    返回 [{date, is_rest, plan_ref, plan_name, title, movements:[{name, target_sets}]}]，
    长度恰为 days；status=ended 的计划不产出训练日。
    """
    end = start + timedelta(days=days - 1)
    by_date: dict[date, dict] = {}
    for row in _candidate_rows(session, start, end, user_id=user_id):
        data = parse_json(row.plan_json)
        if not isinstance(data, dict):
            continue
        if plan_status(data) == PLAN_ENDED:
            continue  # 已结束的计划不再呈现训练日
        name = plan_name_of(data)
        for d in extract_plan_days(data):
            if not (start <= d["date"] <= end) or d["date"] in by_date:
                continue
            by_date[d["date"]] = {
                "date": d["date"].isoformat(),
                "is_rest": False,
                "plan_ref": row.plan_ref,
                "plan_name": name,
                "title": d["title"],
                "movements": [
                    {
                        "name": (mv.get("name") or "").strip() or "未命名动作",
                        "target_sets": mv.get("sets") or [],
                    }
                    for mv in d["movements"]
                ],
            }
    result: list[dict] = []
    for i in range(days):
        day = start + timedelta(days=i)
        result.append(
            by_date.get(day)
            or {
                "date": day.isoformat(),
                "is_rest": True,
                "plan_ref": None,
                "plan_name": None,
                "title": None,
                "movements": [],
            }
        )
    return result


def query_plan_day(session: Session, target_date: date, *,
                     user_id: int | None = None) -> dict | None:
    """取某日的计划训练日（内部形态，movements 归一化 sets，供 prompt 组装）。

    休息日 / 缓存缺失 / 计划已结束均返回 None。
    """
    for row in _candidate_rows(session, target_date, target_date, user_id=user_id):
        data = parse_json(row.plan_json)
        if not isinstance(data, dict) or plan_status(data) == PLAN_ENDED:
            continue
        for d in extract_plan_days(data):
            if d["date"] == target_date:
                return {
                    "plan_ref": row.plan_ref,
                    "plan_name": plan_name_of(data),
                    "date": target_date.isoformat(),
                    "title": d["title"],
                    "movements": d["movements"],
                }
    return None


def plan_day_skip_reason(session: Session, target_date: date) -> str:
    """某日无计划训练日时的可读原因（供 API 404 detail 与日志）。"""
    rows = session.query(XunjiPlan).all()
    if not rows:
        return "训记计划缓存为空，请先刷新计划缓存"
    statuses: set[str] = set()
    for row in rows:
        status = plan_status(parse_json(row.plan_json))
        if status:
            statuses.add(status)
    if statuses and statuses <= {PLAN_ENDED}:
        return "训记计划已全部结束（status=ended），无可点评的计划日"
    return f"{target_date.isoformat()} 为休息日或无计划安排，无需生成计划点评"
