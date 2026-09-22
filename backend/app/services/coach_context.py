"""AI 教练实时上下文：按用户问题装配训练、计划与动作纪录。"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import Workout, XunjiPlan
from app.movements import load_movement_names
from app.services import plans as plan_service
from app.services.ai import _parse_movements

RECENT_DAYS = 14
RECENT_LIMIT = 5
UPCOMING_DAYS = 7
MAX_MOVEMENT_RECORDS = 30

_PLAN_RE = re.compile(r"明天|后天|下次|接下来|未来|计划|这周|本周|下周|周[一二三四五六日天]")
_PR_RE = re.compile(r"\bpr\b|个人纪录|个人记录|最好成绩|最大重量|最高重量|纪录", re.I)
_RECENT_RE = re.compile(r"最近|上次|今天|昨天|练了|训练|状态|复盘|表现")
_ALL_PR_RE = re.compile(r"所有|全部|每个动作|哪些动作")
_RECOVERY_RE = re.compile(r"恢复|疲劳|睡眠|HRV|身体电量|压力|静息心率|体重|体脂", re.I)


def detect_context_intent(content: str) -> dict[str, bool]:
    """本地确定性意图识别，不额外消耗 LLM。"""
    text = (content or "").strip()
    return {
        "recent": bool(_RECENT_RE.search(text)) or not text,
        "plan": bool(_PLAN_RE.search(text)),
        "pr": bool(_PR_RE.search(text)),
        "all_pr": bool(_PR_RE.search(text) and _ALL_PR_RE.search(text)),
        "recovery": bool(_RECOVERY_RE.search(text)),
    }


def _all_workouts(
    session: Session, *, end: date | None = None, limit: int | None = None
) -> list[Workout]:
    query = session.query(Workout).filter(Workout.deleted_at.is_(None))
    if end is not None:
        query = query.filter(Workout.date <= end)
    query = query.order_by(Workout.date.desc(), Workout.id.desc())
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def _movement_names(workouts: list[Workout]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for workout in workouts:
        for movement in _parse_movements(workout):
            name = str(movement.get("name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def find_mentioned_movements(
    content: str, workouts: list[Workout] | None = None
) -> list[str]:
    text = (content or "").replace(" ", "")
    matches = []
    names = list(load_movement_names())
    if workouts:
        names.extend(_movement_names(workouts))
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        compact = name.replace(" ", "")
        aliases = {compact}
        # 支持用户用“卧推/划船/侧平举”等常用简称询问具体动作。
        aliases.update(compact[-size:] for size in range(2, min(5, len(compact)) + 1))
        if any(alias in text for alias in aliases):
            matches.append(name)
    return matches


def query_recent_workouts(
    session: Session,
    anchor: date,
    *,
    days: int = RECENT_DAYS,
    limit: int = RECENT_LIMIT,
) -> list[dict[str, Any]]:
    start = anchor - timedelta(days=days - 1)
    rows = (
        session.query(Workout)
        .filter(
            Workout.date >= start,
            Workout.date <= anchor,
            Workout.deleted_at.is_(None),
        )
        .order_by(Workout.date.desc(), Workout.id.desc())
        .limit(limit)
        .all()
    )
    result = []
    for workout in rows:
        movements = []
        for movement in _parse_movements(workout)[:10]:
            sets = []
            volume_kg = 0.0
            for item in (movement.get("sets") or [])[:10]:
                try:
                    volume_kg += float(item.get("weight") or 0) * float(item.get("reps") or 0)
                except (TypeError, ValueError):
                    pass
                sets.append({
                    "weight": item.get("weight"),
                    "reps": item.get("reps"),
                    "rpe": item.get("rpe"),
                    "completed": item.get("completed"),
                })
            movements.append({
                "name": movement.get("name") or "未命名动作",
                "exetype": movement.get("exetype"),
                "sets": sets,
                "volume_kg": round(volume_kg, 2),
            })
        result.append({
            "id": workout.id,
            "date": workout.date.isoformat(),
            "title": workout.title,
            "tags": workout.tags,
            "duration_s": workout.duration_s,
            "calories": workout.calories,
            "avg_hr": workout.avg_hr,
            "max_hr": workout.max_hr,
            "match_status": workout.match_status,
            "movements": movements,
        })
    return result


def query_upcoming_plan_context(
    session: Session, anchor: date, *, days: int = UPCOMING_DAYS
) -> dict[str, Any]:
    rows = session.query(XunjiPlan).filter(XunjiPlan.plan_json.isnot(None)).all()
    fetched = max((row.fetched_at for row in rows if row.fetched_at), default=None)
    scheduled = [
        item for item in plan_service.query_plan_days(session, anchor, days=days)
        if not item.get("is_rest")
    ]
    return {
        "days": scheduled,
        "cache_available": bool(rows),
        "fetched_at": fetched.isoformat() if fetched else None,
        "stale": bool(fetched and (anchor - fetched.date()).days > 1),
    }


def query_movement_records(
    session: Session,
    anchor: date,
    *,
    names: list[str] | None = None,
    limit: int = MAX_MOVEMENT_RECORDS,
) -> list[dict[str, Any]]:
    """从全部真实训练计算动作纪录；不维护可能过期的 PR 副本。"""
    workouts = _all_workouts(session, end=anchor)
    wanted = set(names or _movement_names(workouts))
    records: dict[tuple[str, str], dict[str, Any]] = {}
    for workout in reversed(workouts):
        for movement in _parse_movements(workout):
            name = str(movement.get("name") or "").strip()
            if not name or name not in wanted:
                continue
            exetype = str(movement.get("exetype") or "").strip()
            key = (name, exetype)
            record = records.setdefault(key, {
                "name": name,
                "exetype": exetype,
                "pr_weight": None,
                "pr_reps": None,
                "pr_date": None,
                "latest": None,
            })
            best_weight = 0.0
            best_reps = 0
            for item in movement.get("sets") or []:
                try:
                    weight = float(item.get("weight") or 0)
                except (TypeError, ValueError):
                    weight = 0.0
                try:
                    reps = int(float(item.get("reps") or 0))
                except (TypeError, ValueError):
                    reps = 0
                if weight > best_weight or (weight == best_weight and reps > best_reps):
                    best_weight, best_reps = weight, reps
                old_weight = float(record["pr_weight"] or 0)
                old_reps = int(record["pr_reps"] or 0)
                if weight > old_weight or (weight == old_weight and reps > old_reps):
                    record.update({
                        "pr_weight": round(weight, 2) if weight > 0 else None,
                        "pr_reps": reps or None,
                        "pr_date": workout.date.isoformat(),
                    })
            record["latest"] = {
                "date": workout.date.isoformat(),
                "best_weight": round(best_weight, 2) if best_weight > 0 else None,
                "best_reps": best_reps or None,
            }
    ordered = sorted(
        records.values(),
        key=lambda row: (row["latest"] or {}).get("date") or "",
        reverse=True,
    )
    return ordered[:limit]


def _format_set(item: dict) -> str:
    weight = item.get("weight")
    reps = item.get("reps")
    unit = item.get("unit") or "kg"
    text = f"{weight}{unit}" if weight not in (None, "", 0, 0.0) else "自重"
    if reps not in (None, ""):
        text += f"×{reps}"
    if item.get("rpe") not in (None, ""):
        text += f" RPE{item['rpe']}"
    if item.get("completed") is False:
        text += "（未完成）"
    return text


def _format_plan_movement(movement: dict) -> str:
    sets = movement.get("target_sets") or []
    if not sets:
        return movement["name"]
    detail = "，".join(_format_set(item) for item in sets[:8])
    return f"{movement['name']}（{detail}）"


def format_realtime_context(context: dict[str, Any]) -> str:
    parts = [f"## 实时训练数据（查询日 {context['anchor_date']}）"]
    recent = context.get("recent_workouts") or []
    if recent:
        parts.append("### 最近训练")
        for workout in recent:
            meta = [workout["date"], workout.get("title") or workout.get("tags") or "训练"]
            if workout.get("duration_s"):
                meta.append(f"{round(workout['duration_s'] / 60)}分钟")
            if workout.get("calories"):
                meta.append(f"{workout['calories']}千卡")
            if workout.get("match_status"):
                meta.append(f"来源状态 {workout['match_status']}")
            parts.append("- " + " · ".join(meta))
            for movement in workout.get("movements") or []:
                sets = "，".join(_format_set(item) for item in movement["sets"])
                volume = f"；容量 {movement['volume_kg']}kg" if movement.get("volume_kg") else ""
                parts.append(f"  - {movement['name']}：{sets or '无有效组次'}{volume}")

    plan = context.get("upcoming_plan")
    if plan is not None:
        parts.append("### 未来计划")
        if not plan.get("cache_available"):
            parts.append("- 计划缓存为空，不能判断未来安排；请用户先刷新计划。")
        elif not plan.get("days"):
            parts.append("- 未来7天缓存中未查到明确训练安排；不能据此断言都是休息日。")
        else:
            for day in plan["days"]:
                names = "、".join(_format_plan_movement(m) for m in day.get("movements") or [])
                parts.append(f"- {day['date']} {day.get('title') or day.get('plan_name') or '训练'}：{names}")
        if plan.get("fetched_at"):
            parts.append(f"- 计划缓存更新时间：{plan['fetched_at']}")
        if plan.get("stale"):
            parts.append("- 注意：计划缓存超过1天未更新，回答时必须提示用户先刷新计划确认。")

    records = context.get("movement_records") or []
    if records:
        parts.append("### 动作纪录（由训练组次实时计算）")
        for record in records:
            kind = f"（{record['exetype']}）" if record.get("exetype") else ""
            if record.get("pr_weight") is not None:
                pr = f"{record['pr_weight']}kg×{record.get('pr_reps') or '-'}"
            else:
                pr = f"自重×{record.get('pr_reps') or '-'}"
            latest = record.get("latest") or {}
            latest_load = (
                f"{latest.get('best_weight')}kg"
                if latest.get("best_weight") is not None else "自重"
            )
            parts.append(
                f"- {record['name']}{kind}：历史最佳 {pr}（{record.get('pr_date') or '日期未知'}）；"
                f"最近一次 {latest_load}×{latest.get('best_reps') or '-'}（{latest.get('date') or '未知'}）"
            )
    recovery = context.get("recovery")
    if recovery:
        parts.append("### 最近7天恢复数据")
        labels = (
            ("有效天数", "days_count", "天"),
            ("平均睡眠", "avg_sleep_hours", "小时"),
            ("HRV状态", "hrv_status", ""),
            ("身体电量高点", "body_battery_high", ""),
            ("身体电量低点", "body_battery_low", ""),
            ("静息心率", "resting_hr", "bpm"),
            ("平均压力", "stress_avg", ""),
        )
        for label, key, unit in labels:
            value = recovery.get(key)
            if value is not None:
                parts.append(f"- {label}：{value}{unit}")
        weights = recovery.get("weight_trend") or []
        if weights:
            parts.append("- 近期体重：" + "，".join(
                f"{item['date']} {item['value']}kg" for item in weights[:7]
            ))
    if len(parts) == 1:
        return ""
    parts.append("只可依据以上真实数据回答；缺失字段须明确说未查到，不得推测。")
    text = "\n".join(parts)
    if len(text) > 12000:
        return text[:12000] + "\n- 上下文已按长度限制截断；不得推测被截断的数据。"
    return text


def build_realtime_context(
    session: Session, content: str, *, anchor: date | None = None
) -> tuple[str, dict[str, Any]]:
    anchor = anchor or date.today()
    intent = detect_context_intent(content)
    # 日常教练默认了解最近训练；计划和完整 PR 按问题加载以控制 token。
    recent = query_recent_workouts(session, anchor)
    recent_rows = _all_workouts(session, end=anchor, limit=RECENT_LIMIT)
    mentioned = find_mentioned_movements(content, recent_rows)
    plan = query_upcoming_plan_context(session, anchor) if intent["plan"] else None
    recovery = None
    if intent["recovery"]:
        from app.services.ai import query_recovery_summary

        recovery = query_recovery_summary(session, anchor)
    records = []
    if intent["pr"] or mentioned:
        names = None if intent["all_pr"] else mentioned
        records = query_movement_records(session, anchor, names=names)
    context = {
        "anchor_date": anchor.isoformat(),
        "recent_workouts": recent,
        "upcoming_plan": plan,
        "movement_records": records,
        "recovery": recovery,
    }
    refs = {
        "recent_workouts": len(recent),
        "upcoming_plan_days": len((plan or {}).get("days") or []),
        "movement_records": [row["name"] for row in records],
        "training_data_through": anchor.isoformat(),
        "plan_fetched_at": (plan or {}).get("fetched_at"),
        "plan_stale": bool((plan or {}).get("stale")),
        "recovery_days": int((recovery or {}).get("days_count") or 0),
    }
    return format_realtime_context(context), refs


def serialize_context_refs(refs: dict[str, Any]) -> str:
    return json.dumps(refs, ensure_ascii=False, default=str)
