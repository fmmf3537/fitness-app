"""V1-3 AI 单次训练点评服务（type='session_review'）。

纪律：
- prompt 组装函数纯函数化，方便测试；
- 历史与恢复数据查询独立封装，便于 mock；
- 生成失败抛 LLMError，由调用方（daily_sync）捕获并写 job_run，不阻塞主流程；
- 不直接操作 HTTP，统一调用 adapters/llm.chat。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import llm
from app.models import AIReport, BodyMetric, GarminDaily, Workout

PROMPT_SECTIONS = ("完成质量", "与历史对比", "恢复评估", "注意事项")


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_movements(workout: Workout) -> list[dict]:
    if not workout.movements_json:
        return []
    try:
        data = json.loads(workout.movements_json)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _format_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "未知"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    return f"{minutes // 60} 小时 {minutes % 60} 分钟"


def _extract_sleep_seconds(sleep_data: dict | None) -> tuple[int | None, int | None]:
    """从佳明 sleep_json 提取总睡眠秒数与深睡秒数，容忍多种字段名。"""
    if not isinstance(sleep_data, dict):
        return None, None
    dto = sleep_data.get("dailySleepDTO") or sleep_data
    total = dto.get("sleepTimeInSeconds") or dto.get("totalSleepTimeInSeconds")
    deep = dto.get("deepSleepSeconds") or dto.get("deepSleepSecondsInWaves")
    return _int_or_none(total), _int_or_none(deep)


def query_movement_history(
    session: Session,
    movement_name: str,
    current_date: date,
    *,
    weeks: int = 4,
    limit: int = 3,
) -> dict:
    """查询近 N 周某动作的历史摘要（最近几次 + PR）。

    返回：
        {
            "count": 出现次数,
            "pr_weight": 最大重量（kg，浮点数）,
            "recent": [
                {"date": "YYYY-MM-DD", "best_weight": float, "best_reps": int,
                 "total_volume": float, "sets_count": int},
                ...
            ]
        }
    """
    start = current_date - timedelta(weeks=weeks)
    end = current_date - timedelta(days=1)
    rows = (
        session.query(Workout)
        .filter(
            Workout.date >= start,
            Workout.date <= end,
            Workout.movements_json.isnot(None),
        )
        .order_by(Workout.date.desc())
        .all()
    )

    recent: list[dict] = []
    pr_weight: float = 0.0
    count = 0
    for w in rows:
        movements = _parse_movements(w)
        for mv in movements:
            if (mv.get("name") or "").strip() != movement_name:
                continue
            sets = mv.get("sets") or []
            if not sets:
                continue
            count += 1
            best_weight = 0.0
            best_reps = 0
            total_volume = 0.0
            valid_sets = 0
            for s in sets:
                weight = _float_or_none(s.get("weight")) or 0.0
                reps = _int_or_none(s.get("reps")) or 0
                if weight <= 0 and reps <= 0:
                    continue
                valid_sets += 1
                total_volume += weight * reps
                if weight > best_weight or (weight == best_weight and reps > best_reps):
                    best_weight = weight
                    best_reps = reps
                if weight > pr_weight:
                    pr_weight = weight
            if valid_sets:
                recent.append(
                    {
                        "date": w.date.isoformat(),
                        "best_weight": round(best_weight, 2),
                        "best_reps": best_reps,
                        "total_volume": round(total_volume, 2),
                        "sets_count": valid_sets,
                    }
                )
            break  # 同一个 workout 中同名动作只计一次

    recent = sorted(recent, key=lambda x: x["date"], reverse=True)[:limit]
    return {
        "count": count,
        "pr_weight": round(pr_weight, 2) if pr_weight > 0 else None,
        "recent": recent,
    }


def query_recovery_summary(
    session: Session,
    current_date: date,
    *,
    days: int = 7,
) -> dict:
    """汇总近 N 天睡眠/HRV/身体电量/压力/静息心率/体重趋势。

    训练准备度当前未接入，故在返回中显式标注为 None，prompt 中说明缺失。
    """
    start = current_date - timedelta(days=days - 1)
    rows = (
        session.query(GarminDaily)
        .filter(GarminDaily.date >= start, GarminDaily.date <= current_date)
        .order_by(GarminDaily.date.desc())
        .all()
    )

    sleep_hours: list[float] = []
    deep_ratios: list[float] = []
    hrv_statuses: list[str] = []
    body_battery_high: list[int] = []
    body_battery_low: list[int] = []
    resting_hrs: list[int] = []
    stress_avgs: list[int] = []

    for row in rows:
        sleep_json = _parse_json(row.sleep_json)
        total_s, deep_s = _extract_sleep_seconds(sleep_json)
        if total_s and total_s > 0:
            sleep_hours.append(total_s / 3600)
            if deep_s and deep_s > 0:
                deep_ratios.append(deep_s / total_s)
        if row.hrv_status:
            hrv_statuses.append(row.hrv_status)
        if row.body_battery_high is not None:
            body_battery_high.append(row.body_battery_high)
        if row.body_battery_low is not None:
            body_battery_low.append(row.body_battery_low)
        if row.resting_hr is not None:
            resting_hrs.append(row.resting_hr)
        if row.stress_avg is not None:
            stress_avgs.append(row.stress_avg)

    # 近 4 周体重趋势（纳入 AI 上下文，US-12 AC6）
    weight_start = current_date - timedelta(weeks=4)
    weight_rows = (
        session.query(BodyMetric)
        .filter(
            BodyMetric.date >= weight_start,
            BodyMetric.date <= current_date,
            BodyMetric.type == "weight",
        )
        .order_by(BodyMetric.date.desc())
        .limit(7)
        .all()
    )
    weights = [
        {"date": r.date.isoformat(), "value": round(r.value, 2)}
        for r in weight_rows
    ]

    def avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    return {
        "days_count": len(rows),
        "avg_sleep_hours": avg(sleep_hours),
        "avg_deep_ratio": avg(deep_ratios),
        "hrv_status": hrv_statuses[0] if hrv_statuses else None,
        "hrv_status_list": hrv_statuses,
        "body_battery_high": avg(body_battery_high),
        "body_battery_low": avg(body_battery_low),
        "resting_hr": avg(resting_hrs),
        "stress_avg": avg(stress_avgs),
        "weight_trend": weights,
        "training_readiness": None,  # 当前 GarminDaily 未收录该字段
    }


def _parse_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def build_session_review_prompt(
    workout: dict,
    history: dict[str, dict],
    recovery: dict,
) -> list[dict]:
    """纯函数：组装单次训练点评 prompt。

    输出固定四节 Markdown 要求：完成质量 / 与历史对比 / 恢复评估 / 注意事项。
    """
    movements = workout.get("movements") or []
    lines: list[str] = []
    lines.append(f"# 本次训练（{workout.get('date') or '未知日期'}）")
    if workout.get("title"):
        lines.append(f"标题：{workout['title']}")
    tags = workout.get("tags")
    if tags:
        lines.append(f"活动类型：{tags}")
    lines.append(
        f"时长：{_format_duration(workout.get('duration_s'))} | "
        f"热量：{workout.get('calories') or '-'} 千卡 | "
        f"平均心率：{workout.get('avg_hr') or '-'} bpm | "
        f"最大心率：{workout.get('max_hr') or '-'} bpm"
    )

    lines.append("")
    lines.append("## 动作组次")
    if movements:
        for mv in movements:
            sets = mv.get("sets") or []
            lines.append(f"- {mv.get('name') or '未命名动作'}：共 {len(sets)} 组")
            for i, s in enumerate(sets, 1):
                weight = s.get("weight")
                unit = s.get("unit") or "kg"
                reps = s.get("reps")
                rpe = s.get("rpe")
                done = s.get("done")
                part = f"  - 第{i}组："
                if weight is not None and reps is not None:
                    part += f"{weight}{unit} × {reps}"
                elif reps is not None:
                    part += f"{reps} 次"
                else:
                    part += "数据缺失"
                if rpe is not None:
                    part += f"（RPE {rpe}）"
                if done is False:
                    part += "【未完成】"
                lines.append(part)
    else:
        lines.append("- 无动作数据")

    lines.append("")
    lines.append(f"# 近4周同动作历史（截至 {workout.get('date') or '今日'}）")
    if history:
        for name, hist in history.items():
            lines.append(f"## {name}")
            lines.append(f"- 出现次数：{hist['count']}")
            if hist.get("pr_weight") is not None:
                lines.append(f"- 个人纪录（PR）重量：{hist['pr_weight']} kg")
            recent = hist.get("recent") or []
            if recent:
                lines.append("- 最近记录：")
                for r in recent:
                    lines.append(
                        f"  - {r['date']}：最佳 {r['best_weight']}kg × {r['best_reps']}，"
                        f"总容量 {r['total_volume']}kg，{r['sets_count']} 组"
                    )
            else:
                lines.append("- 近4周无该动作记录")
    else:
        lines.append("近4周无同动作历史数据。")

    lines.append("")
    lines.append("# 近7天恢复数据")
    if recovery.get("days_count", 0) > 0:
        if recovery.get("avg_sleep_hours") is not None:
            lines.append(f"- 平均睡眠时长：{recovery['avg_sleep_hours']} 小时")
        if recovery.get("avg_deep_ratio") is not None:
            lines.append(f"- 平均深睡比例：{round(recovery['avg_deep_ratio'] * 100, 1)}%")
        if recovery.get("hrv_status"):
            lines.append(f"- HRV 状态：{recovery['hrv_status']}")
        if recovery.get("body_battery_high") is not None and recovery.get("body_battery_low") is not None:
            lines.append(
                f"- 身体电量：高 {recovery['body_battery_high']} / 低 {recovery['body_battery_low']}"
            )
        if recovery.get("resting_hr") is not None:
            lines.append(f"- 平均静息心率：{recovery['resting_hr']} bpm")
        if recovery.get("stress_avg") is not None:
            lines.append(f"- 平均压力：{recovery['stress_avg']}")
    else:
        lines.append("- 近7天无恢复数据")

    if recovery.get("weight_trend"):
        lines.append("- 近4周体重趋势（kg）：")
        for item in recovery["weight_trend"]:
            lines.append(f"  - {item['date']}：{item['value']} kg")
    else:
        lines.append("- 近4周无体重记录")

    if recovery.get("training_readiness") is None:
        lines.append("- 训练准备度：当前未接入该数据源，将结合睡眠/HRV/身体电量综合评估")

    system = (
        "你是一位资深力量训练教练。请根据用户本次训练、近4周同动作历史、"
        "近7天睡眠/HRV/身体电量/压力/静息心率/体重趋势，撰写单次训练点评。"
        "输出为 Markdown，必须且只能包含以下四节（按顺序）：\n"
        "\n".join(f"## {s}" for s in PROMPT_SECTIONS)
        + "\n每节需结合真实数据，给出具体、可执行的评价与建议。"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _resolve_provider(session: Session) -> str:
    """读取默认 provider；若 settings 未配置则回退 deepseek。"""
    try:
        return llm.get_default_provider(session)
    except Exception:
        return llm.DEFAULT_PROVIDER


def generate_session_review(
    session: Session,
    workout_id: int,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
) -> AIReport:
    """为单个 workout 生成单次点评并落库 ai_report。

    chat_fn 用于测试注入；默认调用 adapters.llm.chat。
    """
    workout = session.get(Workout, workout_id)
    if workout is None:
        raise ValueError(f"workout {workout_id} 不存在")

    movements = _parse_movements(workout)
    history: dict[str, dict] = {}
    for mv in movements:
        name = (mv.get("name") or "").strip()
        if not name:
            continue
        history[name] = query_movement_history(session, name, workout.date)

    recovery = query_recovery_summary(session, workout.date)

    workout_dict = {
        "date": workout.date.isoformat(),
        "title": workout.title,
        "tags": workout.tags,
        "duration_s": workout.duration_s,
        "calories": workout.calories,
        "avg_hr": workout.avg_hr,
        "max_hr": workout.max_hr,
        "movements": movements,
    }

    messages = build_session_review_prompt(workout_dict, history, recovery)

    if chat_fn is None:
        chat_fn = lambda msgs: llm.chat(  # noqa: E731
            msgs, session=session, purpose="session_review"
        )

    result = chat_fn(messages)
    content = result.get("content", "")
    prompt_tokens = result.get("prompt_tokens") or 0
    completion_tokens = result.get("completion_tokens") or 0

    provider = _resolve_provider(session)
    model = result.get("model") or llm.PROVIDERS[provider]["default_model"]
    cost = llm.compute_cost(provider, prompt_tokens, completion_tokens)

    report = AIReport(
        type="session_review",
        workout_id=workout.id,
        period_start=workout.date,
        period_end=workout.date,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_estimate=round(cost, 6),
        content_md=content,
    )
    session.add(report)
    session.commit()
    return report


def run_daily_reviews(
    session: Session,
    day: date | str,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
) -> dict:
    """为某日全部 workout 生成单次点评。

    返回 summary：{"date", "generated", "skipped", "reports": [id, ...]}。
    """
    day_date = date.fromisoformat(day) if isinstance(day, str) else day
    workouts = (
        session.query(Workout)
        .filter(Workout.date == day_date)
        .order_by(Workout.id)
        .all()
    )

    reports: list[int] = []
    skipped = 0
    for w in workouts:
        # 幂等：同日同 workout 已存在 session_review 则跳过
        existing = session.scalars(
            select(AIReport).where(
                AIReport.workout_id == w.id,
                AIReport.type == "session_review",
                AIReport.period_start == day_date,
            )
        ).first()
        if existing:
            skipped += 1
            continue
        report = generate_session_review(session, w.id, chat_fn=chat_fn)
        reports.append(report.id)

    return {
        "date": day_date.isoformat(),
        "generated": len(reports),
        "skipped": skipped,
        "reports": reports,
    }
